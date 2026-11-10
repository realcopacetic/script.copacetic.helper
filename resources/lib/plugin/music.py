# author: realcopacetic

import re
from collections import Counter
from functools import lru_cache
from operator import itemgetter
from pathlib import PurePosixPath
from typing import Callable, Iterable, Iterator

from xbmc import getLocalizedString
from xbmcgui import ListItem

from resources.lib.plugin.library import DirectoryItem
from resources.lib.plugin.setter import apply_musicinfotag, joined
from resources.lib.shared.utilities import ADDON, fold, json_call

_DETAILS = {
    "album": (
        "AudioLibrary.GetAlbumDetails",
        ["displayartist", "genre", "title", "userrating", "year"],
    ),
    "artist": (
        "AudioLibrary.GetArtistDetails",
        ["born", "died", "disbanded", "formed", "genre", "yearsactive"],
    ),
    "song": (
        "AudioLibrary.GetSongDetails",
        [
            "album",
            "artist",
            "duration",
            "file",
            "genre",
            "title",
            "track",
            "userrating",
            "year",
        ],
    ),
}
_ICONS = {
    "album": "DefaultAlbumCover.png",
    "artist": "DefaultArtist.png",
    "playlist": "DefaultMusicPlaylists.png",
    "song": "DefaultMusicSongs.png",
}
# Details Kodi's own musicdb items carry as {type}_{field} properties too
_PROPERTIES = {"born", "description", "died", "disbanded", "formed", "yearsactive"}
ALBUM_RANK_PROPERTIES = [
    *_DETAILS["album"][1],
    "art",
    "artistid",
    "musicbrainzreleasegroupid",
]
SONG_RANK_PROPERTIES = [*_DETAILS["song"][1], "art", "musicbrainztrackid", "playcount"]
ALBUM_SONG_PROPERTIES = ["album", "albumid", "musicbrainztrackid", "title", "year"]
K = 10  # reciprocal rank fusion: how fast credit falls with place (1st 1/11)
WEIGHTS = {"deezer": 1.0, "listenbrainz": 1.0}  # what's streamed now, all-time
OVERLAP = 3  # song titles in common that identify an artist with no album in common
_MOVES = {-1: 13332, 1: 13333}  # Move up, Move down
# Speed dial rows above the Move rows: (action, addon string, types without it)
_DIAL_ROWS = (("start_mix", 32821, {"playlist"}), ("shuffle", 32820, {"song"}))


def library_item(details: dict, type: str) -> DirectoryItem:
    """
    A library album, artist or song as a directory item: songs play their file,
    the rest open as folders.

    :param details: AudioLibrary row with the _DETAILS properties and art.
    :param type: album, artist or song.
    :return: (path, ListItem, is_folder).
    """
    li = ListItem(details["label"], offscreen=True)
    li.setArt(details["art"] | {"icon": _ICONS[type]})
    apply_musicinfotag(li, details, type)
    li.setProperties(
        {
            f"{type}_{key}": joined(value)
            for key, value in details.items()
            if key in _PROPERTIES
        }
    )
    if type == "song":
        return details["file"], li, False
    return f"musicdb://{type}s/{details[f'{type}id']}/", li, True


def details_item(
    type: str, dbid: int, parent: str, extra: tuple[str, ...] = ()
) -> DirectoryItem | None:
    """
    A library album, artist or song by id, as library_item builds it.

    :param type: album, artist or song.
    :param dbid: Library id.
    :param parent: Caller name for logging.
    :param extra: Properties to fetch beyond _DETAILS (an album's description).
    :return: (path, ListItem, is_folder), or None if the library lost the item.
    """
    method, properties = _DETAILS[type]
    details = (
        json_call(
            method,
            properties=[*properties, *extra, "art"],
            params={f"{type}id": dbid},
            parent=parent,
        )
        .get("result", {})
        .get(f"{type}details")
    )
    return library_item(details, type) if details else None


def compact_count(count: int) -> str:
    """
    A count to two significant figures with K, M or B once that reaches 1000,
    else as is: 87, 994, 1K (995), 310K, 1.2M.

    :param count: Non-negative count.
    :return: Compact text.
    """
    rounded = float(f"{count:.2g}")
    for power, suffix in ((9, "B"), (6, "M"), (3, "K")):
        if rounded >= 10**power:
            return f"{rounded / 10**power:g}{suffix}"
    return f"{count}"


@lru_cache(maxsize=4096)
def title_key(title: str) -> str:
    """
    A song title reduced for matching across sources: no trailing "(feat. …)",
    "[Remaster]" or " - Live" part, and no case, accents or punctuation.

    :param title: Song title.
    :return: Matching key.
    """
    return fold(re.sub(r"(?<=\S)\s*[(\[].*|\s+-\s.*", "", title.casefold()))


def artist_identity(dbid: int, parent: str) -> tuple[str, str]:
    """
    A library artist's name and MusicBrainz id.

    :param dbid: Library artist id.
    :param parent: Caller name for logging.
    :return: (name, MBID), the MBID empty when untagged.
    """
    details = json_call(
        "AudioLibrary.GetArtistDetails",
        properties=["musicbrainzartistid"],
        params={"artistid": dbid},
        parent=parent,
    )["result"]["artistdetails"]
    return details["artist"], details["musicbrainzartistid"][0]


def fused(rankings: Iterable[tuple[float, Iterable]]) -> Counter:
    """
    Each key's score over weighted rankings: weight / (K + place) in every ranking
    that lists it, at its first place there (reciprocal rank fusion).

    :param rankings: (weight, keys best first) pairs.
    :return: Score per key; 0 for a key no ranking lists.
    """
    scores = Counter()
    for weight, keys in rankings:
        for place, key in enumerate(dict.fromkeys(keys), 1):
            scores[key] += weight / (K + place)
    return scores


def song_finder(songs: list[dict]) -> Callable[..., dict | None]:
    """
    A lookup from a ranking row to a library song: by recording MBID, else title and
    album title, else title; the earliest release of several.

    :param songs: Library songs with album, musicbrainztrackid, title and year.
    :return: find(mbid, title, album="") giving the song or None.
    """
    by_mbid, by_album, by_title = {}, {}, {}
    for song in sorted(songs, key=lambda song: song["year"] or 9999):  # undated last
        key = title_key(song["title"])
        by_mbid.setdefault(song["musicbrainztrackid"], song)
        by_album.setdefault((key, title_key(song["album"])), song)
        by_title.setdefault(key, song)
    by_mbid.pop("", None)  # untagged songs
    by_title.pop("", None)  # titles of symbols only

    def find(mbid: str, title: str, album: str = "") -> dict | None:
        key = title_key(title)
        return (
            by_mbid.get(mbid)
            or (key and (album := title_key(album)) and by_album.get((key, album)))
            or by_title.get(key)
        )

    return find


def deezer_match(songs: list[dict], rows: list) -> bool:
    """
    Whether a Deezer artist's top-track rows are this library artist's: OVERLAP
    song titles in common (all of them, for fewer), or one and an album title.

    :param songs: The library artist's songs with album and title.
    :param rows: ["", title, album title] rows.
    :return: True for a match.
    """
    titles = {title_key(song["title"]) for song in songs} - {""}
    shared = len(titles.intersection(title_key(title) for _, title, _ in rows))
    albums = {title_key(song["album"]) for song in songs} - {""}
    if not albums.isdisjoint(title_key(album) for *_, album in rows):
        return shared >= 1
    return shared >= min(OVERLAP, len(titles)) > 0


def rank_songs(rankings: list[tuple[float, list]], songs: list[dict]) -> list[dict]:
    """
    Songs by their fused score over rankings, then played songs, most played first;
    one per title, earliest release unless an MBID matched; [] if no ranking matches.

    :param rankings: (weight, [recording MBID, title, …] rows best first) pairs.
    :param songs: Library songs with SONG_RANK_PROPERTIES.
    :return: Ranked songs.
    """
    find, shown = song_finder(songs), {}

    def keys(rows: list) -> Iterator[str]:
        for mbid, title, *_ in rows:
            if song := find(mbid, title):
                key = title_key(song["title"])
                shown.setdefault(key, song)
                yield key

    scores = fused((weight, keys(rows)) for weight, rows in rankings)
    if not scores:
        return []
    played = filter(itemgetter("playcount"), songs)  # most played; earliest release
    for song in sorted(played, key=lambda s: (-s["playcount"], s["year"] or 9999)):
        shown.setdefault(title_key(song["title"]), song)
    return sorted(
        shown.values(),
        key=lambda song: (scores[title_key(song["title"])], song["playcount"]),
        reverse=True,
    )


def albums_by_songs(rows: list[list[str]], songs: list[dict]) -> list[int]:
    """
    Library album ids by the credit of their songs in rows: each matched song gives
    its album 1 / (K + place) once, at its first place.

    :param rows: ["", title, album title] rows, best first.
    :param songs: Library songs with ALBUM_SONG_PROPERTIES.
    :return: Album ids, most credited first.
    """
    find = song_finder(songs)
    matched = dict.fromkeys(song["songid"] for row in rows if (song := find(*row)))
    album = {song["songid"]: song["albumid"] for song in songs}
    credit = Counter()
    for place, songid in enumerate(matched, 1):
        credit[album[songid]] += 1 / (K + place)
    return sorted(credit, key=credit.get, reverse=True)


def albums_by_groups(groups: list[list[str]], albums: list[dict]) -> list[int]:
    """
    Library album ids in the order of the release groups they match (by release
    group MBID, else title); newest first among copies of one group.

    :param groups: [release group MBID, title] pairs, most popular first.
    :param albums: Library albums with musicbrainzreleasegroupid, title and year.
    :return: Matched album ids.
    """
    by_mbid, by_title = {}, {}
    for place, (mbid, title) in enumerate(groups):
        by_mbid.setdefault(mbid, place)
        by_title.setdefault(title_key(title), place)
    places = {}
    for album in sorted(albums, key=itemgetter("year"), reverse=True):
        place = by_mbid.get(
            album["musicbrainzreleasegroupid"], by_title.get(title_key(album["title"]))
        )
        if place is not None:
            places[album["albumid"]] = place
    return sorted(places, key=places.get)


def rank_albums(rankings: list[tuple[float, list[int]]], albums: list[dict]) -> list:
    """
    Albums by their fused score over rankings, then the unranked; newest first
    among equals.

    :param rankings: (weight, album ids best first) pairs.
    :param albums: Library albums with albumid and year.
    :return: Ranked albums, all of them.
    """
    scores = fused(rankings)
    return sorted(
        sorted(albums, key=itemgetter("year"), reverse=True),
        key=lambda album: scores[album["albumid"]],
        reverse=True,
    )


def library_rows(
    type: str,
    query_filter: dict | None,
    sort: dict | None,
    limit: int | None,
    parent: str,
    properties: list[str] | None = None,
) -> list[dict]:
    """
    AudioLibrary albums, artists or songs matching query_filter, with _DETAILS
    properties and art unless properties says otherwise.

    :param type: album, artist or song.
    :param query_filter: AudioLibrary filter, a rule tree or an id filter; None for all.
    :param sort: JSON-RPC sort, applied before the limit; None for Kodi's order.
    :param limit: Most rows to return; None for all.
    :param parent: Caller name for logging.
    :param properties: Properties to fetch; None for _DETAILS and art.
    :return: Rows, possibly empty.
    """
    if properties is None:
        properties = [*_DETAILS[type][1], "art"]
    rows = json_call(
        f"AudioLibrary.Get{type.title()}s",
        properties=properties,
        sort=sort,
        query_filter=query_filter,
        limit=limit,
        parent=parent,
    )
    return rows.get("result", {}).get(f"{type}s", [])


def dial_item(entry: dict, offsets: tuple[int, ...] | None) -> DirectoryItem | None:
    """
    A speed dial entry as a directory item: songs play their file, the rest open
    as folders. Its own context rows lead the menu: Start mix, Shuffle, a Move row
    per offset, Unpin if pinned; addon.xml's copies hide on speed dial items.

    :param entry: Speed dial entry (type, ref).
    :param offsets: Moves the entry can make, -1 up and 1 down; None if not pinned.
    :return: (path, ListItem, is_folder), or None if the library lost the item.
    """
    type, ref = entry["type"], entry["ref"]
    if type == "playlist":
        li = ListItem(PurePosixPath(ref).stem, offscreen=True)
        li.setArt({"icon": _ICONS[type]})
        path, args = ref, f'type=playlist,"path={ref}"'
    else:
        if not (item := details_item(type, int(ref), "speed_dial")):
            return None
        path, li, _ = item
        args = f"type={type},id={ref}"
    li.setProperty("speed_dial", "true")  # focused(); addon.xml rows hide on it
    run = f"RunScript(script.copacetic.helper,{args},action="
    rows = [
        *(
            (ADDON.getLocalizedString(string), f"{run}{action})")
            for action, string, without in _DIAL_ROWS
            if type not in without
        ),
        *(
            (getLocalizedString(_MOVES[offset]), f"{run}move_pin,offset={offset})")
            for offset in offsets or ()
        ),
    ]
    if offsets is not None:
        rows.append((ADDON.getLocalizedString(32825), f"{run}unpin)"))
    li.addContextMenuItems(rows)
    return path, li, type != "song"
