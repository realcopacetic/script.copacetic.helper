"""
Offline checks for the web API layer: apis/http.py, the api_cache table,
apis/cache.py and apis/listenbrainz.py (TTLs, stale-on-failure, rate limit),
apis/deezer.py (artist match, TTLs, Deezer's error answers, its chart),
apis/theintrodb.py (the ids tried in turn, best segment, TTLs, clearing),
apis/lrclib.py (the search fallback's nearest hit, payload shapes, TTLs, clearing),
the blended ranking of top_songs and discography, music info's popularity words
(popularity_label), the TMDb client and cache (apis/tmdb), and the plugin URL parser
(shared/parser.py) with a focus guard cut at a "|".

Network calls are replaced by recorded ListenBrainz answers
(tests/fixtures/listenbrainz_*.json, Gorillaz, fetched Oct 2026), recorded Deezer
answers (tests/fixtures/deezer_*.json, Queens of the Stone Age, fetched from a
browser on 10 Nov 2026 and trimmed to the fields the helper reads), Deezer's chart
shape (hand-written from its live answer, 14 Nov 2026), a TMDb /tv/{id} answer in TMDb's shape
(tests/fixtures/tmdb_tv_1399.json, hand-written: no token here), Deezer's error
shape (hand-written), TheIntroDB's v4 /media shape (hand-written from its npm
client's docs), recorded LRCLIB answers (tests/fixtures/lrclib_*.json, Feel Good
Inc., fetched 16 Nov 2026, trimmed to the fields the helper reads and four lines
of lyrics) or the failure under test. Run from the helper root:
python tests/api_offline.py
"""

import io
import json
import sys
import tempfile
import time
import unittest
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock
from http.client import IncompleteRead
from urllib.error import HTTPError, URLError

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
LOG = install_stubs(HELPER, STAGE, STAGE, verbose=False)
vars(sys.modules["xbmc"]).update(  # imported names; a test that calls one patches it
    Monitor=None,
    getCacheThumbName=None,
    getLocalizedString=None,
    AudioStreamDetail=None,
    SubtitleStreamDetail=None,
    VideoStreamDetail=None,
)
sys.modules["xbmcplugin"].SORT_METHOD_LASTPLAYED = 0
sys.modules["xbmcvfs"].mkdirs = lambda path: Path(path).mkdir(exist_ok=True) or 1
sys.path.insert(0, str(HELPER))

from resources.lib.apis import (
    cache,
    deezer,
    http,
    listenbrainz,
    lrclib,
    theintrodb,
)  # noqa: E402
from resources.lib.apis.tmdb import transform  # noqa: E402
from resources.lib.apis.tmdb.context import resolve_tmdb_context  # noqa: E402
from resources.lib.apis.tmdb.fields import filter_tmdb_images_by_size  # noqa: E402
from resources.lib.plugin import handlers, helpers  # noqa: E402
from resources.lib.plugin.music import (  # noqa: E402
    ALBUM_RANK_PROPERTIES,
    PLACES,
    POPULAR,
    deezer_match,
    fused,
    library_item,
    play_place,
    rank_albums,
    rank_songs,
    song_place,
    song_play_place,
    title_key,
)
from resources.lib.plugin.setter import apply_musicinfotag  # noqa: E402
from resources.lib.script import actions, library  # noqa: E402
from resources.lib.shared.parser import parse_plugin_argv  # noqa: E402
from resources.lib.shared.sqlite import ApiCacheHandler  # noqa: E402
from resources.lib.shared.text import fit_lines  # noqa: E402

FIXTURES = HELPER / "tests" / "fixtures"
FIXTURE = (FIXTURES / "listenbrainz_top_recordings.json").read_bytes()
TMDB_TV = (FIXTURES / "tmdb_tv_1399.json").read_bytes()
NEWS = ("new_episode", "next_air", "next_air_episode", "show_status")  # _show_news
DEEZER_SEARCH = (FIXTURES / "deezer_search_qotsa.json").read_bytes()
DEEZER_TOP = (FIXTURES / "deezer_top_1177.json").read_bytes()
DEEZER_QUOTA = (
    b'{"error":{"type":"Exception","message":"Quota limit exceeded","code":4}}'
)
DEEZER_NO_DATA = b'{"error":{"type":"DataException","message":"no data","code":800}}'
GORILLAZ = "e21857d5-3256-4547-afb3-4b6ded592596"
QOTSA = "7dc8f5bd-9d0b-4087-9f73-dc164950bbd8"
DAY = 86400


def song(songid, title, year, playcount=0, mbid="", album="", albumid=0):
    """A library song row as AudioLibrary.GetSongs returns it (fields used here)."""
    return {
        "songid": songid,
        "title": title,
        "year": year,
        "playcount": playcount,
        "musicbrainztrackid": mbid,
        "album": album,
        "albumid": albumid,
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
        self.answers, self.requests, self.timeouts = [], [], []

    def __call__(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        response = io.BytesIO(answer)
        response.status = 200
        return response


def http_error(code, headers=None, body=b""):
    """An HTTPError as urllib raises it."""
    url = "https://api.listenbrainz.org/x"
    return HTTPError(url, code, "", headers or {}, io.BytesIO(body))


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
        self.settings = {"listenbrainz_token": " lb-token ", "deezer": False}
        patch(
            self,
            (time, "time", lambda: self.now),
            (http, "urlopen", self.net),
            (cache, "Monitor", lambda: self),  # waitForAbort: the clock moves on
            (listenbrainz.ADDON, "getSetting", lambda key: self.settings.get(key, "")),
            (listenbrainz.ADDON, "getSettingBool", lambda key: self.settings.get(key)),
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
            IncompleteRead(b"{"),
        ]
        for status, wait in ((429, 7), (None, 0), (None, 0), (None, 0), (None, 0)):
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

    def test_expire_held_leaves_a_newer_answer_fresh(self):
        mine, newer = {"songs": [1], "name": "Forró"}, {"songs": [2]}
        self.cache.put("library:mix:v2:Rock_", mine, 60)
        self.cache.put("library:mix:v2:Rocks", mine, 60)  # a LIKE "_" would catch it
        self.assertTrue(self.cache.expire_held("library:mix:v2:Rock_", mine))
        self.assertEqual(self.cache.get("library:mix:v2:Rock_"), (mine, False))
        self.assertEqual(self.cache.get("library:mix:v2:Rocks"), (mine, True))
        self.cache.put("library:mix:v2:Rock_", newer, 60)  # a rail redrew meanwhile
        self.assertFalse(self.cache.expire_held("library:mix:v2:Rock_", mine))
        self.assertEqual(self.cache.get("library:mix:v2:Rock_"), (newer, True))

    def test_cache_only_serves_stale_and_fetches_nothing(self):
        self.net.answers = [FIXTURE]
        top = listenbrainz.top_recordings(GORILLAZ)
        self.tick(15 * DAY)  # stale
        with cache.cache_only():
            self.assertEqual(listenbrainz.top_recordings(GORILLAZ), top)
            self.assertEqual(listenbrainz.top_recordings(QOTSA), [])  # not fetched
        self.assertEqual(len(self.net.requests), 1)
        self.assertFalse(cache._offline)  # released

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
        self.net.answers = [FIXTURE, FIXTURE, FIXTURE]
        start = self.now
        listenbrainz.top_recordings(GORILLAZ)
        self.assertTrue(listenbrainz.top_recordings("third-artist"))
        self.assertTrue(listenbrainz.top_recordings("other-artist"))
        self.assertEqual(len(self.net.requests), 3)
        self.assertEqual(self.now - start, 2)

    def test_queued_call_takes_what_another_stored(self):
        window = sys.modules["xbmcgui"].Window()
        window.setProperty(listenbrainz.NEXT_CALL, f"{self.now + 1}")
        top = [["mbid", "Feel Good Inc."]]
        key = f"listenbrainz:top-recordings:{GORILLAZ}"
        patch(self, (self, "tick", lambda s: self.cache.put(key, top, 14 * DAY)))
        self.assertEqual(listenbrainz.top_recordings(GORILLAZ), top)
        self.assertEqual(self.net.requests, [])

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
        ranked = [row["songid"] for row in rank_songs([(1, self.recordings)], SONGS)]
        # MBID beats the earlier demo; earliest dated Clint Eastwood; one per title;
        # topped up with played songs (10), unplayed Re-Hash left out
        self.assertEqual(ranked, [2, 5, 7, 8, 9, 10])

    def test_no_match_no_list(self):
        self.assertEqual(rank_songs([(1, [["x", "Unknown"]])], SONGS), [])
        self.assertEqual(rank_songs([], SONGS), [])


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
            "type": "Group",
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
                        "artist_type": "Group",
                        "artist_yearsactive": "1990s / 2000s",
                    },
                ),
                ({},),
            ],
        )

    def test_album_artist_as_kodi_shows_it(self):
        self.assertIn("displayartist", ALBUM_RANK_PROPERTIES)  # what album rows fetch
        li = mock.Mock()
        row = {"albumid": 3, "displayartist": "JAY-Z & Kanye West", "title": "WTT"}
        apply_musicinfotag(li, row, "album")
        tag = li.getMusicInfoTag.return_value
        tag.setArtist.assert_called_once_with("JAY-Z & Kanye West")


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
                            "artistdetails": {
                                "artist": "Gorillaz",
                                "musicbrainzartistid": self.artist_mbids,
                            }
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
        self.assertNotIn("Year", item)  # nothing reads it: not mapped
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

    def test_small_and_odd_images_left_out(self):
        self.net.answers = [TMDB_TV]
        art = transform.tmdb_to_canonical("tvshow", 1399)["art"]
        self.assertTrue(art["landscape"].endswith("/b2.jpg"))
        self.assertTrue(art["keyart"].endswith("/p2.jpg"))
        # The main backdrop and poster are list images too small to keep (b3, p3), so
        # b1 and p1 lead; the 1280x720, 1920x1088 and 680x1000 uploads are out
        self.assertTrue(art["fanart"].endswith("/b1.jpg"))
        self.assertTrue(art["poster"].endswith("/p1.jpg"))
        self.assertNotIn("fanart1", art)
        self.assertNotIn("keyart1", art)  # 680x1000 dropped
        # A main poster outside the lists (a third language) stays first
        tv = json.loads(TMDB_TV)
        tv["id"], tv["poster_path"] = 1400, "/ko_poster.jpg"
        self.net.answers = [json.dumps(tv).encode()]
        art = transform.tmdb_to_canonical("tvshow", 1400)["art"]
        self.assertTrue(art["poster"].endswith("/ko_poster.jpg"))
        self.assertTrue(art["poster1"].endswith("/p1.jpg"))
        sizes = [(3840, 2160), (2560, 1440), (3200, 1800), (1920, 1088), (1280, 720)]
        images = [{"width": w, "height": h} for w, h in sizes] + [{"file_path": "/x"}]
        self.assertEqual(
            [
                (i["width"], i["height"])
                for i in filter_tmdb_images_by_size(images, (1920, 1080))
            ],
            sizes[:3],
        )

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

    def test_cache_only_prefers_a_stale_art_entry(self):
        self.cache.put("tmdb:tvshow:1399:en-US|noart", {"Title": "older"}, DAY)
        self.cache.put("tmdb:tvshow:1399:en-US", {"Title": "renewed"}, DAY)
        self.tick(2 * DAY)
        no_art = dict(append_artwork=False, cache_only=True)
        item = transform.tmdb_to_canonical("tvshow", 1399, **no_art)
        self.assertEqual(item, {"Title": "renewed"})

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
        # The stale art entry is kept in its place for the wait
        self.assertEqual(self.tmdb_row("tmdb:tvshow:1399:en-US|noart"), (item, 300))
        self.assertEqual(transform.tmdb_to_canonical("tvshow", 1399, **no_art), item)
        self.assertEqual(len(self.net.requests), 2)  # no retry inside the 5 minutes

    def test_failed_fetch_prefers_a_stale_art_entry(self):
        self.cache.put("tmdb:tvshow:1399:en-US|noart", {"Title": "older"}, DAY)
        self.cache.put("tmdb:tvshow:1399:en-US", {"Title": "renewed"}, DAY)
        self.tick(2 * DAY)
        self.net.answers = [TimeoutError()]
        for _ in range(2):  # the second read, inside the wait, serves the same
            item = transform.tmdb_to_canonical("tvshow", 1399, append_artwork=False)
            self.assertEqual(item, {"Title": "renewed"})
        self.assertEqual(len(self.net.requests), 1)

    def test_next_air_reads_the_cache_only(self):
        day = date.today() + timedelta(days=30)
        next_ep = {"air_date": str(day), "episode_number": 1, "season_number": 3}
        last_ep = {"air_date": "2024-01-01", "episode_number": 8, "season_number": 2}
        tv = json.loads(TMDB_TV) | {
            "next_episode_to_air": next_ep,
            "last_episode_to_air": last_ep,
            "status": "Returning Series",
        }
        handler = object.__new__(handlers.PluginHandlers)
        handler.params, handler.dbtype = {}, ""
        handler.target_item = "Container(50).ListItem"
        labels = {"DBType": "tvshow", "DBID": "7", "UniqueID(tmdb)": "1399"}
        label = lambda path: labels.get(path.rpartition("ListItem.")[2], "")
        with (
            mock.patch("resources.lib.apis.tmdb.context.infolabel", label),
            mock.patch.object(handlers, "getLocalizedString", "#{}".format),
        ):
            empty = dict.fromkeys(NEWS, "")
            self.assertEqual(handler._show_news(7), empty)  # nothing cached: no request
            self.assertEqual(self.net.requests, [])
            self.net.answers = [json.dumps(tv).encode()]  # the metadata serve's fetch
            item = transform.tmdb_to_canonical("tvshow", 1399, append_artwork=False)
            last = {"tmdb_last_air_season": "2", "tmdb_last_air_episode": "8"}
            self.assertLessEqual(last.items(), item["properties"].items())
            self.tick(8 * DAY)  # stale, still served
            when = f"{day:%d} #{50 + day.month}"  # Kodi's short month: 51 is Jan
            shown = empty | {
                "next_air": when,
                "next_air_episode": "3x01",
                "show_status": "returning",
            }
            # 0, a plugin's show: its episodes aren't looked up
            self.assertEqual(handler._show_news(0), shown)
        self.assertEqual(len(self.net.requests), 1)

    def test_next_air_off_looks_nothing_up(self):
        self.settings = {}  # no TMDb token
        handler = object.__new__(handlers.PluginHandlers)
        handler.params, handler.target_item = {}, "Container(50).ListItem"
        labels = {"DBType": "tvshow", "DBID": "7"}  # no UniqueID(tmdb): a TVDB show
        label = lambda path: labels.get(path.rpartition("ListItem.")[2], "")
        rpc = mock.Mock(return_value="{}")
        empty = dict.fromkeys(NEWS, "")
        with (
            mock.patch("resources.lib.apis.tmdb.context.infolabel", label),
            mock.patch.object(sys.modules["xbmc"], "executeJSONRPC", rpc, create=True),
        ):
            self.assertEqual(handler._show_news(7), empty)
            rpc.assert_not_called()  # no uniqueid lookup
            self.settings = {"tmdb_access_token": "v3key"}  # on: looks the id up
            self.assertEqual(handler._show_news(7), empty)  # no cache: still empty
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
        handler.dialog = False
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
            (item,) = handler.metadata()  # a plot only TMDb has: skips the probe
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
        self.assertEqual(probes, [True, False, True, False, True, False, False, True])

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
            probed = handler._probe_text("truncate_label_id")
            for use_probe, expected in ((True, "Probe"), (False, "Merged")):
                data = {}
                handler._apply_truncated_label(
                    data,
                    target="ListItem",
                    default_text="Merged",
                    probe=use_probe,
                    probed=probed,
                )
                self.assertEqual(data["properties"]["truncated_label"], expected)

    def test_truncated_title(self):
        handler = object.__new__(handlers.PluginHandlers)
        handler.params = {
            "truncate_title_font": "title_identity",
            "truncate_title_id": "6036",
            "truncate_title_width": "20",
        }
        lines = {"Fits on one": ["Fits on one"], "Two. Long": ["Two.", "Long"]}
        clamp = lambda text, **kwargs: "[CR]".join(lines.get(text, ["Cut..."]))
        for title, expected in (
            ("Fits on one", None),
            ("Two. Long", None),
            ("Stop! A title far too long", "Cut..."),
        ):
            data = {}
            with mock.patch.object(handlers, "clamp_text", clamp):
                handler._apply_truncated_title(data, title)
            self.assertEqual(
                data.get("properties", {}).get("truncated_title"), expected
            )
        data, handler.params = {}, {}  # a view with no title params: no read
        self.assertEqual(handler._probe_text("truncate_title_id"), "")
        handler._apply_truncated_title(data, "")
        self.assertEqual(data, {})
        for width in ("0", None):  # width 0 or absent turns it off, a title or not
            handler.params = {"truncate_title_width": width} if width else {}
            handler._apply_truncated_title(data, "Stop! A title far too long")
            self.assertEqual(data, {})

    def test_metadata_reads_probes_before_tmdb(self):
        handler = object.__new__(handlers.PluginHandlers)
        handler.params = {
            "enrich_with_tmdb": "true",
            "truncate_font": "description_l",
            "truncate_label_id": "6009",
            "truncate_title_font": "title_identity",
            "truncate_title_id": "6036",
            "truncate_title_width": "20",
            "truncate_width": "20",
        }
        handler.item, handler.dbtype, handler.dbid = False, "movie", "7"
        handler.dialog = False
        handler.target_item = "Container(50).ListItem"
        handler._guard = lambda: mock.Mock(alive=lambda: True)
        shown = {"6009": "This plot", "6036": "This title"}

        def follow_rail(**kwargs):
            shown.update({"6009": "Rail plot", "6036": "Rail title"})

        handler._get_tmdb_item = follow_rail
        probe = lambda path: shown.get(path[17:21], "")
        clamp = lambda text, **kwargs: f"{text}..."
        fetched = mock.Mock()
        fetched.return_value.fetch_data.return_value = {"Plot": "This plot"}
        with mock.patch.object(handlers, "infolabel", probe), mock.patch.object(
            handlers, "clamp_text", clamp
        ), mock.patch.object(handlers, "DataHandler", fetched), mock.patch.object(
            handlers, "set_items", lambda items, **kwargs: items
        ):
            (item,) = handler.metadata()
        self.assertEqual(item["properties"]["truncated_label"], "This plot...")
        self.assertEqual(item["properties"]["truncated_title"], "This title...")

    def test_fit_lines_sentences(self):
        font = mock.Mock(getlength=len)
        text = "Stop! Or my mother will shoot at the whole town"
        self.assertEqual(fit_lines(font, text, 10, 2), ["Stop!"])
        cut = fit_lines(font, text, 10, 2, sentences=False)
        self.assertEqual(cut, ["Stop! Or", "my..."])

    def test_fit_lines_spaceless_line(self):
        font = mock.Mock(getlength=len)
        text = "abcdefghijklmnopqrstuvwxyz"  # cut at a character: no space to back to
        self.assertEqual(fit_lines(font, text, 10, 2), ["abcdefghij", "klmnopq..."])
        self.assertEqual(
            fit_lines(font, "one two three four five six", 10, 2),
            ["one two", "three..."],
        )


def album(albumid, title, year, artistid=(4,)):
    """A library album row as AudioLibrary.GetAlbums returns it (fields used here)."""
    return {"albumid": albumid, "title": title, "year": year, "artistid": [*artistid]}


ALBUM_ROWS = [
    album(1, "Gorillaz", 2001),
    album(2, "Demon Days", 2005),
    album(3, "Demon Days (Deluxe Edition)", 2006),  # its songs are Demon Days' too
    album(4, "Plastic Beach", 2010),
    album(5, "Song Machine, Season One", 2020),  # no song in the fixture
    album(6, "Cracker Island", 2023),
]
# The fixture's 1st, 2nd, 3rd, 4th and 8th recordings, by title (untagged)
ALBUM_SONGS = [
    song(1, "Clint Eastwood", 2001, album="Gorillaz", albumid=1),
    song(2, "Feel Good Inc.", 2005, album="Demon Days", albumid=2),
    song(3, "DARE", 2005, album="Demon Days", albumid=2),
    song(4, "Feel Good Inc.", 2006, album="Demon Days (Deluxe Edition)", albumid=3),
    song(5, "On Melancholy Hill", 2010, album="Plastic Beach", albumid=4),
    song(6, "Rhinestone Eyes", 2010, album="Plastic Beach", albumid=4),
]


class DiscographyTest(Base):
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
                            "artistdetails": {
                                "artist": "Gorillaz",
                                "musicbrainzartistid": [GORILLAZ],
                            }
                        }
                    }
                )
            if method == "AudioLibrary.GetAlbums":
                return json.dumps({"result": {"albums": ALBUM_ROWS}})
            return json.dumps({"result": {"songs": ALBUM_SONGS}})

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
        # Demon Days sums Feel Good Inc. (1st) and DARE (3rd); the deluxe copy gets no
        # credit (one song per title, the earliest); then the unranked newest first
        rows = [
            [row["recording_mbid"], row["recording_name"]]
            for row in json.loads(FIXTURE)
        ]
        ranked = rank_albums([(1, rows)], ALBUM_SONGS, ALBUM_ROWS)
        self.assertEqual([row["albumid"] for row in ranked], [2, 4, 1, 6, 5, 3])

    def test_no_rankings_is_date_order(self):
        self.assertEqual(
            [row["albumid"] for row in rank_albums([], [], ALBUM_ROWS)],
            [6, 5, 4, 3, 2, 1],
        )

    def test_off_is_date_order_without_requests(self):
        self.settings["listenbrainz_token"] = " "
        self.assertEqual(self.handler.discography(), [6, 5, 4, 3, 2, 1])
        self.assertEqual(self.calls, ["AudioLibrary.GetAlbums"])
        self.assertEqual(self.net.requests, [])

    def test_on(self):
        self.net.answers = [FIXTURE]
        self.assertEqual(self.handler.discography(), [2, 4, 1, 6, 5, 3])
        self.assertTrue(
            self.net.requests[0].full_url.endswith(
                f"top-recordings-for-artist/{GORILLAZ}"
            )
        )
        self.assertIsNotNone(self.cache.get(f"listenbrainz:top-recordings:{GORILLAZ}"))

    def test_offline_is_date_order(self):
        self.net.answers = [URLError("offline")]
        self.assertEqual(self.handler.discography(), [6, 5, 4, 3, 2, 1])


def qotsa(songid, title, album, albumid, year, playcount=0):
    """A Queens of the Stone Age library song (untagged, as many libraries are)."""
    return song(songid, title, year, playcount, "", album, albumid)


QOTSA_SONGS = [
    qotsa(1, "No One Knows", "Songs for the Deaf", 2, 2002),
    qotsa(2, "Go With the Flow", "Songs for the Deaf", 2, 2002),
    qotsa(3, "First It Giveth", "Songs for the Deaf", 2, 2002),
    qotsa(4, "The Lost Art of Keeping a Secret", "Rated R", 1, 2000),
    qotsa(5, "Feel Good Hit of the Summer", "Rated R", 1, 2000, 4),
    qotsa(6, "Little Sister", "Lullabies to Paralyze", 3, 2005),
    qotsa(7, "In My Head", "Lullabies to Paralyze", 3, 2005),
    qotsa(8, "Make It Wit Chu", "Era Vulgaris", 4, 2007),
    qotsa(9, "I Sat by the Ocean", "...Like Clockwork", 5, 2013),
    qotsa(10, "If I Had a Tail", "...Like Clockwork", 5, 2013),
    qotsa(11, "Feet Don't Fail Me", "Villains", 6, 2017),
    qotsa(12, "The Way You Used to Do", "Villains", 6, 2017),
    qotsa(13, "Paper Machete", "In Times New Roman...", 7, 2023),
    qotsa(14, "Insignificant Other", "Perfecth", 8, 2026),
    qotsa(15, "Mono", "Perfecth", 8, 2026),
    qotsa(16, "Easy Street", "Perfecth", 8, 2026),
    qotsa(17, "It's Only Love", "Perfecth", 8, 2026, 2),  # not in Deezer's 100
]
QOTSA_ALBUMS = [
    album(1, "Rated R", 2000),
    album(2, "Songs for the Deaf", 2002),
    album(3, "Lullabies to Paralyze", 2005),
    album(4, "Era Vulgaris", 2007),
    album(5, "...Like Clockwork", 2013),
    album(6, "Villains", 2017),
    album(7, "In Times New Roman...", 2023),
    album(8, "Perfecth", 2026),
]
DEEZER_ROWS = [
    ["", row["title_short"], row["album"]["title"]]
    for row in json.loads(DEEZER_TOP)["data"]
]
# ListenBrainz's all-time order for the same songs, hand-made in its answer's shape
QOTSA_LISTENS = json.dumps(
    [
        {"recording_mbid": f"mbid-{n}", "recording_name": title}
        for n, title in enumerate(
            [
                "No One Knows",
                "Go With the Flow",
                "Little Sister",
                "First It Giveth",
                "Make It Wit Chu",
                "In My Head",
                "Feel Good Hit of the Summer",
                "The Lost Art of Keeping a Secret",
            ]
        )
    ]
).encode()


def deezer_top(*tracks):
    """A Deezer top-tracks answer with (title, album title) tracks."""
    data = [
        {"title_short": title, "album": {"title": album}} for title, album in tracks
    ]
    return json.dumps({"data": data}).encode()


def deezer_search(*artists):
    """A Deezer artist search answer with (id, name, fans) artists."""
    data = [{"id": id, "name": name, "nb_fan": fans} for id, name, fans in artists]
    return json.dumps({"data": data}).encode()


def deezer_releases(*releases):
    """A Deezer artist-albums answer with (title, record type) releases."""
    data = [{"title": title, "record_type": kind} for title, kind in releases]
    return json.dumps({"data": data}).encode()


# Jay-Z's library is Watch the Throne alone: none of it in Deezer's top tracks but
# one censored title, from a compilation (Ash's log, 17 Nov; N81)
THRONE = [
    song(n, title, 2011, album="Watch the Throne", albumid=1)
    for n, title in enumerate(
        ["No Church in the Wild", "Lift Off", "Niggas in Paris", "Otis", "New Day"], 1
    )
]
JAYZ_SEARCH = deezer_search((1309, "JAY Z", 3_584_796), (412481021, "JAŸ-Z", 2484))
JAYZ_TOP = deezer_top(
    ("Empire State of Mind", "The Blueprint 3"),
    ("Ni**as in Paris", "Once Upon a Time in 2011"),
    ("99 Problems", "The Black Album"),
)


class BlendTest(unittest.TestCase):
    def test_fused(self):
        scores = fused([(1, "ab"), (1, "cd")])
        self.assertEqual(sorted(scores, key=scores.get, reverse=True)[:2], ["a", "c"])
        both = fused([(1, "ab"), (1, "cb")])
        self.assertEqual(max(both, key=both.get), "b")  # in both beats first in one
        self.assertEqual(fused([(1, "aab")]), fused([(1, "ab")]))  # once, first place

    def test_deezer_order(self):
        ranked = [row["songid"] for row in rank_songs([(1, DEEZER_ROWS)], QOTSA_SONGS)]
        # Deezer's order: two classics, Perfecth, then the rest; It's Only Love isn't
        # in the 100 but is played, so it closes the list
        self.assertEqual(
            ranked, [1, 2, 14, 15, 16, 6, 9, 8, 12, 4, 3, 10, 11, 7, 13, 5, 17]
        )

    def test_blend(self):
        listens = [
            [row["recording_mbid"], row["recording_name"]]
            for row in json.loads(QOTSA_LISTENS)
        ]
        ranked = rank_songs([(1, listens), (1, DEEZER_ROWS)], QOTSA_SONGS)
        # Songs both rank lead; Perfecth follows those, ahead of the rest
        self.assertEqual(
            [row["songid"] for row in ranked],
            [1, 2, 6, 8, 3, 4, 7, 5, 14, 15, 16, 9, 12, 10, 11, 13, 17],
        )

    def test_versions_and_singles(self):
        titles = [title for _, title, _ in DEEZER_ROWS]
        self.assertIn("First It Giveth", titles)  # title_short: no "(Album Version)"
        self.assertEqual(titles.count("Make It Wit Chu"), 2)  # album track and single
        ranked = rank_songs([(1, DEEZER_ROWS)], QOTSA_SONGS)
        self.assertEqual(len(ranked), len({row["songid"] for row in ranked}))

    def test_one_per_title_earliest(self):
        songs = [song(1, "A", 2000), song(2, "A", 2001, 5), song(3, "B", 2000, 1)]
        ranked = rank_songs([(1, [["", "A"]])], songs)
        self.assertEqual([row["songid"] for row in ranked], [1, 3])  # earliest A

    def test_album_credit(self):
        # Songs for the Deaf leads (two classics), Perfecth next (three songs high)
        ranked = rank_albums([(1, DEEZER_ROWS)], QOTSA_SONGS, QOTSA_ALBUMS)
        self.assertEqual([row["albumid"] for row in ranked], [2, 8, 5, 3, 6, 1, 4, 7])
        # a song credits the album standing for its title, as on Top songs
        live = [qotsa(20, "Mono", "Alive", 9, 2027), *QOTSA_SONGS]
        albums = [*QOTSA_ALBUMS, album(9, "Alive", 2027)]
        ranked = rank_albums([(1, [["", "Mono", "Alive"]])], live, albums)
        self.assertEqual(ranked[0]["albumid"], 8)

    def test_same_year_single_yields_to_its_album(self):
        single = qotsa(30, "Mono", "Mono", 10, 2026)  # scanned before the album
        albums = [*QOTSA_ALBUMS, album(10, "Mono", 2026)]
        ranked = rank_albums([(1, [["", "Mono"]])], [single, *QOTSA_SONGS], albums)
        self.assertEqual(ranked[0]["albumid"], 8)
        self.assertEqual(
            rank_songs([(1, [["", "Mono"]])], [single, *QOTSA_SONGS])[0],
            QOTSA_SONGS[14],
        )

    def test_same_year_editions_keep_scan_order(self):
        titles = ["Insignificant Other", "Mono", "Easy Street", "It's Only Love", "X"]
        deluxe = [
            qotsa(40 + n, t, "Perfecth (Deluxe)", 11, 2026)
            for n, t in enumerate(titles)
        ]
        albums = [*QOTSA_ALBUMS, album(11, "Perfecth (Deluxe)", 2026)]
        for songs, first in ((deluxe + QOTSA_SONGS, 11), (QOTSA_SONGS + deluxe, 8)):
            ranked = rank_albums([(1, [["", "Mono"]])], songs, albums)
            self.assertEqual(ranked[0]["albumid"], first)

    def test_singles_count_songs_by_title(self):
        # a remix EP of one title is a single too: the earlier single, scanned first
        single = qotsa(30, "Mono", "Mono", 10, 2025)
        ep = [
            qotsa(50 + n, f"Mono (Remix {n})", "Mono (Remixes)", 12, 2025)
            for n in range(5)
        ]
        albums = [
            *QOTSA_ALBUMS,
            album(10, "Mono", 2025),
            album(12, "Mono (Remixes)", 2025),
        ]
        ranked = rank_albums([(1, [["", "Mono"]])], [single, *ep, *QOTSA_SONGS], albums)
        self.assertEqual(ranked[0]["albumid"], 10)
        # a 4-track maxi-single of three songs yields to its same-year album
        titles = ["Mono", "Mono (Radio Edit)", "Wicked Ways", "Sunday Morning"]
        maxi = [qotsa(60 + n, t, "Mono", 10, 2026) for n, t in enumerate(titles)]
        albums = [*QOTSA_ALBUMS, album(10, "Mono", 2026)]
        ranked = rank_albums([(1, [["", "Mono"]])], [*maxi, *QOTSA_SONGS], albums)
        self.assertEqual(ranked[0]["albumid"], 8)

    def test_hidden_album_leaves_credit_to_a_shown_one(self):
        # a compilation left out of the list doesn't take the title's credit
        guest = qotsa(30, "The Way You Used to Do", "Cracker Island", 9, 2001)
        rows = [["", "The Way You Used to Do"]]
        ranked = rank_albums([(1, rows)], [guest, *QOTSA_SONGS], QOTSA_ALBUMS)
        self.assertEqual(ranked[0]["albumid"], 6)

    def test_artist_match(self):
        def accept(rows, songs=QOTSA_SONGS):
            return deezer_match(songs, rows)

        self.assertTrue(accept(DEEZER_ROWS))
        three = ("Mono", "Sunday", "Easy Street", "No One Knows")
        self.assertTrue(accept([["", title, "x"] for title in three]))
        self.assertFalse(accept([["", "Mono", "x"], ["", "No One Knows", "x"]]))
        # an album in common lowers the bar to one song, never to none
        self.assertTrue(accept([["", "Mono", "Villains"]]))
        self.assertFalse(accept([["", "Other Song", "Villains"]]))
        self.assertTrue(accept([["", "Mono", "x"]], [song(1, "Mono", 2026)]))
        self.assertFalse(accept([["", "!!!", "x"]], [song(1, "!!!", 2026)]))
        # no match: None while the library has too few titles to tell, else False
        self.assertIsNone(accept([["", "Other", "x"]], QOTSA_SONGS[:2]))
        self.assertIs(accept([["", "Other", "x"]]), False)

    def test_censored_titles(self):
        # each * one letter; a censored title counts as a song in common
        rows = [["", "Ni**as in Paris (feat. X)", "Once Upon a Time in 2011"]]
        self.assertEqual(rank_songs([(1, rows)], THRONE)[0]["songid"], 3)
        self.assertIs(deezer_match(THRONE, rows), False)  # one song, no album
        releases = lambda: ["Watch The Throne (Deluxe)"]  # noqa: E731
        self.assertTrue(deezer_match(THRONE, rows, releases))
        # a release gives the album, never the song: not even read with none shared
        self.assertIs(deezer_match(THRONE, [], lambda: 1 / 0), False)
        # one letter per *, stars alone match nothing, two keys fitting match neither
        self.assertEqual(rank_songs([(1, [["", "Ni*as in Paris"]])], THRONE), [])
        self.assertEqual(rank_songs([(1, [["", "****"]])], THRONE[3:4]), [])
        both = [song(1, "Funk You", 2000), song(2, "Fuck You", 2000)]
        self.assertEqual(rank_songs([(1, [["", "F**k You"]])], both), [])
        self.assertEqual(rank_songs([(1, [["", "F**k You"]])], both[1:]), both[1:])

    def test_played_tail_earliest_release(self):
        songs = [
            song(1, "Hit", 2000),
            song(2, "Deep Cut", 2010, 3, "", "Best Of"),
            song(3, "Deep Cut", 0, 3),  # undated: never the earliest
            song(4, "Deep Cut", 2001, 3, "", "Album"),
        ]
        ranked = rank_songs([(1, [["", "Hit"]])], songs)
        self.assertEqual([row["songid"] for row in ranked], [1, 4])

    def test_generic_titles_match_by_mbid_only(self):
        songs = [
            song(1, "Intro", 2000),
            song(2, "Hit", 2000),
            song(3, "Outro", 2000, 0, "m3"),
        ]
        rows = [["", "Intro"], ["", "Hit"], ["m3", "Outro"]]
        ranked = rank_songs([(1, rows)], songs)
        self.assertEqual([row["songid"] for row in ranked], [2, 3])

    def test_tie_by_play_count(self):
        songs = [song(1, "A", 2000, 1), song(2, "B", 2000, 7)]
        both = [(1, [["", "A"], ["", "B"]]), (1, [["", "B"], ["", "A"]])]
        self.assertEqual([row["songid"] for row in rank_songs(both, songs)], [2, 1])


class DeezerTest(Base):
    def setUp(self):
        super().setUp()
        self.settings["deezer"] = True
        self.songs = QOTSA_SONGS

    def accept(self, *args):
        return deezer_match(self.songs, *args)

    def top(self, key=QOTSA):
        return deezer.top_tracks(key, "Queens of the Stone Age", self.accept)

    def deezer_row(self, key):
        return self.row(key, "deezer:")

    def test_first_open_then_cached(self):
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP]
        rows = self.top()
        self.assertEqual(rows, DEEZER_ROWS)
        self.assertEqual(
            [request.full_url for request in self.net.requests],
            [
                "https://api.deezer.com/search/artist?q=Queens+of+the+Stone+Age&limit=10",
                "https://api.deezer.com/artist/1177/top?limit=100",
            ],
        )  # the 0-fan duplicate is never fetched
        match = [1177, 1377516]  # id and fans
        self.assertEqual(self.deezer_row(f"match:{QOTSA}"), (match, 90 * DAY))
        self.assertEqual(self.deezer_row("top:1177"), (rows, 7 * DAY))
        self.assertIsNone(self.net.requests[0].get_header("Authorization"))
        self.tick(6 * DAY)
        self.assertEqual(self.top(), rows)
        self.assertEqual(len(self.net.requests), 2)

    def test_top_refetched_weekly_artist_kept(self):
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP, DEEZER_TOP]
        self.top()
        self.tick(8 * DAY)
        self.assertEqual(self.top(), DEEZER_ROWS)
        self.assertTrue(
            self.net.requests[2].full_url.endswith("artist/1177/top?limit=100")
        )

    def test_no_artist_of_that_name(self):
        self.net.answers = [deezer_search((5, "Queens of the Stone Age Tribute", 9))]
        self.assertEqual(self.top(), [])
        self.assertEqual(self.deezer_row(f"match:{QOTSA}"), (None, 7 * DAY))
        self.assertEqual(self.top(), [])
        self.assertEqual(len(self.net.requests), 1)

    def test_most_followed_rejected_next_taken(self):
        self.net.answers = [
            deezer_search(
                (9, "Queens of the Stone Age", 9_000_000),
                (1177, "Queens of the stone age", 10),
            ),
            deezer_top(("Other Song", "Other Album")),
            DEEZER_TOP,
        ]
        self.assertEqual(self.top(), DEEZER_ROWS)
        self.assertEqual(self.deezer_row(f"match:{QOTSA}")[0], [1177, 10])
        self.assertIsNone(self.cache._get_one("key = ?", ("deezer:top:9",)))
        self.assertEqual(len(self.net.requests), 3)  # the accepted list isn't refetched

    def test_candidate_without_data_skipped(self):
        self.net.answers = [
            deezer_search(
                (9, "Queens of the Stone Age", 9_000_000),
                (1177, "Queens of the Stone Age", 10),
            ),
            DEEZER_NO_DATA,
            DEEZER_TOP,
        ]
        self.assertEqual(self.top(), DEEZER_ROWS)

    def test_down_mid_search_asked_again_soon(self):
        self.net.answers = [DEEZER_SEARCH, URLError("offline")]
        self.assertEqual(self.top(), [])
        self.assertEqual(self.deezer_row(f"match:{QOTSA}"), (None, 300))

    def test_stale_served_while_down(self):
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP]
        self.top()
        self.tick(91 * DAY)
        self.net.answers = [URLError("offline"), URLError("offline")]
        self.assertEqual(self.top(), DEEZER_ROWS)
        self.assertEqual(self.deezer_row(f"match:{QOTSA}"), ([1177, 1377516], 300))
        self.assertEqual(self.deezer_row("top:1177"), (DEEZER_ROWS, 300))

    def test_failure_keeps_what_a_racing_call_stored(self):
        key, match = f"deezer:match:{QOTSA}", [1177, 1377516]

        def fetch():  # a sibling stores its match while this one waits on a 429
            self.cache.put(key, match, 90 * DAY)
            raise http.HttpError(429)

        self.assertEqual(cache.cached(key, fetch, (DAY, DAY)), match)
        self.assertEqual(self.deezer_row(f"match:{QOTSA}"), (match, 90 * DAY))

    def test_failure_stores_its_own_over_a_racing_failure(self):
        key = f"deezer:match:{QOTSA}"

        def fetch():  # a sibling failed first and stored the same empty read
            self.cache.put(key, None, 300)
            raise http.HttpError(429)

        self.assertIsNone(cache.cached(key, fetch, (DAY, DAY)))
        self.assertEqual(self.deezer_row(f"match:{QOTSA}"), (None, 60))  # 429's wait

    def test_quota_answer_is_an_error(self):
        self.net.answers = [DEEZER_QUOTA]
        self.assertEqual(self.top(), [])
        self.assertEqual(self.deezer_row(f"match:{QOTSA}"), (None, 60))

    def test_album_only_candidate_passed_over(self):
        self.net.answers = [
            deezer_search(
                (9, "Queens of the Stone Age", 9_000_000),
                (1177, "Queens of the Stone Age", 10),
            ),
            deezer_top(("Other Song", "Villains")),  # an album in common, no song
            DEEZER_TOP,
        ]
        self.assertEqual(self.top(), DEEZER_ROWS)

    def test_homonym_not_taken_over_many_songs(self):
        other = deezer_top(("Other Song", "Other Album"))
        self.net.answers = [
            deezer_search(
                (9, "Queens of the Stone Age", 9_000_000),
                (5, "Queens of the Stone Age", 10),
            ),
            other,
            other,
        ]
        self.assertEqual(self.top(), [])
        self.assertEqual(self.deezer_row(f"match:{QOTSA}"), (None, 7 * DAY))

    def test_releases_hold_the_library_album(self):
        self.songs = THRONE
        self.net.answers = [
            JAYZ_SEARCH,
            JAYZ_TOP,
            deezer_top(("Other Song", "Other Album")),
            deezer_releases(
                ("The Blueprint 3", "album"), ("Watch The Throne (Deluxe)", "album")
            ),
        ]
        rows = deezer.top_tracks("jayz", "Jay‐Z", self.accept)
        self.assertEqual(rows[1], ["", "Ni**as in Paris", "Once Upon a Time in 2011"])
        self.assertEqual(self.deezer_row("match:jayz"), ([1309, 3_584_796], 90 * DAY))
        self.assertTrue(  # the most followed's releases, once on a miss
            self.net.requests[3].full_url.endswith("artist/1309/albums?limit=100")
        )
        self.assertEqual(len(self.net.requests), 4)  # its top list isn't refetched
        self.assertEqual(self.deezer_row("top:1309"), (rows, 7 * DAY))

    def test_no_title_in_common_no_releases_read(self):
        self.songs = THRONE
        self.net.answers = [
            JAYZ_SEARCH,
            deezer_top(("Empire State of Mind", "The Blueprint 3")),
            deezer_top(("Other Song", "Other Album")),
        ]
        self.assertEqual(deezer.top_tracks("jayz", "Jay‐Z", self.accept), [])
        self.assertEqual(self.deezer_row("match:jayz"), (None, 7 * DAY))
        self.assertEqual(len(self.net.requests), 3)  # no albums request

    def test_namesake_releases_passed_over(self):
        # a small Genesis (debut "Genesis", a song "Home") against the famous one,
        # whose top shares "Home": its self-titled release, a single, a compilation
        # and a release named like a library song never count as an album in common
        songs = ["Home", "Small A", "Small B"]
        for album, release, kind in (
            ("Genesis", "Genesis (Remastered)", "album"),
            ("Genesis", "Genesis [Remastered]", "album"),
            ("Genesis", "Genesis - Live", "album"),
            ("Home", "Home", "album"),
            ("Small A", "Small A", "single"),
            ("Greatest Hits", "Greatest Hits", "compile"),
        ):
            self.cache.clear_all()
            self.songs = [song(n, t, 1990, album=album) for n, t in enumerate(songs)]
            self.net.answers = [
                deezer_search((9, "Genesis", 2_000_000)),
                deezer_top(("Home", "Some Album")),
                deezer_releases((release, kind), ("Invisible Touch", "album")),
            ]
            self.assertEqual(deezer.top_tracks("genesis", "Genesis", self.accept), [])
            self.assertEqual(len(self.net.requests), 3)  # the releases were read
            self.net.requests.clear()
        self.songs[0]["album"] = "Invisible Touch"  # an album of its own still counts
        self.cache.clear_all()
        self.net.answers = [
            deezer_search((9, "Genesis", 2_000_000)),
            deezer_top(("Home", "Some Album")),
            deezer_releases(("Invisible Touch", "album")),
        ]
        self.assertTrue(deezer.top_tracks("genesis", "Genesis", self.accept))

    def test_far_ahead_taken_with_few_songs(self):
        self.songs = QOTSA_SONGS[:2]
        other = deezer_top(("Other Song", "Other Album"))
        self.net.answers = [
            deezer_search(
                (9, "Queens of the Stone Age", 9_000_000),
                (5, "Queens of the Stone Age", 899_999),
            ),
            other,
            other,
        ]
        self.assertEqual(self.top(), [["", "Other Song", "Other Album"]])
        self.assertEqual(self.deezer_row(f"match:{QOTSA}")[0], [9, 9_000_000])
        self.assertEqual(len(self.net.requests), 3)  # its list isn't refetched

    def test_not_far_ahead_none(self):
        self.songs = QOTSA_SONGS[:2]
        other = deezer_top(("Other Song", "Other Album"))
        self.net.answers = [
            deezer_search(
                (9, "Queens of the Stone Age", 9_000_000),
                (5, "Queens of the Stone Age", 900_000),
            ),
            other,
            other,
        ]
        self.assertEqual(self.top(), [])
        self.assertEqual(self.deezer_row(f"match:{QOTSA}"), (None, 7 * DAY))

    def test_only_one_taken_over_token_fans(self):
        self.songs = QOTSA_SONGS[:2]
        for fans, artist in (
            (deezer.FANS + 1, [9, deezer.FANS + 1]),
            (deezer.FANS, None),
        ):
            self.cache.clear_all()
            self.net.answers = [
                deezer_search((9, "Queens of the Stone Age", fans)),
                deezer_top(("Other Song", "Other Album")),
            ]
            self.top()
            self.assertEqual(self.deezer_row(f"match:{QOTSA}")[0], artist)

    def test_far_ahead_without_data_none(self):
        self.songs = QOTSA_SONGS[:2]
        self.net.answers = [
            deezer_search((9, "Queens of the Stone Age", 9_000_000)),
            DEEZER_NO_DATA,
        ]
        self.assertEqual(self.top(), [])
        self.assertEqual(self.deezer_row(f"match:{QOTSA}"), (None, 7 * DAY))

    def test_symbol_only_name_sends_nothing(self):
        self.assertEqual(deezer.top_tracks("", "!!!", self.accept), [])
        self.assertEqual(self.net.requests, [])

    def test_unexpected_answers_retried_soon(self):
        for answer in (
            b'{"data": [{"id": 1177, "name": "Queens of the Stone Age"}]}',  # no fans
            b'{"nodata": []}',
            b"[]",
            b'{"error": "x"}',
        ):
            self.cache.clear_all()
            self.net.answers = [answer]
            self.assertEqual(self.top(), [])
            self.assertEqual(self.deezer_row(f"match:{QOTSA}"), (None, 300))

    def test_null_titles_never_kept(self):
        self.net.answers = [
            DEEZER_SEARCH,
            json.dumps(
                {
                    "data": [
                        {"title_short": None, "album": {"title": "Villains"}},
                        {"title_short": "Mono", "album": {"title": "Perfecth"}},
                        {"title_short": "x" * 50_000, "album": {"title": "Perfecth"}},
                    ]
                }
            ).encode(),
        ]
        self.assertEqual(
            self.top(), [["", "Mono", "Perfecth"], ["", "x" * 500, "Perfecth"]]
        )

    def test_busy_retried_soon(self):
        self.net.answers = [b'{"error":{"type":"Exception","code":700}}']
        self.assertEqual(self.top(), [])
        self.assertEqual(self.deezer_row(f"match:{QOTSA}"), (None, 300))

    def test_untagged_artist_keyed_by_name(self):
        self.assertEqual(
            deezer.artist_key("", "Queens of the Stone Age"), "queensofthestoneage"
        )
        self.assertEqual(deezer.artist_key(QOTSA, "x"), QOTSA)

    def test_patterns(self):
        self.assertEqual(deezer.patterns(QOTSA), [f"deezer:match:{QOTSA}"])
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP]
        self.top()
        self.assertEqual(
            deezer.patterns(QOTSA),
            [f"deezer:match:{QOTSA}", "deezer:top:1177", "deezer:related:1177"],
        )

    def test_refresh_and_clear(self):
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP]
        self.top()
        self.cache.put(f"listenbrainz:top-recordings:{QOTSA}", [], DAY)
        details = {"artist": "Queens of the Stone Age", "musicbrainzartistid": [QOTSA]}
        patch(self, (library, "_details", lambda *args: details))
        patterns = library.api_patterns("artist", 4)
        self.assertEqual(
            patterns,
            [
                f"listenbrainz:%:{QOTSA}",
                f"deezer:match:{QOTSA}",
                "deezer:top:1177",
                "deezer:related:1177",
            ],
        )
        self.assertEqual(self.cache.expire(*patterns), 3)
        self.net.answers = [URLError("offline"), URLError("offline")]
        self.assertEqual(self.top(), DEEZER_ROWS)  # stale is still served offline
        dialog = mock.Mock(**{"return_value.yesno.return_value": True})
        patch(
            self,
            (actions.xbmcgui, "Dialog", dialog),
            (actions.ADDON, "getLocalizedString", lambda id: "%s"),
        )
        actions.clear_api_cache(source="deezer")
        self.assertIsNone(self.cache.get(f"deezer:match:{QOTSA}"))
        self.assertIsNotNone(self.cache.get(f"listenbrainz:top-recordings:{QOTSA}"))


class QotsaRailsTest(Base):
    def setUp(self):
        super().setUp()
        self.calls, self.mbids = [], [QOTSA]

        def rpc(request):
            request = json.loads(request)
            self.calls.append(request["method"])
            if request["method"] == "AudioLibrary.GetArtistDetails":
                details = {
                    "artist": "Queens of the Stone Age",
                    "musicbrainzartistid": self.mbids,
                }
                return json.dumps({"result": {"artistdetails": details}})
            if request["method"] == "AudioLibrary.GetAlbums":
                return json.dumps({"result": {"albums": QOTSA_ALBUMS}})
            return json.dumps({"result": {"songs": QOTSA_SONGS}})

        patch(
            self,
            (sys.modules["xbmc"], "executeJSONRPC", rpc),
            (handlers, "set_plugincontent", lambda **kwargs: None),
            (
                handlers,
                "library_item",
                lambda row, type: row.get("songid") or row["albumid"],
            ),
        )
        self.handler = object.__new__(handlers.PluginHandlers)
        self.handler.params = {"id": "4"}
        self.handler.dbid, self.handler.limit = "4", 5

    def test_deezer_alone(self):
        self.settings.update(listenbrainz_token="", deezer=True)
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP]
        self.assertEqual(self.handler.top_songs(), [1, 2, 14, 15, 16])

    def test_untagged_with_deezer_skips_listenbrainz(self):
        self.settings["deezer"], self.mbids = True, [""]
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP]
        self.assertEqual(self.handler.top_songs(), [1, 2, 14, 15, 16])
        self.assertEqual(len(self.net.requests), 2)
        self.assertIsNotNone(self.cache.get("deezer:match:queensofthestoneage"))

    def test_blend(self):
        self.settings["deezer"] = True
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP, QOTSA_LISTENS]
        # Deezer x4: its #3, the new album's Insignificant Other, passes Make It Wit Chu
        self.assertEqual(self.handler.top_songs(), [1, 2, 6, 14, 8])
        self.assertIn("listenbrainz", self.net.requests[2].full_url)  # Deezer first

    def test_deezer_down_listenbrainz_alone(self):
        self.settings["deezer"] = True
        self.net.answers = [URLError("offline"), QOTSA_LISTENS]
        self.assertEqual(self.handler.top_songs(), [1, 2, 6, 3, 8])

    def test_both_down_hides(self):
        self.settings["deezer"] = True
        self.net.answers = [URLError("offline"), URLError("offline")]
        self.assertIsNone(self.handler.top_songs())

    def test_both_off_sends_nothing(self):
        self.settings["listenbrainz_token"] = ""
        self.assertIsNone(self.handler.top_songs())
        self.assertEqual((self.calls, self.net.requests), ([], []))

    def test_discography_deezer_alone(self):
        self.settings.update(listenbrainz_token="", deezer=True)
        self.handler.limit = None
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP]
        self.assertEqual(self.handler.discography(), [2, 8, 5, 3, 6, 1, 4, 7])

    def test_discography_both(self):
        self.settings["deezer"] = True
        self.handler.limit = None
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP, QOTSA_LISTENS]
        # Deezer's weight lifts Perfecth's three songs over Lullabies
        self.assertEqual(self.handler.discography(), [2, 8, 3, 1, 5, 6, 4, 7])
        self.assertEqual(self.calls.count("AudioLibrary.GetSongs"), 1)
        self.assertIn("top-recordings-for-artist", self.net.requests[2].full_url)

    def test_discography_shares_top_songs_lists(self):
        self.settings["deezer"] = True
        self.handler.limit = None
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP, QOTSA_LISTENS]
        self.handler.top_songs()
        self.assertEqual(self.handler.discography(), [2, 8, 3, 1, 5, 6, 4, 7])
        self.assertEqual(len(self.net.requests), 3)  # both lists cached: no request

    def test_discography_listenbrainz_without_answer_reads_no_songs(self):
        self.handler.limit = None
        self.mbids = [""]  # untagged: nothing to ask
        self.assertEqual(self.handler.discography(), [8, 7, 6, 5, 4, 3, 2, 1])
        self.mbids, self.net.answers = [QOTSA], [b"[]"]  # an empty answer
        self.assertEqual(self.handler.discography(), [8, 7, 6, 5, 4, 3, 2, 1])
        self.assertEqual(len(self.net.requests), 1)
        self.assertNotIn("AudioLibrary.GetSongs", self.calls)

    def test_no_songs_no_request(self):
        self.settings["deezer"] = True
        patch(self, (handlers.PluginHandlers, "_artist_songs", lambda *a: []))
        self.assertIsNone(self.handler.top_songs())
        self.assertEqual(self.net.requests, [])

    def test_untagged_refresh_patterns(self):
        details = {"artist": "Queens of the Stone Age", "musicbrainzartistid": [""]}
        patch(self, (library, "_details", lambda *args: details))
        self.assertEqual(
            library.api_patterns("artist", 4), ["deezer:match:queensofthestoneage"]
        )

    def test_discography_album_artists_only(self):
        self.settings["listenbrainz_token"] = ""
        self.handler.limit = None
        featured = album(9, "Cracker Island", 2023, artistid=(7,))  # a guest spot
        patch(self, (handlers, "library_rows", lambda *a: [*QOTSA_ALBUMS, featured]))
        self.assertNotIn(9, self.handler.discography())  # setting off: hidden
        self.settings["deezer"] = True  # a hidden album's credit takes no place
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP]
        guest = qotsa(30, "The Way You Used to Do", "Cracker Island", 9, 2001)
        songs = [guest, *QOTSA_SONGS]
        patch(self, (handlers.PluginHandlers, "_artist_songs", lambda *a: songs))
        ranked = self.handler.discography()
        self.assertEqual(sorted(ranked), [1, 2, 3, 4, 5, 6, 7, 8])
        patch(self, (handlers, "condition", lambda condition: True))
        self.assertIn(9, self.handler.discography())

    def test_discography_off_is_date_order(self):
        self.settings["listenbrainz_token"] = ""
        self.handler.limit = None
        self.assertEqual(self.handler.discography(), [8, 7, 6, 5, 4, 3, 2, 1])
        self.assertEqual(self.calls, ["AudioLibrary.GetAlbums"])


def deezer_chart(*ids):
    """A Deezer artist chart answer with these artist ids, best first."""
    data = [{"id": id, "name": f"#{n}", "position": n} for n, id in enumerate(ids, 1)]
    return json.dumps({"data": data}).encode()


# popularity_label's strings, as en_gb words them
WORDS = {
    32993: "Your #%d song",
    32994: "Your most played album",
    32995: "Charting",
    32996: "Popular",
    32997: "#%d song",
    32998: "Most popular album",
    32999: "Your #%d artist",
}


class PopularityLabelTest(Base):
    """Music info's word in place of a count (N13: decisions 1 C with B, 2 C; N94 B)."""

    def setUp(self):
        super().setUp()
        self.settings.update(listenbrainz_token="", deezer=True)
        self.calls, self.song, self.compilation = [], QOTSA_SONGS[0], False
        self.songs = QOTSA_SONGS  # Feel Good Hit… (Rated R) on 4 plays, It's Only… on 2
        self.plays = [  # artist 7 leads on 60 plays, a duet counting for both
            {"albumid": 3, "artistid": [7], "playcount": 50},
            {"albumid": 2, "artistid": [4, 7], "playcount": 10},
            {"albumid": 2, "artistid": [4], "playcount": 5},
        ]

        def rpc(request):
            request = json.loads(request)
            method, params = request["method"], request["params"]
            self.calls.append(method)
            if method == "AudioLibrary.GetArtistDetails":
                details = {"artist": "Queens of the Stone Age"}
                details["musicbrainzartistid"] = [QOTSA]
                return json.dumps({"result": {"artistdetails": details}})
            if method == "AudioLibrary.GetAlbumDetails":
                details = {"artistid": [4], "compilation": self.compilation}
                return json.dumps({"result": {"albumdetails": details}})
            if method == "AudioLibrary.GetSongDetails":
                details = {"artistid": [4], "title": self.song["title"]}
                return json.dumps({"result": {"songdetails": details}})
            if method == "AudioLibrary.GetAlbums":
                return json.dumps({"result": {"albums": QOTSA_ALBUMS}})
            if params.get("filter", {}).get("field") == "playcount":
                return json.dumps({"result": {"songs": self.plays}})
            return json.dumps({"result": {"songs": self.songs}})

        patch(
            self,
            (sys.modules["xbmc"], "executeJSONRPC", rpc),
            (handlers, "set_items", lambda items: items),
            (handlers.ADDON, "getLocalizedString", WORDS.get),
        )
        self.handler = object.__new__(handlers.PluginHandlers)

    def label(self, type, dbid):
        """The label popularity_label gives library type dbid; None for no item."""
        self.handler.params = {"info": "popularity_label", "id": f"{dbid}"}
        self.handler.dbtype, self.handler.dbid = type, f"{dbid}"
        items = self.handler.popularity_label()
        if items:  # it says whose word it is, for the skin to match
            whose = {"dbid": f"{dbid}", "dbtype": type}
            self.assertEqual(items[0]["properties"], whose)
        return items and items[0]["label"]

    def urls(self):
        return [
            request.full_url.removeprefix(deezer.API) for request in self.net.requests
        ]

    def test_artist_charting_first(self):
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP, deezer_chart(27, 1177)]
        self.assertEqual(self.label("artist", 4), "Charting")
        self.assertEqual(self.urls()[-1], "chart/0/artists?limit=100")
        self.assertEqual(self.row("artists", "deezer:chart:"), ([27, 1177], DAY))

    def test_artist_popular_off_the_chart(self):
        # 1,377,516 fans in the search answer: over a million
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP, deezer_chart(27)]
        self.assertEqual(self.label("artist", 4), "Popular")

    def test_artist_below_a_million_says_nothing(self):
        fans = POPULAR - 1
        self.net.answers = [
            deezer_search((1177, "Queens of the Stone Age", fans)),
            DEEZER_TOP,
            deezer_chart(27),
        ]
        self.assertIsNone(self.label("artist", 4))
        self.assertEqual(self.row(QOTSA, "deezer:match:")[0], [1177, fans])

    def test_artist_unmatched_asks_no_chart(self):
        self.net.answers = [deezer_search((5, "Queens of the Stone Age Tribute", 9))]
        self.assertIsNone(self.label("artist", 4))
        self.assertEqual(
            self.urls(), ["search/artist?q=Queens+of+the+Stone+Age&limit=10"]
        )

    def test_chart_asked_once_a_day(self):
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP, deezer_chart(1177)]
        self.label("artist", 4)
        self.tick(DAY - 1)
        self.assertEqual(self.label("artist", 4), "Charting")
        self.assertEqual(len(self.net.requests), 3)  # all cached
        self.tick(2)
        self.net.answers = [deezer_chart(27)]  # off the chart today: still popular
        self.assertEqual(self.label("artist", 4), "Popular")
        self.assertEqual(self.urls()[3:], ["chart/0/artists?limit=100"])

    def test_song_place_in_top_songs(self):
        # Deezer alone, Top songs reads 1, 2, 14, 15, 16 (QotsaRailsTest)
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP]
        self.assertEqual(self.label("song", 1), "#1 song")
        self.song = QOTSA_SONGS[13]  # Insignificant Other
        self.assertEqual(self.label("song", 14), "#3 song")
        self.song = QOTSA_SONGS[16]  # It's Only Love: played, not in Deezer's 100
        self.assertIsNone(self.label("song", 17))
        self.assertEqual(len(self.net.requests), 2)  # Top songs' own, then cached

    def test_song_place_within_ten(self):
        rankings = [(1, [["", song["title"]] for song in QOTSA_SONGS])]
        for song in QOTSA_SONGS[:12]:
            place = song_place(rankings, QOTSA_SONGS, song["title"])
            self.assertEqual(place, song["songid"] if song["songid"] <= PLACES else 0)
        self.assertEqual(song_place([], QOTSA_SONGS, "No One Knows"), 0)
        played = [(1, [["", "No One Knows"]])]  # Feel Good Hit…: 4 plays, no score
        self.assertEqual(song_place(played, QOTSA_SONGS, "No One Knows"), 1)
        title = "Feel Good Hit of the Summer"
        self.assertEqual(song_place(played, QOTSA_SONGS, title), 0)

    def test_album_most_popular(self):
        # Deezer alone, Discography reads 2, 8, 5… (QotsaRailsTest)
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP]
        self.assertEqual(self.label("album", 2), "Most popular album")
        self.assertIsNone(self.label("album", 8))
        self.compilation = True  # its first artist is Various Artists
        calls = len(self.calls)
        self.assertIsNone(self.label("album", 2))
        self.assertEqual(self.calls[calls:], ["AudioLibrary.GetAlbumDetails"])

    def test_album_leads_alone_over_another(self):
        self.net.answers = [DEEZER_SEARCH, DEEZER_TOP]
        for credit, shown in (
            ({2: 0.5, 8: 0.2}, "Most popular album"),
            ({2: 0.5, 8: 0.5}, None),  # a tie: Discography's newer first isn't a lead
            ({2: 0.5}, "Most popular album"),  # every top song on it: the rest score 0
            ({}, None),  # nothing credited
        ):
            patch(self, (handlers, "album_credit", lambda *a, c=credit: Counter(c)))
            self.assertEqual(self.label("album", 2), shown)
        one = [album(2, "Songs for the Deaf", 2002)]  # an artist's only album
        patch(
            self,
            (handlers, "album_credit", lambda *a: Counter({2: 0.5})),
            (handlers.PluginHandlers, "_artist_albums", lambda *a: one),
        )
        self.assertIsNone(self.label("album", 2))

    def test_album_unranked_says_nothing(self):
        self.net.answers = [URLError("offline")]
        self.assertIsNone(self.label("album", 8))  # newest first, but no credit

    def test_deezer_off_your_artist_place(self):
        self.settings["deezer"] = False
        self.assertEqual(self.label("artist", 4), "Your #2 artist")
        self.assertEqual(self.label("artist", 7), "Your #1 artist")
        self.assertIsNone(self.label("artist", 9))  # never played
        self.assertEqual(self.calls, ["AudioLibrary.GetSongs"])  # kept for the day
        self.assertEqual(self.row("artist-places", "library:"), ([7, 4], DAY))
        self.assertEqual(self.net.requests, [])
        self.cache.clear_all()
        self.plays = []  # nothing played
        self.assertIsNone(self.label("artist", 7))

    def test_deezer_off_your_most_played_album(self):
        self.settings["deezer"] = False
        self.assertEqual(self.label("album", 1), "Your most played album")  # Rated R
        self.assertIsNone(self.label("album", 8))  # second
        self.assertIsNone(self.label("album", 2))  # unplayed
        self.assertEqual(self.net.requests, [])
        self.songs = [  # Rated R and Songs for the Deaf on 3 plays each: a tie
            qotsa(1, "No One Knows", "Songs for the Deaf", 2, 2002, 3),
            qotsa(5, "Feel Good Hit of the Summer", "Rated R", 1, 2000, 3),
        ]
        self.assertIsNone(self.label("album", 1))
        self.compilation = True  # its first artist is Various Artists
        calls = len(self.calls)
        self.assertIsNone(self.label("album", 1))
        self.assertEqual(self.calls[calls:], ["AudioLibrary.GetAlbumDetails"])

    def test_deezer_off_your_song_place(self):
        self.settings["deezer"] = False
        self.song = QOTSA_SONGS[4]  # Feel Good Hit of the Summer
        self.assertEqual(self.label("song", 5), "Your #1 song")
        self.song = QOTSA_SONGS[16]  # It's Only Love
        self.assertEqual(self.label("song", 17), "Your #2 song")
        self.song = QOTSA_SONGS[0]  # No One Knows
        self.assertIsNone(self.label("song", 1))  # unplayed
        self.assertEqual(self.net.requests, [])
        live = qotsa(18, "It's Only Love (Live)", "Live", 9, 2027, 3)
        self.songs = [*QOTSA_SONGS, live]  # its versions: 5 plays, one song
        self.song = live
        self.assertEqual(self.label("song", 18), "Your #1 song")
        self.song = QOTSA_SONGS[4]
        self.assertEqual(self.label("song", 5), "Your #2 song")

    def test_play_place(self):
        plays = Counter({n: 100 - n for n in range(1, 13)})  # 1 leads
        places = [play_place(plays, n) for n in (1, PLACES, PLACES + 1)]
        self.assertEqual(places, [1, PLACES, 0])
        self.assertEqual(play_place(Counter({1: 5}), 1), 0)  # one alone has no place
        tie = Counter({1: 5, 2: 5, 3: 1})
        self.assertEqual([play_place(tie, n) for n in (1, 2, 3)], [0, 0, 3])
        self.assertEqual(play_place(Counter({1: 5, 2: 0}), 2), 0)  # unplayed
        symbols = [song(1, "?!", 2000, 9), song(2, "Mono", 2000, 1)]
        self.assertEqual(song_play_place(symbols, "?!"), 0)  # no title to place

    def test_deezer_off_only_the_first_ten(self):
        self.settings["deezer"] = False
        self.plays = [
            {"albumid": n, "artistid": [n], "playcount": 100 - n} for n in range(20)
        ]
        self.assertEqual(self.label("artist", PLACES - 1), f"Your #{PLACES} artist")
        self.assertIsNone(self.label("artist", PLACES))

    def test_other_type_sends_nothing(self):
        self.assertIsNone(self.label("musicvideo", 4))
        self.assertEqual((self.calls, self.net.requests), ([], []))


class ParserTest(unittest.TestCase):
    def parse(self, query):
        return parse_plugin_argv(["plugin://script.copacetic.helper/", "1", query])

    def test_raw_keys_stay_encoded(self):  # clean_name's path: Kodi passes it raw
        query = "?info=clean_name&path=https://h/Who%20Am%20I%3F.mkv&label=a%20b"
        params = parse_plugin_argv(["plugin://x/", "1", query], raw={"path"})
        self.assertEqual(params["path"], "https://h/Who%20Am%20I%3F.mkv")
        self.assertEqual(params["label"], "a b")

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


class PipeGuardTest(unittest.TestCase):
    """The Plot tab's guard ends in the label, which a "|" cuts (CURL::Parse)."""

    def alive(self, label: str, live: str, plot: str = "A plot.") -> tuple[str, bool]:
        """
        Parse the plot render's URL options as Kodi passes them, then run its guard
        from the item at serve start (label) once the dialog's item is live.

        :param label: The label the URL was built with, and the item's at serve start.
        :param live: The label the dialog's item has when the guard is checked.
        :param plot: The text param as the URL carries it.
        :return: The text param, and whether the guard holds.
        """
        query = (
            "?info=text&target=item"
            "&identity_labels=ListItem.DBType,ListItem.DBID,ListItem.Label"
            f"&text={plot}&focus_guard=movie,,{label}"
        ).partition("|")[0]
        handler = handlers.PluginHandlers(parse_plugin_argv(["p://", "1", query]))
        handler.__dict__["window_id"] = 12003
        labels = {"ListItem.DBType": "movie", "ListItem.Label": label}
        with mock.patch.multiple(
            handlers,
            infolabel=lambda label: labels.get(label, ""),
            topmost_window_id=lambda: 12003,
            getCurrentWindowDialogId=lambda: 12003,
            getCurrentWindowId=lambda: 10025,
            focused_control_id=lambda window_id: 4300,
        ):
            guard = handler._guard()
            labels["ListItem.Label"] = live
            return handler.params["text"], guard.alive()

    def test_label_with_a_pipe_keeps_text_and_guard(self):
        self.assertEqual(self.alive(*["Show | S01E02"] * 2), ("A plot.", True))

    def test_another_label_with_a_pipe_aborts(self):
        self.assertFalse(self.alive("Show | S01E02", "Other | S01E02")[1])

    def test_label_without_a_pipe(self):
        self.assertTrue(self.alive("Show", "Show")[1])
        self.assertFalse(self.alive("Show", "Other")[1])

    def test_plot_with_a_pipe_guards_the_item_at_serve_start(self):
        # The guard is cut off the URL: the item the serve started on stands in
        self.assertEqual(self.alive("A", "A", "Act I | Act II"), ("Act I ", True))
        self.assertFalse(self.alive("A", "B", "Act I | Act II")[1])

    def on_top(self, plot: str, cover: int, trailer: bool = False) -> bool:
        """
        Run _info_on_top while one other window (cover) is topmost for a moment.

        :param plot: The text param as the URL carries it.
        :param cover: The window over the info dialog: 10138 busy, else a menu.
        :param trailer: Whether a trailer is resolving (trailer_state pending).
        :return: What it returned.
        """
        query = (
            "?info=text&target=item&identity_labels=ListItem.Label"
            f"&text={plot}&focus_guard=A"
        ).partition("|")[0]
        handler = handlers.PluginHandlers(parse_plugin_argv(["p://", "1", query]))
        handler.__dict__["_info_window"] = 12003
        tops = iter((cover, cover, 12003))
        with mock.patch.multiple(
            handlers,
            topmost_window_id=lambda: next(tops),
            condition=lambda expression: trailer or "trailer_state" not in expression,
            Monitor=lambda: mock.Mock(waitForAbort=lambda timeout: False),
        ):
            return handler._info_on_top()

    def test_busy_wait_stops_a_run_whose_guard_was_cut_off(self):
        # Kodi's Information swaps the item behind the busy dialog
        self.assertFalse(self.on_top("Act I | Act II", 10138))
        self.assertTrue(self.on_top("Act I | Act II", 10106))
        self.assertTrue(self.on_top("A plot.", 10138))

    def test_busy_wait_for_a_trailer_swaps_nothing(self):
        # A trailer's resolve shows the busy dialog over the info screen
        self.assertTrue(self.on_top("Act I | Act II", 10138, trailer=True))


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


class SeasonsTest(unittest.TestCase):
    rows = [
        {"season": -1, "label": "All seasons"},
        {"season": 0, "label": "Specials"},
        {"season": 2, "label": "Season 2"},
        {"season": 1, "label": "Season 1"},
    ]

    def seasons(self, path):
        rpc = lambda request: json.dumps({"result": {"seasons": self.rows}})
        patch(
            self,
            (sys.modules["xbmc"], "executeJSONRPC", rpc),
            (handlers, "set_items", list),
        )
        return handlers.PluginHandlers({"info": "seasons", "path": path}).seasons()

    def test_specials_last_no_all_seasons_and_the_listed_one_current(self):
        items = self.seasons("videodb://tvshows/titles/7/2/?tvshowid=7")
        self.assertEqual(
            [i["label"] for i in items], ["Season 1", "Season 2", "Specials"]
        )
        self.assertEqual(items[0]["file"], "videodb://tvshows/titles/7/1/?tvshowid=7")
        self.assertEqual([i["properties"]["current"] for i in items], ["", "true", ""])

    def test_flattened_or_other_paths(self):
        # -2 is Kodi's flattened listing: no tab is current
        items = self.seasons("videodb://tvshows/titles/7/-2/")
        self.assertFalse(any(i["properties"]["current"] for i in items))
        self.assertIsNone(self.seasons("videodb://recentlyaddedepisodes/"))
        self.assertIsNone(self.seasons(""))


class FileLabelTest(unittest.TestCase):
    def test_name_as_caption(self):
        label = handlers._file_label
        path = "special://home/addons/skin.copacetic2/resources/Grid_with_flags.jpg"
        self.assertEqual(label(path), "Grid with flags")
        self.assertEqual(label(r"C:\Kodi\addons\x\Copacetic_2.png"), "Copacetic 2")
        self.assertEqual(label("Synced_lyrics"), "Synced lyrics")
        self.assertEqual(label(""), "")


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
            if "sort" in params:  # _show_news's newest: specials filtered out
                rows = sorted(
                    (ep for ep in rows if ep["season"] > 0),
                    key=lambda ep: (ep["season"], ep["episode"]),
                    reverse=True,
                )[: params["limits"]["end"]]
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
            (handlers, "getLocalizedString", "#{}".format),
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
        self.assertEqual(self.prop("next_episode", **show), "2x10")
        self.assertNotIn("season", self.calls.pop())
        show["Property(WatchedEpisodes)"] = "0"  # unwatched: its first episode too
        self.assertEqual(self.prop("next_episode", **show), "2x10")
        self.assertNotIn("season", self.calls.pop())
        unwatched_season = show | {"DBType": "season", "TvShowDBID": "7", "Season": "3"}
        properties = self.prop_all(**unwatched_season)  # not started: its next too
        self.assertEqual((properties["next_episode"], properties["new"]), ("3x01", ""))
        self.assertEqual(self.calls.pop()["season"], 3)
        favourite = unwatched_season | {"DBID": "40", "TvShowDBID": ""}
        favourite["Property(tvshowid)"] = "7"
        self.assertEqual(self.prop("next_episode", **favourite), "3x01")
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
        self.assertEqual(self.prop("next_episode", **show), "2x10")
        self.calls.clear()
        self.assertEqual(self.prop("next_episode", **show, TvShowDBID=""), "2x10")
        self.assertEqual(self.calls.pop()["tvshowid"], 7)
        for empty in ({"Property(UnwatchedEpisodes)": "0"}, {"DBID": ""}):
            self.assertEqual(self.prop("next_episode", **show | empty), "")
        self.assertEqual(self.calls, [])  # watched, or a plugin's show: no query

        season = show | {"DBType": "season", "DBID": "40", "TvShowDBID": "7"}
        self.assertEqual(self.prop("next_episode", **season | {"Season": "2"}), "2x10")
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
        self.assertEqual(self.prop("next_runtime", **show), "43m")  # 2x10, 43:01
        self.assertIn("runtime", self.calls.pop()["properties"])
        season = show | {"DBType": "season", "TvShowDBID": "7", "Season": "3"}
        self.assertEqual(self.prop("next_runtime", **season), "1h 2m")  # 3x01
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
        self.assertEqual(self.prop("new", **show), "true")  # 3x01, aired 10 days ago
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
        # Only a special aired lately: new, and its next is still 2x10
        self.episodes = [ep | {"firstaired": aired(400)} for ep in episodes]
        self.episodes[0] = episodes[0]
        properties = self.prop_all(**show)
        self.assertEqual(
            (properties["next_episode"], properties["new"]), ("2x10", "true")
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
            (properties["next_episode"], properties["new"]), ("6x01", "true")
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
            expected = f"{day:%d} #{50 + day.month}" if shown else ""  # Kodi's %b
            self.assertEqual(self.prop("next_air", **show), expected)
        self.handler.params["date_format"] = "%A %d %B, %b"
        self.assertEqual(self.prop("next_air", **show), "")  # still yesterday
        day = date.today() + timedelta(days=2)
        cached["item"]["properties"]["tmdb_next_air_date"] = day.isoformat()
        when = f"{day:%A %d %B}, #{50 + day.month}"  # only %b is Kodi's
        self.assertEqual(self.prop("next_air", **show), when)
        self.assertEqual(asks[0], {"append_artwork": False, "cache_only": True})
        # Cached before the numbers were kept: the date alone
        self.assertEqual(self.prop("next_air_episode", **show), "")
        numbers = {"tmdb_next_air_episode": "1", "tmdb_next_air_season": "3"}
        cached["item"]["properties"] |= numbers
        self.assertEqual(self.prop("next_air_episode", **show), "3x01")
        cached["item"]["properties"]["tmdb_next_air_date"] = "2000-01-01"
        self.assertEqual(self.prop_all(**show)["next_air_episode"], "")  # past
        for labels in (
            show | {"DBType": dbtype} for dbtype in ("season", "episode", "movie")
        ):
            self.labels = labels
            (item,) = self.handler.progressbar()
            self.assertNotIn("next_air", item["properties"])
        self.assertEqual((self.calls, len(asks)), ([], 10))
        # Unstarted (an ended show never begun too) and started shows: no lookup
        for watched, left in (("0", "10"), ("9", "1")):
            counts = {"Property(WatchedEpisodes)": watched}
            counts["Property(UnwatchedEpisodes)"] = left
            self.assertNotIn("next_air", self.prop_all(**show | counts))
        self.assertEqual(len(asks), 10)

    def test_show_news(self):
        props = {}
        self.handler._get_tmdb_item = lambda **kwargs: {"properties": props}
        show = {"DBType": "tvshow", "DBID": "7", "Property(WatchedEpisodes)": "9"}
        show["Property(UnwatchedEpisodes)"] = "0"  # fully watched
        for status, shown in (
            ("Ended", "ended"),
            ("Canceled", "ended"),
            ("Returning Series", "returning"),
            ("In Production", ""),
        ):
            props["tmdb_status"] = status
            self.assertEqual(self.prop("show_status", **show), shown)
        self.assertEqual(self.calls, [])  # no last aired episode: no lookup
        # The library's newest outside the specials is 3x01
        last = {"tmdb_last_air_season": "3", "tmdb_last_air_episode": "1"}
        props |= last
        self.assertEqual(self.prop("new_episode", **show), "")
        asked = self.calls[-1]
        self.assertEqual(
            (asked["tvshowid"], asked["limits"]), (7, {"start": 0, "end": 1})
        )
        self.assertEqual(asked["sort"], {"method": "episode", "order": "descending"})
        props["tmdb_last_air_episode"] = "2"
        self.assertEqual(self.prop("new_episode", **show), "3x02")
        props |= {"tmdb_last_air_season": "2", "tmdb_last_air_episode": "12"}
        self.assertEqual(self.prop("new_episode", **show), "")  # missing, but older
        props["tmdb_last_air_season"] = "4"  # a season the library lacks
        self.assertEqual(self.prop("new_episode", **show), "4x12")
        calls = len(self.calls)
        props["tmdb_last_air_season"] = "0"  # a special, as next_episode leaves out
        self.assertEqual(self.prop("new_episode", **show), "")
        self.assertEqual(self.prop("new_episode", **show | {"DBID": ""}), "")
        self.assertEqual(len(self.calls), calls)


TIDB = {
    "tvdb_id": 81189,
    "type": "tv",
    "season": 1,
    "episode": 1,
    "group_duration_ms": 3480000,
    "intro": [
        {"start_ms": 61000, "end_ms": 91000, "confidence": 0.6, "submission_count": 2},
        {"start_ms": 60500, "end_ms": 90500, "confidence": 0.9, "submission_count": 7},
        {"start_ms": 95000, "end_ms": 94000, "confidence": 1.0},  # ends before start
    ],
    "recap": [{"start_ms": None, "end_ms": 30000, "confidence": 0.8}],
    "credits": [{"start_ms": 3400000, "end_ms": None, "confidence": 0.7}],
}
FILM = {
    "tvdb_id": 169,
    "type": "movie",
    "credits": [  # a mid-credits scene between two: both kept, by start
        {"start_ms": 6408000, "end_ms": None, "confidence": 0.8},
        {"start_ms": 5801777, "end_ms": 6371111, "confidence": 0.9},
        {"start_ms": 5800000, "end_ms": 6300000, "confidence": 0.4},  # a rival take
    ],
}
SHOW = {"tmdb": "1396", "tvdb": "81189", "imdb": "tt0903747"}


class TheIntroDbTest(Base):
    def setUp(self):
        super().setUp()
        sys.modules["xbmcgui"].Window().clearProperty(theintrodb.NEXT_CALL)

    def lookup(self, ids=SHOW):
        return theintrodb.segments(ids, 3_481_234, 1, 1)

    def key(self, kind="tmdb", value="1396"):
        return f"theintrodb:episode:{kind}:{value}:1x1:3481"

    def test_best_segments_cached_half_a_year(self):
        self.net.answers = [json.dumps(TIDB).encode()]
        found = self.lookup()
        self.assertEqual(
            found,
            {
                "recap": [[0, 30000]],
                "intro": [[60500, 90500]],
                "credits": [[3400000, None]],
                "duration": 3480000,
            },
        )
        self.assertEqual(self.row(self.key(), ""), (found, 180 * DAY))
        self.assertEqual(
            self.net.requests[0].full_url,
            "https://api.theintrodb.org/v4/media?tmdb_id=1396&season=1&episode=1"
            "&details=true&duration_ms=3481234",
        )
        self.assertIsNone(self.net.requests[0].get_header("Authorization"))
        self.tick(179 * DAY)
        self.assertEqual(self.lookup(), found)
        self.assertEqual(len(self.net.requests), 1)

    def test_unknown_id_tries_the_next(self):
        # TheIntroDB's 404 bodies, as api.theintrodb.org answered on 13 Nov 2026
        unknown = http_error(404, body=b'{"code":"episode_not_found"}')
        self.net.answers = [unknown, json.dumps(TIDB).encode()]
        self.assertEqual(self.lookup()["intro"], [[60500, 90500]])
        self.assertEqual(self.row(self.key(), ""), ([], 3 * DAY - 1))  # queued 1 s
        self.assertIn("tvdb_id=81189", self.net.requests[1].full_url)
        self.assertEqual(self.lookup()["intro"], [[60500, 90500]])  # both cached
        self.assertEqual(len(self.net.requests), 2)

    def test_no_submissions_ends_the_lookup(self):
        none = b'{"error":"no submissions for this media","code":"no_submissions"}'
        self.net.answers = [http_error(404, body=none)]
        self.assertEqual(self.lookup(), {})
        self.assertEqual(self.row(self.key(), ""), ({}, 3 * DAY))
        self.assertEqual(len(self.net.requests), 1)
        self.net.answers = [http_error(404, body=b"<html>")]  # a proxy's page: no code
        with self.assertRaises(http.HttpError) as caught:
            http.get_json(theintrodb.API)
        self.assertEqual(caught.exception.code, "")

    def test_one_episode_cap_holds_only_that_episode(self):
        capped = b'{"code":"specific_media_usage_limit_exceeded"}'
        self.net.answers = [
            http_error(429, {"Retry-After": "3600"}, capped),
            json.dumps(TIDB).encode(),
        ]
        self.assertEqual(self.lookup(), {})
        self.assertEqual(self.row(self.key(), ""), (None, 3600))
        found = theintrodb.segments(SHOW, 3_481_234, 1, 2)  # the next episode: no wait
        self.assertEqual(found["intro"], [[60500, 90500]])
        self.assertEqual(len(self.net.requests), 2)
        self.cache.clear_all()
        self.net.answers = [http_error(429, {"Retry-After": "3600"})]
        self.lookup()  # the shared limit holds every lookup
        self.assertEqual(theintrodb.segments(SHOW, 3_481_234, 1, 2), {})
        self.assertEqual(len(self.net.requests), 3)

    def test_a_film_by_its_own_ids(self):
        self.net.answers = [json.dumps(FILM).encode()]
        found = theintrodb.segments({"tmdb": "299534"}, 10_860_000)
        self.assertEqual(found, {"credits": [[5801777, 6371111], [6408000, None]]})
        self.assertEqual(
            self.net.requests[0].full_url,
            "https://api.theintrodb.org/v4/media?tmdb_id=299534&details=true"
            "&duration_ms=10860000",
        )
        self.assertEqual(
            self.row("theintrodb:movie:tmdb:299534:10860", ""), (found, 180 * DAY)
        )

    def test_empty_answer_three_days_and_no_other_id(self):
        self.net.answers = [b'{"tvdb_id": 81189, "type": "tv"}']
        self.assertEqual(self.lookup(), {})
        self.assertEqual(self.row(self.key(), ""), ({}, 3 * DAY))
        self.assertEqual(len(self.net.requests), 1)

    def test_odd_types_are_no_answer(self):
        odd = dict(TIDB, intro=[{"start_ms": "61000", "end_ms": {"x": 1}}])
        self.net.answers = [json.dumps(odd).encode()]
        self.assertEqual(self.lookup(), {})
        self.assertEqual(self.row(self.key(), ""), (None, 300))

    def test_no_ids_or_offline(self):
        self.assertEqual(self.lookup({}), {})
        for failure in (URLError("offline"), http_error(429, {"Retry-After": "60"})):
            self.cache.clear_all()
            self.tick(2)
            self.net.answers = [failure]
            self.assertEqual(self.lookup(), {})  # the other ids would fail alike
            self.assertEqual(len(self.net.answers), 0)
        self.assertEqual(self.row(self.key(), ""), (None, 60))

    def test_patterns_refresh_and_clear(self):
        self.net.answers = [json.dumps(TIDB).encode()]
        self.lookup()
        details = {"tvshowid": 3, "uniqueid": SHOW}
        patch(self, (library, "_details", lambda *args: details))
        patterns = library.api_patterns("episode", 9)
        self.assertEqual(
            patterns,
            [
                "tmdb:tvshow:1396:%",
                "tmdb:season_%:1396:%",
                "theintrodb:episode:tmdb:1396:%",
                "theintrodb:episode:tvdb:81189:%",
                "theintrodb:episode:imdb:tt0903747:%",
            ],
        )
        self.assertEqual(self.cache.expire(*patterns), 1)
        details["uniqueid"] = {"tmdb": "299534", "imdb": "tt4154796"}
        self.assertEqual(
            library.api_patterns("movie", 5),
            [
                "tmdb:movie:299534:%",
                "theintrodb:movie:tmdb:299534:%",
                "theintrodb:movie:imdb:tt4154796:%",
            ],
        )
        dialog = mock.Mock(**{"return_value.yesno.return_value": True})
        patch(
            self,
            (actions.xbmcgui, "Dialog", dialog),
            (actions.ADDON, "getLocalizedString", lambda id: "%s"),
        )
        actions.clear_api_cache(source="theintrodb")
        self.assertIsNone(self.cache.get(self.key()))


LRCLIB_GET = json.loads((FIXTURES / "lrclib_get_feel_good_inc.json").read_bytes())
LRCLIB_SEARCH = json.loads((FIXTURES / "lrclib_search_feel_good_inc.json").read_bytes())
# LRCLIB's 404 body, as lrclib.net answered on 16 Nov 2026
LRCLIB_404 = (
    b'{"message":"Failed to find specified track","name":"TrackNotFound",'
    b'"statusCode":404}'
)
SONG = ("Gorillaz", "Feel Good Inc.", "Demon Days", 223)


class LrclibTest(Base):
    def setUp(self):
        super().setUp()
        self.settings["lrclib"] = True
        self.exiting = False

    def aborted(self):
        """The service thread's Monitor.abortRequested."""
        return self.exiting

    def test_no_search_and_nothing_cached_once_kodi_exits(self):
        self.exiting = True
        # A Monitor made now, in the request's thread, would never hear the abort
        later = type("Monitor", (), {"abortRequested": lambda monitor: False})
        patch(self, (sys.modules["xbmc"], "Monitor", later))
        for ask in (lrclib.lyrics, lrclib.prefetch):
            self.net.answers = [http_error(404), json.dumps(LRCLIB_SEARCH).encode()]
            with self.assertRaises(lrclib.Aborted):
                ask(*SONG[:3], 218, self.aborted)
            self.assertIsNone(self.cache.get(self.key(218)))  # the restart asks
        self.assertEqual(len(self.net.requests), 2)  # each /get, no /search
        self.assertEqual(self.net.timeouts, [lrclib.TIMEOUT] * 2)

    def lookup(self, seconds=223):
        return lrclib.lyrics(*SONG[:3], seconds, self.aborted)

    def key(self, seconds=223):
        return f"lrclib:lyrics:Gorillaz|Feel Good Inc.|Demon Days|{seconds}"

    def test_synced_hit_cached_half_a_year(self):
        self.assertTrue(lrclib.enabled())
        self.net.answers = [json.dumps(LRCLIB_GET).encode()]
        found = self.lookup()
        self.assertEqual(
            found,
            {
                "synced": [
                    [1470, "Feel good"],
                    [7050, "Sha, sha-ba-da, sha-ba-da-ca, feel good"],
                    [10060, "Sha, sha-ba-da, sha-ba-da-ca, feel good"],
                    [13160, "Sha, sha-ba-da, sha-ba-da-ca, feel good"],
                ],
                "plain": None,  # synced lines carry it
                "instrumental": False,
            },
        )
        self.assertEqual(self.row(self.key(), ""), (found, 180 * DAY))
        self.assertEqual(
            self.net.requests[0].full_url,
            "https://lrclib.net/api/get?track_name=Feel+Good+Inc.&artist_name=Gorillaz"
            "&album_name=Demon+Days&duration=223",
        )
        self.assertIsNone(self.net.requests[0].get_header("Authorization"))
        self.tick(179 * DAY)
        self.assertEqual(self.lookup(), found)
        self.assertEqual(len(self.net.requests), 1)

    def test_plain_instrumental_and_empty(self):
        plain = dict(LRCLIB_GET, syncedLyrics=None)
        instrumental = dict(plain, plainLyrics=None, instrumental=True)
        empty = dict(instrumental, instrumental=False)
        self.net.answers = [
            json.dumps(r).encode() for r in (plain, instrumental, empty)
        ]
        found = self.lookup(1)
        self.assertEqual(found["plain"], LRCLIB_GET["plainLyrics"])
        self.assertEqual((found["synced"], found["instrumental"]), (None, False))
        self.assertEqual(
            self.lookup(2), {"synced": None, "plain": None, "instrumental": True}
        )
        self.assertEqual(self.row(self.key(2), ""), (self.lookup(2), 180 * DAY))
        self.assertEqual(self.lookup(3), {})
        self.assertEqual(self.row(self.key(3), ""), ({}, 30 * DAY))

    def test_404_takes_the_nearest_search_hit(self):
        self.net.answers = [
            http_error(404, body=LRCLIB_404),
            json.dumps(LRCLIB_SEARCH).encode(),
        ]
        found = self.lookup(218)  # Demon Days (219) and iTunes Session (217) tie
        self.assertEqual(found["synced"][0], [2680, "Feel good"])  # the first of them
        self.assertEqual(
            self.net.requests[1].full_url,
            "https://lrclib.net/api/search?track_name=Feel+Good+Inc."
            "&artist_name=Gorillaz",
        )
        self.assertEqual(self.row(self.key(218), ""), (found, 180 * DAY))

    def test_synced_first_among_equally_near(self):
        hits = [dict(h) for h in LRCLIB_SEARCH]
        hits[2]["syncedLyrics"] = None  # Demon Days, 219: plain only
        self.net.answers = [http_error(404), json.dumps(hits).encode()]
        self.assertEqual(self.lookup(218)["synced"][0], [6130, "Feel good"])

    def test_no_near_hit_is_the_404(self):
        self.net.answers = [http_error(404), json.dumps(LRCLIB_SEARCH).encode()]
        self.assertIsNone(self.lookup(230))  # the nearest, 219, is 11 s off
        self.assertEqual(self.row(self.key(230), ""), (None, 7 * DAY))
        self.net.answers = [http_error(404), b"[]"]
        self.assertIsNone(self.lookup(100))
        self.assertEqual(len(self.net.requests), 4)

    def test_offline_and_odd_answers(self):
        self.net.answers = [URLError("offline"), http_error(404), b'{"x": 1}']
        self.assertIsNone(self.lookup())
        self.assertEqual(self.row(self.key(), ""), (None, 300))
        self.assertIsNone(self.lookup(1))  # a search answer of another shape
        self.assertEqual(self.row(self.key(1), ""), (None, 300))

    def test_prefetch_keeps_answers_only(self):
        self.assertIsNone(lrclib.saved(*SONG))
        self.net.answers = [URLError("offline"), http_error(404), b"[]"]
        self.assertIsNone(lrclib.prefetch(*SONG, self.aborted))
        self.assertIsNone(lrclib.prefetch(*SONG, self.aborted))  # nothing near: the 404
        self.assertIsNone(self.cache.get(self.key()))  # the start asks itself
        self.net.answers = [json.dumps(LRCLIB_GET).encode()]
        found = lrclib.prefetch(*SONG, self.aborted)
        self.assertEqual(found["synced"][0], [1470, "Feel good"])
        self.assertEqual(self.row(self.key(), ""), (found, 180 * DAY))
        self.assertEqual(lrclib.saved(*SONG), (found, True))
        self.assertEqual(self.lookup(), found)  # the start: no request
        self.assertEqual(len(self.net.requests), 4)
        empty = dict(LRCLIB_GET, syncedLyrics=None, plainLyrics=None)
        self.net.answers = [json.dumps(empty).encode()]
        self.assertEqual(lrclib.prefetch(*SONG[:3], 1, self.aborted), {})
        self.assertEqual(self.row(self.key(1), ""), ({}, 30 * DAY))

    def test_a_failed_prefetch_hides_nothing(self):
        self.net.answers = [URLError("offline"), json.dumps(LRCLIB_GET).encode()]
        lrclib.prefetch(*SONG, self.aborted)
        self.assertEqual(self.lookup()["synced"][0], [1470, "Feel good"])

    def test_refresh_cached_expires_the_song(self):
        self.net.answers = [json.dumps(LRCLIB_GET).encode()]
        found = self.lookup()
        details = dict(zip(("displayartist", "title", "album", "duration"), SONG))
        patch(self, (library, "_details", lambda *args: details))
        patterns = library.api_patterns("song", 7)
        self.assertEqual(patterns, [self.key()])
        self.assertEqual(self.cache.expire(*patterns), 1)
        self.assertEqual(lrclib.saved(*SONG), (found, False))

    def test_clear(self):
        self.net.answers = [json.dumps(LRCLIB_GET).encode()]
        self.lookup()
        dialog = mock.Mock(**{"return_value.yesno.return_value": True})
        patch(
            self,
            (actions.xbmcgui, "Dialog", dialog),
            (actions.ADDON, "getLocalizedString", lambda id: "%s"),
        )
        actions.clear_api_cache(source="lrclib")
        self.assertIsNone(self.cache.get(self.key()))


if __name__ == "__main__":
    unittest.main()
