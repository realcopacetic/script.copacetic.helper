# resources/lib/apis/tmdb/context.py
# author: realcopacetic

from typing import Any, Mapping, MutableMapping

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import infolabel, json_call, to_int


def resolve_tmdb_context(params: Mapping[str, str], target: str) -> dict[str, Any]:
    """
    Resolve TMDb context (kind + ids) for the current listitem.

    :param params: URL/query params passed from the plugin call.
    :param target: InfoLabel prefix, e.g. f"{self.container}.ListItem".
    :return: Dict containing "kind", "tmdb_id", "season_number"
    """
    context: MutableMapping[str, Any] = {}

    kind = (params.get("type") or infolabel(f"{target}.DBType") or "").lower()
    context["kind"] = kind or None
    dbid = to_int(params.get("id") or infolabel(f"{target}.DBID"), None)
    context["dbid"] = dbid
    tmdb_id = params.get("tmdb_id") or infolabel(f"{target}.UniqueID(tmdb)") or None

    if kind == "season":
        tvshow_dbid = to_int(params.get("tvshowid") or infolabel(f"{target}.TvShowDBID"), None)
        season = to_int(params.get("season") or infolabel(f"{target}.Season"), None)
        context["season_number"] = season
        if not tmdb_id and tvshow_dbid:
            response = json_call(
                "VideoLibrary.GetTVShowDetails",
                params={"tvshowid": tvshow_dbid}, 
                properties=["uniqueid"],
                parent="resolve_tmdb_context",
            )
            uniqueid = (
                response.get("result", {}).get("tvshowdetails", {}).get("uniqueid", {})
                or {}
            )
            tmdb_id = uniqueid.get("tmdb")

    context["tmdb_id"] = tmdb_id or None
    log.debug(
        f"resolve_tmdb_context → kind={context.get('kind')!r}, "
        f"dbid={context.get('dbid')}, tmdb_id={context.get('tmdb_id')}, "
        f"season_number={context.get('season_number')}, target='{target}'"
    )

    return dict(context)
