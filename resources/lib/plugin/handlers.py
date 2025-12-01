# author: realcopacetic

import inspect
from contextlib import contextmanager
from typing import Callable, Iterator

from xbmcplugin import SORT_METHOD_LASTPLAYED

from resources.lib.apis.tmdb.context import resolve_tmdb_context
from resources.lib.apis.tmdb.transform import tmdb_to_canonical
from resources.lib.art.editor import ImageEditor
from resources.lib.art.multiart import build_multiart_dict, set_multiart_fadelabel
from resources.lib.art.policy import flatten_art_attributes
from resources.lib.plugin.geometry import PlacementOpts
from resources.lib.plugin.helpers import (
    DataHandler,
    JumpButton,
    ProgressBarManager,
    TextTruncator,
    TypewriterAnimation,
    merge_metadata,
)
from resources.lib.plugin.json_map import JSON_PROPERTIES, json_to_canonical
from resources.lib.plugin.library import (
    DirectoryItem,
    TvShowHelper,
    enrich_with_tvshow,
    fetch_and_add,
    role_endpoint,
)
from resources.lib.plugin.registry import PluginInfoRegistry
from resources.lib.plugin.setter import *
from resources.lib.shared import logger as log
from resources.lib.shared.sqlite import ArtworkCacheHandler
from resources.lib.shared.utilities import (
    ADDON,
    condition,
    infolabel,
    json_call,
    set_plugincontent,
    to_float,
    to_int,
)


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
        self.dbtype = params.get("type", "").lower()
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

    def _get_tmdb_item(
        self,
        *,
        append_artwork: bool,
    ) -> dict[str, Any] | None:
        """Resolve TMDb canonical item for the current listitem.

        :param append_artwork: Whether to include TMDb artwork fields.
        :return: canonical item dict or None.
        """
        target = f"{self.container}.ListItem"
        ctx = resolve_tmdb_context(self.params, target=target)

        tmdb_id_str = ctx.get("tmdb_id")
        tmdb_id = to_int(tmdb_id_str, 0) if tmdb_id_str else 0
        if tmdb_id <= 0:
            log.debug(
                f"{self.__class__.__name__} → tmdb: missing or invalid tmdb_id "
                f"({self.params.get('tmdb_id')!r})"
            )
            return None

        item = tmdb_to_canonical(
            kind=(ctx.get("kind") or self.dbtype).lower(),
            tmdb_id=tmdb_id,
            season_number=ctx.get("season_number"),
            language=self.params.get("language"),
            append_artwork=append_artwork,
        )
        if not item:
            log.debug(
                f"{self.__class__.__name__} → tmdb: no data for "
                f"type={self.dbtype}, tmdb_id={tmdb_id}"
            )
            return None

        return item

    def _apply_truncated_label(
        self,
        data: dict[str, Any],
        *,
        target: str,
        default_text: str | None = None,
    ) -> None:
        """Attach a truncated label to a metadata dict.

        :param data: Metadata dict to update in place.
        :param target: ListItem infolabel prefix for plot fallback.
        :param default_text: Optional plot to use before infolabel fallback.
        :return: None.
        """
        truncate_id = to_int(self.params.get("truncate_id", 0))
        if not truncate_id:
            return

        truncate_label = (
            self.params.get("truncate_label")
            or default_text
            or infolabel(f"{target}.Plot")
        )
        if not truncate_label:
            return

        trunc = TextTruncator(measure_ctrl_id=truncate_id)
        truncated = trunc.truncate(
            text=truncate_label,
            min_safe=to_int(self.params.get("truncate_min_safe", 0)),
            smart_cap=self.params.get("truncate_smart_cap", "").lower() == "true",
        )

        props = data.setdefault("properties", {})
        props["truncated_label"] = truncated

    @log.duration
    def artwork(self) -> list[DirectoryItem] | None:
        """
        Process/calculate artwork and attach to listitem; aborts if focus changes.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        with self.focus() as guard:
            if not guard.alive():
                return

            image_processor = ImageEditor(ArtworkCacheHandler()).image_processor
            processed = image_processor(
                processes={"clearlogo": "crop", "fanart": "blur"},
                source=f"{self.container}.ListItem",
                overlay_enabled=self.params.get("overlay_enabled"),
                overlay_source=self.params.get("overlay_source"),
                overlay_rects=self.params.get("overlay_rects"),
                overlay_target=to_float(self.params.get("overlay_target")),
            )
            if not guard.alive():
                return

            art = flatten_art_attributes(processed)
            multiart_dict = build_multiart_dict(
                target=f"{self.container}.ListItem",
                multiart_type=self.params.get("multiart"),
                max_items=self.params.get("multiart_max"),
                get_extra_multiart=(
                    self.params.get("get_extra_multiart", "").lower() == "true"
                ),
                language="en-US",
            )
            art |= multiart_dict
            log.debug(
                f"{self.__class__.__name__} → Artwork returned from ImageEditor {art}"
            )

            if not guard.alive():
                return

            fadelabel_id = self.params.get("multiart_fadelabel")
            if fadelabel_id and multiart_dict:
                set_multiart_fadelabel(
                    fadelabel_id=fadelabel_id,
                    art=multiart_dict,
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
                ]
            )

    @log.duration
    def darken(self) -> list[DirectoryItem] | None:
        """
        On-demand darken for a single fanart path. Acts as a lightweight
        alternative entry point for darkening without invoking artwork handler.
        """
        with self.focus() as guard:
            if not guard.alive():
                return

            overlay_enabled = (
                str(self.params.get("overlay_enabled", "false")).lower() == "true"
            )
            if not overlay_enabled:
                return

            url = self.params.get("fanart") or ""
            if not url:
                return

            val = ImageEditor(ArtworkCacheHandler()).compute_darken_runtime(
                url=url,
                overlay_enabled=overlay_enabled,
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
                        "properties": {"fanart_darken": str(val)},
                    }
                ]
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
    def metadata(self) -> list[DirectoryItem] | None:
        """
        Fetch/attach cleaned metadata to a helper list item; aborts if focus changes.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        with self.focus() as guard:
            if not guard.alive():
                return

            target = f"{self.container}.ListItem"
            data = DataHandler(
                target=target,
                dbtype=self.dbtype,
                dbid=self.dbid,
            ).fetch_data()

            if not guard.alive():
                return

            enrich_with_tmdb = self.params.get("enrich_with_tmdb", "").lower() == "true"
            if enrich_with_tmdb:
                tmdb_item = self._get_tmdb_item(append_artwork=False)
                if tmdb_item:
                    data = merge_metadata(
                        base=data,
                        incoming=tmdb_item,
                        prefer_incoming=True,
                        ignore_keys=("art", "file"),
                    )

            if not guard.alive():
                return

            self._apply_truncated_label(
                data,
                target=target,
                default_text=data.get("Plot"),
            )

            return set_items([data], tag_applier=apply_videoinfotag)

    @log.duration
    def progressbar(self) -> list[DirectoryItem] | None:
        """
        Compute resume/unwatched values and expose a helper item for the list.
        If focus changes after item creation, return it but skip UI update.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples, or None if aborted.
        """
        with self.focus() as guard:
            if not guard.alive():
                return

            pb = ProgressBarManager(target=f"{self.container}.ListItem")
            resume, unwatched = pb.calculate()
            result = set_items(
                [
                    {
                        "file": "progress",
                        "resume": {"position": resume, "total": 100},
                        "properties": {"unwatchedepisodes": str(unwatched)},
                    }
                ],
                tag_applier=apply_videoinfotag,
            )

            if not guard.alive():
                return result

            pb.update(
                percent=resume,
                opts=PlacementOpts.from_params(self.params),
                base_id=to_int(self.params.get("base_id"), None),
                backing_id=to_int(self.params.get("backing_id"), None),
                progress_id=to_int(self.params.get("progress_id"), None),
                btn_id=to_int(self.params.get("btn_id"), None),
            )
            return result

    @log.duration
    def tmdb_details(self) -> list[DirectoryItem] | None:
        """
        Fetch TMDb details for the focused item and build a canonical result list.

        :return: List of (file, xbmcgui.ListItem, isFolder) tuples or None.
        """

        with self.focus() as guard:
            if not guard.alive():
                return

            target = f"{self.container}.ListItem"
            multiart_enabled = str(self.params.get("multiart")).lower() == "true"
            item = self._get_tmdb_item(append_artwork=multiart_enabled)

            if not item:
                return

            if not guard.alive():
                return

            self._apply_truncated_label(
                item,
                target=target,
                default_text=item.get("Plot"),
            )

            return set_items(
                [item],
                tag_applier=apply_videoinfotag,
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

            t = TypewriterAnimation()
            t.update(
                label=self.label,
                opts=PlacementOpts.from_params(self.params),
                label_id=to_int(self.params.get("label_id"), None),
                line_step=to_int(self.params.get("line_step"), None),
                max_lines=to_int(self.params.get("max_lines"), None),
                alive=guard.alive,
            )

    @log.duration
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
                fetch_and_add(
                    method="VideoLibrary.GetMovies",
                    media_type="movie",
                    filters=filters,
                    sort=self.sort_lastplayed,
                    parent="in_progress",
                    tag_applier=apply_videoinfotag,
                )
            )

        if self.dbtype != "movie":
            results.extend(
                fetch_and_add(
                    method="VideoLibrary.GetEpisodes",
                    media_type="episode",
                    filters=filters,
                    sort=self.sort_lastplayed,
                    parent="in_progress",
                    tag_applier=apply_videoinfotag,
                    postprocess=lambda eps: enrich_with_tvshow(
                        eps, parent="in_progress"
                    ),
                )
            )

        return results or None

    @log.duration
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
            tvshow_id = to_int(show.get("tvshowid"), 0)
            if tvshow_id <= 0:
                continue

            ep_query = json_call(
                "VideoLibrary.GetEpisodes",
                properties=JSON_PROPERTIES["episode"],
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

    @role_endpoint(
        field="actor",
        category_id=32603,
        sources=[
            ("VideoLibrary.GetMovies", "movie"),
            ("VideoLibrary.GetTVShows", "tvshow"),
        ],
        parent="actor_credits",
    )
    def actor_credits(self):
        """
        Build a container of movies and TV shows featuring ``self.label``.
        """
        pass

    @role_endpoint(
        field="director",
        category_id=32602,
        sources=[
            ("VideoLibrary.GetMovies", "movie"),
            ("VideoLibrary.GetMusicVideos", "musicvideo"),
        ],
        parent="director_credits",
    )
    def director_credits(self):
        """
        Build a container of movies and music videos directed by ``self.label``.
        """
        pass

    @role_endpoint(
        field="writer",
        category_id=32604,
        sources=[
            ("VideoLibrary.GetMovies", "movie"),
            ("VideoLibrary.GetEpisodes", "episode"),
        ],
        parent="writer_credits",
        postprocess=lambda eps: enrich_with_tvshow(eps, parent="writer_credits"),
    )
    def writer_credits(self):
        """
        Build a container of movies and episodes written by ``self.label``.
        """
        pass
