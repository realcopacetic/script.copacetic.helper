# author: realcopacetic

import random
import sys
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from xbmcplugin import SORT_METHOD_LASTPLAYED

from resources.lib.apis.tmdb.context import resolve_tmdb_context
from resources.lib.apis.tmdb.transform import tmdb_to_canonical
from resources.lib.art.editor import ImageEditor
from resources.lib.art.multiart import build_multiart_dict, set_multiart_fadelabel
from resources.lib.art.policy import ART_PROCESS_MAP
from resources.lib.plugin.geometry import PlacementOpts
from resources.lib.plugin.helpers import (
    DataHandler,
    JumpButton,
    ProgressBarManager,
    TextTruncator,
    TypewriterAnimation,
    merge_metadata,
)
from resources.lib.plugin.json_map import (
    HEAVY_FIELDS,
    trim_properties,
)
from resources.lib.plugin.library import (
    DirectoryItem,
    build_items,
    enrich_with_tvshow,
    fetch_and_add,
    fetch_raw,
    role_endpoint,
    title_filter,
)
from resources.lib.plugin.opts import ArtOpts
from resources.lib.plugin.registry import PluginInfoRegistry
from resources.lib.plugin.setter import apply_videoinfotag, set_items
from resources.lib.shared import logger as log
from resources.lib.shared.sqlite import ArtworkCacheHandler
from resources.lib.shared.utilities import (
    ADDON,
    condition,
    infolabel,
    parse_bool,
    set_plugincontent,
    to_int,
    window_property,
)


class _FocusGuard:
    """
    Lazy focus/identity guard for plugin operations.
    Evaluates container focus and item identity on demand.
    """

    __slots__ = (
        "caller_name",
        "expected_identity",
        "identity_getter",
        "focus_ids",
    )

    def __init__(
        self,
        caller_name: str,
        expected_identity: str | None,
        identity_getter: Callable[[], str],
        focus_ids: tuple[str, ...] = (),
    ):
        """
        Create a guard that checks container focus and item identity.

        :param caller_name: Name of the calling handler, used for logging.
        :param expected_identity: Snapshot identity for the focused item; None to disable identity guarding.
        :param identity_getter: Callable returning current item identity.
        :param focus_ids: Control ids of which one must hold focus; empty to disable focus guarding.
        """
        self.caller_name = caller_name
        self.expected_identity = expected_identity
        self.identity_getter = identity_getter
        self.focus_ids = focus_ids

    def alive(self) -> bool:
        """
        Validate current focus and item identity.

        :return: True if guard conditions still hold, otherwise False.
        """
        if self.focus_ids and not any(
            condition(f"Control.HasFocus({fid})") for fid in self.focus_ids
        ):
            log.debug(
                f"PluginHandlers → {self.caller_name}: ABORTED → focus left "
                f"({', '.join(self.focus_ids)})"
            )
            return False

        if not self.expected_identity:
            return True

        if self.expected_identity != self.identity_getter():
            log.debug(
                f"PluginHandlers → {self.caller_name}: ABORTED → '{self.expected_identity}' lost focus"
            )
            return False

        return True


@contextmanager
def focus_guard(
    caller_name: str,
    identity_container: str,
    expected_identity: str | None,
    identity_labels: tuple[str, ...] = (),
    focus_ids: tuple[str, ...] = (),
) -> Iterator[_FocusGuard]:
    """
    Build an identity guard for a plugin operation.
    Returns a guard object whose ``alive()`` checks focus and item identity.

    :param caller_name: Name of the calling handler, used for logging.
    :param identity_container: Container path for the default CurrentItem identity source.
    :param expected_identity: Snapshot identity of focused item; None to disable identity guarding.
    :param identity_labels: Infolabel paths overriding the default identity source; live values join with ",".
    :param focus_ids: Control ids of which one must hold focus; empty to disable focus guarding.

    :return: A ``_FocusGuard`` instance for lazy identity validation.
    """
    if identity_labels:
        identity_getter = lambda: ",".join(infolabel(p) for p in identity_labels)
    else:
        identity_getter = lambda: infolabel(f"{identity_container}.CurrentItem")
    yield _FocusGuard(caller_name, expected_identity, identity_getter, focus_ids)


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
        self.expected_identity = params.get("focus_guard")
        self.focus_ids = tuple(filter(None, params.get("focus_ids", "").split(",")))
        self.identity_labels = tuple(
            filter(None, params.get("identity_labels", "").split(","))
        )
        self.target_container = (
            f"Container({self.target})" if self.target is not None else "Container"
        )
        identity_id = to_int(params.get("identity_container"), self.target)
        self.identity_container = (
            f"Container({identity_id})" if identity_id is not None else "Container"
        )
        self.sort_lastplayed = {"order": "descending", "method": "lastplayed"}
        self.sort_year = {"order": "descending", "method": "year"}
        self.limit = to_int(params.get("limit"), None)
        self.randomise = params.get("randomise", "")

        self.exclude_key = params.get("exclude_key", "title")
        self.exclude_value = params.get("exclude_value", "")
        self.filter_unwatched = {
            "field": "playcount",
            "operator": "lessthan",
            "value": "1",
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
        Auto-detects the handler name from the call frame.
        """
        caller = sys._getframe(1).f_code.co_name
        return focus_guard(
            caller_name=caller,
            identity_container=self.identity_container,
            expected_identity=self.expected_identity,
            identity_labels=self.identity_labels,
            focus_ids=self.focus_ids,
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
        target = f"{self.target_container}.ListItem"
        ctx = resolve_tmdb_context(self.params, target=target)
        tmdb_id = to_int(ctx.get("tmdb_id"), 0)

        item = tmdb_to_canonical(
            kind=ctx.get("kind") or self.dbtype,
            tmdb_id=tmdb_id,
            season_number=ctx.get("season_number"),
            language=self.params.get("language"),
            append_artwork=append_artwork,
        )
        if not item:
            log.debug(
                f"{self.__class__.__name__} → tmdb: no data for "
                f"type={(ctx.get('kind') or self.dbtype)!r}, tmdb_id={tmdb_id}"
            )
            return

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
            smart_cap=parse_bool(self.params.get("truncate_smart_cap", "false")),
        )

        props = data.setdefault("properties", {})
        props["truncated_label"] = truncated

    @log.duration
    def artwork(self) -> list[DirectoryItem] | None:
        """
        Process/calculate artwork and attach to listitem; aborts if focus changes.

        :return: List of directory items for Kodi, or None if aborted/failed.
        """
        with self.focus() as guard:
            if not guard.alive():
                return

            current_position = to_int(
                self.expected_identity,
                to_int(infolabel(f"{self.identity_container}.CurrentItem"), None),
            )
            art_opts = {
                art_type: ArtOpts.from_params(self.params, art_type)
                for art_type in ("clearlogo", "background", "icon")
            }
            jobs = {
                art_type: [p for p in processes if opts.enabled(p)]
                for art_type, processes in ART_PROCESS_MAP.items()
                if (opts := art_opts.get(art_type)) and opts.url
            }
            if not jobs:
                log.debug(f"{self.__class__.__name__} → artwork: no jobs created")
                return

            image_processor = ImageEditor(ArtworkCacheHandler()).image_processor
            art = image_processor(
                jobs=jobs,
                art_opts=art_opts,
                source=f"{self.target_container}.ListItem",
            )
            if not guard.alive():
                return

            multiart_dict = build_multiart_dict(
                target=f"{self.target_container}.ListItem",
                multiart_type=self.params.get("multiart"),
                max_items=self.params.get("multiart_max"),
                get_extra_multiart=parse_bool(
                    self.params.get("get_extra_multiart", "false")
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
            if background_blur := art.get("background", ""):
                window_property("background_blur", background_blur)

            return set_items(
                [
                    {
                        "file": "artwork",
                        "art": art,
                        "properties": (
                            {
                                "previous": current_position - 1,
                                "next": current_position + 1,
                            }
                            if current_position is not None
                            else {}
                        ),
                    }
                ]
            )

    @log.duration
    def jumpbutton(self) -> None:
        """
        Update jump button overlay using params and placement options.
        No focus guard as needs to remain responsive to scroll.
        """
        jump = JumpButton()
        jump.update(
            sortletter=self.params.get("sortletter"),
            scroll_id=self.params.get("scroll_id"),
            opts=PlacementOpts.from_params(self.params),
        )

    @log.duration
    def metadata(self) -> list[DirectoryItem] | None:
        """
        Fetch/attach cleaned metadata to a helper list item; aborts if focus changes.

        :return: List of directory items for Kodi, or None if aborted/failed.
        """
        with self.focus() as guard:
            if not guard.alive():
                return

            target = f"{self.target_container}.ListItem"
            data = DataHandler(
                target=target,
                dbtype=self.dbtype,
                dbid=self.dbid,
            ).fetch_data()

            if not guard.alive():
                return

            enrich_with_tmdb = parse_bool(self.params.get("enrich_with_tmdb", "false"))
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

        :return: List of directory items for Kodi, or None if aborted/failed.
        """
        with self.focus() as guard:
            if not guard.alive():
                return

            pb = ProgressBarManager(target=f"{self.target_container}.ListItem")
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
                progress_id=to_int(self.params.get("progress_id"), None),
                btn_id=to_int(self.params.get("btn_id"), None),
                img_id=to_int(self.params.get("img_id"), None),
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

            target = f"{self.target_container}.ListItem"
            multiart_enabled = parse_bool(self.params.get("multiart", "false"))
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
        """
        with self.focus() as guard:
            if not guard.alive():
                return

            t = TypewriterAnimation()
            t.update(
                label=self.label,
                opts=PlacementOpts.from_params(self.params),
                label_id=to_int(self.params.get("label_id"), None),
                max_lines=to_int(self.params.get("max_lines"), None),
                alive=guard.alive,
            )

    @log.duration
    def in_progress(self) -> list[DirectoryItem] | None:
        """
        Build a container of in-progress movies and episodes.

        :return: List of directory items for Kodi, or None if aborted/failed.
        """
        set_plugincontent(
            content="videos",
            category=ADDON.getLocalizedString(32601),
            sort_method=SORT_METHOD_LASTPLAYED,
        )
        filters = [self.filter_inprogress]
        jobs: list[Callable[[], list[DirectoryItem]]] = []
        if self.dbtype != "tvshow":
            jobs.append(
                lambda: fetch_and_add(
                    method="VideoLibrary.GetMovies",
                    media_type="movie",
                    filters=filters,
                    sort=self.sort_lastplayed,
                    limit=self.limit,
                    parent="in_progress",
                    tag_applier=apply_videoinfotag,
                    properties=trim_properties("movie", HEAVY_FIELDS),
                )
            )

        if self.dbtype != "movie":
            jobs.append(
                lambda: fetch_and_add(
                    method="VideoLibrary.GetEpisodes",
                    media_type="episode",
                    filters=filters,
                    sort=self.sort_lastplayed,
                    limit=self.limit,
                    parent="in_progress",
                    tag_applier=apply_videoinfotag,
                    postprocess=lambda eps: enrich_with_tvshow(
                        eps, parent="in_progress"
                    ),
                    properties=trim_properties("episode", HEAVY_FIELDS),
                )
            )

        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = [pool.submit(job) for job in jobs]
            results = [item for f in futures for item in f.result()]

        return results or None

    @log.duration
    def next_up(self) -> list[DirectoryItem] | None:
        """
        Build a container of "next up" TV episodes — the lowest unwatched
        non-special episode for each in-progress show.

        :return: List of directory items for Kodi, or None if aborted/failed.
        """
        set_plugincontent(
            content="episodes",
            category=ADDON.getLocalizedString(32600),
            sort_method=SORT_METHOD_LASTPLAYED,
        )
        # 1: In-progress shows, ordered by lastplayed desc.
        shows = fetch_raw(
            "VideoLibrary.GetTVShows",
            "tvshow",
            [self.filter_inprogress],
            sort=self.sort_lastplayed,
            parent="next_up",
            limit=self.limit,
            properties=[
                "title",
                "studio",
                "mpaa",
                "lastplayed",
                "episode",
                "watchedepisodes",
                "art",
            ],
        )
        if not shows:
            log.debug(f"{self.__class__.__name__} → next_up: No TV shows found.")
            return None

        pending_ids = {s["tvshowid"] for s in shows}

        # 2: Unwatched non-special episodes for the pending shows only,
        # episode-level properties (no art, no streamdetails). Single MySQL
        # round-trip; Python picks the first per pending show below.
        bulk_episodes = fetch_raw(
            "VideoLibrary.GetEpisodes",
            "episode",
            [
                self.filter_unwatched,
                self.filter_no_specials,
                title_filter((s["title"] for s in shows), field="tvshow"),
            ],
            sort={"order": "ascending", "method": "episode"},
            parent="next_up",
            properties=trim_properties("episode", HEAVY_FIELDS | {"art"}),
        )

        # 3: First episode per pending show. Bulk result is sorted ascending
        # by episode, so the first hit per tvshowid wins.
        first_per_show: dict[int, dict] = {}
        for ep in bulk_episodes:
            sid = ep.get("tvshowid")
            if sid in pending_ids and sid not in first_per_show:
                first_per_show[sid] = ep

        # Assemble in pending_shows order to preserve lastplayed desc.
        # Attach show-level studio/mpaa to each episode.
        ordered_episodes: list[dict[str, Any]] = []
        for s in shows:
            ep = first_per_show.get(s["tvshowid"])
            if ep is None:
                # In-progress show with only unwatched specials; bulk query
                # excludes specials, so nothing to surface for this show.
                continue
            ep["studio"] = s.get("studio", [])
            ep["mpaa"] = s.get("mpaa", "")
            ep["art"] = {f"tvshow.{k}": v for k, v in s.get("art", {}).items()}
            ordered_episodes.append(ep)

        if not ordered_episodes:
            log.debug(
                f"{self.__class__.__name__} → next_up: No unwatched episodes found."
            )
            return None

        return build_items(ordered_episodes, "episode", tag_applier=apply_videoinfotag)

    @log.duration
    def random_movies(self) -> list[DirectoryItem] | None:
        """Build a seed-stable randomised container of movies."""
        return self._random_video(
            method="VideoLibrary.GetMovies",
            media_type="movie",
            content="movies",
            category=31204,
            parent="random_movies",
            filters=[
                {"field": "lastplayed", "operator": "notinthelast", "value": "14 days"}
            ],
        )

    @log.duration
    def random_tvshows(self) -> list[DirectoryItem] | None:
        """Build a seed-stable randomised container of TV shows."""
        return self._random_video(
            method="VideoLibrary.GetTVShows",
            media_type="tvshow",
            content="tvshows",
            category=31205,
            parent="random_tvshows",
            filters=[],
        )

    def _random_video(
        self,
        *,
        method: str,
        media_type: str,
        content: str,
        category: int,
        parent: str,
        filters: list[dict[str, Any]],
    ) -> list[DirectoryItem] | None:
        """
        Seed-stable random container in two queries: an id+title pool fetch,
        then one title-filtered details fetch for the shuffled slice.
        """

        set_plugincontent(content=content, category=ADDON.getLocalizedString(category))
        id_key = f"{media_type}id"
        result_key = f"{media_type}s"
        pool = fetch_raw(
            method, media_type, filters, sort=None, parent=parent, properties=["title"]
        )
        if not pool:
            return None

        pool.sort(key=lambda item: item[id_key])
        rng = random.Random(self.randomise) if self.randomise else random
        rng.shuffle(pool)
        if self.limit:
            pool = pool[: self.limit]

        order = {item[id_key]: idx for idx, item in enumerate(pool)}
        rows = fetch_raw(
            method,
            media_type,
            [title_filter(item["title"] for item in pool)],
            sort=None,
            parent=parent,
            properties=trim_properties(media_type, HEAVY_FIELDS),
        )
        rows = [r for r in rows if r[id_key] in order]
        if not rows:
            return None
        rows.sort(key=lambda r: order[r[id_key]])

        return build_items(rows, media_type, tag_applier=apply_videoinfotag)

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
