# author: realcopacetic

import json
import sys
import time
import urllib.parse as urllib
from functools import wraps
from pathlib import Path

import xbmc
import xbmcvfs
from xbmcaddon import Addon
from xbmcgui import Dialog, Window
from xbmcplugin import (
    SORT_METHOD_LASTPLAYED,
    addSortMethod,
    setContent,
    setPluginCategory,
)

ADDON = Addon()
ADDON_ID = ADDON.getAddonInfo("id")

ADDONDATA = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}/")
BLURS = str(Path(ADDONDATA) / "blur")
CROPS = str(Path(ADDONDATA) / "crop")
TEMPS = str(Path(ADDONDATA) / "temp")
LOOKUPS = str(Path(ADDONDATA) / "_lookup.db")

SKIN = xbmcvfs.translatePath("special://skin/")
SKINEXTRAS = str(Path(SKIN) / "extras")
SKINXML = str(Path(SKIN) / "16x9")

CONFIGS = str(Path(ADDONDATA) / "configs.json")
CONTROLS = str(Path(ADDONDATA) / "controls.json")
VARIABLES = str(Path(SKINXML) / "script-copacetic-helper_variables.xml")

EXPRESSIONS = str(Path(SKINXML) / "script-copacetic-helper_expressions.xml")
INCLUDES = str(Path(SKINXML) / "script-copacetic-helper_includes.xml")

DEBUG = xbmc.LOGDEBUG
INFO = xbmc.LOGINFO
WARNING = xbmc.LOGWARNING
ERROR = xbmc.LOGERROR

DIALOG = Dialog()
VIDEOPLAYLIST = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
MUSICPLAYLIST = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)


"""HELPER CLASSES"""


class AutoInitMixin:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


"""KODI HELPERS"""


def clear_playlists():
    log("Clear playlists")
    VIDEOPLAYLIST.clear()
    MUSICPLAYLIST.clear()
    MUSICPLAYLIST.unshuffle()


def condition(condition):
    """
    Evaluates a Kodi visibility condition.

    :param condition: String condition (e.g., "Skin.HasSetting(x)").
    :returns: Boolean result.
    """
    return xbmc.getCondVisibility(condition)


def execute(action):
    """
    Executes a Kodi built-in function.

    :param action: The action string to run.
    """
    xbmc.executebuiltin(action)


def infolabel(infolabel):
    """
    Retrieves the value of a Kodi InfoLabel expression.

    :param infolabel: The InfoLabel string.
    :returns: Evaluated string value.
    """
    return xbmc.getInfoLabel(infolabel)


def skin_string(key, value=False, debug=False):
    """
    Sets or clears a Kodi skin string with optional logging.
    If `value` is a value, it sets the string. If it's False or empty, it clears it.

    :param key: Skin string key.
    :param value: Value to assign.
    :param debug: If True, forces debug log.
    """
    if value:
        execute(f"Skin.SetString({key}, {value})")
        log(f"Skin string: Set, {key}, {value}", force=debug)
    else:
        execute(f"Skin.SetString({key},)")
        log(f"Skin string: Clear, {key}", force=debug)


def reset_bool(setting_id, debug=False):
    """
    Resets (clears) a boolean skin setting with optional logging.

    :param setting_id: The skin setting ID (e.g., "mysetting").
    """
    execute(f"Skin.Reset({setting_id})")
    log(f"Skin Bool reset: {setting_id}", force=debug)


def set_bool(setting_id, debug=False):
    """
    Sets a boolean skin setting to True with optional logging.

    :param setting_id: The skin setting ID (e.g., "mysetting").
    """
    execute(f'Skin.SetBool({setting_id})')
    log(f"Skin Bool set: {setting_id}", force=debug)


def toggle_bool(setting_id, debug=False):
    """
    Toggles a boolean skin setting using Kodi built-in functions.

    If the setting is currently enabled (Skin.HasSetting), it will reset (clear it).
    If the setting is currently disabled, it will set it to True.

    :param setting_id: The skin setting ID (e.g., "mysetting").
    """
    if condition(f"Skin.HasSetting({setting_id})"):
        reset_bool(setting_id)
    else: 
        set_bool(setting_id)


def window_property(key, value=False, window_id=10000, debug=False):
    """
    Sets or clears a window property for a specific Kodi window with optional logging.
    If `value` is a value, it sets the prop. If it's False or empty, it clears it.

    :param key: Property name.
    :param value: Value to assign.
    :param window_id: ID of the Kodi window, defaults to 10000 for home
    :param debug: If True, forces debug log.
    """
    window = Window(window_id)
    if value:
        window.setProperty(key, f"{value}")
        log(f"Window property: Set, {window_id}, {key}, {value}", force=debug)
    else:
        window.clearProperty(key)
        log(f"Window property: Clear, {window_id}, {key}", force=debug)


"""FILE HELPERS & PATH UTILITIES"""


def create_dir(path):
    """
    Creates a directory if it doesn't already exist.

    :param path: Directory path.
    :returns: None
    """
    try:  # Try makedir to avoid race conditions
        xbmcvfs.mkdirs(path)
    except FileExistsError:
        return


def clear_cache(**kwargs):
    """
    Clears all temporary artwork processing data and resets the artwork lookup database.
    Resets the cache size display, and posts a notification with the amount of space saved.
    """
    readable_size = get_cache_size()

    for folder in [BLURS, CROPS, TEMPS]:
        if xbmcvfs.exists(folder):
            xbmcvfs.rmdir(folder, force=True)
            create_dir(folder)

    from resources.lib.shared.sqlite import SQLiteHandler

    SQLiteHandler().clear_all()

    log(f"Artwork cache cleared by user. {readable_size} saved.")
    message = f"{ADDON.getLocalizedString(32201)}, {readable_size} {ADDON.getLocalizedString(32202)}."
    DIALOG.notification(ADDON_ID, message)

    get_cache_size()


def get_cache_size(precision=1):
    """
    Computes the combined size of temp and crop folders and sets it as a window property.
    Credit Doug Latornell for bitshift method
    https://code.activestate.com/recipes/577081-humanized-representation-of-a-number-of-bytes/

    :param precision: Decimal precision for human-readable output.
    :returns: Formatted size string (e.g., "1.2 MB").
    """
    size = get_total_size(ADDONDATA)
    abbrevs = ((1 << 30, "GB"), (1 << 20, "MB"), (1 << 10, "KB"), (1, "bytes"))
    for factor, suffix in abbrevs:
        if size >= factor:
            break
    readable = (
        "%.*f %s" % (precision, size / factor, suffix) if size > 0 else "0.0 bytes"
    )
    window_property("Addon_Data_Folder_Size", value=readable)
    return readable


def get_total_size(path):
    """
    Calculates the total size of a file or all files in a folder (recursively).

    :param path: Path to a file or directory.
    :returns: Total size in bytes.
    """
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    elif path.is_dir():
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return 0


def url_encode(string):
    """
    Encodes a string for safe URL usage.

    :param string: Input string.
    :returns: URL-encoded string.
    """
    return urllib.quote(string)


def url_decode_path(path):
    """
    Decodes a Kodi image:// path into a usable file path.

    :param path: Encoded image path.
    :returns: Decoded file path.
    """
    return urllib.unquote(path.replace("image://", "").rstrip("/"))


def validate_path(path):
    """
    Checks if a given path exists on the filesystem.

    :param path: File or folder path.
    :returns: True if path exists.
    """
    return xbmcvfs.exists(str(path))


"""JSON"""


def json_call(
    method,
    properties=None,
    sort=None,
    query_filter=None,
    limit=None,
    params=None,
    item=None,
    options=None,
    parent=None,
    debug=False,
):
    """
    Builds and sends a JSON-RPC request to Kodi with optional debug logging.

    :param method: JSON-RPC method name (e.g., "VideoLibrary.GetMovies").
    :param properties: List of requested fields.
    :param sort: Dictionary describing sort method.
    :param query_filter: Dictionary for filtering results.
    :param limit: End limit for results — sets "limits": {"start": 0, "end": limit}.
    :param params: Additional parameters to inject directly into "params".
    :param item: Single "item" object for certain queries.
    :param options: Dictionary of additional JSON-RPC options.
    :param parent: Name of caller (used in log output).
    :param debug: If True, logs full request and result.
    :returns: Parsed response as a Python dictionary.
    """
    json_string = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {},
    }

    for key, value in [
        ("properties", properties),
        ("sort", sort),
        ("filter", query_filter),
        ("options", options),
        ("item", item),
    ]:
        if value is not None:
            json_string["params"][key] = value

    if limit is not None:
        json_string["params"]["limits"] = {"start": 0, "end": int(limit)}

    if params is not None:
        json_string["params"].update(params)

    jsonrpc_call = json.dumps(json_string, ensure_ascii=False)
    result = json.loads(xbmc.executeJSONRPC(jsonrpc_call))

    if ADDON.getSettingBool("json_logging") or debug:
        log(
            f"JSON call for function {parent} " + pretty_print(json_string), force=debug
        )
        log(f"JSON result for function {parent} " + pretty_print(result), force=debug)

    return result


def pretty_print(string):
    """
    Converts a Python object into a formatted JSON string.

    :param string: JSON-serializable object.
    :returns: Pretty-printed JSON string.
    """
    return json.dumps(string, sort_keys=True, indent=4, separators=(",", ": "))


"""LOGGING"""


def log(message, loglevel=DEBUG, force=False):
    """
    Logs a message with addon prefix, respecting log level and debug settings.

    :param message: Message string.
    :param loglevel: Kodi log level constant.
    :param force: If True, logs regardless of settings.
    """
    if (ADDON.getSettingBool("debug_logging") or force) and loglevel not in [
        WARNING,
        ERROR,
    ]:
        loglevel = INFO
    xbmc.log(f"{ADDON_ID} → {message}", loglevel)


def log_and_execute(action):
    """
    Logs and executes a built-in Kodi command.

    :param action: Built-in Kodi command string.
    """
    log(f"Execute: {action}", DEBUG)
    xbmc.executebuiltin(action)


def log_duration(func):
    """
    Decorator that logs the execution time of a method.

    :param func: The method to wrap.
    :returns: Wrapped method with timing log.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        cls_name = args[0].__class__.__name__ if args else "UnknownClass"
        start = time.time()
        result = func(*args, **kwargs)
        duration = time.time() - start
        log(f"{cls_name}.{func.__name__} took {duration:.4f} seconds")
        return result

    return wrapper


"""PLUGINS"""


def set_plugincontent(content=None, category=None):
    if category:
        setPluginCategory(int(sys.argv[1]), category)
    if content:
        setContent(int(sys.argv[1]), content)
    if category == ADDON.getLocalizedString(32601):
        addSortMethod(int(sys.argv[1]), SORT_METHOD_LASTPLAYED)


"""STRINGS"""


def expand_index(index_obj):
    """
    Expands a dict with start/end/step into a list of string indices.

    :param index_obj: Dictionary with "start", "end", and optional "step".
    :returns: List of stringified index values.
    """
    if not index_obj:
        return []
    try:
        keys = {k.lstrip("@"): v for k, v in index_obj.items()}
        start = int(keys["start"])
        end = int(keys["end"]) + 1
        step = int(keys.get("step", 1))
        return [str(i) for i in range(start, end, step)]
    except (KeyError, TypeError, ValueError):
        return []


def return_label(label=infolabel("ListItem.Label"), *, find=".", replace=" ", **kwargs):
    """
    Replaces a specific character in a label with another character.

    :param label: Input string (defaults to ListItem.Label).
    :param find: Character to replace.
    :param replace: Replacement character.
    :returns: Cleaned-up label.
    """
    find = urllib.unquote(find)
    replace = urllib.unquote(replace)
    return label.replace(find, replace, label.count(find))


def split(string, *, separator=" / ", number=0, **kwargs):
    """
    Returns the Nth element from a split string using a given separator.

    :param string: The input string.
    :param separator: Separator to split on (default: " / ").
    :param number: Index of element to return.
    :returns: Selected substring.
    """
    parts = string.split(separator)
    return parts[number] if 0 <= number < len(parts) else parts[0]


def split_random(string, *, separator="/", **kwargs):
    """
    Randomly selects and cleans a genre substring from a compound string.
    Handles edge case "Hip-Hop" → "Hip Hop"

    :param string: Genre string (e.g., "Action / Hip-Hop & R&B").
    :param separator: Delimiter used to split top-level genres (default: "/").
    :returns: Cleaned and formatted random genre."
    """
    import random

    primary = random.choice(string.split(separator)).strip()
    if "Hip-Hop" in primary:
        primary = "Hip Hop"

    subs = [s.strip() for s in primary.split("&")]
    picked = random.choice(subs)
    return return_label(picked)
