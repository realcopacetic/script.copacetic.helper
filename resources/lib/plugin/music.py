# author: realcopacetic

import re
from collections import Counter
from functools import cache, lru_cache
from operator import itemgetter
from pathlib import PurePosixPath
from typing import Callable, Iterable, Iterator

from xbmc import getLocalizedString
from xbmcgui import ListItem

from resources.lib.plugin.library import DirectoryItem
from resources.lib.plugin.setter import apply_musicinfotag, joined
from resources.lib.shared.genres import genre_bucket
from resources.lib.shared.mix import credits
from resources.lib.shared.utilities import ADDON, fold, json_call

_DETAILS = {
    "album": (
        "AudioLibrary.GetAlbumDetails",
        ["displayartist", "genre", "title", "userrating", "year"],
    ),
    "artist": (
        "AudioLibrary.GetArtistDetails",
        ["born", "died", "disbanded", "formed", "genre", "type", "yearsactive"],
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
_PROPERTIES = {
    "born",
    "description",
    "died",
    "disbanded",
    "formed",
    "type",
    "yearsactive",
}
ALBUM_RANK_PROPERTIES = [*_DETAILS["album"][1], "art", "artistid"]
SONG_RANK_PROPERTIES = [
    *_DETAILS["song"][1],
    "albumid",
    "art",
    "musicbrainztrackid",
    "playcount",
]
ALBUM_SONG_PROPERTIES = ["album", "albumid", "musicbrainztrackid", "title", "year"]
K = 10  # reciprocal rank fusion: how fast credit falls with place (1st 1/11)
# What's streamed now counts double all-time listening: closest to Spotify and YouTube
# Music, new albums included (coding-notes audits/2026-11-12-music-popularity.md)
WEIGHTS = {"deezer": 2.0, "listenbrainz": 1.0}
OVERLAP = 3  # song titles in common that identify an artist with no album in common
# Titles many albums share (title_key form): a ranking row matches them by MBID only
GENERIC = frozenset({"interlude", "intro", "outro", "prelude", "skit", "untitled"})
SINGLE = 4  # a release with fewer different songs yields to a same-year album
# Music info's word for how popular an item is, never a raw number (N13, Ash 14 Nov)
PLACES = 10  # "#2 song", "Your #3 artist": only within the first ten
POPULAR = 1_000_000  # Deezer fans an artist needs to read "Popular"
_MOVES = {-1: 13332, 1: 13333}  # Move up, Move down
# Speed dial rows above the Move rows: (action, addon string, types without it)
_DIAL_ROWS = (("start_mix", 32821, {"playlist"}), ("shuffle", 32820, {"song"}))
MIX_NAMES = 8  # artists a daily mix card names (Ash, 13 Nov)
MIX_SLIDES = 25  # its multiart: every artist of the mix, up to 25 slides (Ash, 13 Nov)


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


def mix_cards(
    mixes: list[tuple[str, dict]], ids: dict[str, int]
) -> list[DirectoryItem]:
    """
    Daily mixes as cards, named by their most played genre still in the library:
    "<genre> mix", that genre and its bucket, an eyebrow with its count, its artists in
    play order (MIX_NAMES named, MIX_SLIDES thumbs). Opens that genre; a click plays it.

    :param mixes: (card, kept_mix dict) pairs, each with a genre still in the library.
    :param ids: The library's genre ids by name (genre_ids).
    :return: (path, ListItem, is_folder) per card.
    """
    names = {
        key: [*dict.fromkeys(credits(song)[0] for song in mix["songs"])]
        for key, mix in mixes
    }
    thumbs = {
        row["artist"]: row["art"]["thumb"]
        for row in json_call(
            "AudioLibrary.GetArtists",
            properties=["art"],
            query_filter={
                "field": "artist",
                "operator": "is",
                "value": [*{name for artists in names.values() for name in artists}],
            },
            params={"albumartistsonly": False},
            parent="daily_mixes",
        )["result"].get("artists", [])
        if "thumb" in row["art"]
    }
    cards = []
    for key, mix in mixes:
        genre = next(g for g in mix["genres"] if g in ids)  # most played still there
        artists = names[key]
        slides = [thumbs[name] for name in artists if name in thumbs][:MIX_SLIDES]
        if artists[MIX_NAMES:]:
            described = ADDON.getLocalizedString(32841) % ", ".join(artists[:MIX_NAMES])
        else:
            *first, last = artists
            described = ADDON.getLocalizedString(32840) % (", ".join(first), last)
        li = ListItem(ADDON.getLocalizedString(32838) % genre, offscreen=True)
        li.setArt(
            {f"square{n or ''}": url for n, url in enumerate(slides)}
            | {"icon": "DefaultMusicGenres.png"}
        )
        li.getMusicInfoTag().setGenres([genre])
        li.setProperties(
            {
                "Artist_Description": described,
                "eyebrow": ADDON.getLocalizedString(32839) % len(mix["songs"]),
                "mix_bucket": genre_bucket(genre) or "",  # a skin's icon, by name
                "mix_genreid": str(ids[genre]),
            }
        )
        cards.append((f"musicdb://genres/{ids[genre]}/", li, True))
    return cards


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
    album title, else title (never a GENERIC one); the earliest release of several, a
    single after an album of the same year.

    :param songs: Library songs with album, albumid, musicbrainztrackid, title, year.
    :return: find(mbid, title, album="") giving the song or None.
    """
    # different songs per release, so a remix EP of one title stays a single
    size = Counter(a for a, _ in {(s["albumid"], title_key(s["title"])) for s in songs})
    by_mbid, by_album, by_title = {}, {}, {}
    # undated last; among full albums (editions, live) the scan order stands
    for song in sorted(
        songs, key=lambda s: (s["year"] or 9999, size[s["albumid"]] < SINGLE)
    ):
        key = title_key(song["title"])
        by_mbid.setdefault(song["musicbrainztrackid"], song)
        by_album.setdefault((key, title_key(song["album"])), song)
        by_title.setdefault(key, song)
    by_mbid.pop("", None)  # untagged songs
    for key in ("", *GENERIC):  # titles of symbols only; a new album's "Intro"
        by_title.pop(key, None)

    def find(mbid: str, title: str, album: str = "") -> dict | None:
        key = title_key(title)
        return (
            by_mbid.get(mbid)
            or (key and (album := title_key(album)) and by_album.get((key, album)))
            or by_title.get(key)
        )

    return find


def deezer_match(songs: list[dict], rows: list) -> bool | None:
    """
    Whether a Deezer artist's top-track rows are this library artist's: OVERLAP
    song titles in common (all of them, for fewer), or one and an album title.

    :param songs: The library artist's songs with album and title.
    :param rows: ["", title, album title] rows.
    :return: True for a match; None for none from fewer than OVERLAP titles.
    """
    titles = {title_key(song["title"]) for song in songs} - {""}
    shared = len(titles.intersection(title_key(title) for _, title, _ in rows))
    albums = {title_key(song["album"]) for song in songs} - {""}
    if shared and (
        shared >= min(OVERLAP, len(titles))
        or not albums.isdisjoint(title_key(album) for *_, album in rows)
    ):
        return True
    return None if len(titles) < OVERLAP else False


def scored_songs(
    rankings: list[tuple[float, list]], songs: list[dict]
) -> tuple[Counter, dict[str, dict]]:
    """
    Each title's fused score over rankings, and the library song standing for it:
    the earliest release unless an MBID matched.

    :param rankings: (weight, [recording MBID, title, …] rows best first) pairs.
    :param songs: Library songs with album, albumid, musicbrainztrackid, title, year.
    :return: (score per title_key, song per title_key).
    """
    find, shown = song_finder(songs), {}

    def keys(rows: list) -> Iterator[str]:
        for mbid, title, *_ in rows:
            if song := find(mbid, title):
                key = title_key(song["title"])
                shown.setdefault(key, song)
                yield key

    return fused((weight, keys(rows)) for weight, rows in rankings), shown


def _by_score(scores: Counter, songs: Iterable[dict]) -> list[dict]:
    """
    Songs by their title's score, then their play count, most first.

    :param scores: Score per title_key.
    :param songs: Library songs with playcount and title.
    :return: Sorted songs.
    """
    return sorted(
        songs,
        key=lambda song: (scores[title_key(song["title"])], song["playcount"]),
        reverse=True,
    )


def rank_songs(rankings: list[tuple[float, list]], songs: list[dict]) -> list[dict]:
    """
    Songs by their fused score over rankings, then played songs, most played first;
    one per title, earliest release unless an MBID matched; [] if no ranking matches.

    :param rankings: (weight, [recording MBID, title, …] rows best first) pairs.
    :param songs: Library songs with SONG_RANK_PROPERTIES.
    :return: Ranked songs.
    """
    scores, shown = scored_songs(rankings, songs)
    if not scores:
        return []
    played = filter(itemgetter("playcount"), songs)  # most played; earliest release
    for song in sorted(played, key=lambda s: (-s["playcount"], s["year"] or 9999)):
        shown.setdefault(title_key(song["title"]), song)
    return _by_score(scores, shown.values())


def song_place(
    rankings: list[tuple[float, list]], songs: list[dict], title: str
) -> int:
    """
    A title's place in Top songs (rank_songs), counting only songs a ranking scores:
    a played song topping the list up takes no place.

    :param rankings: (weight, [recording MBID, title, …] rows best first) pairs.
    :param songs: Library songs with ALBUM_SONG_PROPERTIES and playcount.
    :param title: The song's title.
    :return: 1 to PLACES; 0 when lower or unscored.
    """
    scores, shown = scored_songs(rankings, songs)
    ranked = [title_key(song["title"]) for song in _by_score(scores, shown.values())]
    key = title_key(title)
    return ranked.index(key) + 1 if key in ranked[:PLACES] else 0


def album_credit(
    rankings: list[tuple[float, list]], songs: list[dict], albums: list[dict]
) -> Counter:
    """
    Each album's summed Top songs scores of its songs over rankings; only these
    albums' songs stand for a title.

    :param rankings: (weight, [recording MBID, title, …] rows best first) pairs.
    :param songs: Library songs with ALBUM_SONG_PROPERTIES.
    :param albums: Library albums with albumid.
    :return: Score per albumid; 0 for an album no ranking credits.
    """
    ids = {album["albumid"] for album in albums}
    songs = [song for song in songs if song["albumid"] in ids]
    scores, shown = scored_songs(rankings, songs)
    credit = Counter()
    for key, song in shown.items():
        credit[song["albumid"]] += scores[key]
    return credit


def rank_albums(
    rankings: list[tuple[float, list]], songs: list[dict], albums: list[dict]
) -> list[dict]:
    """
    Albums by the summed Top songs scores of their songs over rankings (album_credit),
    then the unranked; newest first among equals.

    :param rankings: (weight, [recording MBID, title, …] rows best first) pairs.
    :param songs: Library songs with ALBUM_SONG_PROPERTIES.
    :param albums: Library albums with albumid and year.
    :return: Ranked albums, all of them.
    """
    credit = album_credit(rankings, songs, albums)
    return sorted(
        sorted(albums, key=itemgetter("year"), reverse=True),
        key=lambda album: credit[album["albumid"]],
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


def artist_names(parent: str, album_artists: bool = False) -> dict[str, str]:
    """
    Every library artist's name by its folded form, as Kodi's *Show song and album
    artists* setting lists them, or album artists alone (a mix's: their own albums).

    :param parent: Caller name for logging.
    :param album_artists: Album artists alone, whatever the setting.
    :return: {fold(name): name}.
    """
    rows = json_call(
        "AudioLibrary.GetArtists",
        params={"albumartistsonly": True} if album_artists else None,
        parent=parent,
    )["result"].get("artists", [])
    return {fold(row["artist"]): row["artist"] for row in rows}


def artist_places(parent: str) -> list[int]:
    """
    The library's most played artists, by their songs' summed play counts (a duet
    counts for each); worked out once a day.

    :param parent: Caller name for logging.
    :return: Up to PLACES library artist ids, most played first.
    """
    from resources.lib.apis.cache import DAY, cached

    def count() -> list[int]:
        plays = Counter()
        played = {"field": "playcount", "operator": "greaterthan", "value": "0"}
        for song in library_rows(
            "song", played, None, None, parent, ["artistid", "playcount"]
        ):
            plays.update(dict.fromkeys(song["artistid"], song["playcount"]))
        return [artistid for artistid, _ in plays.most_common(PLACES)]

    return cached("library:artist-places", count, (DAY, DAY))


def play_place(plays: Counter, key: int | str) -> int:
    """
    A key's place by plays among two or more, within PLACES: only a clear one, so
    none when it is unplayed or another key has as many plays (a tie).

    :param plays: Plays per key, unplayed keys at 0.
    :param key: The item's key.
    :return: 1 to PLACES; 0 otherwise.
    """
    counts = sorted(plays.values(), reverse=True)
    count = plays[key]
    if len(counts) < 2 or not count or counts.count(count) > 1:
        return 0
    place = counts.index(count) + 1
    return place if place <= PLACES else 0


def song_play_place(songs: list[dict], title: str) -> int:
    """
    A title's place among songs' titles by plays (play_place), its versions' plays
    summed as one song.

    :param songs: Library songs with playcount and title.
    :param title: The song's title.
    :return: 1 to PLACES; 0 otherwise.
    """
    plays = Counter()
    for song in songs:
        plays[title_key(song["title"])] += song["playcount"]
    del plays[""]  # titles of symbols only: no one song
    return play_place(plays, title_key(title))


def similar_artists(
    artistid: int, parent: str, owned: dict[str, str] | None = None
) -> list[str]:
    """
    Library artists like library artist artistid: Deezer's related ones in its order
    and ListenBrainz's (a random sample, so each at the middle place), by WEIGHTS.

    :param artistid: Library artist id.
    :param parent: Caller name for logging.
    :param owned: artist_names, when several lookups share it; None to fetch it.
    :return: Library artist names, closest first, its own left out; [] with no source.
    """
    from resources.lib.apis import deezer, listenbrainz

    name, mbid = artist_identity(artistid, parent)
    scores = Counter()
    if deezer.enabled():  # its songs are read only to check a first Deezer match
        songs = cache(
            lambda: library_rows(
                "song", {"artistid": artistid}, None, None, parent, ["album", "title"]
            )
        )
        related = deezer.related(
            deezer.artist_key(mbid, name),
            name,
            lambda rows: deezer_match(songs(), rows),
        )
        scores = fused([(WEIGHTS["deezer"], map(fold, related))])
    if mbid and listenbrainz.enabled():
        similar = dict.fromkeys(map(fold, listenbrainz.similar_artists(mbid)))
        middle = WEIGHTS["listenbrainz"] / (K + (len(similar) + 1) / 2)
        scores.update(dict.fromkeys(similar, middle))
    scores.pop(fold(name), None)
    if not scores:
        return []
    owned = owned or artist_names(parent)
    ranked = sorted(scores, key=scores.get, reverse=True)
    return [owned[key] for key in ranked if key in owned]


def similar_to(
    names: list[str],
    parent: str,
    owned: Callable[[], dict[str, str]] | None = None,
) -> list[str]:
    """
    Library artists like all of these library artists, fused (similar_artists each),
    the artists themselves left out: a genre mix's, from its leads.

    :param names: Library artist names.
    :param parent: Caller name for logging.
    :param owned: Returns artist_names(album_artists=True), shared; None to fetch it.
    :return: Library artist names, closest first.
    """
    rows = json_call(
        "AudioLibrary.GetArtists",
        query_filter={"field": "artist", "operator": "is", "value": names},
        params={"albumartistsonly": False},
        parent=parent,
    )["result"].get("artists", [])
    owned = owned() if owned else artist_names(parent, album_artists=True)
    scores = fused((1, similar_artists(row["artistid"], parent, owned)) for row in rows)
    return [artist for artist, _ in scores.most_common() if artist not in names]


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
