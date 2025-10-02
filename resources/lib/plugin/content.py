# author: realcopacetic, sualfred

from contextlib import contextmanager
from typing import Callable, Generator, Optional

from xbmcplugin import SORT_METHOD_LASTPLAYED

from resources.lib.art.editor import ImageEditor
from resources.lib.plugin.geometry import PlacementOpts
from resources.lib.plugin.helpers import (
    DataHandler,
    JumpButton,
    ProgressBarManager,
    TypewriterAnimation,
)
from resources.lib.plugin.json_map import JSON_MAP
from resources.lib.art.multiart import collect_multiart
from resources.lib.plugin.library import *
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

PLUGIN_REGISTRY = {}


def info(fn):
    """Decorator to auto-register actions to whitelist"""
    PLUGIN_REGISTRY[fn.__name__] = fn
    return fn


ALLOWED_INFO = {
    "artwork",
    "jumpbutton",
    "metadata",
    "progressbar",
    "typewriter",
    "in_progress",
    "next_up",
    "director_credits",
    "actor_credits",
}


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
                f"PluginContent → {self.caller_name}: ABORTED → '{self.expected_identity}' lost focus"
            )
            return False
        if self.focus_check is not None and not self.focus_check():
            log(
                f"PluginContent → {self.caller_name}: ABORTED → Container lost focus"
            )
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
    focus_check = (lambda: condition(f"Control.HasFocus({target})")) if target is not None else None

    if expected_identity is None:
        yield True  # always alive
        return

    if identity_getter() != expected_identity:
        log(
            f"PluginContent → {caller_name}: ABORTED → '{expected_identity}' lost focus"
        )
        yield None
        return

    if focus_check is not None and not focus_check():
        log(
            f"PluginContent → {caller_name}: ABORTED → Container {target} lost focus"
        )
        yield None
        return

    guard = _FocusGuard(expected_identity, caller_name, identity_getter, focus_check)
    try:
        yield guard
    finally:
        pass


class PluginContent(object):
    """
    High-level plugin actions (artwork, metadata, typewriter) with focus guarding.

    :param params: plugin params dict
    :param li: target listitem.
    """

    def __init__(self, params: dict[str, str]) -> None:
        self.params = params
        self.li = []

        self.label = params.get("label", "")
        self.dbtype = params.get("type", "")
        self.dbid = params.get("id", "")
        self.target = params.get("target")
        self.container = f"Container({self.target})" if self.target and self.target.isdigit() else "Container"

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

    def build(self, action: str) -> list[tuple]:
        """Execute a whitelisted action and return the collected directory tuples."""
        name = action.lower()
        if name not in ALLOWED_ACTIONS or not hasattr(self, name):
            log(f"PluginContent → Ignoring unknown action: {action}")
            return []

        self.li.clear()
        getattr(self, name)()
        return self.li

    @log_duration
    def artwork(self) -> None:
        """
        Process/calculate artwork and attach to listitem; aborts if focus changes.
        """
        with focus_guard(self.expected, "artwork", self.identity_getter) as guard:
            if not guard:
                return

            sqlite = SQLiteHandler()
            image_processor = ImageEditor(sqlite).image_processor
            processed = image_processor(
                self.dbid,
                f"{self.container}.ListItem",
                {"clearlogo": "crop", "fanart": "blur"},
            )

            if not guard.alive():
                return

            art = dict(processed or {})
            art |= collect_multiart(
                target=f"{self.container}.ListItem",
                art_type=self.params.get("multiart"),
                max_items=self.params.get("multiart_max"),
            )

            if not guard.alive():
                return

            data = {"file": self.dbid, "art": art}
            add_items(self.li, [data], media_type="artwork")

    @log_duration
    def jumpbutton(self) -> None:
        """Update jump button overlay using params and placement options."""
        jump = JumpButton()
        jump.update(
            sortletter=self.params.get("sortletter", ""),
            scroll_id=self.params.get("scroll_id", ""),
            opts=PlacementOpts.from_params(self.params),
        )

    @log_duration
    def metadata(self) -> None:
        """Fetch/attach cleaned metadata to a helper list item; aborts if focus changes."""
        with focus_guard(self.expected, "metadata", self.identity_getter) as guard:
            if not guard:
                return

            data = DataHandler(f"{self.container}.ListItem", self.dbtype, self.dbid)

            if not guard.alive():
                return

            add_items(self.li, [data.fetched], media_type="metadata")

    @log_duration
    def progressbar(self) -> None:
        """Compute percent/unwatched and position the progress UI; also exposes values via helper list."""
        with focus_guard(self.expected, "progressbar", self.identity_getter) as guard:
            if not guard:
                return

            pb = ProgressBarManager(target=f"{self.container}.ListItem")
            resume, unwatched = pb.calculate(
                set_target=self.params.get("set_target", None)
            )
            add_items(
                self.li,
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

            if not guard.alive():
                return

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

    @log_duration
    def typewriter(self) -> None:
        """Run typewriter animation for the current listitem; guarded against focus changes."""
        label_id = self.params.get("label_id")
        line_step = self.params.get("line_step")
        max_lines = to_int(self.params.get("max_lines"), None)
        target_id = to_int(self.target, None)

        with focus_guard(self.expected, "typewriter", self.identity_getter, target_id) as guard:
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

    def in_progress(self):
        filters = [self.filter_inprogress]
        if self.dbtype != "tvshow":
            json_query = json_call(
                "VideoLibrary.GetMovies",
                properties=JSON_MAP["movie_properties"],
                sort=self.sort_lastplayed,
                query_filter={"and": filters},
                parent="in_progress",
            )
            try:
                json_query = json_query["result"]["movies"]
            except Exception:
                log("PluginContent → in_progress: No movies found.")
            else:
                add_items(self.li, json_query, media_type="movie")
        if self.dbtype != "movie":
            json_query = json_call(
                "VideoLibrary.GetEpisodes",
                properties=JSON_MAP["episode_properties"],
                sort=self.sort_lastplayed,
                query_filter={"and": filters},
                parent="in_progress",
            )
            try:
                json_query = json_query["result"]["episodes"]
            except Exception:
                log("PluginContent → in_progress: No episodes found.")
            else:
                for episode in json_query:
                    tvshowid = episode.get("tvshowid")
                    tvshow_json_query = json_call(
                        "VideoLibrary.GetTVShowDetails",
                        params={"tvshowid": tvshowid},
                        properties=["studio", "mpaa"],
                        parent="in_progress",
                    )
                    try:
                        tvshow_json_query = tvshow_json_query["result"]["tvshowdetails"]
                    except Exception:
                        log(
                            f"PluginContent → in_progress: Parent tv show not found → {tvshowid}"
                        )
                    else:
                        episode["studio"] = tvshow_json_query.get("studio")
                        episode["mpaa"] = tvshow_json_query.get("mpaa")
                add_items(self.li, json_query, media_type="episode")
        set_plugincontent(
            content="movies",
            category=ADDON.getLocalizedString(32601),
            sort_method=SORT_METHOD_LASTPLAYED,
        )

    def next_up(self):
        filters = [self.filter_inprogress]
        json_query = json_call(
            "VideoLibrary.GetTVShows",
            properties=["title", "lastplayed", "studio", "mpaa"],
            sort=self.sort_lastplayed,
            limit=25,
            query_filter={"and": filters},
            parent="next_up",
        )
        try:
            json_query = json_query["result"]["tvshows"]
        except Exception:
            log("PluginContent → next_up: No TV shows found")
            return
        for episode in json_query:
            use_last_played_season = True
            studio = episode.get("studio", "")
            mpaa = episode.get("mpaa", "")
            last_played_query = json_call(
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
                params={"tvshowid": int(episode["tvshowid"])},
                parent="next_up",
            )
            if last_played_query["result"]["limits"]["total"] < 1:
                use_last_played_season = False
            # Return the next episode of last played season
            if use_last_played_season:
                episode_query = json_call(
                    "VideoLibrary.GetEpisodes",
                    properties=JSON_MAP["episode_properties"],
                    sort={"order": "ascending", "method": "episode"},
                    limit=1,
                    query_filter={
                        "and": [
                            self.filter_unwatched,
                            {
                                "field": "season",
                                "operator": "is",
                                "value": str(
                                    last_played_query["result"]["episodes"][0].get(
                                        "season"
                                    )
                                ),
                            },
                        ]
                    },
                    params={"tvshowid": int(episode["tvshowid"])},
                    parent="next_up",
                )

                if episode_query["result"]["limits"]["total"] < 1:
                    use_last_played_season = False
            # If no episode is left of the last played season, fall back to the very first unwatched episode
            if not use_last_played_season:
                episode_query = json_call(
                    "VideoLibrary.GetEpisodes",
                    properties=JSON_MAP["episode_properties"],
                    sort={"order": "ascending", "method": "episode"},
                    limit=1,
                    query_filter={
                        "and": [self.filter_unwatched, self.filter_no_specials]
                    },
                    params={"tvshowid": int(episode["tvshowid"])},
                    parent="next_up",
                )
            try:
                episode_details = episode_query["result"]["episodes"]
                episode_details[0]["studio"] = studio
                episode_details[0]["mpaa"] = mpaa
            except Exception:
                log(
                    f"PluginContent → next_up: No next episodes found for {episode['title']}"
                )
            else:
                add_items(self.li, episode_details, media_type="episode")
                set_plugincontent(
                    content="episodes", category=ADDON.getLocalizedString(32600)
                )

    def director_credits(self):
        filters = [
            {
                "field": "director",
                "operator": "is",
                "value": self.label,
            },
            *([self.filter_exclude] if self.filter_exclude else []),
        ]
        json_query = json_call(
            "VideoLibrary.GetMovies",
            properties=JSON_MAP["movie_properties"],
            sort=self.sort_year,
            query_filter={"and": filters},
            parent="director_credits",
        )
        try:
            json_query = json_query["result"]["movies"]
        except Exception:
            log("PluginContent → director_credits: No movies found.")
        else:
            add_items(self.li, json_query, media_type="movie")
        json_query = json_call(
            "VideoLibrary.GetMusicVideos",
            properties=JSON_MAP["musicvideo_properties"],
            sort=self.sort_year,
            query_filter={"and": filters},
            parent="director_credits",
        )
        try:
            json_query = json_query["result"]["musicvideos"]
        except Exception:
            log("PluginContent → director_credits: No music videos found.")
        else:
            add_items(self.li, json_query, media_type="musicvideo")
        set_plugincontent(content="videos", category=ADDON.getLocalizedString(32602))

    def actor_credits(self):
        filters = [{"field": "actor", "operator": "is", "value": self.label}]
        # grab current movie or tvshow name
        if condition("String.IsEqual(ListItem.DBType,episode)"):
            current_item = infolabel("ListItem.TVShowTitle")
        else:
            current_item = infolabel("ListItem.Label")
        # json lookup for movies and tvshows by given actor
        movies_json_query = json_call(
            "VideoLibrary.GetMovies",
            properties=JSON_MAP["movie_properties"],
            sort=self.sort_year,
            query_filter={"and": filters},
            parent="actor_credits",
        )

        tvshows_json_query = json_call(
            "VideoLibrary.GetTVShows",
            properties=JSON_MAP["tvshow_properties"],
            sort=self.sort_year,
            query_filter={"and": filters},
            parent="actor_credits",
        )
        # Work out combined number of movie/tvshow credits
        total_items = int(movies_json_query["result"]["limits"]["total"]) + int(
            tvshows_json_query["result"]["limits"]["total"]
        )
        # If there are movie results, remove the current item if it is in the list, then add the remaining to the plugin directory
        try:
            movies_json_query = movies_json_query["result"]["movies"]
        except Exception:
            log(f"PluginContent →  actor_credits: No movies found for {self.label}.")
        else:
            dict_to_remove = next(
                (item for item in movies_json_query if item["label"] == current_item),
                None,
            )
            if dict_to_remove and total_items > 1:
                movies_json_query.remove(dict_to_remove)
            add_items(self.li, movies_json_query, media_type="movie")
        # If there are tvshow results, remove the current item if it is in the list, then add the remaining to the plugin directory
        try:
            tvshows_json_query = tvshows_json_query["result"]["tvshows"]
        except Exception:
            log(f"PluginContent →  actor_credits: No tv shows found for {self.label}.")
        else:
            dict_to_remove = next(
                (item for item in tvshows_json_query if item["label"] == current_item),
                None,
            )
            (
                tvshows_json_query.remove(dict_to_remove)
                if dict_to_remove is not None and total_items > 1
                else None
            )
            add_items(self.li, tvshows_json_query, media_type="tvshow")
        set_plugincontent(content="videos", category=ADDON.getLocalizedString(32603))
