# author: realcopacetic, sualfred

import concurrent.futures
import time

from resources.lib.plugin.json_map import JSON_MAP
from resources.lib.plugin.library import *
from resources.lib.shared.art import ImageEditor
from resources.lib.shared.controls import JumpButton, ProgressIndicator
from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import (
    ADDON,
    condition,
    infolabel,
    json_call,
    log,
    log_duration,
    return_label,
    set_plugincontent,
    split,
    split_random,
    url_encode,
    window_property,
    xbmc,
)


class DataHandler:
    def __init__(self, listitem, dbtype, dbid):
        self.listitem = listitem
        self.dbtype = dbtype
        self.dbid = dbid
        self.infolabels = self._get_infolabels(
            [
                "Label",
                "Director",
                "Writer",
                "Genre",
                "Studio",
                "PercentPlayed",
                "Property(WatchedEpisodePercent)",
                "Property(WatchedProgress)",
                "Property(UnwatchedEpisodes)",
            ]
        )
        self.fetched = self.fetch_data()

    def _get_infolabels(self, keys):
        return {key: infolabel(f"{self.listitem}.{key}") for key in keys}

    def fetch_data(self):
        label = return_label(self.infolabels["Label"])
        encoded_label = url_encode(label)
        director = split_random(self.infolabels["Director"])
        writer = split(self.infolabels["Writer"])
        genre = split_random(self.infolabels["Genre"])
        resume, unwatched = self._resumepoint()
        studio = self._studio()
        multiart = self._multiart()
        if "3100" not in self.listitem:
            window_property("url_encoded_label", value=encoded_label)
            window_property("random_genre", value=genre)
            window_property("random_director", value=director)
        return {
            "file": encoded_label,
            "label": encoded_label,
            "art": multiart,
            "director": director,
            "dbtype": self.dbtype,
            "genre": genre,
            "resume": {"position": resume, "total": 100},
            "unwatchedepisodes": str(unwatched),
            "studio": studio,
            "writer": writer,
        }

    def _resumepoint(self):
        unwatched = self.infolabels["Property(UnwatchedEpisodes)"]
        # Try percentage-based progress tracking first
        for p in [
            self.infolabels["PercentPlayed"],
            self.infolabels["Property(WatchedEpisodePercent)"],
            self.infolabels["Property(WatchedProgress)"],
        ]:
            if p.isdigit() and (resume := int(p)) > 0:
                return resume, unwatched
        # Otherwise check if item marked as watched
        if condition(
            f"String.IsEqual({self.listitem}.Overlay,OverlayWatched.png) | "
            f"Integer.IsGreater({self.listitem}.PlayCount,0)"
        ):
            return 100, ""
        # For sets, calculation is required
        if "set" in self.dbtype:
            if self._wait_for_set_match():
                total = int(infolabel("Container(3100).NumItems") or 0)
                watched = sum(
                    condition(
                        f"Integer.IsGreater(Container(3100).ListItem({x}).PlayCount,0)"
                    )
                    for x in range(total)
                )
                return ((total and watched / total or 0) * 100), (
                    total - watched
                )  # https://stackoverflow.com/a/68118106/21112145 to avoid ZeroDivisionError
        return 0, unwatched

    def _studio(self):
        studio = (
            split(infolabel("Container(3100).ListItem(-1).Studio"))
            if "set" in self.dbtype and self._wait_for_set_match()
            else split(self.infolabels["Studio"])
        )
        return studio.replace("+", "") if studio else ""

    def _wait_for_set_match(self):
        timeout = time.time() + 2  # Set a timeout 2s in the future
        while time.time() < timeout:
            if condition(
                "String.IsEqual(ListItem.DBID,Container(3100).ListItem.SetID)"
            ) and condition("!Container(3100).IsUpdating"):
                return True
            xbmc.Monitor().waitForAbort(0.02)  # Wait for 20ms before retrying
        return False

    def _multiart(self):
        if not (
            self._wait_for_art() and (art_type := infolabel("Control.GetLabel(6400)"))
        ):
            return {}
        return {
            f"multiart{pos if pos else ''}": art
            for pos in range(16)
            if (
                art := infolabel(f"{self.listitem}.Art({art_type}{pos if pos else ''})")
            )
        }

    def _wait_for_art(self):
        timeout = time.time() + 3  # Set a timeout 3s in the future
        while time.time() < timeout:
            if condition("!String.IsEmpty(Window(home).Property(art_loaded))"):
                return True
            xbmc.Monitor().waitForAbort(0.02)  # Wait for 20ms before retrying
        return False


class PluginContent(object):
    def __init__(self, params, li):
        self.sqlite = SQLiteHandler()
        self.image_processor = ImageEditor(self.sqlite).image_processor

        self.title = params.get("title", "")
        self.dbtype = params.get("type", "")
        self.dbid = params.get("id", "")
        self.label = params.get("label", "")
        self.sortletter = params.get("sortletter", "")
        self.target = params.get("target", "ListItem")
        if self.target.isdigit():
            self.target = f"Container({self.target}).ListItem"
        self.exclude_key = params.get("exclude_key", "title")
        self.exclude_value = params.get("exclude_value", "")
        self.li = li

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
        self.filter_director = {
            "field": "director",
            "operator": "is",
            "value": self.label,
        }
        self.filter_actor = {"field": "actor", "operator": "is", "value": self.label}
        self.filter_exclude = {
            "field": self.exclude_key,
            "operator": "isnot",
            "value": self.exclude_value,
        }

    def jumpbutton(self):
        jump_button = JumpButton()
        jump_button.update_position(self.sortletter)

    @log_duration
    def helper(self):
        images_to_process = {"clearlogo": "crop", "fanart": "blur"}
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_data = executor.submit(
                DataHandler, self.target, self.dbtype, self.dbid
            )
            future_images = executor.submit(
                self.image_processor, self.dbid, self.target, images_to_process
            )
            data, processed_images = future_data.result(), future_images.result()
        if processed_images:
            data.fetched.setdefault("art", {}).update(processed_images)
        add_items(self.li, [data.fetched], "helper")
        # Check visibility condition before updating button position
        resume_data = data.fetched.get("resume", {})
        resume_position = resume_data.get("position", 0)  # Default to 0 if not found
        progress_indicator = ProgressIndicator()
        progress_indicator.update_position(resume_position)

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
                log("Widget in_progress: No movies found.")
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
                log("Widget in_progress: No episodes found.")
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
                            f"Widget in_progress: Parent tv show not found → {tvshowid}"
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
            log("Widget next_up: No TV shows found")
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
                log(f"Widget next_up: No next episodes found for {episode['title']}")
            else:
                add_items(self.li, episode_details, type="episode")
                set_plugincontent(
                    content="episodes", category=ADDON.getLocalizedString(32600)
                )

    def director_credits(self):
        filters = [self.filter_director]
        if self.filter_exclude:
            filters.append(self.filter_exclude)
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
            log("Widget director_credits: No movies found.")
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
            log("Widget director_credits: No music videos found.")
        else:
            add_items(self.li, json_query, type="musicvideo")
        set_plugincontent(content="videos", category=ADDON.getLocalizedString(32602))

    def actor_credits(self):
        filters = [self.filter_actor]
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
            log(f"Widget actor_credits: No movies found for {self.label}.")
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
            log(f"Widget actor_credits: No tv shows found for {self.label}.")
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
