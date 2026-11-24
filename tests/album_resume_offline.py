"""
Offline checks for an album's resume point on info=progressbar (shared/helpers.py
album_resume, ProgressBarManager.album): the track after the one heard last, in disc
and track order; after the last track, the first not heard; nothing heard, nothing.
Song rows are hand-written in AudioLibrary.GetSongs's shape (Omega). Run from the
helper root:
python tests/album_resume_offline.py
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
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

from resources.lib.plugin import handlers  # noqa: E402
from resources.lib.shared import helpers  # noqa: E402


def ago(days):
    """A JSON-RPC lastplayed string, days before now."""
    return f"{datetime.now() - timedelta(days=days):%Y-%m-%d %H:%M:%S}"


def song(track, disc=0, days=None, playcount=None):
    """A GetSongs row; days: last played that long ago (played once unless given)."""
    return {
        "songid": disc * 100 + track,
        "title": f"Song {disc}.{track}",
        "track": track,
        "disc": disc,
        "duration": 200,
        "playcount": (days is not None) if playcount is None else playcount,
        "lastplayed": "" if days is None else ago(days),
    }


class AlbumResumeTest(unittest.TestCase):
    """The resume point ProgressBarManager.album gives, from one GetSongs call."""

    def setUp(self):
        self.songs, self.calls = [], []

        def rpc(request):
            request = json.loads(request)
            self.calls.append(request)
            return json.dumps({"result": {"songs": self.songs}})

        for target, name, value in (
            (sys.modules["xbmc"], "executeJSONRPC", rpc),
            (helpers, "Window", mock.Mock()),
            (helpers, "get_infolabels", lambda target, keys: {"DBID": "7"}),
        ):
            patcher = mock.patch.object(target, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def album(self, *songs):
        self.songs = list(songs)
        since = f"{datetime.now() - timedelta(days=14):%Y-%m-%d %H:%M:%S}"
        return helpers.ProgressBarManager("ListItem", 4010, 10025, since).album

    def test_after_the_song_heard_last(self):
        # GetSongs's order isn't album order; 3 was heard after 5
        album = self.album(song(5, days=4), song(1, days=6), song(3, days=2), song(4))
        self.assertEqual(
            album.resume, {"album_next_track": "4", "album_next_title": "Song 0.4"}
        )
        (call,) = self.calls  # the one call, with the fields the point reads
        fields = call["params"]["properties"]
        self.assertTrue(
            {"disc", "lastplayed", "playcount", "title", "track"} <= {*fields}
        )

    def test_the_next_track_even_if_heard(self):
        album = self.album(song(1, days=5), song(2, days=1), song(3, days=3), song(4))
        self.assertEqual(album.resume["album_next_track"], "3")

    def test_after_the_last_track_the_first_not_heard(self):
        album = self.album(song(1, days=5), song(2), song(3, days=3), song(4, days=1))
        self.assertEqual(album.resume["album_next_track"], "2")
        # heard before the window: not heard, so the point
        album = self.album(song(1, days=5), song(2, days=30), song(3, days=1))
        self.assertEqual(album.resume["album_next_track"], "2")

    def test_multi_disc_order_and_disc(self):
        album = self.album(
            song(1, disc=2), song(9, disc=1, days=1), song(2, disc=2), song(1, disc=1)
        )
        self.assertEqual(
            album.resume,
            {
                "album_next_track": "1",
                "album_next_title": "Song 2.1",
                "album_next_disc": "2",
            },
        )
        # the last track of the last disc: the first not heard, on disc 1
        album = self.album(
            song(1, disc=1, days=2), song(2, disc=1), song(1, disc=2, days=1)
        )
        self.assertEqual(album.resume["album_next_disc"], "1")
        self.assertEqual(album.resume["album_next_track"], "2")
        # one disc tagged 1 is no multi-disc album
        album = self.album(song(1, disc=1, days=1), song(2, disc=1))
        self.assertNotIn("album_next_disc", album.resume)

    def test_nothing_recent_no_point(self):
        self.assertEqual(self.album(song(1), song(2)).resume, {})  # never played
        self.assertEqual(self.album(song(1, days=20), song(2)).resume, {})
        # unplayed again: Kodi keeps the last played, the play count says not heard
        self.assertEqual(self.album(song(1, days=1, playcount=0), song(2)).resume, {})

    def test_heard_through_no_point(self):
        # in order, or marked played: one last played for all, the last track wins
        self.assertEqual(self.album(song(1, days=3), song(2, days=1)).resume, {})
        marked = [song(1, days=1), song(2), song(3)]
        for row in marked:
            row["playcount"], row["lastplayed"] = 1, marked[0]["lastplayed"]
        self.assertEqual(self.album(*marked).resume, {})

    def test_on_the_progress_item(self):
        self.songs = [song(1, days=2), song(2), song(3)]
        labels = {"DBType": "album", "DBID": "7"}
        for target, name, value in (
            (helpers, "get_infolabels", lambda target, keys: labels),
            (helpers.ProgressBarManager, "update", lambda self, percent, **kw: None),
            (handlers, "set_items", lambda items, **kwargs: items),
            (handlers, "window_property", lambda *args, **kwargs: None),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        handler = object.__new__(handlers.PluginHandlers)
        handler.params = {"target_id": "4010"}
        handler.target_item = "Container(50).ListItem"
        handler.dialog, handler.window_id = False, 10025
        handler._guard = lambda: mock.Mock(alive=lambda: True)
        (item,) = handler.progressbar()
        props = item["properties"]
        self.assertEqual((props["album_next_track"], props["album"]), ("2", "true"))
        self.assertEqual(props["time_left"], "7m")  # still served: the skin picks
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
