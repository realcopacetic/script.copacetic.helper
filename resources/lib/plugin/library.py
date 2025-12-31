# author: realcopacetic

from functools import wraps
from typing import Any, Callable

from resources.lib.plugin.json_map import JSON_PROPERTIES, json_to_canonical
from resources.lib.plugin.setter import TagApplier, apply_videoinfotag, set_items
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import ADDON, json_call, set_plugincontent, to_int

DirectoryItem = tuple[str, Any, bool]


def fetch_and_add(
    method: str,
    media_type: str,
    filters: list[dict[str, Any]],
    sort: dict[str, Any],
    parent: str,
    tag_applier: TagApplier | None,
    params: dict[str, Any] | None = None,
    postprocess: Callable[[list[dict[str, Any]]], None] | None = None,
) -> list[DirectoryItem]:
    """
    Fetch JSON-RPC library items and build canonical ListItems.

    :param method: JSON-RPC method (e.g. "VideoLibrary.GetMovies").
    :param media_type: Logical content type (e.g. "movie", "episode").
    :param filters: List of filter dicts to AND together.
    :param sort: Sort specification for JSON-RPC.
    :param parent: Parent name for logging.
    :param tag_applier: Optional tag-applier for the VideoInfoTag.
    :param postprocess: Optional in-place mutator for the raw item list.
    :param params: Optional extra params to pass to JSON-RPC.
    :return: List of (file, xbmcgui.ListItem, isFolder) tuples.
    """
    q = json_call(
        method,
        properties=JSON_PROPERTIES.get(media_type, []),
        sort=sort,
        query_filter={"and": filters},
        params=params or {},
        parent=parent,
    )
    items = q.get("result", {}).get(f"{media_type}s", []) or []
    if not items:
        log.debug(f"PluginHandlers → {parent}: No {media_type}s found.")
        return []

    if postprocess is not None:
        postprocess(items)

    canonical_items = [json_to_canonical(raw, media_type) for raw in items]
    return set_items(
        canonical_items,
        media_type=media_type,
        tag_applier=tag_applier,
    )


def enrich_with_tvshow(episodes: list[dict[str, Any]], parent: str) -> None:
    """
    Enrich episodes with studio/mpaa from their parent TV show.
    Required because fields not contained within Video.Fields.Episode enum.
    Results cached to avoid multiple json requests for the same show.

    :param episodes: Episode dicts to enrich (in place).
    :param parent: Parent name for logging.
    """
    cache = {}
    for ep in episodes:
        tvshowid = ep.get("tvshowid")
        if not tvshowid:
            continue

        meta = cache.get(tvshowid)
        if meta is None:
            details = json_call(
                "VideoLibrary.GetTVShowDetails",
                params={"tvshowid": tvshowid},
                properties=["studio", "mpaa"],
                parent=parent,
            )
            meta = details.get("result", {}).get("tvshowdetails", {}) or {}
            cache[tvshowid] = meta

        ep["studio"] = meta.get("studio")
        ep["mpaa"] = meta.get("mpaa")


def role_credits(
    field: str,
    label: str,
    filter_exclude: dict[str, Any] | None,
    sources: list[tuple[str, str]],
    sort: dict[str, Any],
    parent: str,
    tag_applier: TagApplier | None,
    postprocess: Callable[[list[dict[str, Any]]], None] | None = None,
) -> list[DirectoryItem] | None:
    """
    Generic role-based credits fetcher for actors/directors/writers.

    :param field: VideoLibrary filter field ("actor", "director", "writer").
    :param sources: List of (method, media_type) pairs to query.
    :param parent: Parent name for logging.
    :param postprocess: Optional in-place mutator for the raw item list.
    :return: List of (file, ListItem, isFolder) tuples, or None if empty.
    """
    results = []
    filters = [
        {"field": field, "operator": "is", "value": label},
    ]
    if filter_exclude:
        filters.append(filter_exclude)

    for method, media_type in sources:
        results.extend(
            fetch_and_add(
                method=method,
                media_type=media_type,
                filters=filters,
                sort=sort,
                parent=parent,
                tag_applier=tag_applier,
                postprocess=postprocess,
            )
        )

    return results or None


def role_endpoint(
    *,
    field: str,
    category_id: int,
    sources: list[tuple[str, str]],
    parent: str,
    postprocess: Callable[[list[dict[str, Any]]], None] | None = None,
):
    """
    Decorator for role-based credits endpoints.
    Injects static configuration and dispatches into ``role_credits()``.

    :param field: Kodi JSON filter field (``"actor"``, ``"director"``, ``"writer"``).
    :param category_id: Localized string ID for the plugin category label.
    :param sources: List of ``(method, media_type)`` JSON-RPC pairs.
    :param parent: Parent name for logging.
    :param postprocess: Optional in-place postprocessor for episode lists.
    :return: Wrapped handler returning directory items or None.
    """
    def decorator(func: Callable) -> Callable[[Any], list[DirectoryItem | None]]:
        @wraps(func)
        def wrapper(self, *args, **kwargs) -> list[DirectoryItem] | None:
            set_plugincontent(
                content="videos",
                category=ADDON.getLocalizedString(category_id),
            )
            return role_credits(
                field=field,
                label=self.label,
                filter_exclude=self.filter_exclude,
                sources=sources,
                sort=self.sort_year,
                parent=parent,
                tag_applier=apply_videoinfotag,
                postprocess=postprocess,
            )

        return wrapper
    return decorator


class TvShowHelper:
    """Utility helpers for TV show progress and freshness calculations."""

    NEW_UNWATCHED_PROP = "new_unwatched"

    @staticmethod
    def compute_new_unwatched(
        lastplayed: str | None,
        firstaired: str | None,
    ) -> tuple[str, bool]:
        """
        Compute effective recency and whether a show has new unwatched episodes.

        :param lastplayed: Lastplayed timestamp for the TV show.
        :param firstaired: Firstaired date of the candidate next episode.
        :return: Tuple of (effective_lastplayed, is_new_since_lastplayed).
        """
        lp = lastplayed or ""
        fa = firstaired or ""

        if lp and fa:
            effective = max(lp, fa)
            is_new = fa > lp
        else:
            effective = lp or fa or ""
            is_new = False

        return effective, is_new

    @staticmethod
    def compute_episode_stats(
        total_episodes: Any,
        watched_episodes: Any,
    ) -> dict[str, int | float]:
        """
        Compute watched/unwatched episode counters and watched percentage.

        :param total_episodes: Total episode count for the show.
        :param watched_episodes: Number of watched episodes for the show.
        :return: Dict with episodes, watchedepisodes, unwatchedepisodes, watchedpercent.
        """
        total = to_int(total_episodes, 0)
        watched = to_int(watched_episodes, 0)
        return {
            "episodes": total,
            "watchedepisodes": watched,
            "unwatchedepisodes": max(total - watched, 0),
            "watchedpercent": int((watched / total & 100)) if total > 0 else 0,
        }
