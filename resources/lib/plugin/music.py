# author: realcopacetic

from pathlib import PurePosixPath

from xbmc import getLocalizedString
from xbmcgui import ListItem

from resources.lib.plugin.library import DirectoryItem
from resources.lib.plugin.setter import apply_musicinfotag
from resources.lib.shared.utilities import json_call

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


def dial_item(entry: dict, pinned: bool) -> DirectoryItem | None:
    """
    A speed dial entry as a directory item: songs play their file, the rest
    open as folders. Pinned items get Move up/down rows; Unpin is addon.xml's.

    :param entry: Speed dial entry (type, ref).
    :param pinned: Whether the entry is pinned.
    :return: (path, ListItem, is_folder), or None if the library lost the item.
    """
    type, ref = entry["type"], entry["ref"]
    if type == "playlist":
        li = ListItem(PurePosixPath(ref).stem, offscreen=True)
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
        li = ListItem(details["label"], offscreen=True)
        li.setArt(details["art"])
        apply_musicinfotag(li, details, type)
        path = details["file"] if type == "song" else f"musicdb://{type}s/{ref}/"
        args = f"type={type},id={ref}"
    li.setArt({"icon": _ICONS[type]})
    if pinned:
        run = f"RunScript(script.copacetic.helper,{args},action="
        li.addContextMenuItems(
            [
                (getLocalizedString(13332), f"{run}move_pin,offset=-1)"),
                (getLocalizedString(13333), f"{run}move_pin,offset=1)"),
            ]
        )
    return path, li, type != "song"
