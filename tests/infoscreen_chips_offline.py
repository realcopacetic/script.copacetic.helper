"""
Offline checks for the info screen's chips on info=metadata (shared/helpers.py
DataHandler): genre_chips=N gives two genre chips while both names and the second's
" +N" fit N characters, else one; an episode takes its show's genres; album_format
gives an album's most common format, lossless by sample rate, lossy by bitrate, an
.m4a by its bitrate; most_played an album's or artist's most played song, two plays
or more and no tie, a compilation's with its artist. JSON-RPC rows are hand-written
in Omega's shape. Run from the helper root:
python tests/infoscreen_chips_offline.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
vars(sys.modules["xbmc"]).update(  # imported names; a test that calls one patches it
    Monitor=None,
    getCacheThumbName=None,
    getLocalizedString=None,
    AudioStreamDetail=None,
    SubtitleStreamDetail=None,
    VideoStreamDetail=None,
)
sys.modules["xbmcplugin"].SORT_METHOD_LASTPLAYED = 0
sys.path.insert(0, str(HELPER))

from resources.lib.plugin import handlers  # noqa: E402,F401
from resources.lib.shared import helpers  # noqa: E402


class GenreChipsTest(unittest.TestCase):
    """genre_chip_names: the chips' names and the count of the rest."""

    def chips(self, *genres):
        return helpers.genre_chip_names(list(genres), 22)

    def test_none_or_one(self):
        self.assertEqual(self.chips(), {})
        self.assertEqual(
            self.chips("Drama"), {"genre_first": "Drama", "genre_more": ""}
        )

    def test_two_that_fit(self):
        self.assertEqual(
            self.chips("Sci-Fi & Fantasy", "Drama"),  # 21 characters
            {
                "genre_first": "Sci-Fi & Fantasy",
                "genre_second": "Drama",
                "genre_more": "",
            },
        )
        # the second chip's +N counts towards the fit
        self.assertEqual(
            self.chips("Animation", "Comedy", "Family", "Kids", "Adventure"),
            {"genre_first": "Animation", "genre_second": "Comedy", "genre_more": "3"},
        )

    def test_fold_to_one(self):
        self.assertEqual(
            self.chips("Action & Adventure", "Animation"),  # 27 characters
            {"genre_first": "Action & Adventure", "genre_more": "1"},
        )
        # 20 names fit, the +3 doesn't: one chip for all
        self.assertEqual(
            self.chips("Science Fiction", "Drama", "War", "History", "Crime"),
            {"genre_first": "Science Fiction", "genre_more": "4"},
        )


class AudioFormatTest(unittest.TestCase):
    """audio_format: the codec, then the sample rate or the bitrate."""

    def test_lossless_by_sample_rate(self):
        self.assertEqual(
            helpers.audio_format("/music/a/01.FLAC", 44100, 900),
            (("format_codec", "flac"), ("format_samplerate", "44.1")),
        )
        self.assertEqual(
            helpers.audio_format("/music/a/01.wav", 96000, 4608)[1],
            ("format_samplerate", "96"),  # as ListItem.SampleRate, {:.5}
        )

    def test_lossy_by_bitrate(self):
        self.assertEqual(
            helpers.audio_format("smb://nas/a/01.mp3", 44100, 320),
            (("format_codec", "mp3"), ("format_bitrate", "320")),
        )

    def test_m4a_by_bitrate(self):
        self.assertEqual(
            helpers.audio_format("/a/01.m4a", 44100, 256)[1], ("format_bitrate", "256")
        )
        self.assertEqual(
            helpers.audio_format("/a/01.m4a", 44100, 870)[1],
            ("format_samplerate", "44.1"),
        )

    def test_nothing_to_name(self):
        self.assertIsNone(helpers.audio_format("/a/01", 44100, 320))
        self.assertIsNone(helpers.audio_format("/a/01.flac", 0, 900))
        self.assertIsNone(helpers.audio_format("/a/01.mp3", 44100, 0))


class DataHandlerChipsTest(unittest.TestCase):
    """fetch_data with genre_chips and album_format, Kodi's reads stubbed."""

    def setUp(self):
        self.calls, self.answers, self.labels = [], {}, {}

        def rpc(request):
            request = json.loads(request)
            self.calls.append(request)
            return json.dumps({"result": self.answers.get(request["method"], {})})

        for target, name, value in (
            (sys.modules["xbmc"], "executeJSONRPC", rpc),
            (helpers, "get_infolabels", lambda target, keys: dict.fromkeys(keys, "")),
            (helpers, "infolabel", lambda label: self.labels.get(label, "")),
        ):
            patcher = mock.patch.object(target, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def songs_calls(self):
        return [c for c in self.calls if c["method"] == "AudioLibrary.GetSongs"]

    def fetch(self, dbtype, genre="", **opts):
        handler = helpers.DataHandler("ListItem", dbtype, "7")
        handler.infolabels["Genre"] = genre
        return handler.fetch_data(**opts)["properties"]

    def test_opt_in(self):
        properties = self.fetch("movie", "Animation / Comedy")
        self.assertNotIn("genre_first", properties)
        properties = self.fetch("movie", "Animation / Comedy", genre_chips=22)
        self.assertEqual(properties["genre_second"], "Comedy")
        self.assertEqual(self.calls, [])  # a movie's genres are its own label

    def test_episode_takes_its_shows(self):
        self.labels["ListItem.TVShowDBID"] = "12"
        self.answers["VideoLibrary.GetTVShowDetails"] = {
            "tvshowdetails": {"genre": ["Drama", "Fantasy", "Action"]}
        }
        properties = self.fetch("episode", genre_chips=22)
        self.assertEqual(
            {k: v for k, v in properties.items() if k.startswith("genre_")},
            {"genre_first": "Drama", "genre_second": "Fantasy", "genre_more": "1"},
        )
        (call,) = self.calls
        self.assertEqual(call["params"]["tvshowid"], 12)

    def test_album_format_most_common(self):
        self.answers["AudioLibrary.GetSongs"] = {
            "songs": [
                {"file": "/a/01.flac", "samplerate": 44100, "bitrate": 900},
                {"file": "/a/02.flac", "samplerate": 96000, "bitrate": 2800},
                {"file": "/a/03.flac", "samplerate": 44100, "bitrate": 1010},
                {"file": "/a/04.mp3", "samplerate": 44100, "bitrate": 320},
            ]
        }
        properties = self.fetch("album", album_format=True)
        self.assertEqual(properties["format_codec"], "flac")
        self.assertEqual(properties["format_samplerate"], "44.1")
        self.assertNotIn("format_bitrate", properties)
        (call,) = self.songs_calls()
        self.assertEqual(call["params"]["filter"], {"albumid": 7})
        # opt-in, and albums only
        self.calls.clear()
        self.assertNotIn("format_codec", self.fetch("album"))
        self.assertNotIn("format_codec", self.fetch("song", album_format=True))
        self.assertEqual(self.songs_calls(), [])

    def test_album_format_none(self):
        self.answers["AudioLibrary.GetSongs"] = {"songs": []}
        self.assertNotIn("format_codec", self.fetch("album", album_format=True))

    def songs(self, *rows):
        """GetSongs rows, most played first as Kodi sorts them: title, plays, artist
        ids, album artist ids."""
        keys = ("title", "playcount", "artistid", "albumartistid")
        self.answers["AudioLibrary.GetSongs"] = {
            "songs": [
                dict(zip(keys, row), displayartist=f"Artist {row[2][0]}")
                for row in rows
            ]
        }

    def test_most_played(self):
        self.songs(("Single", 12, [1, 2], [1]), ("Hit", 9, [1], [1]))
        self.assertEqual(
            self.fetch("artist", most_played=True),
            {"dbid": "7", "most_played": "Single"},
        )
        (call,) = self.songs_calls()
        self.assertEqual(call["params"]["filter"], {"artistid": 7})
        # the database sorts and cuts: the top two, however many songs
        self.assertEqual(
            call["params"]["sort"], {"method": "playcount", "order": "descending"}
        )
        self.assertEqual(call["params"]["limits"], {"start": 0, "end": 2})
        # an album's own artist among the song's: no artist named
        self.assertNotIn("most_played_artist", self.fetch("album", most_played=True))
        self.assertEqual(self.songs_calls()[-1]["params"]["filter"], {"albumid": 7})
        self.songs(("Only", 2, [1], [1]))  # a lone song needs no runner-up
        self.assertEqual(self.fetch("album", most_played=True)["most_played"], "Only")

    def test_most_played_compilation(self):
        self.songs(("Track", 3, [4], [9]), ("Other", 2, [5], [9]))
        properties = self.fetch("album", most_played=True)
        self.assertEqual(properties["most_played"], "Track")
        self.assertEqual(properties["most_played_artist"], "Artist 4")
        # an artist's song on a compilation names no artist: it is theirs
        self.assertNotIn("most_played_artist", self.fetch("artist", most_played=True))

    def test_most_played_none(self):
        self.songs(("Once", 1, [1], [1]))
        self.assertNotIn("most_played", self.fetch("album", most_played=True))
        self.songs(("Opener", 3, [1], [1]), ("Closer", 3, [1], [1]))  # played through
        self.assertNotIn("most_played", self.fetch("album", most_played=True))
        self.songs()
        self.assertNotIn("most_played", self.fetch("artist", most_played=True))
        # opt-in, and albums and artists only
        self.calls.clear()
        self.assertNotIn("most_played", self.fetch("album"))
        self.assertNotIn("most_played", self.fetch("song", most_played=True))
        self.assertEqual(self.songs_calls(), [])


if __name__ == "__main__":
    unittest.main()
