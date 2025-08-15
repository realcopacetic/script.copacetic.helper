# author: realcopacetic, sualfred

from contextlib import contextmanager
from functools import wraps
from resources.lib.art.editor import ImageEditor
from resources.lib.plugin.json_map import JSON_MAP
from resources.lib.plugin.library import *
from resources.lib.plugin.helpers import (
    DataHandler,
    JumpButton,
    ProgressBarManager,
    TypewriterAnimation,
)
from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import (
    ADDON,
    condition,
    infolabel,
    json_call,
    log,
    log_duration,
    set_plugincontent,
)


class _FocusGuard:
    """Holds the expected item identity and lets you re-check later."""

    __slots__ = ("expected", "who")

    def __init__(self, expected, who):
        self.expected = expected
        self.who = who

    def alive(self) -> bool:
        """Re-check that focus hasn't changed."""
        current = infolabel("ListItem.Label")
        if current != self.expected:
            log(f"PluginContent → {self.who}: ABORTED → '{self.expected}' lost focus")
            return False
        return True


@contextmanager
def focus_guard(expected_label: str, who: str):
    """
    Guard pattern for slow helpers:
      1) pre-check focus
      2) yield guard.alive() for post-check(s)
    """
    current = infolabel("ListItem.Label")
    if current != expected_label:
        log(f"PluginContent → {who}: ABORTED → '{expected_label}' lost focus")
        yield None
        return

    guard = _FocusGuard(expected_label, who)
    try:
        yield guard
    finally:
        pass


class PluginContent(object):
    def __init__(self, params, li):
        self.params = params
        self.li = li
        self.label = params.get("label", "")
        self.dbtype = params.get("type", "")
        self.dbid = params.get("id", "")
        self.target = params.get("target", "ListItem")
        if self.target.isdigit():
            self.target = f"Container({self.target}).ListItem"
        self.exclude_key = params.get("exclude_key", "title")
        self.exclude_value = params.get("exclude_value", "")

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
    def jumpbutton(self):
        sortletter = self.params.get("sortletter", "")
        anchor_id = self.params.get("ancor_id", "")
        jump_button = JumpButton()
        jump_button.update(sortletter, anchor_id)

    @log_duration
    def typewriter(self):
        """Launch the typewriter animation helper for the current list item."""
        label_id = self.params.get("label_id")
        anchor_id = self.params.get("anchor_id")
        coords = self.params.get("coords")
        year = self.params.get("year")
        typewriter = TypewriterAnimation()
        typewriter.update(self.label, year, label_id, anchor_id, coords)

    @log_duration
    def metadata_helper(self):
        with focus_guard(self.label, "metadata_helper") as guard:
            if not guard:
                return

            data = DataHandler(self.target, self.dbtype, self.dbid)

            if not guard.alive():
                return

            add_items(self.li, [data.fetched], "metadata")

            resume = data.fetched.get("resume", {})
            progress_id = self.params.get("progress_id")
            anchor_id = self.params.get("anchor_id")
            coords = self.params.get("coords")
            progress = ProgressBarManager()
            progress.update(resume.get("position", 0), progress_id, anchor_id, coords)

    @log_duration
    def artwork_helper(self):
        with focus_guard(self.label, "metadata_helper") as guard:
            if not guard:
                return

            sqlite = SQLiteHandler()
            image_processor = ImageEditor(sqlite).image_processor
            processed = image_processor(self.dbid, self.target, {"clearlogo": "crop", "fanart": "blur"})

            if not guard.alive():
                return

            data = {"file": self.label, "art": dict(processed or {})}
            add_items(self.li, [data], "artwork")

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
                add_items(self.li, json_query, type="movie")
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
                add_items(self.li, json_query, type="episode")
        set_plugincontent(content="movies", category=ADDON.getLocalizedString(32601))

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
                add_items(self.li, episode_details, type="episode")
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
            add_items(self.li, json_query, type="movie")
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
            add_items(self.li, json_query, type="musicvideo")
        set_plugincontent(content="videos", category=ADDON.getLocalizedString(32602))

    def actor_credits(self):
        filters = [
            {
                "field": "actor", 
                "operator": "is", 
                "value": self.label
            }
        ]
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
            add_items(self.li, movies_json_query, type="movie")
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
            add_items(self.li, tvshows_json_query, type="tvshow")
        set_plugincontent(content="videos", category=ADDON.getLocalizedString(32603))
