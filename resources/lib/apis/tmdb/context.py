# resources/lib/apis/tmdb/context.py
# author: realcopacetic

from typing import Any, Mapping, MutableMapping

from resources.lib.shared.utilities import infolabel, json_call, to_int

def get_tmdb_for_season(target: str) -> tuple[str | None, int | None]:
    """
    Resolve TMDb tvshow id and season number for a season listitem.

    :param target: InfoLabel prefix, e.g. "Container(50).ListItem"
    :return: (tvshow_tmdb_id, season_number) or (None, None) if resolution fails.
    """
    tvshow_dbid = to_int(infolabel(f"{target}.TvShowDBID"))
    if not tvshow_dbid:
        return None, None

    season_number = to_int(infolabel(f"{target}.Season"))
    if season_number is None:
        return None, None

    response: Mapping[str, Any] = json_call(
        "VideoLibrary.GetTVShowDetails",
        params={
            "tvshowid": tvshow_dbid,
            "properties": ["uniqueid"],
        },
        parent="get_tmdb_for_season",
    )

    uniqueid = response.get("result", {}).get("tvshowdetails", {}).get("uniqueid", {})

    tvshow_tmdb = uniqueid.get("tmdb")
    if not tvshow_tmdb:
        return None, None

    return str(tvshow_tmdb), season_number


def resolve_tmdb_context(params: Mapping[str, str], target: str) -> dict[str, Any]:
    """
    Resolve TMDb context (kind + ids) for the current listitem.

    :param params: URL/query params passed from the plugin call.
    :param target: InfoLabel prefix, e.g. f"{self.container}.ListItem".
    :return: Dict containing "kind", "tmdb_id", "season_number"
    """
    context: MutableMapping[str, Any] = {}

    # Normalise kind from param or fallback to InfoLabel
    kind = (params.get("type") or infolabel(f"{target}.DBType")).lower()
    context["kind"] = kind

    # 1: explicit URL param (from XML)
    tmdb_id = (params.get("tmdb_id") or "").strip()

    # 2: InfoLabel fallback
    if not tmdb_id:
        tmdb_id = infolabel(f"{target}.UniqueID(tmdb)").strip()

    # 3: DBID-based lookup (movies/tvshows/episodes)
    if not tmdb_id and kind in {"movie", "tvshow", "episode"}:
        dbid = to_int(infolabel(f"{target}.DBID"))
        if dbid is not None:
            method = {
                "movie": "VideoLibrary.GetMovieDetails",
                "tvshow": "VideoLibrary.GetTVShowDetails",
                "episode": "VideoLibrary.GetEpisodeDetails",
            }[kind]

            result_key = {
                "movie": "moviedetails",
                "tvshow": "tvshowdetails",
                "episode": "episodedetails",
            }[kind]

            response: Mapping[str, Any] = json_call(
                method,
                params={
                    f"{kind}id": dbid,
                    "properties": ["uniqueid"],
                },
                parent="resolve_tmdb_context",
            )

            uniqueid = (
                response.get("result", {}).get(result_key, {}).get("uniqueid", {})
            )
            tmdb_id = str(uniqueid.get("tmdb", "")).strip()

    # 4: seasons – use TvShowDBID + Season number
    if kind == "season":
        tv_tmdb, season_num = get_tmdb_for_season(target)
        context["season_number"] = season_num
        if tv_tmdb:
            tmdb_id = tv_tmdb

    context["tmdb_id"] = tmdb_id or None
    return dict(context)
