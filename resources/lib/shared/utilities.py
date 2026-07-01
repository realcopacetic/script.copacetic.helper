# author: realcopacetic

import ast
import json
import operator
import sys
import time
import urllib.parse as urllib
from pathlib import Path
from typing import Any, Mapping

import xbmc
import xbmcvfs
from xbmcaddon import Addon
from xbmcgui import Dialog, Window, getCurrentWindowId
from xbmcplugin import addSortMethod, setContent, setPluginCategory

THUMB_DB = xbmcvfs.translatePath("special://profile/Thumbnails")

ADDON = Addon()
ADDON_ID = ADDON.getAddonInfo("id")

ADDONDATA = xbmcvfs.translatePath(f"special://profile/addon_data/{ADDON_ID}/")
BLURS = str(Path(ADDONDATA) / "blur")
CROPS = str(Path(ADDONDATA) / "crop")
TEXTS = str(Path(ADDONDATA) / "text")
TEMPS = str(Path(ADDONDATA) / "temp")
LOOKUPS = str(Path(ADDONDATA) / "_lookup.db")

SKIN = xbmcvfs.translatePath("special://skin/")
SKINEXTRAS = str(Path(SKIN) / "extras")
SKINXML = str(Path(SKIN) / "16x9")

RUNTIME_STATE = str(Path(ADDONDATA) / "runtime_state.json")
RESOLVER_CACHE = str(Path(ADDONDATA) / "resolver_cache.json")

TEMPLATES = str(Path(SKINEXTRAS) / "templates")
VARIABLES = str(Path(SKINXML) / "script-copacetic-helper_variables.xml")
EXPRESSIONS = str(Path(SKINXML) / "script-copacetic-helper_expressions.xml")
INCLUDES = str(Path(SKINXML) / "script-copacetic-helper_includes.xml")

DIALOG = Dialog()
VIDEOPLAYLIST = xbmc.PlayList(xbmc.PLAYLIST_VIDEO)
MUSICPLAYLIST = xbmc.PlayList(xbmc.PLAYLIST_MUSIC)

_JSON_RESPONSE_LIMIT = 5

from resources.lib.shared import logger as log

"""ADDON"""


def reset_dev_state() -> None:
    """
    Delete all builder outputs and runtime_state to force a clean rebuild
    on next service boot. Intended for dev/skinner use.
    Imports BUILDER_CONFIG locally to avoid a circular dependency.

    :return: None.
    """
    from resources.lib.builders.builder_config import BUILDER_CONFIG

    for config in BUILDER_CONFIG.values():
        write_path = config.get("write_path")
        if write_path:
            xbmcvfs.delete(write_path)
    xbmcvfs.delete(RUNTIME_STATE)
    xbmcvfs.delete(RESOLVER_CACHE)
    log.info(f"reset_dev_state → outputs and runtime_state cleared")


"""KODI UTILS"""

def clear_label(label_id: int | str, hide: bool = False) -> None:
    """
    Clear a label control, optionally hiding it.

    :param label_id: Control id of the label to clear.
    :param hide: Also set the control invisible when True.
    """
    if (ctrl_id := to_int(label_id, 0)) <= 0:
        return

    if not condition(f"Control.IsVisible({ctrl_id})"):
        log.debug(f"clear_label: Control {ctrl_id} not in current window; skipping.")
        return

    window = Window(getCurrentWindowId())
    try:
        ctrl = window.getControl(ctrl_id)
        if hide:
            ctrl.setVisible(False)
        ctrl.reset()
        ctrl.addLabel("")
    except RuntimeError:
        log.debug(f"clear_label: Label id {label_id} not found.")

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


def focused_control_id() -> int:
    """
    Return the id of the focused control in the current window.

    :return: Focused control id, or 0 if nothing is focused.
    """
    return Window(getCurrentWindowId()).getFocusId()


def infolabel(infolabel: str) -> str:
    """
    Retrieves the value of a Kodi InfoLabel expression.

    :param infolabel: The InfoLabel string.
    :return: Evaluated string value.
    """
    return xbmc.getInfoLabel(infolabel)


def wait_for_infolabel(
    name: str,
    *,
    timeout_ms: int = 250,
    poll_ms: int = 25,
) -> str:
    """
    Wait briefly for an InfoLabel to become non-empty.

    :param name: Fully-qualified InfoLabel name (e.g. "Container.ListItem.DBID").
    :param timeout_ms: Maximum time to wait in milliseconds.
    :param poll_ms: Polling interval in milliseconds.
    :return: First non-empty value observed, or "" if timeout/abort.
    """
    monitor = xbmc.Monitor()
    deadline = time.time() + (timeout_ms / 1000.0)

    value = infolabel(name)
    if value:
        return value

    while not value and not monitor.abortRequested() and time.time() < deadline:
        xbmc.sleep(poll_ms)
        value = infolabel(name)

    return value or ""


def skin_string(key: str, value: str | bool = False) -> None:
    """
    Sets or clears a Kodi skin string with optional logging.
    If `value` is a value, it sets the string. If it's False or empty, it clears it.

    :param key: Skin string key.
    :param value: Value to assign.
    """
    if value:
        log.execute(f"Skin.SetString({key}, {value})")
    else:
        log.execute(f"Skin.SetString({key},)")


def reset_bool(setting_id: str) -> None:
    """
    Resets (clears) a boolean skin setting with optional logging.

    :param setting_id: The skin setting ID (e.g., "mysetting").
    """
    log.execute(f"Skin.Reset({setting_id})")


def set_bool(setting_id: str) -> None:
    """
    Sets a boolean skin setting to True with optional logging.

    :param setting_id: The skin setting ID (e.g., "mysetting").
    """
    log.execute(f"Skin.SetBool({setting_id})")


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
        log.debug(f"Window property → Set, {window_id}, {key}, {value}")
    else:
        window.clearProperty(key)
        log.debug(f"Window property → Clear, {window_id}, {key}")


"""FILE / PATH UTILS"""


def create_dir(path: str) -> None:
    """
    Create a directory if absent; no-op if it already exists.
    xbmcvfs.mkdirs returns True when the path exists or was created.

    :param path: Directory path (local or VFS).
    """
    if not xbmcvfs.mkdirs(path):
        log.debug(f"create_dir: could not create {path}")


def clear_cache(**kwargs: str) -> None:
    """
    Clears all temporary artwork processing data and resets the artwork lookup database.
    Resets the cache size display, and posts a notification with the amount of space saved.
    """
    readable_size = get_cache_size()

    for folder in [BLURS, CROPS, TEXTS, TEMPS]:
        if xbmcvfs.exists(folder):
            xbmcvfs.rmdir(folder, force=True)
            create_dir(folder)

    from resources.lib.shared.sqlite import ArtworkCacheHandler

    ArtworkCacheHandler().clear_all()

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

def skin_uses_builder() -> bool:
    """
    True when the active skin ships the builder folder structure under
    ``extras/templates/``. Any one canonical subfolder suffices. This is 
    the helper's per-skin opt-in signal.

    :return: True if the active skin provides builder inputs.
    """
    from resources.lib.builders.builder_config import TEMPLATE_SUBFOLDERS
    
    return any(
        validate_path(str(Path(TEMPLATES) / sub) + "/") for sub in TEMPLATE_SUBFOLDERS
    )

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


def _build_request(
    method: str,
    properties: list[str] | None = None,
    sort: dict[str, Any] | None = None,
    query_filter: dict[str, Any] | None = None,
    limit: int | None = None,
    params: dict[str, Any] | None = None,
    item: dict[str, Any] | None = None,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Assemble a JSON-RPC methodparams body without the outer envelope.
    Shared between json_call and json_call_batch.

    :param method: JSON-RPC method name (e.g., "VideoLibrary.GetMovies").
    :param properties: List of requested fields.
    :param sort: Dictionary describing sort method.
    :param query_filter: Dictionary for filtering results.
    :param limit: End limit for results — sets "limits": {"start": 0, "end": limit}.
    :param params: Additional parameters to inject directly into "params".
    :param item: Single "item" object for certain queries.
    :param options: Dictionary of additional JSON-RPC options.
    :return: Request body dict with "method" and "params" keys.
    """
    body: dict[str, Any] = {
        "method": method,
        "params": dict(params) if params else {},
    }

    for key, value in [
        ("properties", properties),
        ("sort", sort),
        ("filter", query_filter),
        ("options", options),
        ("item", item),
    ]:
        if value is not None:
            body["params"][key] = value

    if limit is not None:
        body["params"]["limits"] = {"start": 0, "end": int(limit)}

    return body


def _log_call(parent: str | None, payload: Any, result: Any) -> None:
    """
    Conditional debug logging shared between single and batch calls.

    :param parent: Caller name for log output.
    :param payload: Outgoing request envelope or list of envelopes.
    :param result: Parsed response from Kodi.
    """
    if ADDON.getSettingBool("json_logging"):
        log.debug(f"JSON call for function {parent} " + pretty_print(payload))
        log.debug(
            f"JSON result for function {parent} "
            + pretty_print(_truncate_for_log(result))
        )


def _truncate_for_log(payload: Any) -> Any:
    """
    Walk a JSON-RPC result and cap any list longer than _JSON_RESPONSE_LIMIT
    to its first N items, replacing the tail with a summary marker.
    Returns a new structure; does not mutate the input.

    :param payload: Arbitrary JSON-serialisable structure.
    :return: Same shape with long lists truncated.
    """
    if isinstance(payload, dict):
        return {k: _truncate_for_log(v) for k, v in payload.items()}
    if isinstance(payload, list):
        if len(payload) > _JSON_RESPONSE_LIMIT:
            head = [_truncate_for_log(item) for item in payload[:_JSON_RESPONSE_LIMIT]]
            head.append(f"... <{len(payload) - _JSON_RESPONSE_LIMIT} more items omitted>")
            return head
        return [_truncate_for_log(item) for item in payload]
    return payload


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
    Send a single JSON-RPC request to Kodi with optional debug logging.

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
    body = _build_request(
        method, properties, sort, query_filter, limit, params, item, options
    )
    envelope = {"jsonrpc": "2.0", "id": 1, **body}
    result = json.loads(xbmc.executeJSONRPC(json.dumps(envelope, ensure_ascii=False)))
    _log_call(parent, envelope, result)
    return result


def json_call_batch(
    requests: list[dict[str, Any]],
    parent: str | None = None,
) -> list[dict[str, Any] | None]:
    """
    Send multiple JSON-RPC requests in a single IPC round-trip.

    Each request dict accepts the same kwargs as json_call, plus an optional
    ``id`` for response matching (auto-assigned by index if absent). Responses
    are returned in the same order as the input requests; the spec permits
    the server to return them out of order, so they are re-keyed by id.

    :param requests: List of request kwarg dicts.
    :param parent: Caller name for log output.
    :return: List of response dicts in input order; None at any slot whose id is missing from the response.
    """
    if not requests:
        return []

    envelopes: list[dict[str, Any]] = []
    ids: list[Any] = []
    for idx, req in enumerate(requests):
        request_id = req.get("id", idx)
        ids.append(request_id)
        body = _build_request(
            method=req["method"],
            properties=req.get("properties"),
            sort=req.get("sort"),
            query_filter=req.get("query_filter"),
            limit=req.get("limit"),
            params=req.get("params"),
            item=req.get("item"),
            options=req.get("options"),
        )
        envelopes.append({"jsonrpc": "2.0", "id": request_id, **body})

    raw = xbmc.executeJSONRPC(json.dumps(envelopes, ensure_ascii=False))
    results = json.loads(raw)
    _log_call(parent, envelopes, results)

    by_id = {r["id"]: r for r in results if isinstance(r, dict) and "id" in r}
    return [by_id.get(rid) for rid in ids]


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
        end = int(keys["end"]) + 1 if "end" in keys else start + 1
        step = int(keys.get("step", 1))
        return [str(i) for i in range(start, end, step)]
    except (KeyError, TypeError, ValueError):
        log.debug(f"expand_index: Failed to expand {index_obj} — 'end' is required")
        return []


def return_label(
    label: str | None,
    *,
    find: str = ".",
    replace: str = " ",
    **kwargs: object,
) -> str:
    """
    Replaces a specific character in a label with another character.

    :param label: Input string (defaults to ListItem.Label if None).
    :param find: Character to replace.
    :param replace: Replacement character.
    :return: Cleaned-up label.
    """
    if label is None:
        label = infolabel("ListItem.Label")

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


def to_float(value: object, default: float = 0.0) -> float:
    """
    Safely convert a value to float.

    :param value: The value to convert.
    :param default: Value to return if conversion fails.
    :return: The converted float or the default value.
    """
    try:
        return float(value)
    except (TypeError, ValueError, AttributeError):
        return default


def to_int(value: object, default: int | None = 0) -> int:
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


"""ARITHMETIC"""

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}

_FUNCS = {"min": min, "max": max}


def _eval_node(node: ast.AST, names: Mapping[str, Any]) -> Any:
    """
    Recursive AST walker for evaluate_expression.

    :param node: AST node to evaluate.
    :param names: Mapping of identifier to numeric value.
    :return: Numeric result of the node.
    :raises ValueError: For unknown names or unsupported syntax.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in names:
            return names[node.id]
        raise ValueError(f"Unknown name '{node.id}'")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand, names)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](
            _eval_node(node.left, names), _eval_node(node.right, names)
        )
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCS
        and not node.keywords
    ):
        return _FUNCS[node.func.id](*(_eval_node(a, names) for a in node.args))
    raise ValueError(f"Unsupported expression node: {type(node).__name__}")


def evaluate_expression(expr: str, names: Mapping[str, Any]) -> str | None:
    """
    Evaluate a small numeric expression against a name table. Supports the
    four arithmetic operators (, -, *, /), floor division, modulo, unary
    minus, parenthesised sub-expressions, and the functions min() and max()
    with any number of arguments.

    :param expr: Expression text (e.g. "count*100", "min(count*100, 800)").
    :param names: Mapping of identifier to numeric value. String values that
        parse as integers are accepted; other non-numeric values are ignored.
    :return: Stringified result (integer when whole), or None if the
        expression cannot be evaluated against the supplied names.
    """
    numeric_names: dict[str, Any] = {}
    for key, value in names.items():
        if isinstance(value, (int, float)):
            numeric_names[key] = value
        elif isinstance(value, str):
            try:
                numeric_names[key] = int(value)
            except ValueError:
                continue

    try:
        tree = ast.parse(expr, mode="eval")
        result = _eval_node(tree.body, numeric_names)
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError):
        return None

    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return str(result)
