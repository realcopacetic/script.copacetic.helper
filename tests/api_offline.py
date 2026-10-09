"""
Offline checks for the web API layer: apis/http.py, the api_cache table,
apis/listenbrainz.py (TTLs, stale-on-failure, rate limit), top_songs and the
TMDb client and cache (apis/tmdb).

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
from pathlib import Path
from unittest import mock
from urllib.error import HTTPError, URLError

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
LOG = install_stubs(HELPER, HELPER, STAGE, STAGE, verbose=False)
for name in ("xbmc", "xbmcgui", "xbmcplugin"):  # handlers need more than builders
    sys.modules[name].__getattr__ = lambda attr: type(attr, (), {})
sys.modules["xbmcvfs"].mkdirs = lambda path: Path(path).mkdir(exist_ok=True) or 1
sys.path.insert(0, str(HELPER))

from resources.lib.apis import http, listenbrainz  # noqa: E402
from resources.lib.apis.tmdb import transform  # noqa: E402
from resources.lib.apis.tmdb.context import resolve_tmdb_context  # noqa: E402
from resources.lib.plugin import handlers  # noqa: E402
from resources.lib.plugin.music import (  # noqa: E402
    compact_count,
    rank_albums,
    rank_songs,
    title_key,
)
from resources.lib.script import actions  # noqa: E402
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


class Base(unittest.TestCase):
    def setUp(self):
        self.now = 1_800_000_000.0
        time.time = lambda: self.now
        self.net = http.urlopen = Net()
        self.cache = ApiCacheHandler()
        self.cache.clear_all()
        sys.modules["xbmcgui"].Window().clearProperty(listenbrainz.NEXT_CALL)
        listenbrainz.Monitor = lambda: self  # waitForAbort: the clock moves on
        self.settings = {"listenbrainz_token": " lb-token "}
        listenbrainz.ADDON.getSetting = lambda key: self.settings.get(key, "")

    def row(self, mbid=GORILLAZ, key="listenbrainz:top:"):
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

    def test_token_wanted_negative_week(self):
        self.net.answers = [http_error(401)]
        self.assertEqual(listenbrainz.top_recordings(GORILLAZ), [])
        self.assertEqual(self.row(), (None, 7 * DAY))

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
        self.assertEqual(self.row(key="listenbrainz:albums:"), (albums, 14 * DAY))
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
        self.assertIsNone(self.cache.get(f"listenbrainz:top:{GORILLAZ}"))

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

        sys.modules["xbmc"].executeJSONRPC = rpc
        handlers.set_plugincontent = lambda **kwargs: None
        handlers.library_item = lambda row, type: row["title"]
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
        self.settings = {"tmdb_access_token": "v3key"}
        http.ADDON.getSetting = lambda key: self.settings.get(key, "")

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

        sys.modules["xbmc"].executeJSONRPC = rpc
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

    def test_refused_token_warns(self):
        warnings = LOG["WARNING"]
        self.net.answers = [http_error(401)]
        self.assertEqual(transform.tmdb_to_canonical("tvshow", 1399), {})
        self.assertEqual(LOG["WARNING"], warnings + 1)


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

        sys.modules["xbmc"].executeJSONRPC = rpc
        handlers.set_plugincontent = lambda **kwargs: None
        handlers.library_item = lambda row, type: row["albumid"]
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

        sys.modules["xbmc"].executeJSONRPC = rpc
        handlers.set_items = lambda items: items
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


if __name__ == "__main__":
    unittest.main()
