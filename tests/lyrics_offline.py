"""
Offline checks for lyrics: the LRC parser (shared/lrc.py); the service's sources in
order (a .lrc beside the song, its tags, LRCLIB), what it publishes, how it steps
the visualisation's follow list (3510) and the music OSD's browse list (3511) by
their selected item, and the player monitor's poller hook (service/lyrics.py,
service/player.py); a library song's (lyrics.library, shared/tags.py: ID3v2, FLAC,
Ogg and APEv2 tags, art unread); the info=lyrics and info=lyrics_plain plugin paths,
with type=song&id= served or not, the lyrics_seek action, the LRCLIB row's
toggle_setting and the Lyrics row's toggle_skin_bool.
Infolabels and conditions are dicts; nothing reaches the network.
Run from the helper root: python tests/lyrics_offline.py
"""

import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
    """
    xbmcvfs.File over a local path: readBytes gives a bytearray, as Kodi's does (0,
    the rest), seek moves from the start (0) or here (1); read counts the bytes read.
    """

    read = 0

    def __init__(self, path):
        self.data, self.pos = Path(path).read_bytes(), 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def readBytes(self, count=0):
        chunk = self.data[self.pos : self.pos + count if count else None]
        self.pos += len(chunk)
        File.read += len(chunk)
        return bytearray(chunk)

    def seek(self, offset, whence=0):
        self.pos = offset + self.pos * whence
        return self.pos

    def size(self):
        return len(self.data)


sys.modules["xbmcvfs"].File = File
sys.path.insert(0, str(HELPER))

from resources.lib.plugin import handlers  # noqa: E402
from resources.lib.script import actions  # noqa: E402
from resources.lib.service import lyrics, player  # noqa: E402
from resources.lib.shared import lrc  # noqa: E402

LRC = "[ar:Lamplighters]\n[00:01.47]Rain on tin\n[00:07.05]La, la-di-da\n[00:10.06]\n"
LINES = [[1470, "Rain on tin"], [7050, "La, la-di-da"], [10060, ""]]
INTRO = [[0, ""], *LINES]  # as published: a gap for the intro before 00:01.47
SONG = ("Lamplighters", "Tin Roof Rain", "Weathervane", 223)
TAGS = {
    "MusicPlayer.Artist": "Lamplighters",
    "MusicPlayer.Title": "Tin Roof Rain",
    "MusicPlayer.Album": "Weathervane",
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
            "[ar:Lamplighters]\n[ti:Tin Roof Rain]\n[length: 03:43]\n"
            "[00:01.00]<00:01.00>Rain <00:01.40>on tin\n\n[00:05.00]\n"
            "[00:06.00]  Streetlights humming low  \n[offset:+500]\n[re:LRC Maker]"
        )
        self.assertEqual(
            lrc.parse(text),
            [[500, "Rain on tin"], [4500, ""], [5500, "Streetlights humming low"]],
        )
        self.assertEqual(lrc.parse("[offset:-250]\n[00:00.10]a")[0], [350, "a"])
        self.assertEqual(lrc.parse("[offset:+500]\n[00:00.10]a")[0], [0, "a"])

    def test_plain_text_has_no_lines(self):
        self.assertEqual(lrc.parse("Rain on tin\n\nStreetlights humming low"), [])
        self.assertEqual(lrc.parse(""), [])

    def test_plain_drops_tags_keeps_verses(self):
        text = (
            "[ar:Lamps]\r\n[length: 03:43]\r\n[Chorus]\r\n  Rain on tin  \r\n\r\n"
            "[00:01,50]Streetlights [00:02,00]humming\r\n[Verse 1: Lead]\r\n[re:]"
        )
        self.assertEqual(
            lrc.plain(text),
            "[Chorus]\nRain on tin\n\nStreetlights humming\n[Verse 1: Lead]",
        )
        self.assertEqual(lrc.plain("[ar:Lamplighters]\n[ti:Tin Roof Rain]\n\n"), "")


class Kodi(unittest.TestCase):
    """Infolabels, conditions and Home properties as dicts; builtins and asks."""

    def setUp(self):
        self.labels, self.conditions, self.props = dict(TAGS), set(), {}
        self.order, self.builtins, self.asked, self.errors = [], [], [], []
        self.lrclib, self.cache = {}, {}  # by song: LRCLIB's payload, (payload, fresh)
        self.running = True  # a Fetch runs as it starts, here and now
        self.exiting = False  # Kodi asked the service to stop
        for target, name, value in (
            (lyrics, "infolabel", lambda key: self.labels.get(key, "")),
            (lyrics, "condition", lambda key: key in self.conditions),
            (lyrics, "window_property", self.prop),
            (lyrics.log, "execute", self.builtins.append),
            (lyrics.log, "exception", self.errors.append),
            (lyrics, "skin_metric", lambda name: None),  # no skin: nothing long
            (lyrics.lrclib, "enabled", lambda: True),
            (lyrics.lrclib, "lyrics", lambda *args: self.ask("lyrics", *args)),
            (lyrics.lrclib, "prefetch", lambda *args: self.ask("prefetch", *args)),
            (lyrics.lrclib, "saved", lambda *song: self.cache.get(song)),
            (lyrics.Fetch, "start", lambda fetch: self.running and fetch.run()),
            (lyrics.Fetch, "is_alive", lambda fetch: fetch.song in lyrics._fetches),
            (player, "condition", lambda key: key in self.conditions),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(lyrics._fetches.clear)

    def prop(self, key, value=""):
        self.order.append(key)
        if value:
            self.props[key] = value
        else:
            self.props.pop(key, None)

    def ask(self, kind, *args):
        """lrclib.lyrics or prefetch: the song's answer, Aborted once Kodi exits."""
        *song, aborted = args
        self.asked.append((kind, song := tuple(song)))
        if aborted():
            raise lyrics.lrclib.Aborted
        if isinstance(found := self.lrclib.get(song), Exception):
            raise found
        return found

    def aborted(self):
        """The service thread's Monitor.abortRequested."""
        return self.exiting


class SourcesTest(Kodi):
    def song_file(self, lrc_text=None, encoding="utf-8-sig"):
        folder = Path(tempfile.mkdtemp())
        (folder / "Tin Roof Rain.flac").touch()
        if lrc_text is not None:
            (folder / "Tin Roof Rain.lrc").write_bytes(lrc_text.encode(encoding))
        return str(folder / "Tin Roof Rain.flac")

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

    def test_windows_1252_words_read_right(self):
        # Each is valid GB18030 too: a guess at Chinese would garble them
        for words in ("Don’t stop me now", "Vår kärlek", "Über alles", "naïve"):
            path = self.song_file(f"[00:01.00]{words}", "cp1252")
            self.assertEqual(lyrics.find(path)[1], [[1000, words]], words)

    def test_a_sidecar_of_only_tags_falls_through(self):
        self.labels["MusicPlayer.Lyrics"] = "[00:02.00]embedded"
        path = self.song_file("[ar:Lamplighters]\n[ti:Tin Roof Rain]\n[by:someone]\n")
        self.assertEqual(lyrics.find(path)[:2], ("embedded", [[2000, "embedded"]]))
        unsupported = self.song_file("[ar:Lamplighters]\n[00:01,50]Rain on tin\n")
        self.assertEqual(lyrics.find(unsupported), ("file", None, "Rain on tin", False))

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

    def test_embedded_plain_else_none(self):
        path = self.song_file()
        self.labels["MusicPlayer.Lyrics"] = (
            "\r\nRain on tin\r\n\r\nStreetlights humming\r\n"
        )
        self.assertEqual(
            lyrics.find(path),
            ("embedded", None, "Rain on tin\n\nStreetlights humming", False),
        )
        self.labels["MusicPlayer.Lyrics"] = " "
        self.assertIsNone(lyrics.find(path))
        self.assertIsNone(lyrics.find(self.song_file("")))
        self.assertEqual(self.asked, [])


class LookupTest(Kodi):
    def test_searching_clears_the_last_songs_source(self):
        self.props = {
            "lyrics_state": "none",
            "lyrics_source": "lrclib",
            "lyrics_instrumental": "true",
        }
        seen = []
        with patch.object(lyrics, "find", lambda path: seen.append(dict(self.props))):
            lyrics.lookup(self.aborted)
        self.assertEqual(seen, [{"lyrics_state": "searching"}])

    def test_synced_lines_before_their_state(self):
        self.labels["MusicPlayer.Lyrics"] = LRC
        found = lyrics.lookup(self.aborted)
        self.assertEqual(self.order, [*lyrics.SEARCHING, *lyrics.PROPS])
        self.assertEqual(json.loads(self.props.pop("lyrics_lines")), INTRO)
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
        self.assertEqual(found.times, [0, 1470, 7050, 10060])

    def test_only_an_intro_gets_a_gap(self):
        self.assertEqual(lyrics.publish("file", [[0, "Go"]], None, False), [[0, "Go"]])
        gap = [[500, ""], [1470, "Go"]]  # opens on an empty stamp: one gap, not two
        self.assertEqual(lyrics.publish("file", gap, None, False), gap)

    def test_plain_none_and_instrumental_clear_the_rest(self):
        self.props = dict.fromkeys(lyrics.PROPS, "old")
        self.labels["MusicPlayer.Lyrics"] = "Rain on tin"
        found = lyrics.lookup(self.aborted)
        revision = self.props.pop("lyrics_revision")
        self.assertEqual(
            self.props,
            {
                "lyrics_state": "plain",
                "lyrics_source": "embedded",
                "lyrics_plain": "Rain on tin",
            },
        )
        self.assertEqual(found.tick(5.0), 1)  # nothing to follow
        self.labels["MusicPlayer.Lyrics"] = ""
        lyrics.lookup(self.aborted).tick(5.0)  # LRCLIB's answer (none) lands at a pass
        self.assertNotEqual(self.props.pop("lyrics_revision"), revision)
        self.assertEqual(self.props, {"lyrics_state": "none"})
        self.lrclib[SONG] = {"synced": None, "plain": None, "instrumental": True}
        found = lyrics.lookup(self.aborted)
        self.assertEqual(self.props, {"lyrics_state": "searching"})  # till a pass
        self.assertEqual(found.tick(5.0), 1)
        self.props.pop("lyrics_revision")
        self.assertEqual(
            self.props,
            {
                "lyrics_state": "none",
                "lyrics_source": "lrclib",
                "lyrics_instrumental": "true",
            },
        )

    def test_long_lines_overflow_two_lines_at_660(self):
        metric = type("Metric", (), {"getlength": lambda self, text: 30 * len(text)})
        with patch.object(lyrics, "skin_metric", lambda name: metric()):
            # 22 characters a line at 30 px: 44 fit in two, a 45th wraps to a third
            self.assertEqual(
                lyrics.long_lines([[0, "word " * 8], [1, "word " * 9], [2, ""]]),
                [1],
            )

    def test_clear(self):
        self.labels["MusicPlayer.Lyrics"] = LRC
        lyrics.lookup(self.aborted)
        lyrics.clear()
        self.assertEqual(self.props, {})


NEXT = ("Blur", "Song 2", "Blur", 122)
QUEUED = {
    "MusicPlayer.offset(1).Artist": "Blur",
    "MusicPlayer.offset(1).Title": "Song 2",
    "MusicPlayer.offset(1).Album": "Blur",
    "MusicPlayer.offset(1).Duration": "02:02",
}


class LrclibTest(Kodi):
    def test_asked_off_the_service_thread(self):
        self.running = False  # the request is out
        self.lrclib[SONG] = {"synced": LINES, "plain": None, "instrumental": False}
        found = lyrics.lookup(self.aborted)
        self.assertEqual((self.asked, self.props), ([], {"lyrics_state": "searching"}))
        self.assertEqual(found.tick(1.0), lyrics.ASKING_WAIT)
        lyrics.lookup(
            self.aborted
        )  # the setting turned off and on again: the same request
        self.assertEqual(list(lyrics._fetches), [SONG])
        lyrics._fetches[SONG].run()  # it answers
        self.assertAlmostEqual(found.tick(1.0), 0.47)
        self.assertEqual(
            (self.props["lyrics_state"], self.props["lyrics_source"]),
            ("synced", "lrclib"),
        )
        self.assertEqual(
            (found.times, self.asked), ([0, 1470, 7050, 10060], [("lyrics", SONG)])
        )

    def test_a_fresh_cached_answer_shows_at_once(self):
        self.cache[SONG] = (
            {"synced": None, "plain": "Rain on tin", "instrumental": False},
            True,
        )
        lyrics.lookup(self.aborted)
        self.assertEqual(self.props["lyrics_plain"], "Rain on tin")
        self.cache[SONG] = (None, True)  # a failure, still fresh: none, not asked
        lyrics.lookup(self.aborted)
        self.assertEqual(self.props["lyrics_state"], "none")
        self.assertEqual(self.asked, [])
        self.cache[SONG] = (None, False)
        lyrics.lookup(self.aborted).tick(0.0)
        self.assertEqual(self.asked, [("lyrics", SONG)])

    def test_prefetches_the_next_song_once(self):
        self.labels |= QUEUED | {"MusicPlayer.Lyrics": LRC}  # this one has its own
        lyrics.lookup(self.aborted)
        self.assertEqual(self.asked, [("prefetch", NEXT)])
        self.cache[NEXT] = ({}, True)  # fetched already
        lyrics.lookup(self.aborted)
        self.labels["MusicPlayer.offset(1).Title"] = ""  # the last song queued
        lyrics.lookup(self.aborted)
        self.assertEqual(len(self.asked), 1)

    def test_the_prefetch_in_flight_serves_its_start(self):
        self.running = False
        self.labels |= QUEUED | {"MusicPlayer.Lyrics": LRC}
        lyrics.lookup(self.aborted)
        self.labels |= dict(zip(TAGS, ("Blur", "Song 2", "Blur", "02:02")))
        self.labels |= {"MusicPlayer.Lyrics": "", "MusicPlayer.offset(1).Title": ""}
        found = lyrics.lookup(self.aborted)  # Song 2 starts while its prefetch is out
        self.assertEqual(list(lyrics._fetches), [NEXT])
        self.lrclib[NEXT] = {"synced": None, "plain": "Woo-hoo", "instrumental": False}
        lyrics._fetches[NEXT].run()
        found.tick(0.0)
        self.assertEqual(self.asked, [("prefetch", NEXT)])  # one request
        self.assertEqual(self.props["lyrics_plain"], "Woo-hoo")

    def test_a_failed_prefetch_its_start_took_over_is_asked_again(self):
        self.running = False
        self.labels |= QUEUED | {"MusicPlayer.Lyrics": LRC}
        lyrics.lookup(self.aborted)
        self.labels |= dict(zip(TAGS, ("Blur", "Song 2", "Blur", "02:02")))
        self.labels |= {"MusicPlayer.Lyrics": "", "MusicPlayer.offset(1).Title": ""}
        found = lyrics.lookup(self.aborted)  # Song 2 starts while its prefetch is out
        lyrics._fetches[NEXT].run()  # and it fails (offline, or a 404)
        self.assertEqual(found.tick(0.0), lyrics.ASKING_WAIT)
        self.assertEqual(self.props["lyrics_state"], "searching")  # not "none"
        self.lrclib[NEXT] = {"synced": None, "plain": "Woo-hoo", "instrumental": False}
        lyrics._fetches[NEXT].run()  # the start's own request
        found.tick(0.2)
        self.assertEqual(self.asked, [("prefetch", NEXT), ("lyrics", NEXT)])
        self.assertEqual(self.props["lyrics_plain"], "Woo-hoo")

    def test_consent_tags_and_length(self):
        for off in (
            {"MusicPlayer.Artist": ""},
            {"MusicPlayer.Title": ""},
            {"MusicPlayer.Duration": ""},
        ):
            with patch.dict(self.labels, off):
                lyrics.lookup(self.aborted)
        with patch.object(lyrics.lrclib, "enabled", lambda: False):
            lyrics.lookup(self.aborted)
        self.assertEqual((self.asked, self.props["lyrics_state"]), ([], "none"))

    def test_no_new_request_once_kodi_exits(self):
        self.running = False
        self.labels |= QUEUED | {"MusicPlayer.Lyrics": LRC}
        lyrics.lookup(self.aborted)
        self.labels |= dict(zip(TAGS, ("Blur", "Song 2", "Blur", "02:02")))
        self.labels |= {"MusicPlayer.Lyrics": "", "MusicPlayer.offset(1).Title": ""}
        found = lyrics.lookup(self.aborted)  # Song 2 takes over its prefetch
        self.exiting = True
        lyrics._fetches[NEXT].run()  # it ends in Aborted
        self.assertEqual(found.tick(0.0), lyrics.ASKING_WAIT)
        self.assertEqual(lyrics._fetches, {})  # no new request started
        self.assertEqual(found.tick(0.2), 1)
        self.assertEqual(self.props["lyrics_state"], "none")
        lyrics.lookup(self.aborted)  # the setting turned on in the last pass
        self.assertEqual(lyrics._fetches, {})
        self.assertEqual(self.asked, [("prefetch", NEXT)])

    def test_kodi_exiting_stops_a_request_quietly(self):
        self.running = False
        found = lyrics.lookup(self.aborted)
        self.exiting = True  # while the request is out
        lyrics._fetches[SONG].run()
        self.assertEqual((self.asked, self.errors), ([("lyrics", SONG)], []))
        self.assertEqual(lyrics._fetches, {})  # the thread ended: Kodi needn't wait
        self.assertEqual(found.tick(0.0), 1)

    def test_cache_failures_are_logged_as_unknown(self):
        def broken(*song):
            raise sqlite3.OperationalError("database is locked")

        self.lrclib[SONG] = sqlite3.DatabaseError("database disk image is malformed")
        with patch.object(lyrics.lrclib, "saved", broken):
            found = lyrics.lookup(self.aborted)
        self.assertEqual(found.tick(0.0), 1)
        self.assertEqual(self.props["lyrics_state"], "none")
        self.assertEqual(len(self.errors), 2)  # the read, then the request's write


class StepTest(Kodi):
    def setUp(self):
        super().setUp()
        self.conditions.add("Window.IsActive(visualisation)")
        for target in (3510, 3511):
            self.list(target, 10, 1)
        self.lyrics = lyrics.Lyrics([[1000 * s, f"line {s}"] for s in range(2, 12)])
        self.clock = 100.0
        patcher = patch.object(lyrics.time, "monotonic", lambda: self.clock)
        patcher.start()
        self.addCleanup(patcher.stop)

    def list(self, target, count, current):
        """A list's NumItems and CurrentItem; empty with no items, as Kodi reads."""
        self.labels[f"Container({target}).NumItems"] = f"{count}" if count else ""
        self.labels[f"Container({target}).CurrentItem"] = f"{current}" if count else ""

    def test_steps_by_the_lists_own_position(self):
        self.lyrics.tick(1.25)  # before the first line
        self.assertEqual((self.builtins, self.props), ([], {}))  # lookup published -1
        self.lyrics.tick(2.0)
        self.assertEqual(self.builtins, [])  # line 0 is the list's first item
        self.assertEqual(
            (self.props["lyrics_index"], self.props["lyrics_p5"]), ("0", "5")
        )
        self.lyrics.tick(3.5)
        self.assertEqual(self.builtins, ["Control.Move(3510,1)"])
        self.clock += 0.2
        self.lyrics.tick(4.0)  # the move is queued: the list still reads item 1
        self.assertEqual(len(self.builtins), 1)
        self.clock += 0.5
        self.lyrics.tick(6.0)  # a modal dialog took that step: made up now
        self.assertEqual(self.builtins[-1], "Control.Move(3510,4)")
        self.list(3510, 10, 5)
        self.lyrics.tick(2.5)  # a seek back, once that move landed
        self.assertEqual(self.builtins[-1], "Control.Move(3510,-4)")
        self.assertEqual(self.props["lyrics_m2"], "-2")

    def test_a_list_shown_again_is_put_right_at_the_next_pass(self):
        self.lyrics.tick(6.0)
        self.list(3510, 10, 5)  # Kodi ran it
        self.lyrics.tick(6.2)
        self.list(3510, 10, 1)  # reloaded, or the window opened again, on line 0
        self.lyrics.tick(6.4)  # the same line
        self.assertEqual(
            self.builtins, ["Control.Move(3510,4)", "Control.Move(3510,4)"]
        )
        self.list(3510, 3, 1)  # the last song's shorter list: no wrap past its end
        self.lyrics.tick(6.6)  # that move is still queued: nothing on top of it
        self.assertEqual(len(self.builtins), 2)
        self.clock += 1
        self.lyrics.tick(6.8)
        self.assertEqual(self.builtins[-1], "Control.Move(3510,2)")

    def test_waits(self):
        self.assertAlmostEqual(self.lyrics.tick(1.9), 0.1)
        self.assertEqual(self.lyrics.tick(1.0), lyrics.SHOWN_WAIT)
        self.conditions.discard("Window.IsActive(visualisation)")
        self.assertAlmostEqual(self.lyrics.tick(1.0), 1)
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
        self.clock += 2
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
    def abortRequested(self):
        """The player monitor's own Monitor, made on the service thread."""
        return self.exiting

    def test_lookups_get_the_service_threads_abort(self):
        self.conditions.add(lyrics.ENABLED)
        self.monitor.watch_lyrics()
        self.assertEqual(self.lookups, [self.abortRequested])

    def setUp(self):
        super().setUp()
        self.monitor = object.__new__(player.PlayerMonitor)
        self.monitor._lyrics = None
        self.playing, self.lookups = True, []
        self.monitor.isPlayingAudio = lambda: self.playing
        self.monitor.getTime = lambda: 6.5
        self.labels["MusicPlayer.Lyrics"] = LRC
        self.monitor._monitor = self  # its abortRequested
        lookup = lyrics.lookup
        patcher = patch.object(
            lyrics,
            "lookup",
            lambda aborted: self.lookups.append(aborted) or lookup(aborted),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_setting_on_mid_song_looks_up_once(self):
        self.assertEqual(self.monitor.watch_lyrics(), 1)  # setting off
        self.assertEqual((self.lookups, self.props), ([], {}))
        self.conditions.add(lyrics.ENABLED)
        self.assertAlmostEqual(self.monitor.watch_lyrics(), 0.55)  # to 00:07.05
        self.assertEqual(self.props["lyrics_index"], "1")  # after the intro's gap
        self.monitor.watch_lyrics()
        self.assertEqual(len(self.lookups), 1)

    def test_a_late_answer_lands_only_for_its_song(self):
        self.running = False
        self.labels["MusicPlayer.Lyrics"] = ""
        self.conditions.add(lyrics.ENABLED)
        self.assertEqual(self.monitor.watch_lyrics(), lyrics.ASKING_WAIT)
        self.monitor._lyrics = False  # the next file started: its AV start looks up
        self.lrclib[SONG] = {"synced": LINES, "plain": None, "instrumental": False}
        lyrics._fetches[SONG].run()
        self.assertEqual(self.monitor.watch_lyrics(), 1)
        self.assertEqual(self.props, {"lyrics_state": "searching"})

    def start(self, grow):
        """An audio start whose endless queue grows, as grow(song) does."""
        self.conditions |= {lyrics.ENABLED, player.ENDLESS_QUEUE}
        tag = SimpleNamespace(getDbId=lambda: 5, getGenres=list, getDisc=int)
        tag.getArtist = tag.getAlbumArtist = tag.getAlbum = str
        monitor = self.monitor
        monitor.getMusicInfoTag = lambda: tag
        monitor._publish = monitor._record_speed_dial = monitor._album_path = str
        monitor._extend_queue = grow
        item = {"result": {"item": {"albumid": 0}}}
        with (
            patch.object(player, "json_call", lambda *a, **k: item),
            patch.object(player, "window_property", lambda *a, **k: None),
        ):
            monitor._handle_audio_start()

    def test_a_song_the_endless_queue_adds_is_prefetched(self):
        def grow(song):  # the last song queued: the lookup found none next
            self.assertEqual(self.lookups, [self.abortRequested])
            self.labels |= QUEUED
            return True

        self.start(grow)
        self.assertEqual(self.asked, [("prefetch", NEXT)])

    def test_a_growth_behind_the_next_song_asks_nothing_again(self):
        self.labels |= QUEUED  # its prefetch fails: nothing is cached for it
        self.start(lambda song: True)  # songs added after it
        self.assertEqual(self.asked, [("prefetch", NEXT)])

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


def syncsafe(size):
    """An ID3v2 size: four bytes of seven bits."""
    return bytes(size >> shift & 0x7F for shift in (21, 14, 7, 0))


def id3_frame(name, data, version=4):
    """One ID3v2.3 or 2.4 frame, no flags."""
    size = syncsafe(len(data)) if version == 4 else len(data).to_bytes(4, "big")
    return name + size + b"\0\0" + data


def id3(*frames, version=4, unsync=False, audio=b"\xff\xfb"):
    """
    An ID3v2 tag of frames and 20 bytes of padding, then the audio; unsync: the
    whole tag unsynchronised (v2.3's flag), a 0 after every 0xFF.
    """
    body = b"".join(frames) + b"\0" * 20
    if unsync:
        body = body.replace(b"\xff", b"\xff\x00")
    flags = bytes([version, 0, 0x80 if unsync else 0])
    return b"ID3" + flags + syncsafe(len(body)) + body + audio


def vorbis(*comments):
    """A Vorbis comment: vendor, count, then each field with its length."""
    fields = [comment.encode() for comment in comments]
    return b"".join(
        (
            (4).to_bytes(4, "little"),
            b"test",
            len(fields).to_bytes(4, "little"),
            *(len(field).to_bytes(4, "little") + field for field in fields),
        )
    )


def flac(*comments, picture=b""):
    """fLaC, STREAMINFO, a PICTURE block, then the VORBIS_COMMENT block, last."""
    blocks = ((0, b"\0" * 34), (6, picture), (0x80 | 4, vorbis(*comments)))
    return b"fLaC" + b"".join(
        bytes([kind]) + len(data).to_bytes(3, "big") + data for kind, data in blocks
    )


def ogg(*packets, per_page=8):
    """Ogg pages of packets, per_page segments a page, so a long packet spans pages."""
    segments = [
        packet[at : at + 255]
        for packet in packets
        for at in range(0, len(packet) + 1, 255)  # a full last segment gets a 0 one
    ]
    pages = (segments[at : at + per_page] for at in range(0, len(segments), per_page))
    return b"".join(
        b"OggS" + bytes(22) + bytes([len(page), *map(len, page)]) + b"".join(page)
        for page in pages
    )


def ape(*items, audio=b"MAC \x96\x0f", id3v1=False):
    """Audio, then an APEv2 tag of (key, value, flags) items, its footer, an ID3v1."""
    body = b"".join(
        len(value).to_bytes(4, "little") + bytes([flags, 0, 0, 0]) + key + b"\0" + value
        for key, value, flags in items
    )
    sizes = (2000, len(body) + 32, len(items))  # version, items and footer, count
    footer = b"APETAGEX" + b"".join(n.to_bytes(4, "little") for n in sizes)
    return audio + body + footer + bytes(12) + (b"TAG" + bytes(125) if id3v1 else b"")


# Invented lines: no real song's lyrics in fixtures
VERSES = "Paper lanterns over the harbour\nWe counted ships until the morning"
TIMED = "[ar:The Inventions]\n[00:04.00]Paper lanterns over the harbour\n[00:09.50]\n"
DETAILS = {
    "displayartist": "The Inventions",
    "title": "Paper Lanterns",
    "album": "Harbour Lights",
    "duration": 201,
}
KEY = ("The Inventions", "Paper Lanterns", "Harbour Lights", 201)


class LibrarySongTest(Kodi):
    """lyrics.library and info=lyrics_plain&type=song: a song that isn't playing."""

    def song(self, data=b"", name="Paper Lanterns.mp3", lrc_text=None):
        folder = Path(tempfile.mkdtemp())
        (folder / name).write_bytes(data)
        if lrc_text is not None:
            (folder / name).with_suffix(".lrc").write_text(lrc_text)
        return DETAILS | {"file": str(folder / name)}

    def test_id3_lyrics_skip_the_art_unread(self):
        art = id3_frame(b"APIC", b"\0image/jpeg\0\3\0" + b"\x89" * 50000)
        lyric = id3_frame(b"USLT", b"\3eng" + b"note\0" + VERSES.encode())
        path = self.song(id3(id3_frame(b"TIT2", b"\3Paper Lanterns"), art, lyric))[
            "file"
        ]
        File.read = 0
        self.assertEqual(lyrics.tags.lyrics(path), VERSES)
        self.assertLess(File.read, 1000)  # frame headers and the lyrics alone
        utf16 = b"\1eng" + "d".encode("utf-16") + b"\0\0" + VERSES.encode("utf-16")
        path = self.song(id3(id3_frame(b"USLT", utf16, version=3), version=3))["file"]
        self.assertEqual(lyrics.tags.lyrics(path), VERSES)
        self.assertEqual(lyrics.tags.lyrics(self.song(id3())["file"]), "")

    def test_id3_v23_unsynchronised_tag_read_in_memory(self):
        # The art's 0xFF bytes push every frame after it on: its sizes count the
        # bytes once the tag is undone, as v2.3 sets them
        art = id3_frame(b"APIC", b"\0image/jpeg\0\3\0" + b"\xff\xe0" * 300, version=3)
        words = "Paper lanterns ÿ over the harbour"  # Latin-1 0xFF in the text too
        lyric = id3_frame(b"USLT", b"\0eng\0" + words.encode("latin-1"), version=3)
        song = self.song(id3(art, lyric, version=3, unsync=True))
        self.assertEqual(lyrics.tags.lyrics(song["file"]), words)

    def test_id3_last_lyrics_frame_wins_past_grouping_and_length(self):
        first = id3_frame(b"USLT", b"\3eng\0Salt on the window")
        # v2.4: a grouping byte (0x40) and a data length (0x01) ahead of the text
        data = b"\7" + syncsafe(30) + b"\3eng\0" + VERSES.encode()
        size = syncsafe(len(data))
        last = b"USLT" + size + b"\0" + bytes([0x41]) + data
        self.assertEqual(
            lyrics.tags.lyrics(self.song(id3(first, last))["file"]), VERSES
        )
        grouped = data[:1] + data[5:]  # v2.3: the grouping byte (0x20) alone
        frame = b"USLT" + len(grouped).to_bytes(4, "big") + b"\0\x20" + grouped
        song = self.song(id3(first, frame, version=3))
        self.assertEqual(lyrics.tags.lyrics(song["file"]), VERSES)

    def test_flac_behind_an_id3_tag(self):
        data = id3(id3_frame(b"TIT2", b"\3x"), audio=flac(f"LYRICS={VERSES}"))
        path = self.song(data, "Paper Lanterns.flac")["file"]
        self.assertEqual(lyrics.tags.lyrics(path), VERSES)

    def test_flac_lyrics_comment_past_its_picture(self):
        data = flac("TITLE=Paper Lanterns", f"lyrics={VERSES}", picture=b"\0" * 50000)
        path = self.song(data, "Paper Lanterns.flac")["file"]
        File.read = 0
        self.assertEqual(lyrics.tags.lyrics(path), VERSES)
        self.assertLess(File.read, 1000)
        self.assertEqual(lyrics.tags.lyrics(self.song(flac("TITLE=x"))["file"]), "")
        self.assertEqual(lyrics.tags.lyrics(self.song(b"RIFF\0\0")["file"]), "")

    def test_ogg_vorbis_opus_and_ogg_flac_comments_across_pages(self):
        # art ahead of the lyrics: the comment packet spans several pages
        comment = vorbis("METADATA_BLOCK_PICTURE=" + "A" * 5000, f"Lyrics={VERSES}")
        streams = (
            (b"\x01vorbis" + bytes(23), b"\x03vorbis" + comment + b"\x01"),
            (b"OpusHead" + bytes(11), b"OpusTags" + comment),
            (
                b"\x7fFLAC" + bytes(46),
                b"\x84" + len(comment).to_bytes(3, "big") + comment,
            ),
        )
        for head, packet in streams:
            path = self.song(ogg(head, packet), "Paper Lanterns.ogg")["file"]
            self.assertEqual(lyrics.tags.lyrics(path), VERSES)
        empty = ogg(b"OpusHead" + bytes(11), b"OpusTags" + vorbis("TITLE=x"))
        self.assertEqual(lyrics.tags.lyrics(self.song(empty)["file"]), "")
        self.assertEqual(lyrics.tags.lyrics(self.song(ogg(b"x", b"y"))["file"]), "")

    def test_ogg_comment_read_up_to_max_tag(self):
        art = "METADATA_BLOCK_PICTURE=" + "A" * 2 * lyrics.tags.MAX_TAG
        packet = b"OpusTags" + vorbis(art, f"LYRICS={VERSES}")
        path = self.song(ogg(b"OpusHead" + bytes(11), packet, per_page=255))["file"]
        File.read = 0
        self.assertEqual(lyrics.tags.lyrics(path), "")  # behind the cut: missed
        self.assertLess(File.read, lyrics.tags.MAX_TAG + 2 * 65536)  # and a page

    def test_malformed_ogg_reads_as_none(self):
        opus = b"OpusHead" + bytes(11)
        # a field count of 2**32 - 1 over one field: bounded by the block's bytes
        huge = (4).to_bytes(4, "little") + b"test" + b"\xff" * 4 + vorbis("A=b")[12:]
        for data in (
            b"OggS\0\0",  # a page shorter than its header
            ogg(opus, b"OpusTags" + vorbis(f"LYRICS={VERSES}"))[:40],  # cut short
            ogg(opus, b"OpusTags" + huge),
            ogg(opus, b"OpusTags" + b"\xff" * 12),  # a vendor length past the end
        ):
            self.assertEqual(lyrics.tags.lyrics(self.song(data)["file"]), "")

    def test_ape_last_text_lyrics_item_ahead_of_an_id3v1_tag(self):
        items = (
            (b"Title", b"Paper Lanterns", 0),
            (b"Lyrics", b"Salt on the window", 0),
            (b"Lyrics", b"\x89PNG", 2),  # binary
            (b"LYRICS", VERSES.encode() + b"\0Salt on the window", 0),  # the last
        )
        for audio in (b"MAC \x96\x0f", b"wvpk", b"MPCK", b"MP+\x07"):
            for id3v1 in (False, True):
                path = self.song(ape(*items, audio=audio, id3v1=id3v1))["file"]
                self.assertEqual(lyrics.tags.lyrics(path), VERSES)
        # TagLib keeps the last: a binary one reads as none
        self.assertEqual(lyrics.tags.lyrics(self.song(ape(*items[:3]))["file"]), "")
        self.assertEqual(lyrics.tags.lyrics(self.song(ape(items[0]))["file"]), "")
        self.assertEqual(
            lyrics.tags.lyrics(self.song(b"wvpk" + bytes(200))["file"]), ""
        )

    def test_malformed_ape_reads_as_none(self):
        good = ape((b"Lyrics", VERSES.encode(), 0))
        body, footer = good[6:-32], good[-32:]

        def tag(size=None, count=1, items=body):
            size = len(items) + 32 if size is None else size
            fields = (
                footer[:12] + size.to_bytes(4, "little") + count.to_bytes(4, "little")
            )
            return b"MAC \x96\x0f" + items + fields + footer[20:]

        for data in (
            tag(size=0),
            tag(size=32),  # a footer and no items
            tag(size=10**6),  # past the file's start
            tag(count=2**32 - 1, items=bytes(9)),  # a count past the items
            tag(items=b"\0" * 8 + b"Lyrics"),  # a key with no end
            b"MP+",  # shorter than a footer
        ):
            self.assertEqual(lyrics.tags.lyrics(self.song(data)["file"]), "")
        self.assertEqual(lyrics.tags.lyrics(self.song(tag())["file"]), VERSES)

    def test_ape_tag_read_up_to_max_tag(self):
        art = (b"Cover Art (Front)", b"x\0" + bytes(2 * lyrics.tags.MAX_TAG), 2)
        path = self.song(ape(art, (b"Lyrics", VERSES.encode(), 0)))["file"]
        File.read = 0
        self.assertEqual(lyrics.tags.lyrics(path), "")
        self.assertLess(File.read, lyrics.tags.MAX_TAG + 1000)

    def test_lyrics_the_cap_cuts_read_as_none(self):
        # Lyrics that start under MAX_TAG and end past it: a part would win over
        # LRCLIB's whole answer, so they read as none
        words = "Paper lanterns over the harbour\n" * 112  # 3584 characters
        opus = b"OpusHead" + bytes(11)
        art = "METADATA_BLOCK_PICTURE=" + "A" * (lyrics.tags.MAX_TAG - 1047)
        comment = b"OpusTags" + vorbis(art, f"LYRICS={words}")
        self.assertLess(comment.index(b"LYRICS="), lyrics.tags.MAX_TAG)
        path = self.song(ogg(opus, comment, per_page=255))["file"]
        self.assertEqual(lyrics.tags.lyrics(path), "")
        art = (b"Cover Art (Front)", bytes(lyrics.tags.MAX_TAG - 1026), 2)
        path = self.song(ape(art, (b"Lyrics", words.encode(), 0)))["file"]
        self.assertEqual(lyrics.tags.lyrics(path), "")
        whole = ape((b"Lyrics", words.encode(), 0))  # under the cap: read
        self.assertEqual(lyrics.tags.lyrics(self.song(whole)["file"]), words)

    def test_embedded_first_synced_lines_lose_their_times(self):
        song = self.song(id3(id3_frame(b"USLT", b"\3eng\0" + TIMED.encode())))
        self.assertEqual(lyrics.library(song, None), "Paper lanterns over the harbour")
        self.assertEqual(self.asked, [])
        # a .lrc beside it comes first, as for the playing song
        song = self.song(lrc_text="[00:01.00]Salt on the window\n[00:02.00]On the wire")
        self.assertEqual(lyrics.library(song, None), "Salt on the window\nOn the wire")

    def test_one_cache_row_for_the_song_playing_or_in_its_dialog(self):
        # Kodi's MusicPlayer labels for this library song: the tag it plays with is
        # the library's (CMusicInfoTag::SetSong): display artist, title, album, and
        # the length formatted m:ss (SecondsToTimeString), which song() reads back
        playing = {
            "MusicPlayer.Artist": "The Inventions",
            "MusicPlayer.Title": "Paper Lanterns",
            "MusicPlayer.Album": "Harbour Lights",
            "MusicPlayer.Duration": "03:21",
        }
        self.labels |= playing
        self.assertEqual(lyrics.song(), lyrics.library_song(self.song()))
        self.assertEqual(
            lyrics.lrclib.song_key(*lyrics.song()),
            lyrics.lrclib.song_key(*KEY),
        )
        # what the visualisation kept the dialog reads, with no request, and back
        self.cache[KEY] = ({"synced": None, "plain": VERSES, "instrumental": False}, 1)
        self.assertEqual(lyrics.library(self.song(), "again"), VERSES)
        lyrics.lookup(self.aborted)
        self.assertEqual((self.props["lyrics_plain"], self.asked), (VERSES, []))

    def test_lrclib_synced_as_plain_lines(self):
        self.cache[KEY] = (
            {"synced": [[0, ""], [4000, "Paper lanterns"], [9000, "Ships"]]}
            | {"plain": None, "instrumental": False},
            True,
        )
        self.assertEqual(lyrics.library(self.song(), None), "Paper lanterns\nShips")
        self.assertEqual(self.asked, [])  # kept: no request

    def test_instrumental_and_none_serve_nothing(self):
        self.cache[KEY] = ({"synced": None, "plain": None, "instrumental": True}, True)
        self.assertEqual(lyrics.library(self.song(), None), "")
        self.cache[KEY] = (None, True)  # a failure, still fresh: not asked again
        self.assertEqual(lyrics.library(self.song(), None), "")
        self.assertEqual(self.asked, [])

    def test_a_plugin_call_asks_a_served_call_asks_aside(self):
        self.lrclib[KEY] = {"synced": None, "plain": VERSES, "instrumental": False}
        self.assertEqual(lyrics.library(self.song(), None), VERSES)
        self.assertEqual(self.asked, [("lyrics", KEY)])
        asides = []
        with patch.object(lyrics.ASIDES, "ask", lambda *a: asides.append(a)):
            self.assertIsNone(lyrics.library(self.song(), "again"))
        self.assertEqual(asides, [(KEY, "again")])
        with patch.object(lyrics.lrclib, "enabled", lambda: False):  # no consent
            self.assertEqual(lyrics.library(self.song(), "again"), "")
        self.assertEqual(len(self.asked), 1)

    def test_stale_lines_serve_and_refresh_for_the_next_open(self):
        stale = {"synced": None, "plain": "Salt on the window", "instrumental": False}
        self.cache[KEY] = (stale, False)  # Refresh cached data marked it stale
        asides = []
        with patch.object(lyrics.ASIDES, "ask", lambda *a: asides.append(a)):
            self.assertEqual(lyrics.library(self.song(), "again"), "Salt on the window")
        # asked aside by an asker that serves nothing again: no swap of lines
        self.assertEqual((asides, self.asked), ([(KEY, lyrics.Quiet("again"))], []))
        served = []

        class Again:  # a re-serve: Python looks __call__ up on the class
            def __call__(self):
                served.append(1)

            def current(self):
                return True

        Again()()  # it would serve
        served.clear()
        quiet = lyrics.Quiet(Again())
        quiet()
        self.assertEqual((quiet.current(), served), (True, []))
        self.lrclib[KEY] = {"synced": None, "plain": VERSES, "instrumental": False}
        self.assertEqual(lyrics.library(self.song(), None), VERSES)  # a plugin waits
        self.assertEqual(self.asked, [("lyrics", KEY)])

    def test_a_stale_answer_with_no_lines_serves_the_pending_row(self):
        asides = []
        for stale in ({}, {"synced": None, "plain": None, "instrumental": True}):
            self.cache[KEY] = (stale, False)
            with patch.object(lyrics.ASIDES, "ask", lambda *a: asides.append(a)):
                self.assertIsNone(lyrics.library(self.song(), "again"))
        self.assertEqual(asides, [(KEY, "again")] * 2)  # its answer serves the list

    def test_an_aside_the_dialog_left_skips_its_search(self):
        self.lrclib[KEY] = {}
        self.assertEqual(lyrics._ask(KEY, lambda: True), {})
        self.assertIsNone(lyrics._ask(KEY, lambda: False))  # Aborted: nothing kept

    def test_a_broken_tag_reads_as_none(self):
        bad = id3(id3_frame(b"USLT", b"\x09eng\0text"))  # no such encoding
        self.lrclib[KEY] = {"synced": None, "plain": VERSES, "instrumental": False}
        self.assertEqual(lyrics.library(self.song(bad), None), VERSES)
        self.assertEqual(len(self.errors), 1)  # logged, with its traceback

    def serve(self, song, again=None, **params):
        """info=lyrics_plain&type=song&id=7 as a served call (again) or a plugin's."""
        params = {"info": "lyrics_plain", "type": "song", "id": "7"} | params
        handler = handlers.PluginHandlers(params, again=again)
        with (
            patch.object(handlers, "set_items", list),
            patch.object(handlers, "library_details", lambda *args: song),
        ):
            return handler.lyrics_plain()

    def test_the_song_listing_pending_then_lines(self):
        song = self.song()
        with patch.object(lyrics.ASIDES, "ask", lambda *a: None):
            self.assertEqual(
                self.serve(song, again="again"),
                [
                    {
                        "file": "plugin://script.copacetic.helper/lyrics/plain",
                        "label": "",
                        "properties": {"lyrics_pending": "true"},
                    }
                ],
            )
        self.cache[KEY] = ({"synced": None, "plain": VERSES, "instrumental": False}, 1)
        metric = type("Metric", (), {"getlength": lambda self, text: 10 * len(text)})
        with patch.object(handlers, "skin_metric", lambda name: metric()):
            rows = self.serve(song, again="again", wrap_font="plot", wrap_width="200")
        self.assertEqual(
            [row["label"] for row in rows],
            [
                "Paper lanterns over",  # 20 characters a row at 10 px
                "the harbour",
                "We counted ships",
                "until the morning",
            ],
        )

    def test_the_song_listing_keys_on_no_skin_setting(self):
        song = self.song(id3(id3_frame(b"USLT", b"\3eng\0" + VERSES.encode())))
        self.assertEqual(len(self.serve(song)), 2)  # Skin.HasSetting(lyrics) off
        self.assertEqual(self.serve(None), [])  # an id Kodi no longer has
        self.assertEqual(self.serve(song, id="0"), [])  # not a library song


class PluginAndActionTest(unittest.TestCase):
    def setUp(self):
        self.home = sys.modules["xbmcgui"].Window(10000)
        self.addCleanup(self.home.clearProperty, lrc.LINES)
        self.addCleanup(self.home.clearProperty, lrc.LONG)
        patcher = patch.object(handlers, "set_items", list)  # the items as dicts
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_one_item_per_line(self):
        self.home.setProperty(lrc.LINES, json.dumps(LINES))
        self.home.setProperty(lrc.LONG, "[1]")
        items = object.__new__(handlers.PluginHandlers).lyrics()
        self.assertEqual(
            items,
            [
                {
                    "file": "plugin://script.copacetic.helper/lyrics/0",
                    "label": "Rain on tin",
                    "properties": {
                        "index": 0,
                        "time": 1470,
                        "gap": "",
                        "long": "",
                        "m2": -2,
                        "m1": -1,
                        "p1": 1,
                        "p2": 2,
                        "p3": 3,
                        "p4": 4,
                        "p5": 5,
                    },
                },
                {
                    "file": "plugin://script.copacetic.helper/lyrics/1",
                    "label": "La, la-di-da",
                    "properties": {
                        "index": 1,
                        "time": 7050,
                        "gap": "",
                        "long": "true",
                        "m2": -1,
                        "m1": 0,
                        "p1": 2,
                        "p2": 3,
                        "p3": 4,
                        "p4": 5,
                        "p5": 6,
                    },
                },
                {
                    "file": "plugin://script.copacetic.helper/lyrics/2",
                    "label": "",
                    "properties": {
                        "index": 2,
                        "time": 10060,
                        "gap": "true",
                        "long": "",
                        "m2": 0,
                        "m1": 1,
                        "p1": 3,
                        "p2": 4,
                        "p3": 5,
                        "p4": 6,
                        "p5": 7,
                    },
                },
            ],
        )
        self.home.clearProperty(lrc.LINES)  # plain, none, or not playing
        self.assertIsNone(object.__new__(handlers.PluginHandlers).lyrics())

    def plain(self, **params):
        handler = handlers.PluginHandlers(params)  # no type=: the playing song's
        return [(item["file"], item["label"]) for item in handler.lyrics_plain() or ()]

    def test_plain_lines_wrap_to_the_width_in_the_font(self):
        self.addCleanup(self.home.clearProperty, lrc.PLAIN)
        self.home.setProperty(lrc.PLAIN, "Rain on tin\n\nCopper, copper in the rain")
        path = (
            "plugin://script.copacetic.helper/lyrics/plain"  # one: a refetch opens on 0
        )
        self.assertEqual(
            self.plain(),
            [
                (path, "Rain on tin"),
                (path, ""),
                (path, "Copper, copper in the rain"),
            ],
        )
        metric = type("Metric", (), {"getlength": lambda self, text: 10 * len(text)})
        fonts = []
        with patch.object(
            handlers, "skin_metric", lambda name: fonts.append(name) or metric()
        ):
            wrapped = self.plain(wrap_width="200", wrap_font="lyrics_embedded")
        # 20 characters a row at 10 px; the blank line between verses stays a row
        self.assertEqual(
            [label for _, label in wrapped],
            ["Rain on tin", "", "Copper, copper in", "the rain"],
        )
        self.assertEqual(fonts, ["lyrics_embedded"])
        with patch.object(handlers, "skin_metric", lambda name: None):  # no such font
            self.assertEqual(len(self.plain(wrap_width="200", wrap_font="x")), 3)
        self.home.clearProperty(lrc.PLAIN)
        self.assertEqual(self.plain(), [])

    def test_seek_to_a_line(self):
        seeks = []
        player_ = type("Player", (), {"seekTime": lambda self, s: seeks.append(s)})
        with patch.object(actions.xbmc, "Player", player_, create=True):
            actions.lyrics_seek(time="65300")
            actions.lyrics_seek(time="0")
        self.assertEqual(seeks, [65.3, 0.0])
        self.assertIs(actions.REGISTRY["lyrics_seek"], actions.lyrics_seek)

    def test_the_lrclib_row_turns_the_setting_over(self):
        settings = {"lrclib": True}
        addon = SimpleNamespace(
            getSettingBool=settings.get, setSettingBool=settings.__setitem__
        )
        with patch.object(actions, "ADDON", addon):
            actions.REGISTRY["toggle_setting"](id="lrclib")
            self.assertEqual(settings, {"lrclib": False})
            actions.toggle_setting(id="lrclib")
        self.assertEqual(settings, {"lrclib": True})

    def test_the_lyrics_row_turns_the_skin_bool_over_and_waits(self):
        sent = []  # (action, wait), as the log's execute passes them
        with patch.object(
            sys.modules["xbmc"], "executebuiltin", lambda *a: sent.append(a)
        ):
            actions.REGISTRY["toggle_skin_bool"](id="lyrics")
        self.assertEqual(sent, [("Skin.ToggleSetting(lyrics)", True)])


if __name__ == "__main__":
    unittest.main()
