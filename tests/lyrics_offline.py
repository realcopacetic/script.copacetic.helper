"""
Offline checks for lyrics: the LRC parser (shared/lrc.py); the service's sources in
order (a .lrc beside the song, its tags, LRCLIB), what it publishes, how it steps
the visualisation's follow list (3510) and the music OSD's browse list (3511) by
their selected item, and the player monitor's poller hook (service/lyrics.py,
service/player.py); the info=lyrics plugin path and the lyrics_seek action.
Infolabels and conditions are dicts; nothing reaches the network.
Run from the helper root: python tests/lyrics_offline.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
vars(sys.modules["xbmc"]).update(  # imported names; a test that calls one patches it
    Player=object,
    InfoTagVideo=None,
    Monitor=None,
    getCacheThumbName=None,
    getLocalizedString=None,
    VideoStreamDetail=None,
    AudioStreamDetail=None,
    SubtitleStreamDetail=None,
)
sys.modules["xbmcplugin"].SORT_METHOD_LASTPLAYED = 0


class File:
    """xbmcvfs.File over a local path: readBytes gives a bytearray, as Kodi's does."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def readBytes(self):
        return bytearray(Path(self.path).read_bytes())


sys.modules["xbmcvfs"].File = File
sys.path.insert(0, str(HELPER))

from resources.lib.plugin import handlers  # noqa: E402
from resources.lib.script import actions  # noqa: E402
from resources.lib.service import lyrics, player  # noqa: E402
from resources.lib.shared import lrc  # noqa: E402

LRC = "[ar:Gorillaz]\n[00:01.47]Feel good\n[00:07.05]Sha, sha-ba-da\n[00:10.06]\n"
LINES = [[1470, "Feel good"], [7050, "Sha, sha-ba-da"], [10060, ""]]
SONG = ("Gorillaz", "Feel Good Inc.", "Demon Days", 223)
TAGS = {
    "MusicPlayer.Artist": "Gorillaz",
    "MusicPlayer.Title": "Feel Good Inc.",
    "MusicPlayer.Album": "Demon Days",
    "MusicPlayer.Duration": "03:43",
}


class ParseTest(unittest.TestCase):
    def test_stamp_forms(self):
        text = (
            "[00:01]one\n[00:02.5]two\n[00:03.25]three\n[01:04.125]four\n[0:05:50]five"
        )
        self.assertEqual(
            lrc.parse(text),
            [
                [1000, "one"],
                [2500, "two"],
                [3250, "three"],
                [5500, "five"],  # a colon before the hundredths
                [64125, "four"],
            ],
        )

    def test_several_stamps_share_a_line_and_sort(self):
        text = "[00:30.00][00:10.00]chorus\n[00:20.00]verse"
        self.assertEqual(
            lrc.parse(text), [[10000, "chorus"], [20000, "verse"], [30000, "chorus"]]
        )

    def test_offset_tags_gaps_and_word_stamps(self):
        text = (
            "[ar:Gorillaz]\n[ti:Feel Good Inc]\n[length: 03:43]\n"
            "[00:01.00]<00:01.00>Feel <00:01.40>good\n\n[00:05.00]\n"
            "[00:06.00]  City's breaking down  \n[offset:+500]\n[re:LRC Maker]"
        )
        self.assertEqual(
            lrc.parse(text),
            [[500, "Feel good"], [4500, ""], [5500, "City's breaking down"]],
        )
        self.assertEqual(lrc.parse("[offset:-250]\n[00:00.10]a")[0], [350, "a"])
        self.assertEqual(lrc.parse("[offset:+500]\n[00:00.10]a")[0], [0, "a"])

    def test_plain_text_has_no_lines(self):
        self.assertEqual(lrc.parse("Feel good\n\nCity's breaking down"), [])
        self.assertEqual(lrc.parse(""), [])

    def test_plain_drops_tags_keeps_verses(self):
        text = (
            "[ar:Gorillaz]\r\n[length: 03:43]\r\n[Chorus]\r\n  Feel good  \r\n\r\n"
            "[00:01,50]City's [00:02,00]breaking\r\n[Verse 1: 2-D]\r\n[re:]"
        )
        self.assertEqual(
            lrc.plain(text),
            "[Chorus]\nFeel good\n\nCity's breaking\n[Verse 1: 2-D]",
        )
        self.assertEqual(lrc.plain("[ar:Gorillaz]\n[ti:Feel Good Inc]\n\n"), "")


class Kodi(unittest.TestCase):
    """Infolabels, conditions and Home properties as dicts; builtins and asks."""

    def setUp(self):
        self.labels, self.conditions, self.props = dict(TAGS), set(), {}
        self.order, self.builtins, self.asked, self.threads = [], [], [], []
        self.lrclib = {}  # LRCLIB's payload by song
        for target, name, value in (
            (lyrics, "infolabel", lambda key: self.labels.get(key, "")),
            (lyrics, "condition", lambda key: key in self.conditions),
            (lyrics, "window_property", self.prop),
            (lyrics.log, "execute", self.builtins.append),
            (lyrics.lrclib, "enabled", lambda: True),
            (lyrics.lrclib, "lyrics", self.ask),
            (lyrics, "Thread", self.thread),
            (player, "condition", lambda key: key in self.conditions),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def prop(self, key, value=""):
        self.order.append(key)
        if value:
            self.props[key] = value
        else:
            self.props.pop(key, None)

    def ask(self, *song):
        self.asked.append(song)
        return self.lrclib.get(song)

    def thread(self, target, args, daemon):
        """A Thread that runs its target on start, here and now."""
        self.assertTrue(daemon)
        self.threads.append(args)
        return type("Thread", (), {"start": lambda thread: target(*args)})()


class SourcesTest(Kodi):
    def song_file(self, lrc_text=None, encoding="utf-8-sig"):
        folder = Path(tempfile.mkdtemp())
        (folder / "Feel Good Inc.flac").touch()
        if lrc_text is not None:
            (folder / "Feel Good Inc.lrc").write_bytes(lrc_text.encode(encoding))
        return str(folder / "Feel Good Inc.flac")

    def test_sidecar_encodings(self):
        text = "[00:01.00]Café, señor\n[00:02.00]Ünder"
        lines = [[1000, "Café, señor"], [2000, "Ünder"]]
        for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-16-be", "cp1252"):
            if encoding == "utf-16-be":  # Python's utf-16-be writes no mark
                path = self.song_file()
                lrc_path = Path(path).with_suffix(".lrc")
                lrc_path.write_bytes(b"\xfe\xff" + text.encode(encoding))
            else:
                path = self.song_file(text, encoding)
            self.assertEqual(lyrics.find(path), ("file", lines, None, False), encoding)

    def test_a_sidecar_of_only_tags_falls_through(self):
        self.labels["MusicPlayer.Lyrics"] = "[00:02.00]embedded"
        path = self.song_file("[ar:Gorillaz]\n[ti:Feel Good Inc]\n[by:someone]\n")
        self.assertEqual(lyrics.find(path)[:2], ("embedded", [[2000, "embedded"]]))
        unsupported = self.song_file("[ar:Gorillaz]\n[00:01,50]Feel good\n")
        self.assertEqual(lyrics.find(unsupported), ("file", None, "Feel good", False))

    def test_song_tags_and_length(self):
        self.assertEqual(lyrics.song(), SONG)
        self.labels["MusicPlayer.offset(1).Duration"] = "1:02:03"
        self.assertEqual(lyrics.song("MusicPlayer.offset(1).")[3], 3723)
        self.labels["MusicPlayer.Duration"] = ""
        self.assertEqual(lyrics.song()[3], 0)

    def test_sidecar_first(self):
        self.labels["MusicPlayer.Lyrics"] = "[00:02.00]embedded"
        path = self.song_file(LRC)  # with a byte order mark
        self.assertEqual(lyrics.find(path), ("file", LINES, None, False))
        self.conditions.add("Player.IsInternetStream")  # a stream: no file beside it
        self.assertEqual(lyrics.find(path)[:2], ("embedded", [[2000, "embedded"]]))
        self.assertEqual(self.asked, [])

    def test_embedded_plain_then_lrclib(self):
        path = self.song_file()
        self.labels["MusicPlayer.Lyrics"] = "\r\nFeel good\r\n\r\nCity's breaking\r\n"
        self.assertEqual(
            lyrics.find(path), ("embedded", None, "Feel good\n\nCity's breaking", False)
        )
        self.labels["MusicPlayer.Lyrics"] = " "
        self.lrclib[SONG] = {"synced": None, "plain": None, "instrumental": True}
        self.assertEqual(lyrics.find(path), ("lrclib", None, None, True))
        self.assertEqual(self.asked, [SONG])
        self.lrclib[SONG] = {}  # LRCLIB holds the song with nothing
        self.assertEqual(lyrics.find(path), ("", None, None, False))
        self.assertEqual(lyrics.find(self.song_file("")), ("", None, None, False))

    def test_lrclib_needs_consent_tags_and_length(self):
        path = self.song_file()
        with patch.object(lyrics.lrclib, "enabled", lambda: False):
            self.assertEqual(lyrics.find(path), ("", None, None, False))
        for label in (
            "MusicPlayer.Artist",
            "MusicPlayer.Title",
            "MusicPlayer.Duration",
        ):
            with patch.dict(self.labels, {label: ""}):
                self.assertEqual(lyrics.find(path)[0], "")
        self.assertEqual(self.asked, [])


class LookupTest(Kodi):
    def test_searching_clears_the_last_songs_source(self):
        self.props = {
            "lyrics_state": "none",
            "lyrics_source": "lrclib",
            "lyrics_instrumental": "true",
        }
        seen = []
        with patch.object(
            lyrics,
            "find",
            lambda path: seen.append(dict(self.props)) or ("", None, None, False),
        ):
            lyrics.lookup()
        self.assertEqual(seen, [{"lyrics_state": "searching"}])

    def test_synced_lines_before_their_state(self):
        self.labels["MusicPlayer.Lyrics"] = LRC
        found = lyrics.lookup()
        self.assertEqual(self.order, [*lyrics.SEARCHING, *lyrics.PROPS])
        self.assertEqual(json.loads(self.props.pop("lyrics_lines")), LINES)
        self.assertTrue(self.props.pop("lyrics_revision"))
        self.assertEqual(
            self.props,
            {
                "lyrics_state": "synced",
                "lyrics_source": "embedded",
                "lyrics_index": "-1",
                "lyrics_m2": "-3",
                "lyrics_m1": "-2",
                "lyrics_p1": "0",
                "lyrics_p2": "1",
                "lyrics_p3": "2",
                "lyrics_p4": "3",
                "lyrics_p5": "4",
            },
        )
        self.assertEqual(found.times, [1470, 7050, 10060])

    def test_plain_none_and_instrumental_clear_the_rest(self):
        self.props = dict.fromkeys(lyrics.PROPS, "old")
        self.labels["MusicPlayer.Lyrics"] = "Feel good"
        found = lyrics.lookup()
        revision = self.props.pop("lyrics_revision")
        self.assertEqual(
            self.props,
            {
                "lyrics_state": "plain",
                "lyrics_source": "embedded",
                "lyrics_plain": "Feel good",
            },
        )
        self.assertEqual(found.tick(5.0), 1)  # nothing to follow
        self.labels["MusicPlayer.Lyrics"] = ""
        lyrics.lookup()
        self.assertNotEqual(self.props.pop("lyrics_revision"), revision)
        self.assertEqual(self.props, {"lyrics_state": "none"})
        self.lrclib[SONG] = {"synced": None, "plain": None, "instrumental": True}
        lyrics.lookup()
        self.props.pop("lyrics_revision")
        self.assertEqual(
            self.props,
            {
                "lyrics_state": "none",
                "lyrics_source": "lrclib",
                "lyrics_instrumental": "true",
            },
        )

    def test_prefetches_the_next_song(self):
        self.labels |= {
            "MusicPlayer.offset(1).Artist": "Blur",
            "MusicPlayer.offset(1).Title": "Song 2",
            "MusicPlayer.offset(1).Album": "Blur",
            "MusicPlayer.offset(1).Duration": "02:02",
        }
        lyrics.lookup()
        next_song = ("Blur", "Song 2", "Blur", 122)
        self.assertEqual((self.asked, self.threads), ([SONG, next_song], [next_song]))
        self.labels["MusicPlayer.offset(1).Title"] = ""  # the last song queued
        lyrics.lookup()
        self.assertEqual(self.asked[2:], [SONG])

    def test_clear(self):
        self.labels["MusicPlayer.Lyrics"] = LRC
        lyrics.lookup()
        lyrics.clear()
        self.assertEqual(self.props, {})


class StepTest(Kodi):
    def setUp(self):
        super().setUp()
        self.conditions.add("Window.IsActive(visualisation)")
        for target in (3510, 3511):
            self.list(target, 10, 1)
        self.lyrics = lyrics.Lyrics([[1000 * s, f"line {s}"] for s in range(2, 12)])

    def list(self, target, count, current):
        """A list's NumItems and CurrentItem; empty with no items, as Kodi reads."""
        self.labels[f"Container({target}).NumItems"] = f"{count}" if count else ""
        self.labels[f"Container({target}).CurrentItem"] = f"{current}" if count else ""

    def test_steps_by_the_lists_own_position(self):
        self.assertAlmostEqual(self.lyrics.tick(1.25), 0.75)  # before the first line
        self.assertEqual((self.builtins, self.props), ([], {}))  # lookup published -1
        self.assertAlmostEqual(self.lyrics.tick(2.0), 1)
        self.assertEqual(self.builtins, [])  # line 0 is the list's first item
        self.assertEqual(
            (self.props["lyrics_index"], self.props["lyrics_p5"]), ("0", "5")
        )
        self.lyrics.tick(3.5)
        self.assertEqual(self.builtins, ["Control.Move(3510,1)"])
        self.lyrics.tick(3.6)  # the move is queued: the list still reads item 1
        self.assertEqual(len(self.builtins), 1)
        self.lyrics.tick(6.0)  # a modal dialog took that step: made up now
        self.assertEqual(self.builtins[-1], "Control.Move(3510,4)")
        self.list(3510, 10, 5)
        self.lyrics.tick(2.5)  # a seek back
        self.assertEqual(self.builtins[-1], "Control.Move(3510,-4)")
        self.assertEqual(self.props["lyrics_m2"], "-2")

    def test_waits(self):
        self.assertAlmostEqual(self.lyrics.tick(2.999), lyrics.MIN_WAIT)
        self.conditions.add("Player.Paused")
        self.assertEqual(self.lyrics.tick(4.5), 1)
        self.conditions.discard("Player.Paused")
        self.assertEqual(self.lyrics.tick(11.5), 1)  # the last line
        self.assertAlmostEqual(self.lyrics.tick(4.5), 0.5)

    def test_osd_browse_list(self):
        self.lyrics.tick(4.5)  # line 2
        self.conditions.add("Window.IsActive(musicosd)")
        self.list(3511, 0, 0)  # still filling
        self.lyrics.tick(4.6)
        self.assertEqual(self.builtins, ["Control.Move(3510,2)"])
        self.list(3510, 10, 3)  # Kodi ran that move
        self.list(3511, 10, 1)
        self.lyrics.tick(4.7)
        self.assertEqual(self.builtins[-1], "Control.Move(3511,2)")
        self.conditions.add("Control.HasFocus(3511)")  # browsing: left alone
        self.list(3511, 10, 8)
        self.lyrics.tick(5.5)
        self.assertEqual(len(self.builtins), 2)
        self.conditions.discard("Control.HasFocus(3511)")  # back to the buttons
        self.lyrics.tick(5.6)
        self.assertEqual(self.builtins[-1], "Control.Move(3511,-4)")
        self.conditions -= {
            "Window.IsActive(musicosd)",
            "Window.IsActive(visualisation)",
        }
        self.lyrics.tick(6.5)  # neither window: no step, the line still published
        self.assertEqual((len(self.builtins), self.props["lyrics_index"]), (3, "4"))
        self.conditions.add("Window.IsActive(visualisation)")
        self.lyrics.tick(6.6)
        self.assertEqual(self.builtins[-1], "Control.Move(3510,2)")


class PollerHookTest(Kodi):
    def setUp(self):
        super().setUp()
        self.monitor = object.__new__(player.PlayerMonitor)
        self.monitor._lyrics = None
        self.playing, self.lookups = True, []
        self.monitor.isPlayingAudio = lambda: self.playing
        self.monitor.getTime = lambda: 6.5
        self.labels["MusicPlayer.Lyrics"] = LRC
        lookup = lyrics.lookup
        patcher = patch.object(
            lyrics, "lookup", lambda: self.lookups.append(1) or lookup()
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_setting_on_mid_song_looks_up_once(self):
        self.assertEqual(self.monitor.watch_lyrics(), 1)  # setting off
        self.assertEqual((self.lookups, self.props), ([], {}))
        self.conditions.add(lyrics.ENABLED)
        self.assertAlmostEqual(self.monitor.watch_lyrics(), 0.55)  # to 00:07.05
        self.assertEqual(self.props["lyrics_index"], "0")
        self.monitor.watch_lyrics()
        self.assertEqual(len(self.lookups), 1)

    def test_off_clears_and_a_start_waits_for_its_av_start(self):
        self.conditions.add(lyrics.ENABLED)
        self.monitor.watch_lyrics()
        self.conditions.discard(lyrics.ENABLED)
        self.monitor.watch_lyrics()
        self.assertEqual((self.monitor._lyrics, self.props), (None, {}))
        self.conditions.add(lyrics.ENABLED)
        self.monitor._lyrics = False  # a new song started: its AV start looks up
        self.assertEqual(self.monitor.watch_lyrics(), 1)
        self.monitor._lyrics, self.playing = None, False  # a video
        self.assertEqual(self.monitor.watch_lyrics(), 1)
        self.assertEqual(len(self.lookups), 1)


class PluginAndActionTest(unittest.TestCase):
    def setUp(self):
        self.home = sys.modules["xbmcgui"].Window(10000)
        self.addCleanup(self.home.clearProperty, lrc.LINES)
        patcher = patch.object(handlers, "set_items", list)  # the items as dicts
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_one_item_per_line(self):
        self.home.setProperty(lrc.LINES, json.dumps(LINES))
        items = object.__new__(handlers.PluginHandlers).lyrics()
        self.assertEqual(
            items,
            [
                {
                    "file": "plugin://script.copacetic.helper/lyrics/0",
                    "label": "Feel good",
                    "properties": {"index": 0, "time": 1470, "gap": ""},
                },
                {
                    "file": "plugin://script.copacetic.helper/lyrics/1",
                    "label": "Sha, sha-ba-da",
                    "properties": {"index": 1, "time": 7050, "gap": ""},
                },
                {
                    "file": "plugin://script.copacetic.helper/lyrics/2",
                    "label": "",
                    "properties": {"index": 2, "time": 10060, "gap": "true"},
                },
            ],
        )
        self.home.clearProperty(lrc.LINES)  # plain, none, or not playing
        self.assertIsNone(object.__new__(handlers.PluginHandlers).lyrics())

    def test_seek_to_a_line(self):
        seeks = []
        player_ = type("Player", (), {"seekTime": lambda self, s: seeks.append(s)})
        with patch.object(actions.xbmc, "Player", player_, create=True):
            actions.lyrics_seek(time="65300")
            actions.lyrics_seek(time="0")
        self.assertEqual(seeks, [65.3, 0.0])
        self.assertIs(actions.REGISTRY["lyrics_seek"], actions.lyrics_seek)


if __name__ == "__main__":
    unittest.main()
