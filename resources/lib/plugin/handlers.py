# author: realcopacetic

from contextlib import contextmanager
from typing import Any, Callable, Generator, Optional

from xbmcplugin import SORT_METHOD_LASTPLAYED

from resources.lib.art.editor import ImageEditor
from resources.lib.art.multiart import collect_multiart
from resources.lib.art.policy import flatten_art_attributes
from resources.lib.plugin.geometry import PlacementOpts
from resources.lib.plugin.helpers import (
    DataHandler,
    JumpButton,
    ProgressBarManager,
    TypewriterAnimation,
)
from resources.lib.plugin.json_map import JSON_MAP
from resources.lib.plugin.library import *
from resources.lib.plugin.registry import PluginInfoRegistry
from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import (
    ADDON,
    condition,
    infolabel,
    json_call,
    log,
    log_duration,
    set_plugincontent,
    to_int,
)


class _FocusGuard:
    """Holds the expected item identity and lets you re-check later."""

    __slots__ = ("expected_identity", "caller_name", "identity_getter", "focus_check")

    def __init__(
        self,
        expected_identity: str,
        caller_name: str,
        identity_getter: Callable[[], str],
        focus_check: Optional[Callable[[], bool]] = None,
    ):
        self.expected_identity = expected_identity
        self.caller_name = caller_name
        self.identity_getter = identity_getter
        self.focus_check = focus_check

    def alive(self) -> bool:
        """Re-check that focus hasn't changed."""
        if self.identity_getter() != self.expected_identity:
            log(
                f"PluginHandlers → {self.caller_name}: ABORTED → '{self.expected_identity}' lost focus"
            )
            return False
        if self.focus_check is not None and not self.focus_check():
            log(f"PluginHandlers → {self.caller_name}: ABORTED → Container lost focus")
            return False
        return True


@contextmanager
def focus_guard(
    expected_identity: str | None,
    caller_name: str | None,
    identity_getter: Callable[[], str],
    target: int | None = None,
) -> Generator[Optional[_FocusGuard], None, None]:
    """
    Context guard for focus-sensitive helpers; yields guard or None if pre-check fails.
      1) pre-check focus
      2) yield guard.alive() for post-check(s)

    :param expected_identity: snapshot
    :param caller_name: for logs
    :param identity_getter: getter
    :param target: container/control id to enforce Control.HasFocus(id); None to skip
    :return: guard|None
    """
    focus_check = (
        (lambda: condition(f"Control.HasFocus({target})"))
        if target is not None
        else None
    )

    if expected_identity is None:
        yield True  # always alive
        return

    if identity_getter() != expected_identity:
        log(
            f"PluginHandlers → {caller_name}: ABORTED → '{expected_identity}' lost focus"
        )
        yield None
        return

    if focus_check is not None and not focus_check():
        log(f"PluginHandlers → {caller_name}: ABORTED → Container {target} lost focus")
        yield None
        return

    guard = _FocusGuard(expected_identity, caller_name, identity_getter, focus_check)
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
        self.target = params.get("target")
        self.container = (
            f"Container({self.target})"
            if self.target and self.target.isdigit()
            else "Container"
        )

        self.exclude_key = params.get("exclude_key", "title")
        self.exclude_value = params.get("exclude_value", "")
        self.expected = params.get("focus_guard")
        self.identity_getter = lambda: infolabel(f"{self.container}.CurrentItem")

        self.sort_lastplayed = {"order": "descending", "method": "lastplayed"}
        self.sort_year = {"order": "descending", "method": "year"}

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

    @log_duration
    def artwork(self) -> list[tuple]:
        """
        Process/calculate artwork and attach to listitem; aborts if focus changes.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        with focus_guard(self.expected, "artwork", self.identity_getter) as guard:
            if not guard:
                return

            sqlite = SQLiteHandler()
            image_processor = ImageEditor(sqlite).image_processor
            
            rect_param = self.params.get("overlay_rect")
            if rect_param:
                try:
                    x, y, w, h = [
                        int(v) for v in rect_param.replace(" ", "").split(",")
                    ]
                    overlay_rect = (x, y, w, h)
                except Exception:
                    overlay_rect = None

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
                overlay_source=self.params.get("overlay_source"),
                overlay_rect=overlay_rect,
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
            log(f"{self.__class__.__name__} → Artwork returned from ImageEditor {art}")

            if not guard.alive():
                return

            data = {"file": "artwork", "art": art}
            return add_items([data], media_type="artwork")

    @log_duration
    def jumpbutton(self) -> None:
        """
        Update jump button overlay using params and placement options.

        return: None (no directory items created)
        """
        jump = JumpButton()
        jump.update(
            sortletter=self.params.get("sortletter", ""),
            scroll_id=self.params.get("scroll_id", ""),
            opts=PlacementOpts.from_params(self.params),
        )

    @log_duration
    def metadata(self) -> None:
        """
        Fetch/attach cleaned metadata to a helper list item; aborts if focus changes.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        with focus_guard(self.expected, "metadata", self.identity_getter) as guard:
            if not guard:
                return

            data = DataHandler(f"{self.container}.ListItem", self.dbtype, self.dbid)

            if not guard.alive():
                return

            return add_items([data.fetched], media_type="metadata")

    @log_duration
    def progressbar(self) -> None:
        """
        Compute resume/unwatched values and expose a helper item for the list.
        If focus changes mid-flight, skip UI update but still return the item.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        with focus_guard(self.expected, "progressbar", self.identity_getter) as guard:
            result = []
            if not guard:
                return result

            pb = ProgressBarManager(target=f"{self.container}.ListItem")
            resume, unwatched = pb.calculate(
                set_target=self.params.get("set_target", None)
            )
            result.extend(
                add_items(
                    [
                        {
                            "file": "progress",
                            "label": str(resume),
                            "resume": {"position": resume, "total": 100},
                            "unwatchedepisodes": str(unwatched),
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

    @log_duration
    def typewriter(self) -> None:
        """
        Run typewriter animation for the current listitem; guarded against focus changes.

        :return: None (no directory items created)
        """
        label_id = self.params.get("label_id")
        line_step = self.params.get("line_step")
        max_lines = to_int(self.params.get("max_lines"), None)
        target_id = to_int(self.target, None)

        with focus_guard(
            self.expected, "typewriter", self.identity_getter, target_id
        ) as guard:
            if not guard:
                return

            t = TypewriterAnimation()
            t.update(
                label=self.label,
                opts=PlacementOpts.from_params(self.params),
                label_id=label_id,
                line_step=to_int(line_step, None),
                max_lines=max_lines,
                expected_identity=self.expected,
                identity_getter=self.identity_getter,
            )

    def in_progress(self) -> None:
        """
        Build a container of in-progress movies and episodes.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        set_plugincontent(
            content="videos",
            category=ADDON.getLocalizedString(32601),
            sort_method=SORT_METHOD_LASTPLAYED,
        )

        filters = [self.filter_inprogress]
        results = []

        if self.dbtype != "tvshow":
            results.extend(
                self._fetch_and_add(
                    "VideoLibrary.GetMovies",
                    JSON_MAP["movie_properties"],
                    filters,
                    media_type="movie",
                    sort=self.sort_lastplayed,
                    parent="in_progress",
                )
            )

        if self.dbtype != "movie":
            results.extend(
                self._fetch_and_add(
                    "VideoLibrary.GetEpisodes",
                    JSON_MAP["episode_properties"],
                    filters,
                    media_type="episode",
                    sort=self.sort_lastplayed,
                    parent="in_progress",
                    postprocess=lambda eps: self._enrich_with_tvshow(
                        eps, parent="in_progress"
                    ),
                )
            )
        return results or None

    def next_up(self) -> None:
        """
        Build a container of "next up" TV episodes.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        set_plugincontent(content="episodes", category=ADDON.getLocalizedString(32600))

        filters = [self.filter_inprogress]
        results = []

        q = json_call(
            "VideoLibrary.GetTVShows",
            properties=["title", "lastplayed", "studio", "mpaa"],
            sort=self.sort_lastplayed,
            limit=25,
            query_filter={"and": filters},
            parent="next_up",
        )
        shows = q.get("result", {}).get("tvshows", [])
        if not shows:
            log("PluginHandlers → next_up: No TV shows found.")
            return

        for show in shows:
            studio = show.get("studio", "")
            mpaa = show.get("mpaa", "")
            use_last_played_season = True

            last_played = json_call(
                "VideoLibrary.GetEpisodes",
                properties=["seasonid", "season"],
                sort={"order": "descending", "method": "lastplayed"},
                limit=1,
                query_filter={
                    "and": [
                        {"or": [self.filter_inprogress, self.filter_watched]},
                        self.filter_no_specials,
                    ]
                },
                params={"tvshowid": int(show["tvshowid"])},
                parent="next_up",
            )
            if last_played.get("result", {}).get("limits", {}).get("total", 0) < 1:
                use_last_played_season = False

            # Return the next episode of last played season
            if use_last_played_season:
                season = last_played["result"]["episodes"][0].get("season")
                ep_query = json_call(
                    "VideoLibrary.GetEpisodes",
                    properties=JSON_MAP["episode_properties"],
                    sort={"order": "ascending", "method": "episode"},
                    limit=1,
                    query_filter={
                        "and": [
                            self.filter_unwatched,
                            {"field": "season", "operator": "is", "value": str(season)},
                        ]
                    },
                    params={"tvshowid": int(show["tvshowid"])},
                    parent="next_up",
                )
                if ep_query.get("result", {}).get("limits", {}).get("total", 0) < 1:
                    use_last_played_season = False

            # If no episode is left of the last played season, fall back to the very first unwatched episode
            if not use_last_played_season:
                ep_query = json_call(
                    "VideoLibrary.GetEpisodes",
                    properties=JSON_MAP["episode_properties"],
                    sort={"order": "ascending", "method": "episode"},
                    limit=1,
                    query_filter={
                        "and": [self.filter_unwatched, self.filter_no_specials]
                    },
                    params={"tvshowid": int(show["tvshowid"])},
                    parent="next_up",
                )

            eps = ep_query.get("result", {}).get("episodes", [])
            if not eps:
                log(
                    f"PluginHandlers → next_up: No next episode found for {show['title']}"
                )
                continue
            eps[0]["studio"] = studio
            eps[0]["mpaa"] = mpaa
            results.extend(add_items(eps, media_type="episode"))

        return results or None

    def director_credits(self) -> None:
        """
        Build a container of movies and music videos directed by ``self.label``.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        set_plugincontent(content="videos", category=ADDON.getLocalizedString(32602))

        filters = [{"field": "director", "operator": "is", "value": self.label}]
        results = []

        if self.filter_exclude:
            filters.append(self.filter_exclude)

        for method, props, media_type in [
            ("VideoLibrary.GetMovies", JSON_MAP["movie_properties"], "movie"),
            (
                "VideoLibrary.GetMusicVideos",
                JSON_MAP["musicvideo_properties"],
                "musicvideo",
            ),
        ]:
            results.extend(
                self._fetch_and_add(
                    method,
                    props,
                    filters,
                    media_type,
                    sort=self.sort_year,
                    parent="director_credits",
                )
            )
        return results or ModuleNotFoundError

    def actor_credits(self) -> None:
        """
        Build a container of movies and TV shows featuring ``self.label``.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        set_plugincontent(content="videos", category=ADDON.getLocalizedString(32603))

        filters = [{"field": "actor", "operator": "is", "value": self.label}]
        results = []

        current_item = (
            infolabel("ListItem.TVShowTitle")
            if condition("String.IsEqual(ListItem.DBType,episode)")
            else infolabel("ListItem.Label")
        )
        movies = json_call(
            "VideoLibrary.GetMovies",
            properties=JSON_MAP["movie_properties"],
            sort=self.sort_year,
            query_filter={"and": filters},
            parent="actor_credits",
        )
        tvshows = json_call(
            "VideoLibrary.GetTVShows",
            properties=JSON_MAP["tvshow_properties"],
            sort=self.sort_year,
            query_filter={"and": filters},
            parent="actor_credits",
        )
        total = int(movies.get("result", {}).get("limits", {}).get("total", 0)) + int(
            tvshows.get("result", {}).get("limits", {}).get("total", 0)
        )

        for src, media_type in [(movies, "movie"), (tvshows, "tvshow")]:
            items = src.get("result", {}).get(f"{media_type}s", [])
            if not items:
                log(
                    f"PluginHandlers → actor_credits: No {media_type}s found for {self.label}."
                )
                continue
            items = self._remove_current(items, current_item, total)
            results.extend(add_items(items, media_type=media_type))

        return results or None

    def _fetch_and_add(
        self,
        method: str,
        props: list[str],
        filters: list[dict[str, Any]],
        media_type: str,
        sort: dict[str, Any],
        parent: str,
        postprocess: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> list[tuple]:
        """
        Generic helper to fetch JSON items, optionally postprocess, and append.

        :param method: JSON-RPC method (e.g. "VideoLibrary.GetMovies").
        :param props: List of property names to request.
        :param filters: List of filter dicts for query_filter.
        :param media_type: Media type for add_items (e.g. "movie").
        :param sort: Sort specification for JSON-RPC.
        :param parent: Parent name for logging.
        :param postprocess: Optional function to transform/enrich the items.
        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or [] if aborted.
        """
        q = json_call(
            method,
            properties=props,
            sort=sort,
            query_filter={"and": filters},
            parent=parent,
        )
        items = q.get("result", {}).get(f"{media_type}s", [])
        if not items:
            log(f"PluginHandlers → {parent}: No {media_type}s found.")
            return []

        if postprocess:
            postprocess(items)
        return add_items(items, media_type=media_type)

    def _enrich_with_tvshow(self, episodes: list[dict[str, Any]], parent: str) -> None:
        """
        Postprocess episodes to add studio/mpaa from parent TV show.

        :param episodes: Episode dicts to enrich (in place).
        :param parent: Parent name for logging.
        :returns: None
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

    def _remove_current(
        self, items: list[dict[str, Any]], current_label: str, total: int
    ) -> list[dict[str, Any]]:
        """
        Remove the current item from a list of items if present.

        :param items: List of item dicts.
        :param current_label: Label of the current playing item.
        :param total: Combined total of credits.
        :returns: Filtered list of items.
        """
        match = next((i for i in items if i.get("label") == current_label), None)
        if match and total > 1:
            items.remove(match)
        return items
