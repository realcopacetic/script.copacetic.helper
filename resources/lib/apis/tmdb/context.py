# resources/lib/apis/tmdb/context.py
# author: realcopacetic

from typing import Any, Mapping

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import infolabel, json_call, to_int

_DETAILS_LOOKUP_BY_KIND = {
    "movie": {
        "method": "VideoLibrary.GetMovieDetails",
        "id_key": "movieid",
        "result_key": "moviedetails",
    },
    "tvshow": {
        "method": "VideoLibrary.GetTVShowDetails",
        "id_key": "tvshowid",
        "result_key": "tvshowdetails",
    },
}


# A library movie's or show's TMDb id once found, kept for the process until its next
# library update: a season's bar and its metadata serve look its show up once
_TMDB_IDS = {}


def forget_tmdb_id(kind: str, dbid: int) -> None:
    """
    Drop a library item's kept TMDb id, read again at its next lookup: a rescrape
    can give it another.

    :param kind: Its library type, as VideoLibrary.OnUpdate names it.
    :param dbid: Its library id.
    """
    _TMDB_IDS.pop((kind, dbid), None)


def _library_tmdb_id(kind: str, dbid: int) -> str | None:
    """
    A library movie's or show's TMDb id from its details (_TMDB_IDS once found).

    :param kind: "movie" or "tvshow".
    :param dbid: Its library id.
    :return: The TMDb id; None if it has none.
    """
    if not (found := _TMDB_IDS.get((kind, dbid))):
        lookup = _DETAILS_LOOKUP_BY_KIND[kind]
        found = _lookup_uniqueid_tmdb(
            method=lookup["method"],
            id_key=lookup["id_key"],
            id_value=dbid,
            result_key=lookup["result_key"],
        )
        if found:
            _TMDB_IDS[kind, dbid] = found
    return found


def _lookup_uniqueid_tmdb(
    *,
    method: str,
    id_key: str,
    id_value: int,
    result_key: str,
) -> str | None:
    """
    Fetch a TMDb uniqueid from a VideoLibrary JSON-RPC details endpoint.

    :param method: JSON-RPC method, for example "VideoLibrary.GetMovieDetails".
    :param id_key: Request parameter key, for example "movieid" or "tvshowid".
    :param id_value: Numeric DBID value for the request parameter.
    :param result_key: Result envelope key, for example "moviedetails".
    :return: TMDb id string if present, else None.
    """
    response = json_call(
        method,
        params={id_key: id_value},
        properties=["uniqueid"],
        parent="resolve_tmdb_context",
    )
    uniqueid = response.get("result", {}).get(result_key, {}).get("uniqueid", {}) or {}
    return uniqueid.get("tmdb")


def resolve_tmdb_context(params: Mapping[str, str], target: str) -> dict[str, Any]:
    """
    Resolve TMDb context (kind + ids) for the current listitem.

    :param params: URL/query params passed from the plugin call.
    :param target: InfoLabel prefix, e.g. f"{self.container}.ListItem".
    :return: Dict containing "kind", "dbid", "tmdb_id", "season_number".
    """

    def first(key: str, label: str) -> str | None:
        return params.get(key) or infolabel(f"{target}.{label}") or None

    kind = (first("type", "DBType") or "").lower() or None
    dbid = to_int(first("id", "DBID"), None)
    tmdb_id = first("tmdb_id", "UniqueID(tmdb)")
    season_number = to_int(first("season", "Season"), None)

    if kind == "season" and season_number is None:
        # "* All seasons" node: no season number — skip the uniqueid lookup.
        log.debug(
            f"resolve_tmdb_context → season without season number for {dbid=}; "
            f"skipping TMDb lookup"
        )
        return {"kind": kind, "dbid": dbid, "season_number": None, "tmdb_id": None}

    if kind in ("season", "episode"):
        lookup_dbid = to_int(
            first("tvshowid", "TvShowDBID")
            or infolabel(f"{target}.Property(tvshowid)"),
            None,
        )
        lookup_kind = "tvshow"
        if kind == "episode":  # its UniqueID(tmdb) is the episode's: look up the show
            tmdb_id = None
    else:
        lookup_dbid = dbid
        lookup_kind = kind

    if not tmdb_id and lookup_dbid and lookup_kind in _DETAILS_LOOKUP_BY_KIND:
        tmdb_id = _library_tmdb_id(lookup_kind, lookup_dbid)

    tmdb_id = tmdb_id or None
    log.debug(
        f"resolve_tmdb_context → {kind=}, {dbid=}, {tmdb_id=}, "
        f"{season_number=}, target='{target}'"
    )
    return {
        "kind": kind,
        "dbid": dbid,
        "season_number": season_number,
        "tmdb_id": tmdb_id,
    }
