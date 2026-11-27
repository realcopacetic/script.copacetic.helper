"""
Offline checks for an album's resume point on info=progressbar (shared/helpers.py
album_resume, ProgressBarManager.album), part-heard albums only: the track after the
one heard last, in disc and track order; after the last track, the first not heard;
disc 0 no disc of its own, a track 0 no point. And play_album_resume
(script/actions.py): Kodi's resume menu past the first track, else the start unasked.
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
from resources.lib.script import actions  # noqa: E402
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


class LibraryTest(unittest.TestCase):
    """GetSongs answers self.songs; each request is kept in self.calls."""

    def setUp(self):
        self.songs, self.calls, self.props = [], [], {}  # props: the bar's window's
        window = mock.Mock(
            getProperty=lambda key: self.props.get(key, ""),
            setProperty=self.props.__setitem__,
        )

        def rpc(request):
            request = json.loads(request)
            self.calls.append(request)
            return json.dumps({"result": {"songs": self.songs}})

        for target, name, value in (
            (sys.modules["xbmc"], "executeJSONRPC", rpc),
            (helpers, "Window", mock.Mock(return_value=window)),
            (helpers, "get_infolabels", lambda target, keys: {"DBID": "7"}),
        ):
            patcher = mock.patch.object(target, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)


class AlbumResumeTest(LibraryTest):
    """The resume point ProgressBarManager.album gives, from one GetSongs call."""

    def album(self, *songs):
        self.songs = list(songs)
        return helpers.ProgressBarManager("ListItem", 4010, 10025, 14).album

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
        # part-heard only: in order, out of order, or marked played
        self.assertEqual(self.album(song(1, days=3), song(2, days=1)).resume, {})
        self.assertEqual(self.album(song(1, days=1), song(2, days=3)).resume, {})
        marked = [song(1, days=1), song(2), song(3)]
        for row in marked:
            row["playcount"], row["lastplayed"] = 1, marked[0]["lastplayed"]
        self.assertEqual(self.album(*marked).resume, {})
        # a song added since it was marked: the latest of the ties counts as last
        album = self.album(*marked, song(4))
        self.assertEqual(album.resume["album_next_track"], "4")

    def test_disc_0_is_no_disc_of_its_own(self):
        album = self.album(song(1, disc=0, days=1), song(1, disc=1), song(2, disc=1))
        self.assertEqual(album.resume["album_next_track"], "1")
        self.assertNotIn("album_next_disc", album.resume)

    def test_track_0_no_point(self):
        # untagged: no number to show, so no title alone either
        self.assertEqual(self.album(song(0, days=1), song(0)).resume, {})
        self.assertEqual(self.album(song(1, days=1), song(0, disc=1)).resume, {})

    def test_point_at_the_first_track_no_position(self):
        # the last track heard: the first not heard is track 1, the start
        album = self.album(song(1), song(2), song(3, days=1))
        self.assertEqual((album.resume["album_next_track"], album.position), ("1", 0))
        album = self.album(song(1, days=2), song(2), song(3))
        self.assertEqual(album.position, 1)

    def serve(self, dbid="7"):
        """The progress item's properties for album dbid, served in window 10025."""
        labels = {"DBType": "album", "DBID": dbid}
        published = {}
        for target, name, value in (
            (helpers, "get_infolabels", lambda target, keys: labels),
            (helpers.ProgressBarManager, "update", lambda self, percent, **kw: None),
            (handlers, "set_items", lambda items, **kwargs: items),
            (
                handlers,
                "window_property",
                lambda name, value: published.update({name: value}),
            ),
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
        return item["properties"], published

    def test_on_the_progress_item(self):
        self.songs = [song(1, days=2), song(2), song(3)]
        props, published = self.serve()
        self.assertEqual((props["album_next_track"], props["album"]), ("2", "true"))
        self.assertEqual(props["time_left"], "7m")  # still served: the skin picks
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(published["album_resume"], "7")  # the context menu's Resume

    def test_row_flip_turns_on_an_in_place_change(self):
        self.songs = [song(1, days=2), song(2), song(3)]
        flip = self.serve()[0]["row_flip"]
        self.assertEqual(self.serve()[0]["row_flip"], flip)  # the same row: kept
        self.songs[1] = song(2, days=1)  # a song heard: the re-serve's new row
        turned = self.serve()[0]["row_flip"]
        self.assertNotEqual(turned, flip)
        self.serve("8")  # another album: a move, no flip
        self.assertEqual(self.serve()[0]["row_flip"], turned)


class PlayAlbumResumeTest(LibraryTest):
    """play_album_resume: the menu's choice, the queue and where it starts."""

    def setUp(self):
        super().setUp()
        self.menus, self.choice, self.played, self.closed = [], 0, [], []
        strings = {
            32845: "Resume from track %s",
            32846: "Resume from disc %s, track %s",
        }

        def contextmenu(labels):
            self.menus.append(labels)
            return self.choice

        for target, name, value in (
            (actions, "ADDON", mock.Mock(getLocalizedString=strings.get)),
            (actions.xbmc, "getLocalizedString", lambda id: f"#{id}"),
            (actions.xbmcgui, "Dialog", lambda: mock.Mock(contextmenu=contextmenu)),
            (
                actions,
                "play_files",
                lambda songs, position: self.played.append(
                    ([s["songid"] for s in songs], position)
                ),
            ),
            (actions, "mark_source", mock.Mock()),
            (actions.log, "execute", self.closed.append),
        ):
            patcher = mock.patch.object(target, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    def play(self, *songs, **params):
        self.songs = list(songs)
        actions.play_album_resume(id="7", **params)

    def test_resume_or_from_the_start(self):
        rows = song(3), song(1, days=2), song(2)
        self.play(*rows)
        self.assertEqual(self.menus, [["Resume from track 2", "#12021"]])
        self.assertEqual(self.played, [([1, 2, 3], 1)])  # disc and track order
        self.assertIn("file", self.calls[0]["params"]["properties"])
        self.choice = 1  # Play from beginning
        self.play(*rows)
        self.assertEqual(self.played[-1], ([1, 2, 3], 0))

    def test_cancel_plays_nothing(self):
        self.choice = -1
        self.play(song(1, days=2), song(2), close="musicinformation")
        self.assertEqual((self.played, self.closed), ([], []))

    def test_close_once_chosen(self):
        self.play(song(1, days=2), song(2), close="musicinformation")
        self.assertEqual(self.closed, ["Dialog.Close(musicinformation)"])

    def test_resume_unasked(self):
        self.play(song(1, days=2), song(2), resume="true")
        self.assertEqual((self.menus, self.played), ([], [([1, 2], 1)]))

    def test_disc_in_the_label(self):
        self.play(song(1, disc=1, days=1), song(1, disc=2))
        self.assertEqual(self.menus[0][0], "Resume from disc 2, track 1")
        self.assertEqual(self.played, [([101, 201], 1)])

    def test_not_part_heard_from_the_start_unasked(self):
        for rows in (
            [song(1), song(2)],  # never played
            [song(1, days=2), song(2, days=1)],  # heard through
            [song(1, days=30), song(2)],  # heard before album_days
            [song(1), song(2, days=1)],  # its point the first track
        ):
            self.play(*rows)
        self.assertEqual(self.menus, [])
        self.assertEqual(self.played, [([1, 2], 0)] * 4)
        self.play(song(1, days=20), song(2), album_days="30")  # a longer window
        self.assertEqual(self.played[-1], ([1, 2], 1))

    def test_no_songs_nothing(self):
        self.play()
        self.assertEqual((self.menus, self.played), ([], []))


if __name__ == "__main__":
    unittest.main()
