# resources/lib/apis/tmdb/context.py
# author: realcopacetic

from typing import Any, Mapping, MutableMapping

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import infolabel, json_call, to_int

_DETAILS_LOOKUP_BY_KIND: dict[str, dict[str, str]] = {
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
    uniqueid = (
        response.get("result", {}).get(result_key, {}).get("uniqueid", {}) or {}
    )
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

    context: MutableMapping[str, Any] = {}
    context["kind"] = kind = (first("type", "DBType") or "").lower() or None
    context["dbid"] = dbid = to_int(first("id", "DBID"), None)
    tmdb_id = first("tmdb_id", "UniqueID(tmdb)")
    context["season_number"] = to_int(first("season", "Season"), None)

    if kind in ("season", "episode"):
        lookup_dbid = to_int(
            first("tvshowid", "TvShowDBID")
            or infolabel(f"{target}.Property(tvshowid)"),
            None,
        )
        lookup_kind = "tvshow"
        if kind == "episode":
            # No /tv/{id}/episode endpoint — escalate to show-level fetch.
            context["kind"] = "tvshow"
            tmdb_id = None
    else:
        lookup_dbid = dbid
        lookup_kind = kind

    if not tmdb_id and lookup_dbid and lookup_kind in _DETAILS_LOOKUP_BY_KIND:
        lookup = _DETAILS_LOOKUP_BY_KIND[lookup_kind]
        tmdb_id = _lookup_uniqueid_tmdb(
            method=lookup["method"],
            id_key=lookup["id_key"],
            id_value=lookup_dbid,
            result_key=lookup["result_key"],
        )

    context["tmdb_id"] = tmdb_id or None
    log.debug(
        f"resolve_tmdb_context → kind={context.get('kind')!r}, "
        f"dbid={context.get('dbid')}, tmdb_id={context.get('tmdb_id')}, "
        f"season_number={context.get('season_number')}, target='{target}'"
    )
    return dict(context)
