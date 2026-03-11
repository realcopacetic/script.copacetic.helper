# author: realcopacetic

import xml.etree.ElementTree as ETree

import xbmc
import xbmcvfs
from xbmcgui import Dialog, DialogProgress

from resources.lib.shared.utilities import ADDON, json_call


# ---------------------------------------------------------------------------
# Localisation
# ---------------------------------------------------------------------------


def _L(string_id):
    """
    Resolve an addon localised string by ID.

    :param string_id: Addon string ID (32xxx range).
    :return: Localised string.
    """
    return ADDON.getLocalizedString(string_id)


# Module-level caches — populated on first use so Kodi's language system
# is fully initialised before any getLocalizedString() calls.
_strings = None
_top_level = None
_menu_extra = None
_addon_sources = None


def _get_strings():
    """
    Build and cache the localised strings dict.

    :return: Dict of string keys to localised values.
    """
    global _strings
    if _strings is None:
        _strings = {
            "video_library": xbmc.getLocalizedString(14236),  # Video library
            "music_library": xbmc.getLocalizedString(14237),  # Music library
            "video_playlists": xbmc.getLocalizedString(20012),  # Video playlists
            "music_playlists": xbmc.getLocalizedString(20011),  # Music playlists
            "addons": xbmc.getLocalizedString(24001),  # Add-ons
            "custom_path": _L(32804),  # Custom path...
            "video_addons": xbmc.getLocalizedString(1037),  # Video add-ons
            "music_addons": xbmc.getLocalizedString(1038),  # Music add-ons
            "program_addons": xbmc.getLocalizedString(1043),  # Program add-ons
            "picture_addons": xbmc.getLocalizedString(1039),  # Picture add-ons
            "back": "..",
            "use_this_path": _L(32809),  # Use this path
            "my_playlists": _L(32810),  # My playlists
            "skin_playlists": _L(32811),  # Skin playlists
            "finding_playlists": _L(32812),  # Finding playlists...
            "no_playlists_found": _L(32813),  # No playlists found
            "no_favourites_found": _L(32814),  # No favourites found
            "getting_directory": _L(32815),  # Getting directory listing...
            "enter_path": _L(32816),  # Enter content path
            "select_content": _L(32817),  # Select content
            "common": _L(32818),  # Common
            "settings": xbmc.getLocalizedString(5),  # Settings
            "favourites": xbmc.getLocalizedString(1036),  # Favourites
            "kodi_commands": _L(32819),  # Kodi commands
        }
    return _strings


def _get_top_level():
    """
    Build and cache the top-level source list.

    :return: List of (label, path) tuples.
    """
    global _top_level
    if _top_level is None:
        s = _get_strings()
        _top_level = [
            (s["video_library"], "library://video/"),
            (s["music_library"], "library://music/"),
            (s["video_playlists"], None),
            (s["music_playlists"], None),
            (s["addons"], None),
            (s["custom_path"], None),
        ]
    return _top_level


def _get_menu_extra():
    """
    Build and cache the menu-mode extra source list.

    :return: List of (label, path) tuples.
    """
    global _menu_extra
    if _menu_extra is None:
        s = _get_strings()
        _menu_extra = [
            (s["common"], None),
            (s["settings"], None),
            (s["favourites"], None),
            (s["kodi_commands"], None),
        ]
    return _menu_extra


def _get_addon_sources():
    """
    Build and cache the addon source list.

    :return: List of (label, path) tuples.
    """
    global _addon_sources
    if _addon_sources is None:
        s = _get_strings()
        _addon_sources = [
            (s["video_addons"], "addons://sources/video"),
            (s["music_addons"], "addons://sources/audio"),
            (s["program_addons"], "addons://sources/executable"),
            (s["picture_addons"], "addons://sources/image"),
        ]
    return _addon_sources


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

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
# Menu-mode static shortcut sources
# ---------------------------------------------------------------------------

_COMMON_SHORTCUTS = [
    (
        xbmc.getLocalizedString(3),
        "ActivateWindow(Videos)",
        "DefaultVideo.png",
    ),  # Videos
    (
        xbmc.getLocalizedString(342),
        "ActivateWindow(Videos,videodb://movies/titles/,return)",
        "DefaultMovies.png",
    ),  # Movies
    (
        xbmc.getLocalizedString(20343),
        "ActivateWindow(Videos,videodb://tvshows/titles/,return)",
        "DefaultTVShows.png",
    ),  # TV Shows
    (
        xbmc.getLocalizedString(19020),
        "ActivateWindow(TVChannels)",
        "DefaultTVShows.png",
    ),  # Live TV
    (
        xbmc.getLocalizedString(19021),
        "ActivateWindow(RadioChannels)",
        "DefaultAudio.png",
    ),  # Radio
    (
        xbmc.getLocalizedString(2),
        "ActivateWindow(Music,musicdb://,return)",
        "DefaultMusicAlbums.png",
    ),  # Music
    (
        xbmc.getLocalizedString(20389),
        "ActivateWindow(Videos,videodb://musicvideos/titles/,return)",
        "DefaultMusicVideos.png",
    ),  # Music Videos
    (
        xbmc.getLocalizedString(589),
        "PlayerControl(PartyMode)",
        "DefaultAudio.png",
    ),  # Party Mode
    (
        xbmc.getLocalizedString(589) + " (" + xbmc.getLocalizedString(20389) + ")",
        "PlayerControl(PartyMode(video))",
        "DefaultMusicVideos.png",
    ),  # Party Mode (Music Videos)
    (
        xbmc.getLocalizedString(1),
        "ActivateWindow(Pictures)",
        "DefaultPicture.png",
    ),  # Pictures
    (
        xbmc.getLocalizedString(8),
        "ActivateWindow(Weather)",
        "DefaultAddonWeather.png",
    ),  # Weather
    (
        xbmc.getLocalizedString(350),
        "ActivateWindow(Programs)",
        "DefaultProgram.png",
    ),  # Programs
    (xbmc.getLocalizedString(341), "PlayDVD", "DefaultDVDFull.png"),  # Play disc
    (xbmc.getLocalizedString(13391), "EjectTray()", "DefaultDVDFull.png"),  # Eject Tray
    (
        xbmc.getLocalizedString(5),
        "ActivateWindow(Settings)",
        "DefaultAddon.png",
    ),  # Settings
    (
        xbmc.getLocalizedString(7),
        "ActivateWindow(FileManager)",
        "DefaultFolder.png",
    ),  # File manager
    (
        xbmc.getLocalizedString(13200),
        "ActivateWindow(LoginScreen)",
        "DefaultUser.png",
    ),  # Profiles
    (
        xbmc.getLocalizedString(10007),
        "ActivateWindow(SystemInformation)",
        "DefaultAddon.png",
    ),  # System information
    (
        xbmc.getLocalizedString(14111),
        "ActivateWindow(EventLog)",
        "DefaultAddon.png",
    ),  # Events
    (
        xbmc.getLocalizedString(10134),
        "ActivateWindow(Favourites)",
        "DefaultFavourites.png",
    ),  # Favourites
]

_SETTINGS_SHORTCUTS = [
    (
        xbmc.getLocalizedString(14200),
        "ActivateWindow(Settings,player)",
        "DefaultAddon.png",
    ),  # Player
    (
        xbmc.getLocalizedString(14201),
        "ActivateWindow(Settings,media)",
        "DefaultAddon.png",
    ),  # Media
    (
        xbmc.getLocalizedString(19180),
        "ActivateWindow(Settings,pvr)",
        "DefaultAddon.png",
    ),  # PVR & Live TV
    (
        xbmc.getLocalizedString(14206),
        "ActivateWindow(Settings,interface)",
        "DefaultAddon.png",
    ),  # Interface
    (
        xbmc.getLocalizedString(14036),
        "ActivateWindow(Settings,services)",
        "DefaultAddon.png",
    ),  # Services
    (
        xbmc.getLocalizedString(13000),
        "ActivateWindow(Settings,system)",
        "DefaultAddon.png",
    ),  # System
    (
        xbmc.getLocalizedString(10035),
        "ActivateWindow(SkinSettings)",
        "DefaultAddon.png",
    ),  # Skin Settings
]

_KODI_COMMANDS = [
    (xbmc.getLocalizedString(13013), "Reboot", "DefaultShortcut.png"),  # Reboot
    (xbmc.getLocalizedString(13005), "Shutdown", "DefaultShortcut.png"),  # Shut down
    (xbmc.getLocalizedString(13016), "Powerdown", "DefaultShortcut.png"),  # Power off
    (xbmc.getLocalizedString(13009), "Quit", "DefaultShortcut.png"),  # Quit
    (xbmc.getLocalizedString(13010), "Hibernate", "DefaultShortcut.png"),  # Hibernate
    (xbmc.getLocalizedString(13011), "Suspend", "DefaultShortcut.png"),  # Suspend
    (
        xbmc.getLocalizedString(19026),
        "ShutdownTimer",
        "DefaultShortcut.png",
    ),  # Add timer...
    (
        xbmc.getLocalizedString(20151),
        "CancelShutdownTimer",
        "DefaultShortcut.png",
    ),  # Cancel shutdown timer
    (
        xbmc.getLocalizedString(356),
        "ActivateScreensaver",
        "DefaultShortcut.png",
    ),  # Screensaver mode
    (xbmc.getLocalizedString(13014), "Minimize", "DefaultShortcut.png"),  # Minimise
    (
        xbmc.getLocalizedString(20045),
        "MasterMode",
        "DefaultShortcut.png",
    ),  # Master mode
    (
        xbmc.getLocalizedString(653),
        "UpdateLibrary(video)",
        "DefaultMovies.png",
    ),  # Update video library
    (
        xbmc.getLocalizedString(654),
        "UpdateLibrary(music)",
        "DefaultMusicAlbums.png",
    ),  # Update music library
    (
        xbmc.getLocalizedString(334) + " (" + xbmc.getLocalizedString(3) + ")",
        "CleanLibrary(video)",
        "DefaultMovies.png",
    ),  # Clean library... (Videos)
    (
        xbmc.getLocalizedString(334) + " (" + xbmc.getLocalizedString(2) + ")",
        "CleanLibrary(music)",
        "DefaultMusicAlbums.png",
    ),  # Clean library... (Music)
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Returned by _browse_level when the user presses "..".
# Distinct from None (hard cancel / dialog dismissed).
_BACK_SENTINEL = object()

# videodb:// and musicdb:// are direct content endpoints — never fetched.
_ENDPOINT_PREFIXES = ("videodb://", "musicdb://")

# Known URL scheme prefixes for real paths (vs action/command strings).
_PATH_SCHEMES = (
    "library://",
    "videodb://",
    "musicdb://",
    "plugin://",
    "special://",
    "addons://",
    "nfs://",
    "smb://",
    "http://",
    "https://",
    "ftp://",
    "upnp://",
)

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

# item type → library path template for constructing db paths from individual items.
_LIBRARY_PATH_MAP = {
    "movie": "videodb://movies/titles/{id}/",
    "tvshow": "videodb://tvshows/titles/{id}/",
    "musicvideo": "videodb://musicvideos/titles/{id}/",
    "artist": "musicdb://artists/{id}/",
    "album": "musicdb://albums/{id}/",
    "song": "musicdb://songs/{id}/",
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
    etc.). These are returned as endpoints without fetching.
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


def _build_library_path(item_type, item_id):
    """
    Construct a videodb/musicdb path for an individual library item.

    :param item_type: Kodi item type (movie, tvshow, etc.).
    :param item_id: Database ID.
    :return: Library path string or None if type is unknown.
    """
    template = _LIBRARY_PATH_MAP.get(item_type)
    if not template:
        return None
    return template.format(id=item_id)


def _is_action_string(path):
    """
    Return True if path is an action/command string rather than a real path.
    Action strings don't start with any known URL scheme.

    :param path: String to test.
    :return: True if this looks like a Kodi action, not a browsable path.
    """
    return not any(path.startswith(scheme) for scheme in _PATH_SCHEMES)


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
    progress.create(heading, _get_strings()["getting_directory"])
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

    For menu mode, if the path is an action/command string (not a real path),
    it is used directly as the action without wrapping in ActivateWindow.
    """
    # Action strings (commands, builtins) bypass path-based derivation
    if mode == "menu" and _is_action_string(path):
        return {
            "path": path,
            "label": label,
            "icon": "DefaultShortcut.png",
            "type": "command",
            "window": "",
            "action": path,
        }

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
# Static list browsers (menu mode only)
# ---------------------------------------------------------------------------


def _browse_static_list(shortcuts, heading):
    """
    Show a flat select dialog of static shortcut entries.

    :param shortcuts: List of (label, action, icon) tuples.
    :param heading: Dialog heading.
    :return: (action, label, icon) tuple, or None if cancelled.
    """
    s = _get_strings()
    labels = [s["back"]] + [label for label, _, _ in shortcuts]
    idx = Dialog().select(heading, labels)

    if idx == -1:
        return None
    if idx == 0:
        return None  # back to top level

    label, action, icon = shortcuts[idx - 1]
    return action, label, icon


def _browse_favourites(heading):
    """
    Show user's Kodi favourites as selectable shortcuts.

    :param heading: Dialog heading.
    :return: (path_or_action, label, icon) tuple, or None if cancelled.
    """
    s = _get_strings()
    result = json_call(
        "Favourites.GetFavourites",
        properties=["path", "window", "windowparameter", "thumbnail"],
        parent="browse_favourites",
    )
    favourites = result.get("result", {}).get("favourites") or []
    if not favourites:
        Dialog().notification(heading, s["no_favourites_found"], time=2000)
        return None

    labels = [s["back"]] + [fav.get("title", "") for fav in favourites]
    idx = Dialog().select(heading, labels)

    if idx == -1:
        return None
    if idx == 0:
        return None

    fav = favourites[idx - 1]
    fav_type = fav.get("type", "")
    fav_label = fav.get("title", "")
    fav_icon = fav.get("thumbnail", "DefaultFavourites.png") or "DefaultFavourites.png"

    if fav_type == "window":
        window = fav.get("window", "")
        param = fav.get("windowparameter", "")
        action = (
            f"ActivateWindow({window},{param},return)"
            if param
            else f"ActivateWindow({window})"
        )
        return action, fav_label, fav_icon

    # media and script types use the path directly
    return fav.get("path", ""), fav_label, fav_icon


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
    s = _get_strings()

    while True:
        if _is_endpoint(path):
            return path, heading

        if _is_known_flat(path):
            return path, heading

        items = _get_directory(path, heading)

        if not items:
            return path, heading

        if _is_flat_content(items):
            return path, heading

        items = [item for item in items if item["file"] not in _SUPPRESS_ITEMS]

        suppress_use_path = mode == "widget" and (
            path in _NO_USE_PATH or path in _NO_USE_PATH_XML
        )
        labels = [s["back"]]
        if not suppress_use_path:
            labels.append(s["use_this_path"])
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
            # For menu mode, prefer library paths over raw file paths
            if mode == "menu" and selected.get("id") and selected.get("type"):
                db_path = _build_library_path(selected["type"], selected["id"])
                if db_path:
                    return db_path, selected["label"]
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
    s = _get_strings()
    labels = [s["back"]] + [item["label"] for item in playlist_items]
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
    s = _get_strings()
    sources = _PLAYLIST_SOURCES[media]

    while True:
        labels = [
            s["back"],
            s["my_playlists"] + "  >",
            s["skin_playlists"] + "  >",
        ]
        idx = Dialog().select(heading, labels)

        if idx == -1:
            return None

        if idx == 0:
            return None  # ".." — back to top-level picker

        paths = sources["my"] if idx == 1 else sources["skin"]

        progress = DialogProgress()
        progress.create(heading, s["finding_playlists"])
        playlist_items = []
        for path in paths:
            playlist_items.extend(_walk_playlists(path))
        progress.close()

        if not playlist_items:
            Dialog().notification(heading, s["no_playlists_found"], time=2000)
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
    s = _get_strings()
    addon_sources = _get_addon_sources()

    while True:
        labels = [s["back"]] + [label + "  >" for label, _ in addon_sources]
        idx = Dialog().select(heading, labels)

        if idx == -1:
            return None

        if idx == 0:
            return None  # ".." — back to top-level picker

        label, path = addon_sources[idx - 1]
        result = _browse_level(path, label, mode)

        if result is _BACK_SENTINEL:
            continue
        return result  # (path, label) or None


def _custom_path():
    """
    Open a keyboard dialog and return (path, "") or None.
    Label is empty — the user typed a raw path with no associated name.
    """
    s = _get_strings()
    kb = xbmc.Keyboard("", s["enter_path"])
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

    :return:
      Both modes return a dict, or None if cancelled:

      widget: {"path": str, "label": str, "icon": str}

      menu:   {"path": str, "label": str, "icon": str,
               "type": str, "window": str, "action": str}
    """
    s = _get_strings()
    heading = cfg.get("heading", s["select_content"])
    mode = cfg.get("mode", "widget")

    while True:
        sources = _get_top_level() + (_get_menu_extra() if mode == "menu" else [])
        labels = [
            label + ("" if label == s["custom_path"] else "  >") for label, _ in sources
        ]
        idx = Dialog().select(heading, labels)

        if idx == -1:
            return None

        label, path = sources[idx]

        if label == s["video_playlists"]:
            result = _browse_playlists("video", heading)
        elif label == s["music_playlists"]:
            result = _browse_playlists("music", heading)
        elif label == s["addons"]:
            result = _browse_addons(heading, mode)
        elif label == s["custom_path"]:
            result = _custom_path()
        elif label == s["common"]:
            result = _browse_static_list(_COMMON_SHORTCUTS, heading)
        elif label == s["settings"]:
            result = _browse_static_list(_SETTINGS_SHORTCUTS, heading)
        elif label == s["kodi_commands"]:
            result = _browse_static_list(_KODI_COMMANDS, heading)
        elif label == s["favourites"]:
            result = _browse_favourites(heading)
        else:
            result = _browse_level(path, label, mode)
            if result is _BACK_SENTINEL:
                result = None

        if result is None:
            continue

        # Static lists and favourites return (action, label, icon) tuples
        if isinstance(result, tuple) and len(result) == 3:
            action, label, icon = result
            built = _build_result(action, label, mode)
            # Preserve the specific icon from the static list
            built["icon"] = icon
            return built

        path, label = result
        return _build_result(path, label, mode)
