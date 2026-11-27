# author: realcopacetic

import codecs
import json
import os
import sqlite3
import time
from bisect import bisect_right
from collections.abc import Callable, Sequence
from threading import Thread
from typing import Any

import xbmcvfs

from resources.lib.apis import lrclib
from resources.lib.apis.cache import Asker, Asides
from resources.lib.shared import logger as log
from resources.lib.shared import tags
from resources.lib.shared.lrc import LINES, LONG, NEIGHBOURS, PLAIN, parse, plain
from resources.lib.shared.text import skin_metric, wrap_text
from resources.lib.shared.utilities import (
    condition,
    infolabel,
    to_int,
    window_property,
)

ENABLED = "Skin.HasSetting(lyrics)"
# The playing line's box (skin lyrics.xml txt_lyrics_current): two title_identity lines
# at 660; a line that needs more is drawn a size down
CURRENT_FONT, CURRENT_WIDTH, CURRENT_LINES = "title_identity", 660, 2
FOLLOW, BROWSE = 3510, 3511  # the visualisation's follow list, the music OSD's browse
# Seconds: a playhead stalled just before a line (buffering) polls up to 20 times a
# second until it moves, not faster
MIN_WAIT = 0.05
SHOWN = "Window.IsActive(visualisation)"
# Seconds between passes while the visualisation shows. Kodi runs the service's
# callbacks inside the poller's wait without ending it (Monitor::waitForAbort), so a
# list reloaded or shown again (a new song, the OSD reopening) is put right this soon
SHOWN_WAIT = 0.2
# Seconds a posted Control.Move has to land (Kodi runs it on the GUI thread) before
# the list is read as missed and moved again
SETTLE = 0.5
# Written in this order: the lines before the revision that refetches them, the
# state, which shows them, last
PROPS = (
    LINES,
    LONG,
    "lyrics_revision",
    "lyrics_source",
    PLAIN,
    "lyrics_instrumental",
    "lyrics_index",
    *(f"lyrics_{key}" for key in NEIGHBOURS),
    "lyrics_state",
)
# The last song's source and instrumental mark go with its state while this one is
# looked up
SEARCHING = {
    "lyrics_source": "",
    "lyrics_instrumental": "",
    "lyrics_state": "searching",
}
ASKING_WAIT = 0.2  # seconds between passes while LRCLIB is asked: its answer shows soon
Song = tuple[str, str, str, int]  # (artist, title, album, seconds)
# (source, synced, plain, instrumental)
Found = tuple[str, list | None, str | None, bool]
NONE = ("", None, None, False)
# A library song's details for library(): its LRCLIB key matches the playing song's
# (MusicPlayer.Artist is the display artist), so both share one cache row
SONG_FIELDS = ["file", "displayartist", "title", "album", "duration"]
_fetches = {}  # LRCLIB lookups in flight, by song


def clear() -> None:
    """Clear every published lyrics property."""
    for key in PROPS:
        window_property(key)


def around(index: int) -> dict[str, str]:
    """
    The current line's index and its neighbours', for the skin's distance fade.

    :param index: The current line; -1 before the first.
    :return: lyrics_index and lyrics_m2 ... lyrics_p5.
    """
    return {"lyrics_index": f"{index}"} | {
        f"lyrics_{key}": f"{index + step}" for key, step in NEIGHBOURS.items()
    }


def song(prefix: str = "MusicPlayer.") -> Song:
    """
    The playing song's tags and length, or a queued one's.

    :param prefix: MusicPlayer., or MusicPlayer.offset(n). for a queued song.
    :return: (artist, title, album, seconds); seconds 0 when unknown.
    """
    artist, title, album, clock = (
        infolabel(f"{prefix}{label}")
        for label in ("Artist", "Title", "Album", "Duration")
    )
    parts = reversed(clock.split(":"))  # Kodi's m:ss or h:mm:ss
    return artist, title, album, sum(to_int(p) * 60**i for i, p in enumerate(parts))


def _sidecar(path: str) -> str:
    """
    The text of a .lrc of the same name beside a song's file: UTF-16 by its byte
    order mark, else UTF-8, else Windows-1252.

    :param path: The song's file.
    :return: Its text; "" for none.
    """
    lrc = f"{os.path.splitext(path)[0]}.lrc"
    if not xbmcvfs.exists(lrc):
        return ""
    with xbmcvfs.File(lrc) as file:
        data = file.readBytes()
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:  # an older file: Windows-1252, as most Western ones
        return data.decode("cp1252", "replace")


def _played(path: str) -> str:
    """
    The playing song's tagged lyrics, as Kodi read them from its file at play.

    :param path: Unused: the playing file's.
    :return: The text; "" for none.
    """
    return infolabel("MusicPlayer.Lyrics")


def find(path: str, embedded: Callable[[str], str] = _played) -> Found | None:
    """
    A song's lyrics from a .lrc beside it, else its tags: the playing song's by
    default (a stream has no file beside it), or another's by embedded(path).

    :param path: The song's file.
    :param embedded: Reads the file's tagged lyrics.
    :return: (source, synced lines, plain text, instrumental); None when neither has any.
    """
    readers = [("file", _sidecar), ("embedded", embedded)]
    if embedded is _played and condition("Player.IsInternetStream"):
        del readers[0]
    for source, read in readers:
        text = read(path)
        if synced := parse(text):
            return source, synced, None, False
        if text := plain(text):  # a .lrc of only tags holds none
            return source, None, text, False
    return None


def _wanted(song: Song) -> bool:
    """
    True when LRCLIB may be asked for a song: it is on, and the song's artist,
    title and length are known.

    :param song: (artist, title, album, seconds).
    """
    artist, title, _, seconds = song
    return bool(lrclib.enabled() and artist and title and seconds)


def _saved(song: Song) -> tuple[Any, bool]:
    """
    LRCLIB's cached answer for a song, read on the service thread (no request).

    :param song: (artist, title, album, seconds).
    :return: (payload, fresh); (None, False) when never asked, or the cache fails.
    """
    try:
        return lrclib.saved(*song) or (None, False)
    except sqlite3.Error:
        log.exception(f"lyrics → the LRCLIB cache failed for {song}")
        return None, False


def _found(payload: dict[str, Any] | None) -> Found:
    """
    An LRCLIB payload as find's tuple.

    :param payload: lrclib.lyrics' payload.
    :return: (source, synced lines, plain text, instrumental); NONE for none.
    """
    if not payload:
        return NONE
    return "lrclib", payload["synced"], payload["plain"], payload["instrumental"]


def _ask(song: Song, live: Callable[[], bool]) -> dict[str, Any] | None:
    """
    Ask LRCLIB for a library song, and cache its answer.

    :param song: (artist, title, album, seconds).
    :param live: Whether the answer is still wanted: if not, its search is skipped.
    :return: lrclib.lyrics' payload; None after a failure, or once unwanted.
    """
    try:
        return lrclib.lyrics(*song, lambda: not live())
    except lrclib.Aborted:
        return None


# Served calls' LRCLIB lookups for library songs, one at a time; the answer serves
# their lists again
ASIDES = Asides(_ask)


def library(song: dict[str, Any], again: Asker | None) -> str | None:
    """
    A library song's lyrics as plain text, synced lines without their times: a .lrc
    beside its file, its tags, else LRCLIB's kept answer. One never kept is asked:
    in the call for a plugin, aside for a served call (again), which reads None.

    :param song: Its details, SONG_FIELDS.
    :param again: A served list's re-serve; None for a plugin call.
    :return: The text; "" for none or an instrumental; None while LRCLIB is asked.
    """
    key = song["displayartist"], song["title"], song["album"], song["duration"]
    try:
        found = find(song["file"], tags.lyrics)
    except Exception:  # a file's bytes: a tag that breaks the reader reads as none
        log.exception(f"lyrics → the tags of {song['file']} failed")
        found = None
    if not found and _wanted(key):
        payload, fresh = _saved(key)
        if payload is None and not fresh:
            if again:
                ASIDES.ask(key, again)
                return None
            payload = _ask(key, lambda: True)
        found = _found(payload)
    _, synced, text, instrumental = found or NONE
    if instrumental:
        return ""
    return "\n".join(line for _, line in synced).strip() if synced else text or ""


class Fetch(Thread):
    """
    A song's LRCLIB lookup off the service thread, the only one in flight for that
    song (in _fetches until done); found holds its payload once it has ended.
    """

    def __init__(self, song: Song, ask: Callable, aborted: Callable[[], bool]) -> None:
        """
        Start the lookup, unless Kodi is exiting: then it reads as done, with none.

        :param song: (artist, title, album, seconds).
        :param ask: lrclib.lyrics for the playing song, lrclib.prefetch for the next.
        :param aborted: abortRequested of a Monitor made on the service thread.
        """
        super().__init__(daemon=True)
        self.song, self.ask, self.aborted, self.found = song, ask, aborted, None
        if aborted():  # Kodi is exiting: no thread for it to wait on; found stays None
            return
        _fetches[song] = self
        self.start()

    def run(self) -> None:
        """Ask; Kodi exiting or a cache failure (logged) leaves found None."""
        try:
            self.found = self.ask(*self.song, self.aborted)
        except lrclib.Aborted:
            log.debug(f"lyrics → Kodi is exiting: stopped asking for {self.song}")
        except sqlite3.Error:
            log.exception(f"lyrics → the LRCLIB cache failed for {self.song}")
        finally:
            del _fetches[self.song]


def long_lines(synced: list) -> list[int]:
    """
    The indexes of the synced lines that wrap past the playing line's box, as Kodi
    lays them out at the GUI's scale; none without the skin's font.

    :param synced: [[ms, text], ...].
    :return: Their indexes, in order.
    """
    if not (metric := skin_metric(CURRENT_FONT)):
        return []
    return [
        index
        for index, (_, text) in enumerate(synced)
        if len(wrap_text(metric, text, CURRENT_WIDTH)) > CURRENT_LINES
    ]


def publish(
    source: str, synced: list | None, text: str | None, instrumental: bool
) -> list:
    """
    Publish a song's lyrics: the lines before the revision that refetches them, the
    state, which shows them, last. A first line with text after 0 gets a gap before
    it, so an intro shows its dots row above that line.

    :param source: file, embedded or lrclib; "" for none.
    :param synced: [[ms, text], ...]; None unless synced.
    :param text: The plain text; None unless plain.
    :param instrumental: LRCLIB marks the song instrumental.
    :return: The synced lines, with that gap; empty unless synced.
    """
    if synced and synced[0][0] and synced[0][1]:
        synced = [[0, ""], *synced]
    long = long_lines(synced) if synced else []
    props = {
        LINES: json.dumps(synced) if synced else "",
        LONG: json.dumps(long) if long else "",
        "lyrics_revision": f"{time.monotonic_ns()}",
        "lyrics_source": source,
        PLAIN: text,
        "lyrics_instrumental": "true" if instrumental else "",
        "lyrics_state": "synced" if synced else "plain" if text else "none",
    }
    if synced:
        props |= around(-1)
    for key in PROPS:
        window_property(key, value=props.get(key) or "")
    return synced or []


def prefetch(aborted: Callable[[], bool]) -> None:
    """
    Ask LRCLIB on a thread for the song queued next, unless it is out or cached.

    :param aborted: abortRequested of a Monitor made on the service thread.
    """
    queued = song("MusicPlayer.offset(1).")
    if _wanted(queued) and queued not in _fetches and not _saved(queued)[1]:
        Fetch(queued, lrclib.prefetch, aborted)


def lookup(aborted: Callable[[], bool]) -> "Lyrics":
    """
    Publish the playing song's lyrics from a .lrc, its tags or LRCLIB's cache, else
    ask LRCLIB on a thread for the poller to publish; and ask ahead for the next song.
    A Monitor made in a request's thread after Kodi's abort never hears it.

    :param aborted: abortRequested of a Monitor made on the service thread.
    :return: Lyrics to follow; with no lines unless synced, or LRCLIB's on the way.
    """
    for key, value in SEARCHING.items():
        window_property(key, value=value)
    found, fetch = find(infolabel("Player.Filenameandpath")), None
    if not found and _wanted(playing := song()):
        payload, fresh = _saved(playing)
        if fresh:
            found = _found(payload)
        else:  # the next song's prefetch may still be out: it serves
            fetch = _fetches.get(playing) or Fetch(playing, lrclib.lyrics, aborted)
    prefetch(aborted)  # after: the playing song's own request is never asked twice
    return Lyrics(fetch=fetch) if fetch else Lyrics(publish(*(found or NONE)))


class Lyrics:
    """
    A playing song's synced lines: publishes the line at the playhead with its
    neighbours and steps the skin's list in view to it.
    """

    def __init__(self, lines: Sequence[list] = (), fetch: Fetch | None = None) -> None:
        """
        Hold the lines' times, or the LRCLIB lookup that brings them; lookup has
        published the state before the first line.

        :param lines: [[ms, text], ...]; empty unless synced.
        :param fetch: The song's LRCLIB lookup, published at the first pass after it.
        """
        self.times = [ms for ms, _ in lines]
        self.fetch = fetch
        self.index = -1  # the line published
        # (list, item it moves to, monotonic deadline) of the last move
        self.moved = None

    def tick(self, now: float) -> float:
        """
        Poller step: publish LRCLIB's answer once in, then the line at the playhead,
        and step the list in view. It waits until the next line, at most 1 s (1 s
        while paused or after the last line), or 0.2 s while the visualisation shows.

        :param now: The playhead in seconds.
        :return: Seconds to wait before the next tick.
        """
        if self.fetch:
            if self.fetch.is_alive():
                return ASKING_WAIT
            fetch, self.fetch = self.fetch, None
            if fetch.found is None and fetch.ask is lrclib.prefetch:
                # The prefetch this start took over failed: ask for it now, as a
                # start does, so a failure is cached and waited out
                self.fetch = _fetches.get(fetch.song) or Fetch(
                    fetch.song, lrclib.lyrics, fetch.aborted
                )
                return ASKING_WAIT
            self.times = [ms for ms, _ in publish(*_found(fetch.found))]
        if not self.times:
            return 1
        ms = now * 1000
        if (index := bisect_right(self.times, ms) - 1) != self.index:
            self.index = index
            for key, value in around(index).items():
                window_property(key, value=value)
        shown = condition(SHOWN)  # read once: each condition waits on the GUI
        self._step(index, shown)
        if index + 1 == len(self.times) or condition("Player.Paused"):
            wait = 1
        else:
            wait = max(MIN_WAIT, (self.times[index + 1] - ms) / 1000)
        return min(wait, SHOWN_WAIT if shown else 1)

    def _step(self, index: int, shown: bool) -> None:
        """
        Put the list in view on the line whenever it isn't (a step a dialog took, a
        list reloaded or shown again), by its distance from the selected item: the
        OSD's browse list unless it has focus, else the visualisation's follow list.

        :param index: The current line; -1 before the first (the first item then).
        :param shown: The visualisation is the active window.
        """
        if condition("Window.IsActive(musicosd)"):
            target = 0 if condition(f"Control.HasFocus({BROWSE})") else BROWSE
        else:
            target = FOLLOW if shown else 0
        # Read in the topmost modal dialog: none under another one, as Control.Move
        if not (
            target and (count := to_int(infolabel(f"Container({target}).NumItems")))
        ):
            return
        selected = to_int(infolabel(f"Container({target}).CurrentItem")) - 1
        if (
            self.moved
            and self.moved[0] == target
            and self.moved[1] != selected
            and time.monotonic() < self.moved[2]
        ):
            return  # the last move is still queued: another now would add to it
        self.moved = None
        line = min(max(index, 0), count - 1)  # within a list still the last song's
        if line != selected:
            log.execute(f"Control.Move({target},{line - selected})")
            self.moved = target, line, time.monotonic() + SETTLE
