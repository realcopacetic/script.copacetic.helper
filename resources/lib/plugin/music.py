# author: realcopacetic

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
