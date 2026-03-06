# author: realcopacetic

import xml.etree.ElementTree as ETree

import xbmc
import xbmcvfs
from xbmcgui import Dialog, DialogProgress

from resources.lib.shared.utilities import json_call

# ---------------------------------------------------------------------------
# Localisation
# Replace any value with xbmc.getLocalizedString(id) to localise.
# ---------------------------------------------------------------------------

STRINGS = {
    "video_library": "Video Library",
    "music_library": "Music Library",
    "video_playlists": "Video Playlists",
    "music_playlists": "Music Playlists",
    "addons": "Add-ons",
    "custom_path": "Custom path...",
    "video_addons": "Video add-ons",
    "music_addons": "Music add-ons",
    "program_addons": "Program add-ons",
    "picture_addons": "Picture add-ons",
    "back": "..",
    "use_this_path": "Use this path",
    "my_playlists": "My Playlists",
    "skin_playlists": "Skin Playlists",
    "finding_playlists": "Finding playlists...",
    "no_playlists_found": "No playlists found",
    "getting_directory": "Getting directory listing...",
    "enter_path": "Enter content path",
    "select_content": "Select content",
}

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TOP_LEVEL = [
    (STRINGS["video_library"], "library://video/"),
    (STRINGS["music_library"], "library://music/"),
    (STRINGS["video_playlists"], None),
    (STRINGS["music_playlists"], None),
    (STRINGS["addons"], None),
    (STRINGS["custom_path"], None),
]

ADDON_SOURCES = [
    (STRINGS["video_addons"], "addons://sources/video"),
    (STRINGS["music_addons"], "addons://sources/audio"),
    (STRINGS["program_addons"], "addons://sources/executable"),
    (STRINGS["picture_addons"], "addons://sources/image"),
]

# Playlist source paths per media type.
# "my"   — user playlists (flat, single directory)
# "skin" — skinner-provided playlists (walked recursively)
_PLAYLIST_SOURCES = {
    "video": {
        "my": ["special://videoplaylists/"],
        "skin": ["special://skin/playlists/", "special://skin/extras/"],
    },
    "music": {
        "my": ["special://musicplaylists/"],
        "skin": ["special://skin/playlists/", "special://skin/extras/"],
    },
}

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BACK = STRINGS["back"]
_USE_PATH = STRINGS["use_this_path"]

# Returned by _browse_level when the user presses "..".
# Distinct from None (hard cancel / dialog dismissed).
_BACK_SENTINEL = object()

# videodb:// and musicdb:// are direct content endpoints — never fetched.
_ENDPOINT_PREFIXES = ("videodb://", "musicdb://")

# Paths where "Use this path" is suppressed in widget mode.
_NO_USE_PATH = {
    "library://video/",
    "library://music/",
    "special://videoplaylists/",
    "special://musicplaylists/",
}

# library:// nodes that are navigable containers but not useful as widget paths.
_NO_USE_PATH_XML = {
    "library://video/playlists.xml/",
    "library://music/playlists.xml/",
    "library://video/files.xml/",
    "library://music/files.xml/",
}

# Items suppressed from library listings — handled by dedicated top-level entries.
_SUPPRESS_ITEMS = {
    "library://video/playlists.xml/",
    "library://music/playlists.xml/",
    "library://video/addons.xml/",
    "library://music/addons.xml/",
    "library://video/files.xml/",
    "library://music/files.xml/",
}

# library:// node paths (by suffix) whose contents are always flat media items.
# In widget mode these are returned as endpoints without fetching.
_FLAT_XML_SUFFIXES = {
    "titles.xml/",
    "recentlyaddedmovies.xml/",
    "recentlyaddedepisodes.xml/",
    "recentlyaddedmusicvideos.xml/",
    "inprogressmovies.xml/",
    "inprogressepisodes.xml/",
}

# Ordered prefix → content type mapping for _derive_type().
_PATH_TYPE_PREFIXES = [
    ("videodb://movies/", "movies"),
    ("videodb://tvshows/", "tvshows"),
    ("videodb://musicvideos/", "musicvideos"),
    ("videodb://recentlyadded", "mixed"),
    ("videodb://inprogress", "mixed"),
    ("library://video/movies/", "movies"),
    ("library://video/tvshows/", "tvshows"),
    ("library://video/musicvideos/", "musicvideos"),
    ("library://video/recentlyadded/", "mixed"),
    ("library://video/inprogress/", "mixed"),
    ("library://video/", "video"),
    ("musicdb://", "music"),
    ("library://music/", "music"),
    ("addons://sources/video", "video"),
    ("addons://sources/audio", "music"),
    ("addons://sources/executable", "programs"),
    ("addons://sources/image", "pictures"),
]

_MUSIC_TYPES = {"music", "albums", "artists", "songs"}
_PROGRAM_TYPES = {"programs"}
_PICTURE_TYPES = {"pictures"}

# Content type → Kodi default icon
_TYPE_ICON = {
    "movies": "DefaultMovies.png",
    "tvshows": "DefaultTVShows.png",
    "musicvideos": "DefaultMusicVideos.png",
    "mixed": "DefaultVideo.png",
    "video": "DefaultVideo.png",
    "music": "DefaultMusicAlbums.png",
    "albums": "DefaultMusicAlbums.png",
    "artists": "DefaultArtist.png",
    "songs": "DefaultMusicSongs.png",
    "programs": "DefaultProgram.png",
    "pictures": "DefaultPicture.png",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_endpoint(path):
    """
    Return True if path is a content endpoint that should be returned directly
    without fetching or drilling into.

    - videodb:// / musicdb://  — direct database content paths
    - *.xsp / *.m3u            — smart playlist / music playlist files
    """
    return (
        any(path.startswith(p) for p in _ENDPOINT_PREFIXES)
        or path.endswith(".xsp")
        or path.endswith(".m3u")
    )


def _is_known_flat(path):
    """
    Return True if path is a known flat content node (titles, recently added,
    etc.). In widget mode these are returned as endpoints without fetching.
    """
    return any(path.endswith(suffix) for suffix in _FLAT_XML_SUFFIXES)


def _is_flat_content(items):
    """
    Return True if fetched items represent flat content rather than navigation
    nodes. Fallback for paths not covered by _is_known_flat.
    """
    return bool(items) and any(
        item.get("type", "unknown") != "unknown" for item in items
    )


def _fetch_raw(path):
    """Fetch a directory listing without a progress dialog."""
    params = {"directory": path}
    if not path.startswith("special://"):
        params["media"] = "files"
    result = json_call(
        "Files.GetDirectory",
        properties=["thumbnail"],
        params=params,
        parent="browse_content",
    )
    return result.get("result", {}).get("files", [])


def _get_directory(path, heading):
    """Fetch a directory listing via JSON-RPC, showing a progress dialog."""
    params = {"directory": path}
    if not path.startswith("special://"):
        params["media"] = "files"

    progress = DialogProgress()
    progress.create(heading, STRINGS["getting_directory"])
    result = json_call(
        "Files.GetDirectory",
        properties=["thumbnail"],
        params=params,
        parent="browse_content",
    )
    progress.close()
    return result.get("result", {}).get("files", [])


def _walk_playlists(path):
    """
    Recursively collect .xsp and .m3u items from *path*.
    Mirrors skinshortcuts' kodiwalk().
    """
    items = []
    for item in _fetch_raw(path):
        f = item["file"]
        if f.endswith((".xsp", ".m3u")):
            items.append(item)
        elif item["filetype"] == "directory" and not f.endswith((".xml/", ".xml")):
            items.extend(_walk_playlists(f))
    return items


def _read_xsp_type(path):
    """
    Read the smartplaylist type attribute from an .xsp file.
    Returns the type string or "unknown" on any failure.
    """
    try:
        translated = xbmcvfs.translatePath(path)
        with xbmcvfs.File(translated) as f:
            data = f.read()
        root = ETree.fromstring(data)
        if root.tag == "smartplaylist":
            return root.attrib.get("type", "unknown")
    except Exception:
        pass
    return "unknown"


def _derive_type(path):
    """Derive the content type string for a path."""
    if path.endswith(".xsp"):
        return _read_xsp_type(path)
    for prefix, content_type in _PATH_TYPE_PREFIXES:
        if path.startswith(prefix):
            return content_type
    return "unknown"


def _derive_window(content_type):
    """Return the Kodi window name for a given content type."""
    if content_type in _MUSIC_TYPES:
        return "Music"
    if content_type in _PROGRAM_TYPES:
        return "Programs"
    if content_type in _PICTURE_TYPES:
        return "Pictures"
    return "Videos"


def _build_result(path, label, mode):
    """
    Build the final return value for a selected path.

    Both modes return a dict so callers always have a consistent structure.

    widget: {"path", "label", "icon"}
    menu:   {"path", "label", "icon", "type", "window", "action"}
    """
    content_type = _derive_type(path)
    icon = _TYPE_ICON.get(content_type, "DefaultFolder.png")
    result = {"path": path, "label": label, "icon": icon}

    if mode == "menu":
        window = _derive_window(content_type)
        result.update(
            {
                "type": content_type,
                "window": window,
                "action": 'ActivateWindow(%s,"%s",return)' % (window, path),
            }
        )

    return result


# ---------------------------------------------------------------------------
# Browser
# ---------------------------------------------------------------------------


def _browse_level(path, heading, mode="widget"):
    """
    Show a select dialog for *path* and handle user navigation.

    Returns:
        (path, label)  — selected content path and its display label
        _BACK_SENTINEL — user pressed ".."
        None           — dialog dismissed (hard cancel)

    Label semantics:
      - Endpoint / known flat / empty directory → heading (the node name)
      - "Use this path" selected               → heading
      - File item selected                     → item["label"]
      - Directory drilled into                 → label propagated from sub-level
    """
    while True:
        if _is_endpoint(path):
            return path, heading

        if mode == "widget" and _is_known_flat(path):
            return path, heading

        items = _get_directory(path, heading)

        if not items:
            return path, heading

        if mode == "widget" and _is_flat_content(items):
            return path, heading

        items = [item for item in items if item["file"] not in _SUPPRESS_ITEMS]

        suppress_use_path = mode == "widget" and (
            path in _NO_USE_PATH or path in _NO_USE_PATH_XML
        )
        labels = [_BACK]
        if not suppress_use_path:
            labels.append(_USE_PATH)
        offset = len(labels)

        for item in items:
            label = item["label"]
            if item["filetype"] == "directory" and not _is_endpoint(item["file"]):
                label += "  >"
            labels.append(label)

        idx = Dialog().select(heading, labels)

        if idx == -1:
            return None

        if idx == 0:
            return _BACK_SENTINEL

        if not suppress_use_path and idx == 1:
            return path, heading

        selected = items[idx - offset]

        if selected["filetype"] != "directory":
            return selected["file"], selected["label"]

        next_path = selected["file"]

        if next_path == path:
            return next_path, selected["label"]

        result = _browse_level(next_path, selected["label"], mode)
        if result is _BACK_SENTINEL:
            continue
        return result  # (path, label) or None — propagate as-is


def _browse_playlist_list(playlist_items, heading):
    """
    Show a flat select dialog listing *playlist_items*.

    Returns (path, label), _BACK_SENTINEL, or None.
    """
    labels = [_BACK] + [item["label"] for item in playlist_items]
    idx = Dialog().select(heading, labels)

    if idx == -1:
        return None
    if idx == 0:
        return _BACK_SENTINEL

    item = playlist_items[idx - 1]
    return item["file"], item["label"]


def _browse_playlists(media, heading):
    """
    Show a 'My Playlists / Skin Playlists' sub-picker, then a flat playlist list.
    Returns (path, label), or None.
    """
    sources = _PLAYLIST_SOURCES[media]

    while True:
        labels = [
            _BACK,
            STRINGS["my_playlists"] + "  >",
            STRINGS["skin_playlists"] + "  >",
        ]
        idx = Dialog().select(heading, labels)

        if idx == -1:
            return None

        if idx == 0:
            return None  # ".." — back to top-level picker

        paths = sources["my"] if idx == 1 else sources["skin"]

        progress = DialogProgress()
        progress.create(heading, STRINGS["finding_playlists"])
        playlist_items = []
        for path in paths:
            playlist_items.extend(_walk_playlists(path))
        progress.close()

        if not playlist_items:
            Dialog().notification(heading, STRINGS["no_playlists_found"], time=2000)
            continue

        result = _browse_playlist_list(playlist_items, heading)

        if result is _BACK_SENTINEL:
            continue
        return result  # (path, label) or None


def _browse_addons(heading, mode="widget"):
    """
    Show the add-on type picker, then browse the chosen source.
    Returns (path, label), or None.
    """
    while True:
        labels = [_BACK] + [label + "  >" for label, _ in ADDON_SOURCES]
        idx = Dialog().select(heading, labels)

        if idx == -1:
            return None

        if idx == 0:
            return None  # ".." — back to top-level picker

        label, path = ADDON_SOURCES[idx - 1]
        result = _browse_level(path, label, mode)

        if result is _BACK_SENTINEL:
            continue
        return result  # (path, label) or None


def _custom_path():
    """
    Open a keyboard dialog and return (path, "") or None.
    Label is empty — the user typed a raw path with no associated name.
    """
    kb = xbmc.Keyboard("", STRINGS["enter_path"])
    kb.doModal()
    if kb.isConfirmed():
        text = kb.getText().strip()
        if text:
            return text, ""
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def browse_content(cfg):
    """
    Entry point for content path browsing.

    Called from OnClickActions.browse_content().

    :param cfg: Control onclick config dict. Supports:
                  heading    (str) — dialog title (default: "Select content")
                  mode       (str) — "widget" (default) or "menu"
                  label_field (str) — optional sibling field name to populate
                                      with the selected label (handled by caller)

    :return:
      Both modes return a dict, or None if cancelled:

      widget: {"path": str, "label": str}

      menu:   {"path": str, "label": str,
               "type": str, "window": str, "action": str}

      The caller (onclick_actions) uses "label_field" from cfg to decide
      whether to also write the label to a sibling runtime field.
    """
    heading = cfg.get("heading", STRINGS["select_content"])
    mode = cfg.get("mode", "widget")

    while True:
        labels = [
            label + ("" if label == STRINGS["custom_path"] else "  >")
            for label, _ in TOP_LEVEL
        ]
        idx = Dialog().select(heading, labels)

        if idx == -1:
            return None

        label, path = TOP_LEVEL[idx]

        if label == STRINGS["video_playlists"]:
            result = _browse_playlists("video", heading)
        elif label == STRINGS["music_playlists"]:
            result = _browse_playlists("music", heading)
        elif label == STRINGS["addons"]:
            result = _browse_addons(heading, mode)
        elif label == STRINGS["custom_path"]:
            result = _custom_path()
        else:
            result = _browse_level(path, label, mode)
            if result is _BACK_SENTINEL:
                result = None

        if result is None:
            continue

        path, label = result
        return _build_result(path, label, mode)
