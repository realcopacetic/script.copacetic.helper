# author: realcopacetic

import re
import time
from urllib.parse import quote

from xbmcgui import Window

from resources.lib.plugin.registry import LOG_TAG
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import json_call, window_property

# Library folders a favourite can open, by their ids: a show or season under
# titles or one filter node (genres/3, years/2010 …); an all-seasons or
# all-albums node is the show or artist itself
_SHOW_NODE = r"videodb://tvshows/(?:titles|(?!titles/)[a-z]+/[^/]+)/(\d+)/"
_DB_FOLDERS = (
    (re.compile(_SHOW_NODE + r"(?:-1/)?$"), "tvshow"),
    (re.compile(r"videodb://movies/sets/(\d+)/$"), "set"),
    (re.compile(r"musicdb://artists/(\d+)/(?:-1/)?$"), "artist"),
    (
        re.compile(
            r"musicdb://(?:artists/\d+|albums|recentlyaddedalbums"
            r"|recentlyplayedalbums)/(\d+)/$"
        ),
        "album",
    ),
)
_SEASON = re.compile(_SHOW_NODE + r"(\d+)/$")
# Stacks and archive members the video library stores whole as the file name
_WHOLE_NAME = ("stack://", "rar://", "zip://")
# Libraries a favourite's file can be in, by their JSON-RPC list method
_FILE_LIBRARIES = (
    ("VideoLibrary.GetMovies", "movie"),
    ("VideoLibrary.GetEpisodes", "episode"),
    ("VideoLibrary.GetMusicVideos", "musicvideo"),
    ("AudioLibrary.GetSongs", "song"),
)
_FILE_TYPES = {dbtype for _, dbtype in _FILE_LIBRARIES}
_TARGET_PARAM = {"playmedia": 0, "activatewindow": 1}  # CFavouritesURL::Parse


def _split_params(text: str) -> list[str]:
    """
    Split an exec string's parameters at top-level commas as Kodi's SplitParams
    does: quotes group, a backslash escapes a quote or itself, brackets nest.

    :param text: The text between the function's brackets.
    :return: Each parameter, trimmed and unquoted.
    """
    params, param, quoted, depth, escaped = [], "", False, 0, False
    for ch in text:
        if escaped:
            escaped = False
            if ch in '"\\':
                param = param[:-1] + ch
                continue
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            quoted = not quoted
            continue
        elif not quoted and ch == "(":
            depth += 1
        elif not quoted and ch == ")" and depth:
            depth -= 1
        elif not quoted and ch == "," and not depth:
            params.append(param.strip())
            param = ""
            continue
        param += ch
    return [*params, param.strip()]


def favourite_target(path: str) -> str:
    """
    The media path a favourite runs: PlayMedia's first parameter or
    ActivateWindow's second, as CFavouritesURL::Parse reads them.

    :param path: The favourite's ListItem.FileNameAndPath, URL-decoded.
    :return: The target, or "" for any other action.
    """
    exec_string = path.removeprefix("favourites://").rstrip("/")
    function, _, rest = exec_string.partition("(")
    params = _split_params(rest.rpartition(")")[0])
    index = _TARGET_PARAM.get(function.strip().lower())
    return params[index] if index is not None and index < len(params) else ""


def listed_path(path: str) -> str:
    """
    A favourite's path as Kodi lists it (ListItem.FileNameAndPath): the exec
    string encoded as CURL::Encode does, which keeps only alphanumerics and -_.!().

    :param path: The favourite's ListItem.FileNameAndPath, URL-decoded.
    :return: The listed path, hex in upper case (String.IsEqual ignores case).
    """
    exec_string = path.removeprefix("favourites://").removesuffix("/")
    return f"favourites://{quote(exec_string, safe='!()').replace('~', '%7E')}/"


def _rows(method: str, key: str, **kwargs) -> list[dict] | None:
    """
    A JSON-RPC list call's rows.

    :param method: JSON-RPC method.
    :param key: The result's list field.
    :param kwargs: json_call arguments.
    :return: The rows, or None when the call errored.
    """
    response = json_call(method, parent="favourite", **kwargs)
    return None if "error" in response else response["result"].get(key, [])


def _season_key(tvshowid: int, season: int) -> str | None:
    """
    A show's season by its number.

    :param tvshowid: Library show id.
    :param season: Season number.
    :return: "season:<seasonid>", "" when the show has no such season, None on error.
    """
    seasons = _rows(
        "VideoLibrary.GetSeasons",
        "seasons",
        properties=["season"],
        params={"tvshowid": tvshowid},
    )
    if seasons is None:
        return None
    return next(
        (f"season:{r['seasonid']}" for r in seasons if r["season"] == season), ""
    )


def _file_key(file: str) -> str | None:
    """
    A file's library item, found in the library databases by its folder and
    name (the path and filename rules), so no share is touched. The rules
    match with LIKE, so a row counts only when its file is this one.

    :param file: Media file path.
    :return: "<dbtype>:<dbid>", "" when no library holds it, None on error.
    """
    cut = max(file.rfind("/"), file.rfind("\\")) + 1
    split = [
        {"field": "path", "operator": "is", "value": file[:cut]},
        {"field": "filename", "operator": "is", "value": file[cut:]},
    ]
    whole = [{"field": "filename", "operator": "is", "value": file}]
    for method, dbtype in _FILE_LIBRARIES:
        # The video library keeps a stack or archive member whole, music splits it
        video_whole = file.startswith(_WHOLE_NAME) and dbtype != "song"
        rules = whole if video_whole else split
        rows = _rows(
            method, f"{dbtype}s", properties=["file"], query_filter={"and": rules}
        )
        if rows is None:
            return None
        if found := next((r for r in rows if r["file"] == file), None):
            return f"{dbtype}:{found[f'{dbtype}id']}"
    return ""


def _target_key(target: str) -> str | None:
    """
    The library item a favourite's target names, from its db path or its file.

    :param target: The favourite's target path.
    :return: "<dbtype>:<dbid>", "" when it names none, None on a lookup error.
    """
    db_path = target.startswith(("videodb://", "musicdb://"))
    path = target.partition("?")[0] if db_path else target
    for pattern, dbtype in _DB_FOLDERS:
        if match := pattern.match(path):
            return f"{dbtype}:{match[1]}"
    if match := _SEASON.match(path):
        return _season_key(int(match[1]), int(match[2]))
    if not path or db_path or path.startswith("plugin://"):
        return ""
    return _file_key(path)


def forget(path: str, dbtype: str) -> None:
    """
    A favourite whose item the library has lost: a file's answer is dropped to
    look it up again; a folder's, read from its path, is kept as none.

    :param path: The favourite's ListItem.FileNameAndPath, URL-decoded.
    :param dbtype: The lost item's library type.
    """
    window_property(f"favourite:{path}", "" if dbtype in _FILE_TYPES else "none")


def library_key(path: str) -> str:
    """
    A favourite's library item, kept in a Home property for the session
    (favourites rarely change); a lookup that errored is not kept.

    :param path: The favourite's ListItem.FileNameAndPath, URL-decoded.
    :return: "<dbtype>:<dbid>", or "" when it names none.
    """
    start = time.perf_counter()
    prop = f"favourite:{path}"
    if cached := Window(10000).getProperty(prop):
        key = "" if cached == "none" else cached
    else:
        if (key := _target_key(favourite_target(path))) is not None:
            window_property(prop, key or "none")
    ms = (time.perf_counter() - start) * 1000
    log.debug(
        f"{LOG_TAG} → favourite: {path} → "
        f"{key or ('lookup failed' if key is None else 'no library item')}"
        f"{' (cached)' if cached else ''} in {ms:.0f}ms"
    )
    return key or ""
