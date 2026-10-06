"""
Offline checks for the web API layer: apis/http.py, the api_cache table,
apis/listenbrainz.py (TTLs, stale-on-failure, rate limit), top_songs and the
TMDb client and cache (apis/tmdb).

Network calls are replaced by a recorded ListenBrainz answer
(tests/fixtures/listenbrainz_top_recordings.json, fetched 7 Oct 2026), a TMDb
/tv/{id} answer in TMDb's shape (tests/fixtures/tmdb_tv_1399.json, hand-written:
no token here) or by the failure under test. Run from the helper root:
python tests/api_offline.py
"""

import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
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
from resources.lib.plugin.music import rank_songs, title_key  # noqa: E402
from resources.lib.shared.sqlite import ApiCacheHandler  # noqa: E402

FIXTURE = (
    HELPER / "tests" / "fixtures" / "listenbrainz_top_recordings.json"
).read_bytes()
TMDB_TV = (HELPER / "tests" / "fixtures" / "tmdb_tv_1399.json").read_bytes()
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
        listenbrainz.ADDON.getSettingBool = lambda key: key == "listenbrainz_access"

    def row(self, mbid=GORILLAZ):
        """The api_cache row for mbid: (payload, seconds left)."""
        row = self.cache._get_one("key = ?", (f"listenbrainz:top:{mbid}",))
        return (
            row["payload"] and json.loads(row["payload"]),
            row["expires_at"] - self.now,
        )

    def tick(self, seconds):
        self.now += seconds


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
        self.assertTrue(self.net.requests[0].full_url.endswith(GORILLAZ))
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

    def test_one_request_a_second_across_calls(self):
        self.net.answers = [FIXTURE, FIXTURE]
        listenbrainz.top_recordings(GORILLAZ)
        self.tick(0.5)
        self.assertEqual(listenbrainz.top_recordings("other-artist"), [])
        self.assertEqual(len(self.net.requests), 1)
        self.assertIsNone(self.cache.get("listenbrainz:top:other-artist"))
        self.tick(0.5)
        self.assertTrue(listenbrainz.top_recordings("other-artist"))
        self.assertEqual(len(self.net.requests), 2)

    def test_429_waits_reset_in(self):
        self.net.answers = [http_error(429, {"X-RateLimit-Reset-In": "30"}), FIXTURE]
        self.assertEqual(listenbrainz.top_recordings(GORILLAZ), [])
        self.assertEqual(self.row(), (None, 30))
        self.tick(29)
        self.assertEqual(listenbrainz.top_recordings("other-artist"), [])
        self.assertEqual(len(self.net.requests), 1)
        self.tick(1)
        self.assertTrue(listenbrainz.top_recordings(GORILLAZ))

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
        listenbrainz.ADDON.getSettingBool = lambda key: False
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
        self.settings = {"tmdb_access": "true", "tmdb_access_token": "v3key"}
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

    def test_refused_token_warns(self):
        warnings = LOG["WARNING"]
        self.net.answers = [http_error(401)]
        self.assertEqual(transform.tmdb_to_canonical("tvshow", 1399), {})
        self.assertEqual(LOG["WARNING"], warnings + 1)


if __name__ == "__main__":
    unittest.main()
