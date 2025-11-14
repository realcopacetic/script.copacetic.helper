# author: realcopacetic

import json
import sys
import urllib.parse as urllib
from pathlib import Path
from typing import Any

import xbmc
import xbmcvfs
from xbmcaddon import Addon
from xbmcgui import Dialog, Window
from xbmcplugin import addSortMethod, setContent, setPluginCategory

from resources.lib.shared import logger as log

THUMB_DB = xbmcvfs.translatePath("special://profile/Thumbnails")

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
RUNTIME_STATE = str(Path(ADDONDATA) / "runtime_state.json")

VARIABLES = str(Path(SKINXML) / "script-copacetic-helper_variables.xml")
EXPRESSIONS = str(Path(SKINXML) / "script-copacetic-helper_expressions.xml")
INCLUDES = str(Path(SKINXML) / "script-copacetic-helper_includes.xml")

DIALOG = Dialog()
VIDEOPLAYLIST = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
MUSICPLAYLIST = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)


"""KODI UTILS"""


def clear_playlists() -> None:
    log.debug("Clear playlists")
    VIDEOPLAYLIST.clear()
    MUSICPLAYLIST.clear()
    MUSICPLAYLIST.unshuffle()


def condition(condition: str) -> bool:
    """
    Evaluates a Kodi visibility condition.

    :param condition: String condition (e.g., "Skin.HasSetting(x)").
    :return: Boolean result.
    """
    return xbmc.getCondVisibility(condition)


def execute(action: str) -> None:
    """
    Executes a Kodi built-in function.

    :param action: The action string to run.
    """
    xbmc.executebuiltin(action)


def infolabel(infolabel: str) -> str:
    """
    Retrieves the value of a Kodi InfoLabel expression.

    :param infolabel: The InfoLabel string.
    :return: Evaluated string value.
    """
    return xbmc.getInfoLabel(infolabel)


def skin_string(key: str, value: str | bool = False) -> None:
    """
    Sets or clears a Kodi skin string with optional logging.
    If `value` is a value, it sets the string. If it's False or empty, it clears it.

    :param key: Skin string key.
    :param value: Value to assign.
    """
    if value:
        execute(f"Skin.SetString({key}, {value})")
        log.debug(f"Skin string: Set, {key}, {value}")
    else:
        execute(f"Skin.SetString({key},)")
        log.debug(f"Skin string: Clear, {key}")


def reset_bool(setting_id: str) -> None:
    """
    Resets (clears) a boolean skin setting with optional logging.

    :param setting_id: The skin setting ID (e.g., "mysetting").
    """
    execute(f"Skin.Reset({setting_id})")
    log.debug(f"Skin Bool reset: {setting_id}")


def set_bool(setting_id: str) -> None:
    """
    Sets a boolean skin setting to True with optional logging.

    :param setting_id: The skin setting ID (e.g., "mysetting").
    """
    execute(f"Skin.SetBool({setting_id})")
    log.debug(f"Skin Bool set: {setting_id}")


def toggle_bool(setting_id: str):
    """
    Toggles a boolean skin setting using Kodi built-in functions.

    If the setting is currently enabled (Skin.HasSetting), it will reset (clear it).
    If the setting is currently disabled, it will set it to True.

    :param setting_id: The skin setting ID (e.g., "mysetting").
    """
    (
        reset_bool(setting_id)
        if condition(f"Skin.HasSetting({setting_id})")
        else set_bool(setting_id)
    )


def window_property(
    key: str, value: str | bool = False, window_id: int = 10000
) -> None:
    """
    Sets or clears a window property for a specific Kodi window with optional logging.
    If `value` is a value, it sets the prop. If it's False or empty, it clears it.

    :param key: Property name.
    :param value: Value to assign.
    :param window_id: ID of the Kodi window, defaults to 10000 for home
    """
    window = Window(window_id)
    if value:
        window.setProperty(key, f"{value}")
        log.debug(f"Window property: Set, {window_id}, {key}, {value}")
    else:
        window.clearProperty(key)
        log.debug(f"Window property: Clear, {window_id}, {key}")


"""FILE / PATH UTILS"""


def create_dir(path: str) -> None:
    """
    Creates a directory if it doesn't already exist.

    :param path: Directory path.
    :return: None
    """
    try:  # Try makedir to avoid race conditions
        xbmcvfs.mkdirs(path)
    except FileExistsError:
        return


def clear_cache(**kwargs: str) -> None:
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

    log.info(f"Artwork cache cleared by user. {readable_size} saved.")
    message = f"{ADDON.getLocalizedString(32201)}, {readable_size} {ADDON.getLocalizedString(32202)}."
    DIALOG.notification(ADDON_ID, message)

    get_cache_size()


def get_cache_size(precision: int = 1) -> str:
    """
    Computes the combined size of temp and crop folders and sets it as a window property.
    Credit Doug Latornell for bitshift method
    https://code.activestate.com/recipes/577081-humanized-representation-of-a-number-of-bytes/

    :param precision: Decimal precision for human-readable output.
    :return: Formatted size string (e.g., "1.2 MB").
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


def get_total_size(path: str | Path) -> int:
    """
    Calculates the total size of a file or all files in a folder (recursively).

    :param path: Path to a file or directory.
    :return: Total size in bytes.
    """
    path = Path(path)
    if path.is_file():
        return path.stat().st_size
    elif path.is_dir():
        return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return 0


def url_encode(value: str) -> str:
    """
    URL-encode a string for safe use in query parameters.

    :param value: Raw string to encode.
    :return: Encoded string.
    """
    return urllib.quote_plus(value)


def url_decode_path(path: str) -> str:
    """
    Decodes a Kodi image:// path into a usable file path.

    :param path: Encoded image path.
    :return: Decoded file path.
    """
    return urllib.unquote(path.replace("image://", "").rstrip("/"))


def validate_path(path: str | Path) -> bool:
    """
    Checks if a given path exists on the filesystem.

    :param path: File or folder path.
    :return: True if path exists.
    """
    return xbmcvfs.exists(str(path))


"""JSON"""


def json_call(
    method: str,
    properties: list[str] | None = None,
    sort: dict[str, Any] | None = None,
    query_filter: dict[str, Any] | None = None,
    limit: int | None = None,
    params: dict[str, Any] | None = None,
    item: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
    parent: str | None = None,
) -> dict[str, Any]:
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
    :return: Parsed response as a Python dictionary.
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

    if ADDON.getSettingBool("json_logging"):
        log.debug(f"JSON call for function {parent} " + pretty_print(json_string))
        log.debug(f"JSON result for function {parent} " + pretty_print(result))

    return result


def pretty_print(obj: object) -> str:
    """
    Converts a Python object into a formatted JSON string.

    :param obj: JSON-serializable object.
    :return: Pretty-printed JSON string.
    """
    return json.dumps(obj, sort_keys=True, indent=4, separators=(",", ": "))


"""PLUGINS"""


def set_plugincontent(
    content: str | None = None,
    category: str | None = None,
    sort_method: int | None = None,
) -> None:
    """
    Set directory-level metadata (category/content) and optional sort method.
    This wraps xbmcplugin calls and pulls the handle from sys.argv[1].

    :param content: e.g. "videos", "movies", "tvshows", "episodes".
    :param category: Displayed category label in the UI.
    :param sort_method: xbmcplugin.SORT_METHOD_* constant to add sorting.
    """
    handle = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    if category:
        setPluginCategory(handle, category)
    if content:
        setContent(handle, content)
    if sort_method is not None:
        addSortMethod(handle, sort_method)


"""STRINGS"""


def expand_index(index_obj: dict[str, Any]) -> list[str]:
    """
    Expands a dict with start/end/step into a list of string indices.

    :param index_obj: Dictionary with "start", "end", and optional "step".
    :return: List of stringified index values.
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


def return_label(
    label: str = infolabel("ListItem.Label"),
    *,
    find: str = ".",
    replace: str = " ",
    **kwargs: object,
) -> str:
    """
    Replaces a specific character in a label with another character.

    :param label: Input string (defaults to ListItem.Label).
    :param find: Character to replace.
    :param replace: Replacement character.
    :return: Cleaned-up label.
    """
    find = urllib.unquote(find)
    replace = urllib.unquote(replace)
    return label.replace(find, replace, label.count(find))


def split(
    string: str, *, separator: str = " / ", number: int = 0, **kwargs: object
) -> str:
    """
    Returns the Nth element from a split string using a given separator.

    :param string: The input string.
    :param separator: Separator to split on (default: " / ").
    :param number: Index of element to return.
    :return: Selected substring.
    """
    parts = string.split(separator)
    return parts[number] if 0 <= number < len(parts) else parts[0]


def split_random(string: str, *, separator: str = "/", **kwargs: object) -> str:
    """
    Randomly selects and cleans a genre substring from a compound string.
    Handles edge case "Hip-Hop" → "Hip Hop"

    :param string: Genre string (e.g., "Action / Hip-Hop & R&B").
    :param separator: Delimiter used to split top-level genres (default: "/").
    :return: Cleaned and formatted random genre."
    """
    import random

    primary = random.choice(string.split(separator)).strip()
    if "Hip-Hop" in primary:
        primary = "Hip Hop"

    subs = [s.strip() for s in primary.split("&")]
    picked = random.choice(subs)
    return return_label(picked)


"""TYPE UTILS"""


def to_int(value: object, default: int = 0) -> int:
    """
    Safely convert a value to an integer, returning a default on failure.

    :param value: The value to convert.
    :param default: Value to return if conversion fails.
    :return: The converted integer or the default value.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def clamp(value: int | float, low: int | float, high: int | float) -> int | float:
    """
    Clamp a numeric value to the inclusive range [low, high].

    :param value: Input number.
    :param low: Minimum allowed value.
    :param high: Maximum allowed value.
    :return: Value constrained within the range.
    """
    return low if value < low else high if value > high else value


def parse_bool(s: object, default: bool = False) -> bool:
    """
    Convert a value to bool using common truthy strings.

    :param s: Input value (str, bool, int, None, etc.).
    :param default: Fallback if input is None or not parseable.
    :return: Parsed boolean value.
    """
    if isinstance(s, bool):
        return s
    if s is None:
        return default
    return str(s).strip().lower() in {"1", "true", "yes", "on"}
