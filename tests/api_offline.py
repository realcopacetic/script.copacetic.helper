"""
Offline checks for the web API layer: apis/http.py, the api_cache table,
apis/listenbrainz.py (TTLs, stale-on-failure, rate limit), top_songs and the
TMDb client and cache (apis/tmdb), and the plugin URL parser (shared/parser.py).

Network calls are replaced by recorded ListenBrainz answers
(tests/fixtures/listenbrainz_*.json, Gorillaz, fetched Oct 2026), the documented
popularity count shape, a TMDb /tv/{id} answer in TMDb's shape
(tests/fixtures/tmdb_tv_1399.json, hand-written: no token here) or the failure
under test. Run from the helper root: python tests/api_offline.py
"""

import io
import json
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
LOG = install_stubs(HELPER, STAGE, STAGE, verbose=False)
for name in ("xbmc", "xbmcgui", "xbmcplugin"):  # handlers need more than builders
    sys.modules[name].__getattr__ = lambda attr: type(attr, (), {})
sys.modules["xbmcvfs"].mkdirs = lambda path: Path(path).mkdir(exist_ok=True) or 1
sys.path.insert(0, str(HELPER))

from resources.lib.apis import http, listenbrainz  # noqa: E402
from resources.lib.apis.tmdb import transform  # noqa: E402
from resources.lib.apis.tmdb.context import resolve_tmdb_context  # noqa: E402
from resources.lib.plugin import handlers, helpers  # noqa: E402
from resources.lib.plugin.music import (  # noqa: E402
    compact_count,
    library_item,
    rank_albums,
    rank_songs,
    title_key,
)
from resources.lib.script import actions  # noqa: E402
from resources.lib.shared.parser import parse_plugin_argv  # noqa: E402
from resources.lib.shared.sqlite import ApiCacheHandler  # noqa: E402

FIXTURES = HELPER / "tests" / "fixtures"
FIXTURE = (FIXTURES / "listenbrainz_top_recordings.json").read_bytes()
ALBUMS = (FIXTURES / "listenbrainz_top_release_groups.json").read_bytes()
TMDB_TV = (FIXTURES / "tmdb_tv_1399.json").read_bytes()
GORILLAZ = "e21857d5-3256-4547-afb3-4b6ded592596"
DAY = 86400


def song(songid, title, year, playcount=0, mbid=""):
    """A library song row as AudioLibrary.GetSongs returns it (fields used here)."""
    return {
        "songid": songid,
        "title": title,
        "year": year,
        "playcount": playcount,
        "musicbrainztrackid": mbid,
    }


SONGS = [
    song(1, "Feel Good Inc. (Demo)", 2004),
    song(2, "Feel Good Inc.", 2005, 2, "5004ea88-6c7e-4096-a89f-b24e358408ee"),
    song(3, "Feel Good Inc", 2010, 9),  # greatest hits copy, most played
    song(4, "Clint Eastwood (Live)", 0, 1),  # undated: must not count as earliest
    song(5, "Clint Eastwood", 2001, 0, "another-recording-mbid"),
    song(6, "Clint Eastwood - Ed Case Refix", 2002),
    song(7, "Dare (feat. Shaun Ryder & Rosie Wilson)", 2005),
    song(8, "El Mañana", 2005),
    song(9, "Kids with Guns", 2005, 3),
    song(10, "Tomorrow Comes Today", 2001, 5),
    song(11, "Re-Hash", 2001),
]


class Net:
    """Stands in for urlopen: each call pops the next answer, recording requests."""

    def __init__(self):
        self.answers, self.requests = [], []

    def __call__(self, request, timeout):
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        response = io.BytesIO(answer)
        response.status = 200
        return response


def http_error(code, headers=None):
    """An HTTPError as urllib raises it."""
    return HTTPError("https://api.listenbrainz.org/x", code, "", headers or {}, None)


def patch(test, *patches):
    """Set each (target, name, value) until test ends, creating absent names."""
    for target, name, value in patches:
        patcher = mock.patch.object(target, name, value, create=True)
        patcher.start()
        test.addCleanup(patcher.stop)


class Base(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000.0
        self.net = Net()
        self.settings = {"listenbrainz_token": " lb-token "}
        patch(
            self,
            (time, "time", lambda: self.now),
            (http, "urlopen", self.net),
            (listenbrainz, "Monitor", lambda: self),  # waitForAbort: the clock moves on
            (listenbrainz.ADDON, "getSetting", lambda key: self.settings.get(key, "")),
        )
        self.cache = ApiCacheHandler()
        self.cache.clear_all()
        sys.modules["xbmcgui"].Window().clearProperty(listenbrainz.NEXT_CALL)

    def row(self, mbid=GORILLAZ, key="listenbrainz:top-recordings:"):
        """The api_cache row for mbid: (payload, seconds left)."""
        row = self.cache._get_one("key = ?", (f"{key}{mbid}",))
        return (
            row["payload"] and json.loads(row["payload"]),
            row["expires_at"] - self.now,
        )

    def tick(self, seconds):
        self.now += seconds

    def waitForAbort(self, seconds):
        self.tick(seconds)
        return False


class HttpTest(Base):
    def test_user_agent_and_accept(self):
        self.net.answers = [b"[]"]
        http.get_json("https://example.org/x", {"a": "b c"})
        request = self.net.requests[0]
        self.assertEqual(request.full_url, "https://example.org/x?a=b+c")
        self.assertRegex(
            request.get_header("User-agent"),
            r"^script\.copacetic\.helper/\S* \( https://github\.com/\S+ \)$",
        )
        self.assertEqual(request.get_header("Accept"), "application/json")

    def test_post_body(self):
        self.net.answers = [b"[]"]
        http.get_json("https://example.org/x", body={"artist_mbids": [GORILLAZ]})
        request = self.net.requests[0]
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(json.loads(request.data), {"artist_mbids": [GORILLAZ]})
        self.assertEqual(request.get_header("Content-type"), "application/json")

    def test_errors(self):
        self.net.answers = [
            http_error(429, {"X-RateLimit-Reset-In": "7"}),
            URLError("offline"),
            TimeoutError(),
            b"<html>",
        ]
        for status, wait in ((429, 7), (None, 0), (None, 0), (None, 0)):
            with self.assertRaises(http.HttpError) as caught:
                http.get_json("https://example.org/x")
            self.assertEqual(
                (caught.exception.status, caught.exception.retry_after), (status, wait)
            )


class ListenBrainzTest(Base):
    def test_hit_cached_two_weeks(self):
        self.net.answers = [FIXTURE]
        top = listenbrainz.top_recordings(GORILLAZ)
        self.assertEqual(
            top[:3],
            [
                ["5004ea88-6c7e-4096-a89f-b24e358408ee", "Feel Good Inc."],
                ["318a1c51-5910-4823-bda1-09ea6d84648a", "Clint Eastwood"],
                ["a06d7304-5980-408d-9227-70c2ded24293", "DARE"],
            ],
        )
        self.assertEqual(self.row(), (top, 14 * DAY))
        request = self.net.requests[0]
        self.assertTrue(request.full_url.endswith(GORILLAZ))
        self.assertEqual(request.get_header("Authorization"), "Token lb-token")
        self.tick(13 * DAY)
        self.assertEqual(listenbrainz.top_recordings(GORILLAZ), top)
        self.assertEqual(len(self.net.requests), 1)

    def test_empty_cached_three_days(self):
        self.net.answers = [b"[]"]
        self.assertEqual(listenbrainz.top_recordings(GORILLAZ), [])
        self.assertEqual(self.row(), ([], 3 * DAY))

    def test_rejected_mbid_negative_week(self):
        for code in (400, 404):
            self.cache.clear_all()
            self.tick(2)
            self.net.answers = [http_error(code)]
            self.assertEqual(listenbrainz.top_recordings(GORILLAZ), [])
            self.assertEqual(self.row(), (None, 7 * DAY))
        self.tick(6 * DAY)
        listenbrainz.top_recordings(GORILLAZ)
        self.assertEqual(len(self.net.requests), 2)  # negative entry served

    def test_token_refused_retried_in_five_minutes(self):
        warnings = LOG["WARNING"]
        self.net.answers = [http_error(401), FIXTURE]
        self.assertEqual(listenbrainz.top_recordings(GORILLAZ), [])
        self.assertEqual(self.row(), (None, 300))
        self.assertEqual(LOG["WARNING"], warnings + 1)
        self.tick(301)
        self.assertTrue(listenbrainz.top_recordings(GORILLAZ))

    def test_tokenless_refusals_left_behind(self):
        self.cache.put(f"listenbrainz:top:{GORILLAZ}", None, 7 * DAY)  # pre-token key
        self.net.answers = [FIXTURE]
        self.assertTrue(listenbrainz.top_recordings(GORILLAZ))

    def test_top_release_groups(self):
        self.net.answers = [ALBUMS]
        albums = listenbrainz.top_release_groups(GORILLAZ)
        self.assertEqual(
            albums[:2],
            [
                ["f959a46a-a136-3134-9412-6572b23fad95", "Demon Days"],
                ["b0405d2a-5720-340a-bb56-4e135d031cc2", "Gorillaz"],
            ],
        )
        self.assertEqual(
            self.row(key="listenbrainz:top-release-groups:"), (albums, 14 * DAY)
        )
        self.assertTrue(
            self.net.requests[0].full_url.endswith(
                f"/1/popularity/top-release-groups-for-artist/{GORILLAZ}"
            )
        )

    def test_listeners(self):
        answer = [
            {
                "artist_mbid": GORILLAZ,
                "total_listen_count": 1000,
                "total_user_count": 10,
            }
        ]  # the documented answer shape
        self.net.answers = [json.dumps(answer).encode()]
        self.assertEqual(listenbrainz.listeners("artist", GORILLAZ), 10)
        request = self.net.requests[0]
        self.assertTrue(request.full_url.endswith("/1/popularity/artist"))
        self.assertEqual(json.loads(request.data), {"artist_mbids": [GORILLAZ]})
        self.assertEqual(request.get_header("Authorization"), "Token lb-token")
        key = "listenbrainz:listeners:artist:"
        self.assertEqual(self.row(key=key), (10, 14 * DAY))

    def test_listeners_unknown_negative(self):
        answer = [
            {
                "release_group_mbid": GORILLAZ,
                "total_listen_count": None,
                "total_user_count": None,
            }
        ]
        self.net.answers = [json.dumps(answer).encode()]
        self.assertIsNone(listenbrainz.listeners("release-group", GORILLAZ))
        self.assertEqual(
            json.loads(self.net.requests[0].data), {"release_group_mbids": [GORILLAZ]}
        )
        key = "listenbrainz:listeners:release-group:"
        self.assertEqual(self.row(key=key), (None, 3 * DAY))

    def test_offline_without_stale(self):
        self.net.answers = [URLError("offline")]
        self.assertEqual(listenbrainz.top_recordings(GORILLAZ), [])
        self.assertEqual(self.row(), (None, 300))

    def test_stale_served_when_refresh_fails(self):
        self.net.answers = [FIXTURE, http_error(503), FIXTURE]
        top = listenbrainz.top_recordings(GORILLAZ)
        self.tick(15 * DAY)
        self.assertEqual(listenbrainz.top_recordings(GORILLAZ), top)
        self.assertEqual(self.row(), (top, 300))  # kept, retried in 5 minutes
        self.tick(299)
        listenbrainz.top_recordings(GORILLAZ)
        self.assertEqual(len(self.net.requests), 2)
        self.tick(2)
        listenbrainz.top_recordings(GORILLAZ)
        self.assertEqual(len(self.net.requests), 3)

    def test_calls_inside_a_second_queue(self):
        self.net.answers = [FIXTURE, ALBUMS, FIXTURE]
        start = self.now
        listenbrainz.top_recordings(GORILLAZ)
        self.assertTrue(listenbrainz.top_release_groups(GORILLAZ))
        self.assertTrue(listenbrainz.top_recordings("other-artist"))
        self.assertEqual(len(self.net.requests), 3)
        self.assertEqual(self.now - start, 2)

    def test_queue_past_max_wait_skips(self):
        self.net.answers = [FIXTURE]
        window = sys.modules["xbmcgui"].Window()
        window.setProperty(listenbrainz.NEXT_CALL, f"{self.now + 3.5}")
        self.assertEqual(listenbrainz.top_recordings(GORILLAZ), [])
        self.assertEqual(self.net.requests, [])
        self.assertIsNone(self.cache.get(f"listenbrainz:top-recordings:{GORILLAZ}"))

    def test_429_waits_reset_in(self):
        self.net.answers = [http_error(429, {"X-RateLimit-Reset-In": "30"}), FIXTURE]
        self.assertEqual(listenbrainz.top_recordings(GORILLAZ), [])
        self.assertEqual(self.row(), (None, 30))
        self.tick(26)
        self.assertEqual(listenbrainz.top_recordings("other-artist"), [])
        self.assertEqual(len(self.net.requests), 1)
        self.tick(4)
        self.assertTrue(listenbrainz.top_recordings(GORILLAZ))

    def test_token_test_action(self):
        shown = []
        notify = {
            "notification": lambda _, heading, message, time: shown.append(message)
        }
        self.net.answers = [b'{"valid": true}', b'{"valid": false}', http_error(400)]
        with (
            mock.patch.object(actions.xbmcgui, "Dialog", type("Dialog", (), notify)),
            mock.patch.object(actions.ADDON, "getLocalizedString", str, create=True),
        ):
            for token in ("lb-token", "lb-token", "lb-token", ""):
                self.settings["listenbrainz_token"] = token
                actions.listenbrainz_test()
        self.assertEqual(shown, ["32213", "32214", "32214", "32212"])
        self.assertEqual(len(self.net.requests), 3)  # no token: nothing sent
        request = self.net.requests[0]
        self.assertTrue(request.full_url.endswith("/1/validate-token"))
        self.assertEqual(request.get_header("Authorization"), "Token lb-token")

    def test_prune_keeps_recently_expired(self):
        self.cache.put("a", [1], 0)
        self.cache.put("b", [2], 0)
        self.tick(31 * DAY)
        self.cache.put("b", [2], 0)
        self.cache.prune()
        self.assertIsNone(self.cache.get("a"))
        self.assertEqual(self.cache.get("b"), ([2], False))


class MatchTest(unittest.TestCase):
    recordings = [
        [row["recording_mbid"], row["recording_name"]] for row in json.loads(FIXTURE)
    ]

    def test_title_key(self):
        self.assertEqual(title_key("Dare (feat. Shaun Ryder)"), title_key("DARE"))
        self.assertEqual(title_key("El Mañana"), title_key("El mañana"))
        self.assertEqual(title_key("Clint Eastwood - 2005 Remaster"), "clinteastwood")
        self.assertEqual(title_key("(Intro)"), "intro")

    def test_rank(self):
        ranked = [row["songid"] for row in rank_songs(self.recordings, SONGS)]
        # MBID beats the earlier demo; earliest dated Clint Eastwood; one per title;
        # topped up with played songs (10), unplayed Re-Hash left out
        self.assertEqual(ranked, [2, 5, 7, 8, 9, 10])

    def test_no_match_no_list(self):
        self.assertEqual(rank_songs([["x", "Unknown"]], SONGS), [])


class LibraryItemTest(unittest.TestCase):
    @mock.patch("resources.lib.plugin.music.apply_musicinfotag")
    @mock.patch("resources.lib.plugin.music.ListItem")
    def test_properties_as_kodi_sets_them(self, list_item, _):
        artist = {
            "artistid": 4,
            "art": {},
            "born": "",
            "description": "Virtual band.",
            "died": "",
            "disbanded": "",
            "formed": "1998",
            "genre": ["Alternative"],
            "label": "Gorillaz",
            "yearsactive": ["1990s", "2000s"],
        }
        song = {"art": {}, "file": "f.mp3", "genre": [], "label": "Dare", "songid": 2}
        self.assertEqual(library_item(artist, "artist")[0], "musicdb://artists/4/")
        library_item(song, "song")
        self.assertEqual(
            [call.args for call in list_item.return_value.setProperties.call_args_list],
            [
                (
                    {
                        "artist_born": "",
                        "artist_description": "Virtual band.",
                        "artist_died": "",
                        "artist_disbanded": "",
                        "artist_formed": "1998",
                        "artist_yearsactive": "1990s / 2000s",
                    },
                ),
                ({},),
            ],
        )


class TopSongsTest(Base):
    def setUp(self):
        super().setUp()
        self.calls = []

        def rpc(request):
            method = json.loads(request)["method"]
            self.calls.append(method)
            if method == "AudioLibrary.GetArtistDetails":
                return json.dumps(
                    {
                        "result": {
                            "artistdetails": {"musicbrainzartistid": self.artist_mbids}
                        }
                    }
                )
            return json.dumps({"result": {"songs": SONGS}})

        patch(
            self,
            (sys.modules["xbmc"], "executeJSONRPC", rpc),
            (handlers, "set_plugincontent", lambda **kwargs: None),
            (handlers, "library_item", lambda row, type: row["title"]),
        )
        self.handler = object.__new__(handlers.PluginHandlers)
        self.handler.params = {"info": "top_songs", "id": "4"}
        self.handler.dbid, self.handler.limit = "4", 3
        self.artist_mbids = [GORILLAZ]

    def test_off_sends_nothing(self):
        self.settings["listenbrainz_token"] = " "
        self.assertIsNone(self.handler.top_songs())
        self.assertEqual((self.calls, self.net.requests), ([], []))

    def test_on(self):
        self.net.answers = [FIXTURE]
        self.assertEqual(
            self.handler.top_songs(),
            [
                "Feel Good Inc.",
                "Clint Eastwood",
                "Dare (feat. Shaun Ryder & Rosie Wilson)",
            ],
        )

    def test_untagged_artist(self):
        self.artist_mbids = [""]
        self.assertIsNone(self.handler.top_songs())
        self.assertEqual(self.net.requests, [])

    def test_offline_hides(self):
        self.net.answers = [URLError("offline")]
        self.assertIsNone(self.handler.top_songs())
        self.assertEqual(self.calls, ["AudioLibrary.GetArtistDetails"])


class TmdbTest(Base):
    def setUp(self):
        super().setUp()
        self.settings = {"tmdb_access_token": "v3key"}  # Base's getSetting reads it
        sys.modules["xbmcgui"].Window().clearProperty(transform.TOKEN_REFUSED)

    def tmdb_row(self, key="tmdb:tvshow:1399:en-US"):
        """The api_cache row for key: (payload, seconds left)."""
        row = self.cache._get_one("key = ?", (key,))
        return (
            row["payload"] and json.loads(row["payload"]),
            row["expires_at"] - self.now,
        )

    def test_hit_cached_a_week(self):
        self.net.answers = [TMDB_TV]
        item = transform.tmdb_to_canonical("tvshow", 1399)
        self.assertEqual(item["Title"], "Game of Thrones")
        self.assertEqual(item["Writers"], ["David Benioff", "D. B. Weiss"])
        self.assertEqual(item["Year"], 2011)
        self.assertTrue(item["Trailer"].endswith("video_id=trailer-key"))
        self.assertEqual(self.tmdb_row(), (item, 7 * DAY))
        request = self.net.requests[0]
        self.assertTrue(
            request.full_url.startswith("https://api.themoviedb.org/3/tv/1399?")
        )
        self.assertIn("api_key=v3key", request.full_url)
        self.assertIn("language=en-US", request.full_url)
        self.assertIn("script.copacetic.helper/", request.get_header("User-agent"))
        self.tick(6 * DAY)
        self.assertEqual(transform.tmdb_to_canonical("tvshow", 1399), item)
        self.assertEqual(len(self.net.requests), 1)

    def test_v4_token_in_header(self):
        self.settings["tmdb_access_token"] = "eyJ.token"
        self.net.answers = [TMDB_TV]
        transform.tmdb_to_canonical("tvshow", 1399)
        request = self.net.requests[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer eyJ.token")
        self.assertNotIn("api_key", request.full_url)

    def test_404_negative_a_day(self):
        self.net.answers = [http_error(404)]
        self.assertEqual(transform.tmdb_to_canonical("tvshow", 1399), {})
        self.assertEqual(self.tmdb_row(), (None, DAY))
        self.tick(DAY - 1)
        self.assertEqual(transform.tmdb_to_canonical("tvshow", 1399), {})
        self.assertEqual(len(self.net.requests), 1)

    def test_offline_without_stale(self):
        warnings = LOG["WARNING"] + LOG["ERROR"]
        self.net.answers = [URLError("offline")]
        self.assertEqual(transform.tmdb_to_canonical("tvshow", 1399), {})
        self.assertEqual(self.tmdb_row(), (None, 300))
        self.assertEqual(LOG["WARNING"] + LOG["ERROR"], warnings)
        transform.tmdb_to_canonical("tvshow", 1399)
        self.assertEqual(len(self.net.requests), 1)  # no second wait for the timeout

    def test_stale_served_while_offline(self):
        self.net.answers = [TMDB_TV, TimeoutError(), TMDB_TV]
        item = transform.tmdb_to_canonical("tvshow", 1399)
        self.tick(8 * DAY)
        self.assertEqual(transform.tmdb_to_canonical("tvshow", 1399), item)
        self.assertEqual(self.tmdb_row(), (item, 300))
        self.assertEqual(
            transform.tmdb_to_canonical("tvshow", 1399, cache_only=True), item
        )
        self.tick(301)
        transform.tmdb_to_canonical("tvshow", 1399)
        self.assertEqual(self.tmdb_row(), (item, 7 * DAY))
        self.assertEqual(len(self.net.requests), 3)

    def test_episode_takes_show_level_keys_only(self):
        self.net.answers = [TMDB_TV]
        episode = transform.tmdb_to_canonical("episode", 1399)
        self.assertEqual(set(episode), {"file", "art", "properties", "Trailer"})
        self.assertTrue(episode["Trailer"].endswith("video_id=trailer-key"))
        self.assertTrue(self.tmdb_row()[0]["Title"])  # one show entry serves both
        transform.tmdb_to_canonical("tvshow", 1399)
        self.assertEqual(len(self.net.requests), 1)

    def test_episode_context_looks_up_its_show(self):
        requests = []

        def rpc(request):
            requests.append(json.loads(request))
            show = {"uniqueid": {"tmdb": "1399"}}
            return json.dumps({"result": {"tvshowdetails": show}})

        patch(self, (sys.modules["xbmc"], "executeJSONRPC", rpc))
        params = {"type": "episode", "id": "5", "tvshowid": "7", "tmdb_id": "63056"}
        ctx = resolve_tmdb_context(params, "ListItem")
        self.assertEqual((ctx["kind"], ctx["tmdb_id"]), ("episode", "1399"))
        self.assertEqual(requests[0]["method"], "VideoLibrary.GetTVShowDetails")
        self.assertEqual(requests[0]["params"]["tvshowid"], 7)

    def test_no_token_sends_serves_and_logs_nothing(self):
        self.cache.put("tmdb:tvshow:1399:en-US", {"Title": "cached"}, DAY)
        logged = sum(LOG.values())
        for token in ("", " "):
            self.settings["tmdb_access_token"] = token
            self.assertEqual(transform.tmdb_to_canonical("tvshow", 1399), {})
        self.assertEqual((self.net.requests, sum(LOG.values())), ([], logged))

    def test_no_art_reads_the_art_entry(self):
        self.net.answers = [TMDB_TV, TMDB_TV]
        item = transform.tmdb_to_canonical("tvshow", 1399)
        self.assertIn("include_image_language=en%2Cnull", self.net.requests[0].full_url)
        self.assertEqual(
            transform.tmdb_to_canonical("tvshow", 1399, append_artwork=False), item
        )
        self.assertEqual(len(self.net.requests), 1)
        self.cache.clear_all()
        transform.tmdb_to_canonical("tvshow", 1399, append_artwork=False)
        url = self.net.requests[1].full_url
        self.assertIn("append_to_response=videos&", url)
        self.assertNotIn("include_image_language", url)
        self.assertTrue(self.tmdb_row("tmdb:tvshow:1399:en-US|noart")[0])

    def test_no_art_falls_back_to_a_stale_art_entry(self):
        self.net.answers = [TMDB_TV, TimeoutError()]
        item = transform.tmdb_to_canonical("tvshow", 1399)
        self.tick(8 * DAY)
        no_art = dict(append_artwork=False)
        self.assertEqual(
            transform.tmdb_to_canonical("tvshow", 1399, cache_only=True, **no_art), item
        )
        self.assertEqual(len(self.net.requests), 1)  # cache only: no request
        self.assertEqual(transform.tmdb_to_canonical("tvshow", 1399, **no_art), item)
        self.assertEqual(self.tmdb_row("tmdb:tvshow:1399:en-US|noart"), (None, 300))
        self.assertEqual(transform.tmdb_to_canonical("tvshow", 1399, **no_art), item)
        self.assertEqual(len(self.net.requests), 2)  # no retry inside the 5 minutes

    def test_next_air_reads_the_cache_only(self):
        day = date.today() + timedelta(days=30)
        tv = json.loads(TMDB_TV) | {"next_episode_to_air": {"air_date": str(day)}}
        handler = object.__new__(handlers.PluginHandlers)
        handler.params, handler.dbtype = {}, ""
        handler.target_item = "Container(50).ListItem"
        labels = {"DBType": "tvshow", "DBID": "7", "UniqueID(tmdb)": "1399"}
        label = lambda path: labels.get(path.rpartition("ListItem.")[2], "")
        with mock.patch("resources.lib.apis.tmdb.context.infolabel", label):
            self.assertEqual(handler._next_air(), "")  # nothing cached: no request
            self.assertEqual(self.net.requests, [])
            self.net.answers = [json.dumps(tv).encode()]  # the metadata serve's fetch
            transform.tmdb_to_canonical("tvshow", 1399, append_artwork=False)
            self.tick(8 * DAY)  # stale, still served
            self.assertEqual(handler._next_air(), day.strftime("%d %b"))
        self.assertEqual(len(self.net.requests), 1)

    def test_next_air_off_looks_nothing_up(self):
        self.settings = {}  # no TMDb token
        handler = object.__new__(handlers.PluginHandlers)
        handler.params, handler.target_item = {}, "Container(50).ListItem"
        labels = {"DBType": "tvshow", "DBID": "7"}  # no UniqueID(tmdb): a TVDB show
        label = lambda path: labels.get(path.rpartition("ListItem.")[2], "")
        rpc = mock.Mock(return_value="{}")
        with (
            mock.patch("resources.lib.apis.tmdb.context.infolabel", label),
            mock.patch.object(sys.modules["xbmc"], "executeJSONRPC", rpc, create=True),
        ):
            self.assertEqual(handler._next_air(), "")
            rpc.assert_not_called()  # no uniqueid lookup
            self.settings = {"tmdb_access_token": "v3key"}
            self.assertEqual(handler._next_air(), "")  # on: looks the id up, no cache
        self.assertEqual(rpc.call_count, 1)

    def test_refused_token_warns_once(self):
        warnings = LOG["WARNING"]
        self.net.answers = [http_error(401), http_error(403)]
        self.assertEqual(transform.tmdb_to_canonical("tvshow", 1399), {})
        self.assertEqual(transform.tmdb_to_canonical("movie", 603), {})
        self.assertEqual(len(self.net.requests), 2)
        self.assertEqual(LOG["WARNING"], warnings + 1)

    def test_metadata_keeps_library_plot_and_tagline(self):
        library = {"Plot": "Library plot", "Writer": "Library writer"}
        self.net.answers = [TMDB_TV] * 2
        patch(  # an empty JSON-RPC answer: the album has no album artist
            self,
            (sys.modules["xbmc"], "executeJSONRPC", lambda request: "{}"),
            (handlers, "set_items", lambda items, **kwargs: items),
        )
        handler = object.__new__(handlers.PluginHandlers)
        handler.params = {"enrich_with_tmdb": "true"}
        handler.item, handler.dbtype, handler.dbid = False, "tvshow", "7"
        handler.target_item = "Container(50).ListItem"
        handler._guard = lambda: mock.Mock(alive=lambda: True)
        handler._get_tmdb_item = lambda **kwargs: transform.tmdb_to_canonical(
            "tvshow", 1399
        )
        probes = []
        handler._apply_truncated_label = lambda *a, **kw: probes.append(kw["probe"])
        label = lambda path: library.get(path.rpartition(".")[2], "")
        with mock.patch.object(helpers, "infolabel", label):
            (item,) = handler.metadata()
            self.assertEqual(item["Plot"], "Library plot")
            self.assertEqual(item["TagLine"], "Winter is coming.")  # library has none
            self.assertNotEqual(item["Writers"], ["Library writer"])  # TMDb still wins
            library["Tagline"] = "Library tagline"
            library["Plot"] = ""
            (item,) = handler.metadata()
        self.assertEqual(item["TagLine"], "Library tagline")
        self.assertTrue(item["Plot"].startswith("Seven noble families"))
        handler.dbtype, library["Plot"] = "season", "The show's plot"
        with mock.patch.object(helpers, "infolabel", label):
            (item,) = handler.metadata()
        self.assertTrue(item["Plot"].startswith("Seven noble families"))
        self.assertEqual(item["TagLine"], "Library tagline")
        handler.params["truncate_probe"] = "season"
        with mock.patch.object(helpers, "infolabel", label):
            handler.metadata()
            handler.dbtype = "episode"  # an episode's plot is its own: keeps the probe
            handler.metadata()
            handler.params["truncate_probe"] = "false"  # a favourite: video skips
            handler.metadata()
            handler._get_tmdb_item, library["Plot"] = lambda **kwargs: {}, ""
            handler.dbtype = "season"  # a favourite season, no plot: still skips
            handler.metadata()
            handler.params["truncate_probe"], handler.dbtype = "false", "album"
            handler.metadata()  # music keeps the probe (an album caption: description)
        self.assertEqual(probes, [True, True, True, False, True, False, False, True])

    def test_truncated_label_probe(self):
        handler = object.__new__(handlers.PluginHandlers)
        handler.params = {
            "truncate_font": "description_l",
            "truncate_label_id": "6009",
            "truncate_width": "520",
        }
        probe = lambda path: "Probe" if path == "Control.GetLabel(6009)" else ""
        clamp = lambda text, **kwargs: text
        with mock.patch.object(handlers, "infolabel", probe), mock.patch.object(
            handlers, "clamp_text", clamp
        ):
            for use_probe, expected in ((True, "Probe"), (False, "Merged")):
                data = {}
                handler._apply_truncated_label(
                    data, target="ListItem", default_text="Merged", probe=use_probe
                )
                self.assertEqual(data["properties"]["truncated_label"], expected)


def album(albumid, title, year, mbid=""):
    """A library album row as AudioLibrary.GetAlbums returns it (fields used here)."""
    return {
        "albumid": albumid,
        "title": title,
        "year": year,
        "musicbrainzreleasegroupid": mbid,
    }


ALBUM_ROWS = [
    album(1, "Gorillaz", 2001),
    album(2, "Demon Days", 2005, "f959a46a-a136-3134-9412-6572b23fad95"),
    album(3, "Demon Days (Deluxe Edition)", 2006),  # same title once trimmed
    album(4, "Plastic Beach", 2010, "other-release-group"),  # wrong MBID, title hits
    album(5, "Song Machine, Season One", 2020),  # unknown to the fixture
    album(6, "Cracker Island", 2023),
]


class DiscographyTest(Base):
    groups = [
        [row["release_group_mbid"], row["release_group"]["name"]]
        for row in json.loads(ALBUMS)
    ]

    def setUp(self):
        super().setUp()
        self.calls = []

        def rpc(request):
            method = json.loads(request)["method"]
            self.calls.append(method)
            if method == "AudioLibrary.GetArtistDetails":
                return json.dumps(
                    {"result": {"artistdetails": {"musicbrainzartistid": [GORILLAZ]}}}
                )
            return json.dumps({"result": {"albums": ALBUM_ROWS}})

        patch(
            self,
            (sys.modules["xbmc"], "executeJSONRPC", rpc),
            (handlers, "set_plugincontent", lambda **kwargs: None),
            (handlers, "library_item", lambda row, type: row["albumid"]),
        )
        self.handler = object.__new__(handlers.PluginHandlers)
        self.handler.params = {"info": "discography", "id": "4"}
        self.handler.dbid, self.handler.limit = "4", None

    def test_rank(self):
        # Demon Days by MBID, its deluxe copy by title (newer first among equals),
        # Gorillaz, Plastic Beach by title; then the unmatched newest first
        self.assertEqual(
            [row["albumid"] for row in rank_albums(self.groups, ALBUM_ROWS)],
            [3, 2, 1, 4, 6, 5],
        )

    def test_no_groups_is_date_order(self):
        self.assertEqual(
            [row["albumid"] for row in rank_albums([], ALBUM_ROWS)], [6, 5, 4, 3, 2, 1]
        )

    def test_off_is_date_order_without_requests(self):
        self.settings["listenbrainz_token"] = " "
        self.assertEqual(self.handler.discography(), [6, 5, 4, 3, 2, 1])
        self.assertEqual(self.calls, ["AudioLibrary.GetAlbums"])
        self.assertEqual(self.net.requests, [])

    def test_on(self):
        self.net.answers = [ALBUMS]
        self.assertEqual(self.handler.discography(), [3, 2, 1, 4, 6, 5])
        self.assertTrue(
            self.net.requests[0].full_url.endswith(
                f"top-release-groups-for-artist/{GORILLAZ}"
            )
        )

    def test_offline_is_date_order(self):
        self.net.answers = [URLError("offline")]
        self.assertEqual(self.handler.discography(), [6, 5, 4, 3, 2, 1])


class ListenersTest(Base):
    def setUp(self):
        super().setUp()
        self.calls = []

        def rpc(request):
            request = json.loads(request)
            self.calls.append((request["method"], request["params"]["properties"]))
            kind = request["method"].removeprefix("AudioLibrary.Get").lower()
            field = request["params"]["properties"][0]
            return json.dumps({"result": {kind: {field: self.mbid}}})

        patch(
            self,
            (sys.modules["xbmc"], "executeJSONRPC", rpc),
            (handlers, "set_items", lambda items: items),
        )
        self.handler = object.__new__(handlers.PluginHandlers)
        self.handler.params = {"info": "listeners", "id": "7", "type": "album"}
        self.handler.dbid, self.handler.dbtype = "7", "album"
        self.mbid = "f959a46a-a136-3134-9412-6572b23fad95"

    def answer(self, users):
        self.net.answers = [
            json.dumps(
                [
                    {
                        "release_group_mbid": self.mbid,
                        "total_listen_count": 1,
                        "total_user_count": users,
                    }
                ]
            ).encode()
        ]

    def test_compact_count(self):
        cases = {
            0: "0",
            87: "87",
            994: "994",
            999: "1K",
            1234: "1.2K",
            99_950: "100K",
            314_279: "310K",
            999_999: "1M",
            1_234_567: "1.2M",
            15_812_594: "16M",
            2_500_000_000: "2.5B",
        }
        for count, text in cases.items():
            self.assertEqual(compact_count(count), text)

    def test_off_sends_nothing(self):
        self.settings["listenbrainz_token"] = " "
        self.assertIsNone(self.handler.listeners())
        self.assertEqual((self.calls, self.net.requests), ([], []))

    def test_other_type_sends_nothing(self):
        self.handler.dbtype = "musicvideo"
        self.assertIsNone(self.handler.listeners())
        self.assertEqual((self.calls, self.net.requests), ([], []))

    def test_album_asks_its_release_group(self):
        self.answer(314_279)
        [item] = self.handler.listeners()
        self.assertEqual(item["properties"], {"listeners": "310K"})
        self.assertEqual(
            self.calls,
            [("AudioLibrary.GetAlbumDetails", ["musicbrainzreleasegroupid"])],
        )
        self.assertTrue(
            self.net.requests[0].full_url.endswith("/1/popularity/release-group")
        )

    def test_song_and_artist_ids(self):
        for type, field, entity in (
            ("song", "musicbrainztrackid", "recording"),
            ("artist", "musicbrainzartistid", "artist"),
        ):
            self.calls, self.net.requests = [], []
            self.tick(2)
            self.handler.dbtype = self.handler.params["type"] = type
            self.mbid = [GORILLAZ] if type == "artist" else GORILLAZ
            self.answer(10)
            self.assertEqual(
                self.handler.listeners()[0]["properties"], {"listeners": "10"}
            )
            self.assertEqual(self.calls[0][1], [field])
            request = self.net.requests[0]
            self.assertTrue(request.full_url.endswith(f"/1/popularity/{entity}"))
            self.assertEqual(json.loads(request.data), {f"{entity}_mbids": [GORILLAZ]})

    def test_untagged_or_unknown_hides(self):
        self.mbid = ""
        self.assertIsNone(self.handler.listeners())
        self.assertEqual(self.net.requests, [])
        self.mbid = "f959a46a-a136-3134-9412-6572b23fad95"
        self.answer(None)
        self.assertIsNone(self.handler.listeners())


class ParserTest(unittest.TestCase):
    def parse(self, query):
        return parse_plugin_argv(["plugin://script.copacetic.helper/", "1", query])

    def test_empty_var_separators(self):
        # An empty $VAR leaves a trailing '&' or '&&': neither joins the value
        for query in (
            "?info=metadata&random_pick=true&",
            "?info=metadata&random_pick=true&&",
            "?info=metadata&random_pick=true&&season_probe=false",
            "?&info=metadata&&random_pick=true",
        ):
            params = self.parse(query)
            self.assertEqual(params["info"], "metadata")
            self.assertEqual(params["random_pick"], "true")
        self.assertEqual(
            self.parse("?focus_ids=3200,4200,215&&target_id=4010&img_h=2"),
            {"focus_ids": "3200,4200,215", "target_id": "4010", "img_h": "2"},
        )
        self.assertEqual(self.parse("?label=&id=3&"), {"label": "", "id": "3"})

    def test_raw_and_encoded_ampersands(self):
        # A raw '&' not followed by key= stays in the value; '%26' always does
        self.assertEqual(
            self.parse("?label=Tom & Jerry&amp;id=3&tag=R&&B"),
            {"label": "Tom & Jerry", "id": "3", "tag": "R&&B"},
        )
        self.assertEqual(
            self.parse("?label=Tom %26 Jerry&tag=true%26&"),
            {"label": "Tom & Jerry", "tag": "true&"},
        )


class NextUpTest(unittest.TestCase):
    shows = [
        {"tvshowid": 1, "title": "Specials Left"},
        {"tvshowid": 2, "title": "Bluey"},
        {"tvshowid": 3, "title": "Taskmaster"},
    ]
    episodes = [{"tvshowid": 3, "title": "TM 1x01"}, {"tvshowid": 2, "title": "B 1x01"}]

    def setUp(self):
        self.calls = []

        def rpc(request):
            request = json.loads(request)
            self.calls.append(request["method"])
            if request["method"] == "VideoLibrary.GetEpisodes":
                return json.dumps({"result": {"episodes": self.episodes}})
            # as SortUtils::Sort: a start at or past the end trims nothing
            limits = request["params"].get("limits", {})
            start = limits.get("start", 0)
            rows = self.shows[start if start < len(self.shows) else 0 :]
            rows = rows[: limits["end"] - start] if "end" in limits else rows
            return json.dumps({"result": {"tvshows": rows}})

        patch(
            self,
            (sys.modules["xbmc"], "executeJSONRPC", rpc),
            (handlers, "set_plugincontent", lambda **kwargs: None),
            (handlers, "build_items", lambda rows, *a, **k: [r["title"] for r in rows]),
            (handlers.ADDON, "getLocalizedString", str),
        )
        self.handler = object.__new__(handlers.PluginHandlers)
        self.handler.sort_lastplayed = None
        self.handler.filter_inprogress = self.handler.filter_unwatched = {}
        self.handler.filter_no_specials = {}

    def test_full_page_is_one_round(self):
        self.handler.limit = 1
        self.shows = self.shows[1:]
        self.assertEqual(self.handler.next_up(), ["B 1x01"])
        self.assertEqual(len(self.calls), 2)

    def test_specials_only_show_pages_on(self):
        # the most recent show has only specials left; limit 2 still gives two
        self.handler.limit = 2
        self.assertEqual(self.handler.next_up(), ["B 1x01", "TM 1x01"])
        self.assertEqual(self.calls.count("VideoLibrary.GetTVShows"), 2)

    def test_rest_comes_in_one_round(self):
        # limit 1: the first page is specials-only, the other two come together
        self.handler.limit = 1
        self.assertEqual(self.handler.next_up(), ["B 1x01"])
        self.assertEqual(self.calls.count("VideoLibrary.GetTVShows"), 2)

    def test_start_at_the_end_does_not_repeat(self):
        # exactly `limit` shows, one specials-only: round 2 gets them all again
        self.handler.limit = 3
        self.assertEqual(self.handler.next_up(), ["B 1x01", "TM 1x01"])
        self.assertEqual(self.calls.count("VideoLibrary.GetTVShows"), 2)

    def test_no_limit_is_one_round(self):
        self.handler.limit = None
        self.assertEqual(self.handler.next_up(), ["B 1x01", "TM 1x01"])
        self.assertEqual(len(self.calls), 2)


def days_ago(days):
    """A JSON-RPC dateadded string, days before now."""
    return f"{datetime.now() - timedelta(days=days):%Y-%m-%d %H:%M:%S}"


def aired(days):
    """A JSON-RPC firstaired string (a date), days before now; negative: to come."""
    return str(date.today() - timedelta(days=days))


class ProgressbarTest(unittest.TestCase):
    """info=progressbar's context properties, read off the item it returns."""

    episodes = [
        {"season": 0, "episode": 1, "firstaired": aired(3), "runtime": 600},
        {"season": 2, "episode": 11, "firstaired": aired(400), "runtime": 2700},
        {"season": 3, "episode": 1, "firstaired": aired(10), "runtime": 3720},
        {"season": 2, "episode": 10, "firstaired": aired(400), "runtime": 2581},
    ]
    film_added = days_ago(5)
    episode_aired = aired(2)

    def setUp(self):
        self.labels, self.calls, self.shows, self.films = {}, [], [], []
        self.episode_ids, self.fields = [], []
        self.watched = False

        def rpc(request):
            request = json.loads(request)
            if request["method"] == "VideoLibrary.GetMovieDetails":
                self.films.append(request["params"]["movieid"])
                self.fields.append(request["params"]["properties"])
                if self.film_added is None:  # an error answer
                    return json.dumps({"error": {"code": -32100}})
                details = {"dateadded": self.film_added}
                return json.dumps({"result": {"moviedetails": details}})
            if request["method"] == "VideoLibrary.GetEpisodeDetails":
                self.episode_ids.append(request["params"]["episodeid"])
                self.fields.append(request["params"]["properties"])
                if self.episode_aired is None:  # an error answer
                    return json.dumps({"error": {"code": -32100}})
                details = {"firstaired": self.episode_aired}
                return json.dumps({"result": {"episodedetails": details}})
            if request["method"] == "VideoLibrary.GetTVShowDetails":
                self.shows.append(request["params"]["tvshowid"])  # none expected
                return json.dumps({"result": {"tvshowdetails": {}}})
            params = request["params"]
            self.calls.append(params)
            season = params.get("season")  # none: the whole show
            rows = [ep for ep in self.episodes if season in (None, ep["season"])]
            return json.dumps({"result": {"episodes": rows}})

        patch(
            self,
            (sys.modules["xbmc"], "executeJSONRPC", rpc),
            (helpers, "infolabel", self.label),
            (handlers, "infolabel", self.label),
            (helpers, "condition", lambda expr: self.watched),
            (helpers.ProgressBarManager, "update", lambda self, percent, **kw: None),
            (handlers, "set_items", lambda items, **kwargs: items),
            (handlers, "getCurrentWindowId", lambda: 10025),
        )
        self.handler = object.__new__(handlers.PluginHandlers)
        self.handler.params = {"target_id": "4010"}
        self.handler.target_item = "Container(50).ListItem"
        self.handler.dialog = False
        self.alive = lambda: True
        self.handler._guard = lambda: mock.Mock(alive=lambda: self.alive())
        self.handler._get_tmdb_item = lambda **kwargs: None
        self.handler.filter_unwatched = {}

    def label(self, path):
        return self.labels.get(path.removeprefix("Container(50).ListItem."), "")

    def prop_all(self, **labels):
        self.labels = labels
        (item,) = self.handler.progressbar()
        return item["properties"]

    def prop(self, name, **labels):
        return self.prop_all(**labels)[name]

    def test_time_left(self):
        movie = {"DBType": "movie", "Duration(secs)": "7200"}
        self.assertEqual(self.prop("time_left", **movie, PercentPlayed="30"), "1h 24m")
        self.assertEqual(self.prop("time_left", **movie, PercentPlayed="99"), "2m")
        self.assertEqual(self.prop("time_left", **movie, PercentPlayed="50"), "1h")
        episode = {"DBType": "episode", "Duration(secs)": "2700"}
        self.assertEqual(self.prop("time_left", **episode, PercentPlayed="1"), "45m")
        self.assertEqual(self.prop("time_left", **movie), "")  # not started
        self.assertEqual(self.prop("time_left", DBType="movie", PercentPlayed="5"), "")
        season = {"DBType": "season", "Duration(secs)": "2700"}
        season["Property(WatchedEpisodePercent)"] = "50"
        self.assertEqual(self.prop("time_left", **season), "")
        self.assertEqual(self.calls, [])

    def test_resume_seconds(self):
        def served(**labels):
            self.labels = labels
            (item,) = self.handler.progressbar()
            return item["Duration"], item["resume"]

        # Part-watched with a runtime: seconds, for EndTimeResume (now + 5040 s)
        movie = {"DBType": "movie", "Duration(secs)": "7200", "PercentPlayed": "30"}
        self.assertEqual(served(**movie), (7200, {"position": 2160, "total": 7200}))
        episode = movie | {"DBType": "episode", "Duration(secs)": "2700"}
        self.assertEqual(served(**episode), (2700, {"position": 810, "total": 2700}))
        # A fractional position: 180.67 s of 2581, still 7 %, 2400.33 s (41m) left
        odd = episode | {"Duration(secs)": "2581", "PercentPlayed": "7"}
        _, resume = served(**odd)
        self.assertAlmostEqual(resume["position"], 180.67)
        self.assertEqual(round(resume["position"] / resume["total"] * 100), 7)
        self.assertEqual(self.prop("time_left", **odd), "41m")
        # Percent of 100 otherwise: no runtime, a season, unstarted, watched
        percent = {"position": 30, "total": 100}
        self.assertEqual(served(**movie | {"Duration(secs)": ""}), (0, percent))
        season = {"DBType": "season", "Duration(secs)": "2700"}
        season["Property(WatchedEpisodePercent)"] = "30"
        self.assertEqual(served(**season), (0, percent))
        unstarted = movie | {"PercentPlayed": "0"}
        self.assertEqual(served(**unstarted), (0, {"position": 0, "total": 100}))
        self.watched = True
        self.assertEqual(served(**unstarted), (0, {"position": 100, "total": 100}))
        self.watched = False
        self.alive = iter([True, False]).__next__  # superseded: the bare item too
        self.assertEqual(served(**movie)[1], {"position": 2160, "total": 7200})

    def test_next_episode(self):
        show = {"DBType": "tvshow", "DBID": "7", "Season": "4"}  # a show's Season: 4
        show["Property(UnwatchedEpisodes)"] = "4"
        show["Property(WatchedEpisodes)"] = "9"
        self.assertEqual(self.prop("next_episode", **show), "S02E10")
        self.assertNotIn("season", self.calls.pop())
        show["Property(WatchedEpisodes)"] = "0"  # unwatched: its first episode too
        self.assertEqual(self.prop("next_episode", **show), "S02E10")
        self.assertNotIn("season", self.calls.pop())
        unwatched_season = show | {"DBType": "season", "TvShowDBID": "7", "Season": "3"}
        properties = self.prop_all(**unwatched_season)  # not started: its next too
        self.assertEqual(
            (properties["next_episode"], properties["new"]), ("S03E01", "")
        )
        self.assertEqual(self.calls.pop()["season"], 3)
        favourite = unwatched_season | {"DBID": "40", "TvShowDBID": ""}
        favourite["Property(tvshowid)"] = "7"
        self.assertEqual(self.prop("next_episode", **favourite), "S03E01")
        self.assertEqual(self.calls.pop()["tvshowid"], 7)  # a helper season's show id
        for empty in (
            {"Season": "0"},
            {"Property(UnwatchedEpisodes)": "0"},
            {"Property(tvshowid)": ""},
            {"DBID": ""},  # another add-on's season: its tvshowid may be a TMDb id
        ):
            self.assertEqual(self.prop("next_episode", **favourite | empty), "")
        self.assertEqual(self.calls, [])  # Specials, none left or no show id: no query
        show["Property(InProgressEpisodes)"] = "1"  # its first episode, part-watched
        self.assertEqual(self.prop("next_episode", **show), "S02E10")
        self.calls.clear()
        self.assertEqual(self.prop("next_episode", **show, TvShowDBID=""), "S02E10")
        self.assertEqual(self.calls.pop()["tvshowid"], 7)
        for empty in ({"Property(UnwatchedEpisodes)": "0"}, {"DBID": ""}):
            self.assertEqual(self.prop("next_episode", **show | empty), "")
        self.assertEqual(self.calls, [])  # watched, or a plugin's show: no query

        season = show | {"DBType": "season", "DBID": "40", "TvShowDBID": "7"}
        self.assertEqual(
            self.prop("next_episode", **season | {"Season": "2"}), "S02E10"
        )
        call = self.calls.pop()
        self.assertEqual((call["tvshowid"], call["season"]), (7, 2))
        self.prop("next_episode", **season | {"Season": ""})  # * All seasons
        self.assertNotIn("season", self.calls.pop())  # -1 fails GetEpisodes' minimum
        self.assertEqual(self.prop("next_episode", **season | {"Season": "0"}), "")
        self.assertEqual(self.calls, [])  # Specials: no query
        self.episodes = self.episodes[:1]  # only a special left
        self.assertEqual(self.prop("next_episode", **season | {"Season": ""}), "")
        self.assertEqual(self.shows, [])  # no lastplayed, started or not

    def test_next_runtime(self):
        show = {"DBType": "tvshow", "DBID": "7", "Property(UnwatchedEpisodes)": "4"}
        show["Property(WatchedEpisodes)"] = "9"
        self.assertEqual(self.prop("next_runtime", **show), "43m")  # S02E10, 43:01
        self.assertIn("runtime", self.calls.pop()["properties"])
        season = show | {"DBType": "season", "TvShowDBID": "7", "Season": "3"}
        self.assertEqual(self.prop("next_runtime", **season), "1h 2m")  # S03E01
        episodes = self.episodes
        for runtime, shown in ((2610, "44m"), (3590, "1h")):  # half up; a round hour
            self.episodes = [ep | {"runtime": runtime} for ep in episodes]
            self.assertEqual(self.prop("next_runtime", **show), shown)
        self.episodes = [ep | {"runtime": 0} for ep in episodes]  # none known
        self.assertEqual(self.prop("next_runtime", **show), "")
        self.episodes = self.episodes[:1]  # only a special left: no next
        self.assertEqual(self.prop("next_runtime", **show), "")
        self.assertEqual(self.prop("next_runtime", **season | {"Season": "0"}), "")
        self.assertEqual(len(self.calls), 5)  # one GetEpisodes per serve; Season 0 none

    def test_new(self):
        show = {"DBType": "tvshow", "DBID": "7", "Property(UnwatchedEpisodes)": "4"}
        show["Property(WatchedEpisodes)"] = "9"
        self.assertEqual(self.prop("new", **show), "true")  # S03E01, aired 10 days ago
        self.assertIn("firstaired", self.calls.pop()["properties"])
        self.handler.params["new_days"] = "10"  # on the cutoff date: still new
        self.assertEqual(self.prop("new", **show), "true")
        self.handler.params["new_days"] = "9"  # the special aired 3 days ago counts
        self.assertEqual(self.prop("new", **show), "true")
        self.handler.params["new_days"] = "2"  # before both
        self.assertEqual(self.prop("new", **show), "")
        del self.handler.params["new_days"]
        # Started or not, Kodi's item or the add-on's: no lastplayed rule
        for started in (
            {"Property(WatchedEpisodes)": "0"},
            {"Property(WatchedEpisodes)": "0", "Property(InProgressEpisodes)": "1"},
            {"Property(WatchedEpisodes)": "0", "LastPlayed": "27/10/2026"},
        ):
            self.assertEqual(self.prop("new", **show | started), "true")
        season = show | {"DBType": "season", "TvShowDBID": "7", "Season": "3"}
        self.assertEqual(self.prop("new", **season), "")  # a show-only property
        self.episodes = []  # the library lost them since the item was listed
        self.assertEqual(self.prop("new", **show), "")
        self.assertEqual((len(self.calls), self.shows), (8, []))

    def test_new_by_air_date(self):
        show = {"DBType": "tvshow", "DBID": "7", "Property(UnwatchedEpisodes)": "4"}
        show["Property(WatchedEpisodes)"] = "9"
        episodes = self.episodes
        # Long aired, added (and half watched) this week: never new
        self.episodes = [ep | {"firstaired": aired(4000)} for ep in episodes]
        self.assertEqual(self.prop("new", **show), "")
        self.episodes = [ep | {"firstaired": aired(31)} for ep in episodes]
        self.assertEqual(self.prop("new", **show), "")
        self.episodes = [ep | {"firstaired": ""} for ep in episodes]  # none known
        self.assertEqual(self.prop("new", **show), "")
        self.episodes[2] = episodes[2] | {"firstaired": aired(-7)}  # a pre-release
        self.assertEqual(self.prop("new", **show), "true")
        # Only a special aired lately: new, and its next is still S02E10
        self.episodes = [ep | {"firstaired": aired(400)} for ep in episodes]
        self.episodes[0] = episodes[0]
        properties = self.prop_all(**show)
        self.assertEqual(
            (properties["next_episode"], properties["new"]), ("S02E10", "true")
        )
        self.assertEqual((len(self.calls), self.shows), (5, []))

    def test_new_abbott(self):
        # 6x01 part-watched (no play count: still in the unwatched call), 6x02 not
        # started, both aired lately; Kodi's show lastplayed is 6x01's part-play
        self.episodes = [
            {"season": 6, "episode": 1, "firstaired": aired(17), "runtime": 1320},
            {"season": 6, "episode": 2, "firstaired": aired(10), "runtime": 1320},
        ]
        show = {"DBType": "tvshow", "DBID": "7", "Property(UnwatchedEpisodes)": "2"}
        show |= {"Property(WatchedEpisodes)": "95", "Property(InProgressEpisodes)": "1"}
        properties = self.prop_all(**show)
        self.assertEqual(
            (properties["next_episode"], properties["new"]), ("S06E01", "true")
        )
        started = {"DBType": "episode", "DBID": "601", "PercentPlayed": "40"}
        self.assertNotIn("new", self.prop_all(**started | {"Duration(secs)": "1320"}))
        self.episode_aired = aired(10)
        self.assertEqual(self.prop("new", DBType="episode", DBID="602"), "true")
        self.assertEqual((self.episode_ids, self.shows), ([602], []))

    def test_new_film(self):
        film = {"DBType": "movie", "DBID": "12"}
        self.assertEqual(self.prop("new", **film), "true")  # added 5 days ago
        self.handler.params["new_days"] = "4"
        self.assertEqual(self.prop("new", **film), "")
        del self.handler.params["new_days"]
        self.film_added = None
        self.assertEqual(self.prop("new", **film), "")
        self.film_added = ""  # no dateadded
        self.assertEqual(self.prop("new", **film), "")
        self.assertEqual(self.films, [12] * 4)
        self.assertEqual(self.fields, [["dateadded"]] * 4)  # a film: still added
        for labels in (
            film | {"PercentPlayed": "30"},  # started
            film | {"DBID": ""},  # a plugin's film
            film | {"DBType": "musicvideo"},
        ):
            self.assertNotIn("new", self.prop_all(**labels))
        self.watched = True
        self.assertNotIn("new", self.prop_all(**film))
        self.watched = False
        self.alive = iter([True, True, False]).__next__  # focus left after the move
        self.assertNotIn("new", self.prop_all(**film))
        self.assertEqual((self.films, self.calls, self.shows), ([12] * 4, [], []))
        self.assertEqual(self.episode_ids, [])

    def test_new_episode(self):
        episode = {"DBType": "episode", "DBID": "301"}
        self.assertEqual(self.prop("new", **episode), "true")  # aired 2 days ago
        self.handler.params["new_days"] = "1"
        self.assertEqual(self.prop("new", **episode), "")
        del self.handler.params["new_days"]
        for days, new in ((30, "true"), (31, ""), (-3, "true"), (4000, "")):
            self.episode_aired = aired(days)  # -3: a pre-release file; 4000: GoT
            self.assertEqual(self.prop("new", **episode), new)
        self.episode_aired = None
        self.assertEqual(self.prop("new", **episode), "")
        self.episode_aired = ""  # not aired yet, or the scraper had no date
        self.assertEqual(self.prop("new", **episode), "")
        self.assertEqual(self.episode_ids, [301] * 8)
        self.assertEqual(self.fields, [["firstaired"]] * 8)
        for labels in (
            episode | {"PercentPlayed": "30", "Duration(secs)": "2700"},  # started
            episode | {"DBID": ""},  # a plugin's episode
        ):
            self.assertNotIn("new", self.prop_all(**labels))
        self.watched = True
        self.assertNotIn("new", self.prop_all(**episode))
        self.watched = False
        self.alive = iter([True, True, False]).__next__  # focus left after the move
        self.assertNotIn("new", self.prop_all(**episode))
        self.alive = iter([True, True, True]).__next__  # one check before the call
        self.episode_aired = aired(2)
        self.assertEqual(self.prop("new", **episode), "true")
        self.assertEqual(self.episode_ids, [301] * 9)
        self.assertEqual((self.films, self.calls, self.shows), ([], [], []))

    def test_focus_lost(self):
        show = {"DBType": "tvshow", "DBID": "7", "Property(UnwatchedEpisodes)": "4"}
        show["Property(WatchedEpisodes)"] = "9"
        moved = mock.Mock()
        for checks in (
            [True, False],  # before the move
            [True, True, False],  # after it
        ):
            self.alive = iter(checks).__next__
            with mock.patch.object(helpers.ProgressBarManager, "update", moved):
                properties = self.prop_all(**show)
            shown = {key: value for key, value in properties.items() if value}
            self.assertEqual(shown, {"unwatchedepisodes": "4"})  # a show: time_left ""
            self.assertEqual(self.calls, [])
        self.alive = iter([True, True, True]).__next__  # no check after the move's
        self.assertEqual(self.prop("new", **show), "true")
        self.assertEqual((len(self.calls), self.shows, moved.call_count), (1, [], 1))

    def test_next_air(self):
        cached, asks = {}, []

        def tmdb(**kwargs):
            asks.append(kwargs)
            return cached.get("item")

        self.handler._get_tmdb_item = tmdb
        show = {"DBType": "tvshow", "DBID": "7", "Property(WatchedEpisodes)": "9"}
        show["Property(UnwatchedEpisodes)"] = "0"  # fully watched: no episode query
        self.assertEqual(self.prop("next_air", **show), "")  # not cached
        cached["item"] = {"properties": {}}  # ended, or between seasons
        self.assertEqual(self.prop("next_air", **show), "")
        for days, shown in ((23, True), (0, True), (-1, False)):
            day = date.today() + timedelta(days=days)
            cached["item"]["properties"]["tmdb_next_air_date"] = day.isoformat()
            expected = day.strftime("%d %b") if shown else ""
            self.assertEqual(self.prop("next_air", **show), expected)
        self.handler.params["date_format"] = "%A %d %B"
        self.assertEqual(self.prop("next_air", **show), "")  # still yesterday
        day = date.today() + timedelta(days=2)
        cached["item"]["properties"]["tmdb_next_air_date"] = day.isoformat()
        self.assertEqual(self.prop("next_air", **show), day.strftime("%A %d %B"))
        self.assertEqual(asks[0], {"append_artwork": False, "cache_only": True})
        for labels in (
            show | {"DBType": dbtype} for dbtype in ("season", "episode", "movie")
        ):
            self.labels = labels
            (item,) = self.handler.progressbar()
            self.assertNotIn("next_air", item["properties"])
        self.assertEqual((self.calls, len(asks)), ([], 7))
        # Unstarted (an ended show never begun too) and started shows: no lookup
        for watched, left in (("0", "10"), ("9", "1")):
            counts = {"Property(WatchedEpisodes)": watched}
            counts["Property(UnwatchedEpisodes)"] = left
            self.assertNotIn("next_air", self.prop_all(**show | counts))
        self.assertEqual(len(asks), 7)


if __name__ == "__main__":
    unittest.main()
