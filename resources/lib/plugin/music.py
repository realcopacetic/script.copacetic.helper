# author: realcopacetic

import re
import unicodedata
from itertools import chain
from operator import itemgetter
from pathlib import PurePosixPath

from xbmc import getLocalizedString
from xbmcgui import ListItem

from resources.lib.plugin.library import DirectoryItem
from resources.lib.plugin.setter import apply_musicinfotag
from resources.lib.shared.utilities import ADDON, json_call

_DETAILS = {
    "album": (
        "AudioLibrary.GetAlbumDetails",
        ["artist", "genre", "title", "userrating", "year"],
    ),
    "artist": ("AudioLibrary.GetArtistDetails", ["genre"]),
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
_MBIDS = {  # MusicBrainz entity and AudioLibrary field per library type
    "album": ("release-group", "musicbrainzreleasegroupid"),
    "artist": ("artist", "musicbrainzartistid"),
    "song": ("recording", "musicbrainztrackid"),
}
ALBUM_RANK_PROPERTIES = [*_DETAILS["album"][1], "art", "musicbrainzreleasegroupid"]
SONG_RANK_PROPERTIES = [*_DETAILS["song"][1], "art", "musicbrainztrackid", "playcount"]
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
    if type == "song":
        return details["file"], li, False
    return f"musicdb://{type}s/{details[f'{type}id']}/", li, True


def musicbrainz_id(type: str, dbid: int, parent: str) -> tuple[str, str]:
    """
    A library album, artist or song's MusicBrainz entity and id: its release group,
    first artist id or recording (Picard's "MusicBrainz Track Id").

    :param type: album, artist or song.
    :param dbid: Library id.
    :param parent: Caller name for logging.
    :return: (entity, MBID), the MBID empty when untagged.
    """
    entity, field = _MBIDS[type]
    mbid = json_call(
        _DETAILS[type][0],
        properties=[field],
        params={f"{type}id": dbid},
        parent=parent,
    )["result"][f"{type}details"][field]
    # An artist's is a one-id list, [""] when untagged
    return entity, mbid[0] if type == "artist" else mbid


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


def title_key(title: str) -> str:
    """
    A song title reduced for matching across sources: no trailing "(feat. …)",
    "[Remaster]" or " - Live" part, and no case, accents or punctuation.

    :param title: Song title.
    :return: Matching key.
    """
    title = re.sub(r"(?<=\S)\s*[(\[].*|\s+-\s.*", "", title.casefold())
    return "".join(c for c in unicodedata.normalize("NFKD", title) if c.isalnum())


def rank_songs(recordings: list[list[str]], songs: list[dict]) -> list[dict]:
    """
    Songs matching recordings (by recording MBID, else title) in their order, then
    played songs, most played first; one per title, earliest release; [] if no match.

    :param recordings: [recording MBID, title] pairs, most popular first.
    :param songs: Library songs with musicbrainztrackid, playcount, title and year.
    :return: Ranked songs.
    """
    songs = sorted(songs, key=lambda song: song["year"] or 9999)  # undated last
    by_mbid, by_title = {}, {}
    for song in songs:
        by_mbid.setdefault(song["musicbrainztrackid"], song)
        by_title.setdefault(title_key(song["title"]), song)
    by_mbid.pop("", None)  # untagged songs
    popular = [
        song
        for mbid, title in recordings
        if (song := by_mbid.get(mbid) or by_title.get(title_key(title)))
    ]
    if not popular:
        return []
    played = sorted(
        filter(itemgetter("playcount"), songs),
        key=itemgetter("playcount"),
        reverse=True,
    )
    ranked = {}
    for song in chain(popular, played):
        ranked.setdefault(title_key(song["title"]), song)
    return [*ranked.values()]


def rank_albums(groups: list[list[str]], albums: list[dict]) -> list[dict]:
    """
    Albums in the order of release groups they match (by release group MBID, else
    title), then the unmatched; newest first within each.

    :param groups: [release group MBID, title] pairs, most popular first.
    :param albums: Library albums with musicbrainzreleasegroupid, title and year.
    :return: Ranked albums.
    """
    by_mbid, by_title = {}, {}
    for rank, (mbid, title) in enumerate(groups):
        by_mbid.setdefault(mbid, rank)
        by_title.setdefault(title_key(title), rank)
    unmatched = len(groups)
    return sorted(
        sorted(albums, key=itemgetter("year"), reverse=True),
        key=lambda album: by_mbid.get(
            album["musicbrainzreleasegroupid"],
            by_title.get(title_key(album["title"]), unmatched),
        ),
    )


def library_rows(
    type: str,
    query_filter: dict,
    sort: dict | None,
    limit: int | None,
    parent: str,
    properties: list[str] | None = None,
) -> list[dict]:
    """
    AudioLibrary albums, artists or songs matching query_filter, with _DETAILS
    properties and art unless properties says otherwise.

    :param type: album, artist or song.
    :param query_filter: AudioLibrary filter, a rule tree or an id filter.
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
        method, properties = _DETAILS[type]
        details = (
            json_call(
                method,
                properties=[*properties, "art"],
                params={f"{type}id": int(ref)},
                parent="speed_dial",
            )
            .get("result", {})
            .get(f"{type}details")
        )
        if not details:
            return None
        path, li, _ = library_item(details, type)
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
