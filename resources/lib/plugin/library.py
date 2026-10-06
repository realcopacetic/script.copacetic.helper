# author: realcopacetic

from functools import wraps
from typing import Any, Callable, Iterable

from resources.lib.plugin.json_map import JSON_PROPERTIES, json_to_canonical
from resources.lib.plugin.registry import LOG_TAG
from resources.lib.plugin.setter import TagApplier, apply_videoinfotag, set_items
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import ADDON, json_call, set_plugincontent

DirectoryItem = tuple[str, Any, bool]


def title_filter(titles: Iterable[str], field: str = "title") -> dict[str, Any]:
    """
    Build an any-of exact-match filter rule from a collection of titles.
    De-duplicates and drops empty values.

    :param titles: Titles to match.
    :param field: Filter field name ("title", or "tvshow" for episode queries).
    :return: Filter rule dict.
    """
    return {
        "field": field,
        "operator": "is",
        "value": sorted({t for t in titles if t}),
    }


def fetch_raw(
    method: str,
    media_type: str,
    filters: list[dict[str, Any]],
    sort: dict[str, Any] | None,
    parent: str,
    params: dict[str, Any] | None = None,
    limit: int | None = None,
    properties: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Fetch raw JSON-RPC library items.

    :param method: JSON-RPC method (e.g. "VideoLibrary.GetMovies").
    :param media_type: Logical content type (e.g. "movie", "episode").
    :param filters: List of filter dicts to AND together; empty for no filter.
    :param sort: Sort specification for JSON-RPC; None for server default order.
    :param parent: Parent name for logging.
    :param params: Optional extra params to pass to JSON-RPC.
    :param limit: Optional maximum number of items to fetch.
    :param properties: Property-list override; None selects the full JSON_PROPERTIES set.
    :return: List of raw item dicts.
    """
    if properties is None:
        properties = JSON_PROPERTIES.get(media_type)
        if properties is None:
            raise ValueError(f"fetch_raw: unknown media_type {media_type!r}")

    q = json_call(
        method,
        properties=properties,
        sort=sort,
        query_filter={"and": filters} if filters else None,  # "and" needs 1+ rules
        params=params or {},
        limit=limit,
        parent=parent,
    )
    return q.get("result", {}).get(f"{media_type}s", []) or []


def build_items(
    raw_items: list[dict[str, Any]],
    media_type: str,
    tag_applier: TagApplier | None,
) -> list[DirectoryItem]:
    """
    Canonicalise raw library dicts and build directory ListItems.

    :param raw_items: Raw JSON-RPC item dicts.
    :param media_type: Logical content type for canonicalisation.
    :param tag_applier: Optional tag-applier for the VideoInfoTag.
    :return: List of (file, xbmcgui.ListItem, isFolder) tuples.
    """
    canonical_items = [json_to_canonical(raw, media_type) for raw in raw_items]
    return set_items(
        canonical_items,
        media_type=media_type,
        tag_applier=tag_applier,
    )


def fetch_and_add(
    method: str,
    media_type: str,
    filters: list[dict[str, Any]],
    sort: dict[str, Any],
    parent: str,
    tag_applier: TagApplier | None,
    params: dict[str, Any] | None = None,
    limit: int | None = None,
    postprocess: Callable[[list[dict[str, Any]]], None] | None = None,
    properties: list[str] | None = None,
) -> list[DirectoryItem]:
    """
    Fetch JSON-RPC library items and build canonical ListItems.

    :param method: JSON-RPC method (e.g. "VideoLibrary.GetMovies").
    :param media_type: Logical content type (e.g. "movie", "episode").
    :param filters: List of filter dicts to AND together.
    :param sort: Sort specification for JSON-RPC.
    :param parent: Parent name for logging.
    :param tag_applier: Optional tag-applier for the VideoInfoTag.
    :param params: Optional extra params to pass to JSON-RPC.
    :param limit: Optional maximum number of items to fetch.
    :param postprocess: Optional in-place mutator for the raw item list.
    :param properties: Optional property-list override; defaults to JSON_PROPERTIES.
    :return: List of (file, xbmcgui.ListItem, isFolder) tuples.
    """
    items = fetch_raw(
        method,
        media_type,
        filters,
        sort=sort,
        parent=parent,
        params=params,
        limit=limit,
        properties=properties,
    )
    if not items:
        log.debug(f"{LOG_TAG} → {parent}: No {media_type}s found.")
        return []

    if postprocess is not None:
        postprocess(items)

    return build_items(items, media_type, tag_applier)


def enrich_with_tvshow(episodes: list[dict[str, Any]], parent: str) -> None:
    """
    Enrich episodes with studio/mpaa from their parent TV show.
    Required because these fields are not in the Video.Fields.Episode enum.
    Uses a single title-filtered GetTVShows.

    :param episodes: Episode dicts to enrich (in place).
    :param parent: Parent name for logging.
    """

    wanted = {ep["tvshowid"] for ep in episodes if ep.get("tvshowid")}
    if not wanted:
        return

    rule = title_filter(ep.get("showtitle", "") for ep in episodes)
    q = json_call(
        "VideoLibrary.GetTVShows",
        properties=["studio", "mpaa"],
        query_filter={"and": [rule]} if rule["value"] else None,
        parent=parent,
    )
    meta = {
        s["tvshowid"]: s
        for s in q.get("result", {}).get("tvshows", [])
        if s.get("tvshowid") in wanted
    }
    for ep in episodes:
        s = meta.get(ep.get("tvshowid"))
        if s:
            ep["studio"] = s.get("studio")
            ep["mpaa"] = s.get("mpaa")


def role_credits(
    field: str,
    label: str,
    filter_exclude: dict[str, Any] | None,
    sources: list[tuple[str, str]],
    sort: dict[str, Any],
    parent: str,
    tag_applier: TagApplier | None,
    postprocess: Callable[[list[dict[str, Any]]], None] | None = None,
    limit: int | None = None,
) -> list[DirectoryItem] | None:
    """
    Generic role-based credits fetcher for actors/directors/writers.

    :param field: VideoLibrary filter field ("actor", "director", "writer").
    :param label: Actor/director/writer name to filter by.
    :param filter_exclude: Optional exclusion filter dict appended to the filter list.
    :param sources: List of (method, media_type) pairs to query.
    :param sort: Sort specification for JSON-RPC.
    :param parent: Parent name for logging.
    :param tag_applier: Optional tag-applier for the VideoInfoTag.
    :param postprocess: Optional in-place mutator for the raw item list.
    :param limit: Most items per source, after the sort; None for all.
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
                limit=limit,
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
    Decorator for role-based credits endpoints: injects static configuration and
    dispatches into ``role_credits()`` with the path's sort= (a JSON-RPC sort
    method, descending; default year) and limit=.

    :param field: Kodi JSON filter field (``"actor"``, ``"director"``, ``"writer"``).
    :param category_id: Localized string ID for the plugin category label.
    :param sources: List of ``(method, media_type)`` JSON-RPC pairs.
    :param parent: Parent name for logging.
    :param postprocess: Optional in-place postprocessor for episode lists.
    :return: Wrapped handler returning directory items or None.
    """

    def decorator(func: Callable) -> Callable[[Any], list[DirectoryItem] | None]:
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
                # type= keeps one media type, e.g. movies only for a movie
                sources=[s for s in sources if self.dbtype in ("", s[1])],
                sort={"method": self.params.get("sort", "year"), "order": "descending"},
                parent=parent,
                tag_applier=apply_videoinfotag,
                postprocess=postprocess,
                limit=self.limit,
            )

        return wrapper

    return decorator
