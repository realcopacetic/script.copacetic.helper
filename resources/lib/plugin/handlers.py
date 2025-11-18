# author: realcopacetic

import inspect
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from xbmcplugin import SORT_METHOD_LASTPLAYED

from resources.lib.art.editor import ImageEditor
from resources.lib.art.multiart import collect_multiart, set_multiart_fadelabel
from resources.lib.art.policy import flatten_art_attributes
from resources.lib.plugin.geometry import PlacementOpts
from resources.lib.plugin.helpers import (
    DataHandler,
    JumpButton,
    ProgressBarManager,
    TextTruncator,
    TypewriterAnimation,
)
from resources.lib.plugin.json_map import JSON_PROPERTIES, json_to_canonical
from resources.lib.plugin.registry import PluginInfoRegistry
from resources.lib.plugin.setter import *
from resources.lib.plugin.tvshows import TvShowHelper
from resources.lib.shared import logger as log
from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import (
    ADDON,
    condition,
    infolabel,
    json_call,
    set_plugincontent,
    to_int,
)

DirectoryItem = tuple[str, Any, bool]


class _FocusGuard:
    """
    Lazy focus/identity guard for plugin operations.
    Evaluates container focus and item identity on demand.
    """

    __slots__ = (
        "caller_name",
        "focus_check",
        "expected_identity",
        "identity_getter",
    )

    def __init__(
        self,
        caller_name: str,
        focus_check: Callable[[], bool] | None,
        expected_identity: str | None,
        identity_getter: Callable[[], str],
    ):
        """
        Create a guard that checks container focus and item identity.

        :param caller_name: Name of the calling handler, used for logging.
        :param focus_check: Callable evaluating Control.HasFocus; None to skip.
        :param expected_identity: Snapshot identity for the focused item; None to disable identity guarding.
        :param identity_getter: Callable returning current item identity.
        """
        self.caller_name = caller_name
        self.focus_check = focus_check
        self.expected_identity = expected_identity
        self.identity_getter = identity_getter

    def alive(self) -> bool:
        """
        Validate current focus and item identity.

        :return: True if guard conditions still hold, otherwise False.
        """
        if self.focus_check is None and self.expected_identity is None:
            return True

        if self.focus_check is not None and not self.focus_check():
            log.debug(
                f"PluginHandlers → {self.caller_name}: ABORTED → Container lost focus"
            )
            return False

        if (
            self.expected_identity is not None
            and self.expected_identity != self.identity_getter()
        ):
            log.debug(
                f"PluginHandlers → {self.caller_name}: ABORTED → '{self.expected_identity}' lost focus"
            )
            return False

        return True


@contextmanager
def focus_guard(
    caller_name: str,
    target: int | None,
    container: str,
    expected_identity: str | None,
) -> Iterator[_FocusGuard]:
    """
    Build a focus/identity guard for a plugin operation.
    Returns a guard object whose ``alive()`` enforces stability checks.

    :param caller_name: Name of the calling handler, used for logging.
    :param target: Container/control id for Control.HasFocus; None to disable focus guarding.
    :param container: Container path used to read CurrentItem.
    :param expected_identity: Snapshot identity of focused item; None to disable identity guarding.
    :return: A ``_FocusGuard`` instance for lazy focus/identity validation.
    """
    focus_check = (
        (lambda: condition(f"Control.HasFocus({target})"))
        if target is not None
        else None
    )
    identity_getter = lambda: infolabel(f"{container}.CurrentItem")

    guard = _FocusGuard(caller_name, focus_check, expected_identity, identity_getter)
    try:
        yield guard
    finally:
        pass


class PluginHandlers(metaclass=PluginInfoRegistry):
    """
    High-level plugin actions (artwork, metadata, typewriter) with focus guarding.
    """

    def __init__(self, params: dict[str, str]) -> None:
        self.params = params

        self.label = params.get("label", "")
        self.dbtype = params.get("type", "")
        self.dbid = params.get("id", "")
        self.target = to_int(params.get("target"), None)
        self.expected = params.get("focus_guard")
        self.container = (
            f"Container({self.target})" if self.target is not None else "Container"
        )

        self.sort_lastplayed = {"order": "descending", "method": "lastplayed"}
        self.sort_year = {"order": "descending", "method": "year"}

        self.exclude_key = params.get("exclude_key", "title")
        self.exclude_value = params.get("exclude_value", "")
        self.filter_unwatched = {
            "field": "playcount",
            "operator": "lessthan",
            "value": "1",
        }
        self.filter_watched = {
            "field": "playcount",
            "operator": "greaterthan",
            "value": "0",
        }
        self.filter_no_specials = {
            "field": "season",
            "operator": "greaterthan",
            "value": "0",
        }
        self.filter_inprogress = {
            "field": "inprogress",
            "operator": "true",
            "value": "",
        }
        self.filter_exclude = {
            "field": self.exclude_key,
            "operator": "isnot",
            "value": self.exclude_value,
        }

    def focus(self):
        """
        Return a pre-filled focus guard for the calling handler.
        Auto-detects the handler name using inspect.
        """
        caller = inspect.stack()[1].function
        return focus_guard(
            caller_name=caller,
            target=self.target,
            container=self.container,
            expected_identity=self.expected,
        )

    @log.duration
    def artwork(self) -> list[tuple]:
        """
        Process/calculate artwork and attach to listitem; aborts if focus changes.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        with self.focus() as guard:
            if not guard.alive():
                return

            image_processor = ImageEditor(SQLiteHandler()).image_processor
            overlay_target = self.params.get("overlay_target")
            try:
                overlay_target = (
                    float(overlay_target) if overlay_target is not None else None
                )
            except:
                overlay_target = None

            processed = image_processor(
                processes={"clearlogo": "crop", "fanart": "blur"},
                source=f"{self.container}.ListItem",
                overlay_enable=self.params.get("overlay_enable"),
                overlay_source=self.params.get("overlay_source"),
                overlay_rects=self.params.get("overlay_rects"),
                overlay_target=overlay_target,
            )

            if not guard.alive():
                return

            art = flatten_art_attributes(processed)
            art |= collect_multiart(
                target=f"{self.container}.ListItem",
                art_type=self.params.get("multiart"),
                max_items=self.params.get("multiart_max"),
            )
            log.debug(
                f"{self.__class__.__name__} → Artwork returned from ImageEditor {art}"
            )

            if not guard.alive():
                return

            fadelabel_id = self.params.get("multiart_fadelabel")
            if fadelabel_id and art:
                set_multiart_fadelabel(
                    fadelabel_id=fadelabel_id,
                    art=art,
                    randomize=True,
                    keep_main_first=True,
                )
            current_position = to_int(self.expected, 0)
            return set_items(
                [
                    {
                        "file": "artwork",
                        "art": art,
                        "properties": {
                            "previous": current_position - 1,
                            "next": current_position + 1,
                        },
                    }
                ],
                media_type="artwork",
            )

    @log.duration
    def darken(self) -> list[tuple]:
        """
        On-demand darken for a single fanart path. Acts as a lightweight
        alternative entry point for darkening without invoking artwork handler.
        """
        with self.focus() as guard:
            if not guard.alive():
                return

            url = self.params.get("fanart") or ""
            if not url:
                return

            val = ImageEditor(SQLiteHandler()).compute_darken_runtime(
                url=url,
                overlay_enable=self.params.get("overlay_enable", "true"),
                overlay_source=self.params.get("overlay_source"),
                overlay_rects=self.params.get("overlay_rects"),
                overlay_target=self.params.get("overlay_target"),
            )
            if not guard.alive() or val is None:
                return

            return set_items(
                [
                    {
                        "file": "darken",
                        "label": str(val),
                        "properties": {"fanart_darken": str(val)},
                    }
                ],
                media_type="darken",
            )

    @log.duration
    def jumpbutton(self) -> None:
        """
        Update jump button overlay using params and placement options.

        :return: None (no directory items created)
        """
        jump = JumpButton()
        jump.update(
            sortletter=self.params.get("sortletter", ""),
            scroll_id=self.params.get("scroll_id", ""),
            opts=PlacementOpts.from_params(self.params),
        )

    @log.duration
    def metadata(self) -> None:
        """
        Fetch/attach cleaned metadata to a helper list item; aborts if focus changes.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        with self.focus() as guard:
            if not guard.alive():
                return

            data = DataHandler(
                target=f"{self.container}.ListItem",
                dbtype=self.dbtype,
                dbid=self.dbid,
            ).fetch_data()

            if not guard.alive():
                return

            truncate_label = self.params.get("truncate_label")
            truncate_id = to_int(self.params.get("truncate_id", 0))
            if truncate_label and truncate_id > 0:
                trunc = TextTruncator(
                    measure_ctrl_id=truncate_id,
                )
                truncated = trunc.truncate(
                    text=truncate_label,
                    min_safe=to_int(self.params.get("truncate_min_safe", 0)),
                    smart_cap=self.params.get("truncate_smart_cap", "").lower()
                    == "true",
                )
                data |= {"properties": {"truncated_label": truncated}}

            return set_items([data], media_type="metadata")

    @log.duration
    def progressbar(self) -> list[tuple]:
        """
        Compute resume/unwatched values and expose a helper item for the list.
        If focus changes mid-flight, skip UI update but still return the item.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        with self.focus() as guard:
            result = []
            if not guard.alive():
                return result

            pb = ProgressBarManager(target=f"{self.container}.ListItem")
            resume, unwatched = pb.calculate()
            result.extend(
                set_items(
                    [
                        {
                            "file": "progress",
                            "label": str(resume),
                            "resume": {"position": resume, "total": 100},
                            "properties": {"unwatchedepisodes": str(unwatched)},
                        }
                    ],
                    media_type="progressbar",
                )
            )

            if not guard.alive():
                return result

            opts = PlacementOpts.from_params(self.params)
            base_id = to_int(self.params.get("base_id"), None)
            backing_id = to_int(self.params.get("backing_id"), None)
            progress_id = to_int(self.params.get("progress_id"), None)
            btn_id = to_int(self.params.get("btn_id"), None)
            pb.update(
                percent=resume,
                opts=opts,
                base_id=base_id,
                backing_id=backing_id,
                progress_id=progress_id,
                btn_id=btn_id,
            )
            return result

    @log.duration
    def tmdb(self) -> list[tuple]:

        from resources.lib.apis.tmdb.client import fetch_tmdb_fields

        with self.focus() as guard:
            if not guard.alive():
                return

            kind = (self.params.get("kind") or "tvshow").lower()
            tmdb_id = to_int(self.params.get("tmdb_id"), 0)

            if tmdb_id <= 0:
                log.debug(
                    f"{self.__class__.__name__} → tmdb: missing or invalid tmdb_id "
                    f"({self.params.get('tmdb_id')!r})"
                )
                return

            tagline = fetch_tmdb_fields(kind, tmdb_id, fields=["tagline"])
            data = {"file": "tmdb"}
            data |= tagline
            log.debug(f"FUCK DEBUG data {data}")

            if not guard.alive():
                return

            return set_items(
                [data],
                media_type="tmdb",
            )

    @log.duration
    def typewriter(self) -> None:
        """
        Run typewriter animation for the current listitem; guarded against focus changes.

        :return: None (no directory items created)
        """
        with self.focus() as guard:
            if not guard.alive():
                return

            label_id = to_int(self.params.get("label_id"), None)
            line_step = to_int(self.params.get("line_step"), None)
            max_lines = to_int(self.params.get("max_lines"), None)

            t = TypewriterAnimation()
            t.update(
                label=self.label,
                opts=PlacementOpts.from_params(self.params),
                label_id=label_id,
                line_step=line_step,
                max_lines=max_lines,
                alive=guard.alive,
            )

    def in_progress(self) -> list[DirectoryItem] | None:
        """
        Build a container of in-progress movies and episodes.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        set_plugincontent(
            content="videos",
            category=ADDON.getLocalizedString(32601),
            sort_method=SORT_METHOD_LASTPLAYED,
        )
        results = []
        filters = [self.filter_inprogress]
        if self.dbtype != "tvshow":
            results.extend(
                self._fetch_and_add(
                    method="VideoLibrary.GetMovies",
                    content_type="movies",
                    filters=filters,
                    sort=self.sort_lastplayed,
                    parent="in_progress",
                    tag_applier=apply_videoinfotag,
                )
            )

        if self.dbtype != "movie":
            results.extend(
                self._fetch_and_add(
                    method="VideoLibrary.GetEpisodes",
                    content_type="episodes",
                    filters=filters,
                    sort=self.sort_lastplayed,
                    parent="in_progress",
                    tag_applier=apply_videoinfotag,
                    postprocess=lambda eps: self._enrich_with_tvshow(
                        eps, parent="in_progress"
                    ),
                )
            )

        return results or None

    def next_up(self) -> list[DirectoryItem] | None:
        """
        Build a container of "next up" TV episodes.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        set_plugincontent(content="episodes", category=ADDON.getLocalizedString(32600))
        results_meta = []
        q = json_call(
            "VideoLibrary.GetTVShows",
            properties=["title", "tvshowid", "studio", "mpaa", "lastplayed"],
            sort=self.sort_lastplayed,
            limit=25,
            query_filter={"and": [self.filter_inprogress]},
            parent="next_up",
        )
        shows = q.get("result", {}).get("tvshows", [])
        if not shows:
            log.debug(f"{self.__class__.__name__} → next_up: No TV shows found.")
            return

        for show in shows:
            tvshow_id = to_int(show.get("tvshowid"), 00)
            if tvshow_id <= 0:
                continue

            ep_query = json_call(
                "VideoLibrary.GetEpisodes",
                properties=JSON_PROPERTIES["episodes"],
                sort={"order": "ascending", "method": "episode"},
                limit=1,
                query_filter={"and": [self.filter_unwatched, self.filter_no_specials]},
                params={"tvshowid": tvshow_id},
                parent="next_up",
            )

            episodes = ep_query.get("result", {}).get("episodes", [])
            if not episodes:
                log.debug(
                    f"{self.__class__.__name__} → next_up: No unwatched episodes for "
                    f"{show.get('title', '<unknown>')}"
                )
                continue

            raw_ep = episodes[0]
            raw_ep.setdefault("studio", show.get("studio", ""))
            raw_ep.setdefault("mpaa", show.get("mpaa", ""))
            canonical = json_to_canonical(raw_ep, "episode")

            dir_items = set_items(
                [canonical],
                media_type="episode",
                tag_applier=apply_videoinfotag,
            )
            if not dir_items:
                continue

            file_path, li, is_folder = dir_items[0]
            effective_lastplayed, is_new = TvShowHelper.compute_new_unwatched(
                show.get("lastplayed"),
                raw_ep.get("firstaired"),
            )

            if is_new:
                li.setProperty(TvShowHelper.NEW_UNWATCHED_PROP, "true")

            results_meta.append((effective_lastplayed, (file_path, li, is_folder)))

        if not results_meta:
            return None

        results_meta.sort(key=lambda r: r[0] or "", reverse=True)
        results = [entry[1] for entry in results_meta]

        return results or None

    def actor_credits(self) -> list[DirectoryItem] | None:
        """
        Build a container of movies and TV shows featuring ``self.label``.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        set_plugincontent(
            content="videos",
            category=ADDON.getLocalizedString(32603),
        )
        return self._role_credits(
            field="actor",
            sources=[
                ("VideoLibrary.GetMovies", "movies"),
                ("VideoLibrary.GetTVShows", "tvshows"),
            ],
            parent="actor_credits",
        )

    def director_credits(self) -> list[DirectoryItem] | None:
        """
        Build a container of movies and music videos directed by ``self.label``.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        set_plugincontent(
            content="videos",
            category=ADDON.getLocalizedString(32602),
        )
        return self._role_credits(
            field="director",
            sources=[
                ("VideoLibrary.GetMovies", "movies"),
                ("VideoLibrary.GetMusicVideos", "musicvideos"),
            ],
            parent="director_credits",
        )

    def writer_credits(self) -> list[DirectoryItem] | None:
        """
        Build a container of movies and episodes written by ``self.label``.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        set_plugincontent(content="videos", category=ADDON.getLocalizedString(32604))
        results = self._role_credits(
            field="writer",
            content_map=[
                ("VideoLibrary.GetMovies", "movie"),
                ("VideoLibrary.GetEpisodes", "episode"),
            ],
            parent="writer_credits",
            enrich_tvshows=True,  # so episodes get mpaa/studio
        )
        return results or None

    def _role_credits(
        self,
        field: str,
        sources: list[tuple[str, str]],
        parent: str,
    ) -> list[DirectoryItem] | None:
        """
        Generic role-based credits fetcher for actors/directors.

        :param field: VideoLibrary filter field (e.g. "actor", "director").
        :param sources: List of (method, content_type) pairs to query.
        :param parent: Parent name for logging.
        :return: List of (file, ListItem, isFolder) tuples, or None if empty.
        """
        results = []
        filters = [
            {"field": field, "operator": "is", "value": self.label},
        ]
        if self.filter_exclude:
            filters.append(self.filter_exclude)

        for method, content_type in sources:
            results.extend(
                self._fetch_and_add(
                    method=method,
                    content_type=content_type,
                    filters=filters,
                    sort=self.sort_year,
                    parent=parent,
                    tag_applier=apply_videoinfotag,
                )
            )

        return results or None

    def _fetch_and_add(
        self,
        method: str,
        content_type: str,
        filters: list[dict[str, Any]],
        sort: dict[str, Any],
        parent: str,
        tag_applier: TagApplier | None = apply_videoinfotag,
        postprocess: Callable[[list[dict[str, Any]]], None] | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[tuple]:
        """
        Fetch JSON-RPC items, normalise to canonical metadata, and build ListItems.

        :param method: JSON-RPC method (e.g. "VideoLibrary.GetMovies").
        :param content_type: Logical content type (e.g. "movie", "episode").
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
            properties=JSON_PROPERTIES.get(content_type, []),
            sort=sort,
            query_filter={"and": filters},
            params=params or {},
            parent=parent,
        )

        items = q.get("result", {}).get(f"{content_type}s", []) or []
        if not items:
            log.debug(f"PluginHandlers → {parent}: No {content_type}s found.")
            return []

        if postprocess is not None:
            postprocess(items)

        canonical_items = [json_to_canonical(raw, content_type) for raw in items]

        return set_items(
            canonical_items,
            media_type=content_type,
            tag_applier=tag_applier,
        )

    def _enrich_with_tvshow(self, episodes: list[dict[str, Any]], parent: str) -> None:
        """
        Postprocess episodes to add studio/mpaa from parent TV show.
        Caches each json lookup to save processing for multiple episodes from same show.

        :param episodes: Episode dicts to enrich (in place).
        :param parent: Parent name for logging.
        :return: None
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
