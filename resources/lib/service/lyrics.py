# author: realcopacetic

import codecs
import json
import os
import sqlite3
import time
from bisect import bisect_right
from threading import Thread
from typing import Any, Callable

import xbmcvfs

from resources.lib.apis import lrclib
from resources.lib.shared import logger as log
from resources.lib.shared.lrc import LINES, parse, plain
from resources.lib.shared.utilities import (
    condition,
    infolabel,
    to_int,
    window_property,
)

ENABLED = "Skin.HasSetting(lyrics)"
FOLLOW, BROWSE = 3510, 3511  # the visualisation's follow list, the music OSD's browse
NEIGHBOURS = {"lyrics_m2": -2, "lyrics_m1": -1} | {
    f"lyrics_p{n}": n for n in range(1, 6)
}
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
    "lyrics_revision",
    "lyrics_source",
    "lyrics_plain",
    "lyrics_instrumental",
    "lyrics_index",
    *NEIGHBOURS,
    "lyrics_state",
)
# The last song's eyebrow words go with its state while this one is looked up
SEARCHING = {
    "lyrics_source": "",
    "lyrics_instrumental": "",
    "lyrics_state": "searching",
}
ASKING_WAIT = 0.2  # seconds between passes while LRCLIB is asked: its answer shows soon
Song = tuple[str, str, str, int]  # (artist, title, album, seconds)
Found = tuple[
    str, list | None, str | None, bool
]  # (source, synced, plain, instrumental)
NONE: Found = ("", None, None, False)
_fetches: dict[Song, "Fetch"] = {}  # LRCLIB lookups in flight, by song


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
        key: f"{index + step}" for key, step in NEIGHBOURS.items()
    }


def song(prefix: str = "MusicPlayer.") -> tuple[str, str, str, int]:
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
    The text of a .lrc of the same name beside the playing file: UTF-16 by its byte
    order mark, else UTF-8, else Windows-1252.

    :param path: The playing file.
    :return: Its text; "" for none, or a stream.
    """
    lrc = f"{os.path.splitext(path)[0]}.lrc"
    if condition("Player.IsInternetStream") or not xbmcvfs.exists(lrc):
        return ""
    with xbmcvfs.File(lrc) as file:
        data = file.readBytes()
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:  # an older file: Windows-1252, as most Western ones
        return data.decode("cp1252", "replace")


def find(path: str) -> Found | None:
    """
    The playing song's lyrics from a .lrc beside it, else its tags (Kodi reads them
    from the file at play).

    :param path: The playing file.
    :return: (source, synced lines, plain text, instrumental); None when neither has any.
    """
    for source, text in (
        ("file", _sidecar(path)),
        ("embedded", infolabel("MusicPlayer.Lyrics")),
    ):
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


class Fetch(Thread):
    """
    A song's LRCLIB lookup off the service thread, the only one in flight for that
    song (in _fetches until done); found holds its payload once it has ended.
    """

    def __init__(self, song: Song, ask: Callable) -> None:
        """
        Start the lookup.

        :param song: (artist, title, album, seconds).
        :param ask: lrclib.lyrics for the playing song, lrclib.prefetch for the next.
        """
        super().__init__(daemon=True)
        self.song, self.ask, self.found = song, ask, None
        _fetches[song] = self
        self.start()

    def run(self) -> None:
        """Ask; a cache failure is logged and found stays None."""
        try:
            self.found = self.ask(*self.song)
        except sqlite3.Error:
            log.exception(f"lyrics → the LRCLIB cache failed for {self.song}")
        finally:
            del _fetches[self.song]


def publish(
    source: str, synced: list | None, text: str | None, instrumental: bool
) -> list:
    """
    Publish a song's lyrics: the lines before the revision that refetches them, the
    state, which shows them, last.

    :param source: file, embedded or lrclib; "" for none.
    :param synced: [[ms, text], ...]; None unless synced.
    :param text: The plain text; None unless plain.
    :param instrumental: LRCLIB marks the song instrumental.
    :return: The synced lines; empty unless synced.
    """
    props = {
        LINES: json.dumps(synced) if synced else "",
        "lyrics_revision": f"{time.monotonic_ns()}",
        "lyrics_source": source,
        "lyrics_plain": text,
        "lyrics_instrumental": "true" if instrumental else "",
        "lyrics_state": "synced" if synced else "plain" if text else "none",
    }
    if synced:
        props |= around(-1)
    for key in PROPS:
        window_property(key, value=props.get(key) or "")
    return synced or []


def lookup() -> "Lyrics":
    """
    Publish the playing song's lyrics from a .lrc, its tags or LRCLIB's cache, else
    ask LRCLIB on a thread for the poller to publish; and ask ahead for the next song.

    :return: Lyrics to follow; with no lines unless synced, or LRCLIB's on the way.
    """
    for key, value in SEARCHING.items():
        window_property(key, value=value)
    found, fetch = find(infolabel("Player.Filenameandpath")), None
    playing, queued = song(), song("MusicPlayer.offset(1).")
    if not found and _wanted(playing):
        payload, fresh = _saved(playing)
        if fresh:
            found = _found(payload)
        else:  # the next song's prefetch may still be out: it serves
            fetch = _fetches.get(playing) or Fetch(playing, lrclib.lyrics)
    if _wanted(queued) and queued not in _fetches and not _saved(queued)[1]:
        Fetch(queued, lrclib.prefetch)
    return Lyrics(fetch=fetch) if fetch else Lyrics(publish(*(found or NONE)))


class Lyrics:
    """
    A playing song's synced lines: publishes the line at the playhead with its
    neighbours and steps the skin's list in view to it.
    """

    def __init__(self, lines: list[list] = (), fetch: Fetch | None = None) -> None:
        """
        Hold the lines' times, or the LRCLIB lookup that brings them; lookup has
        published the state before the first line.

        :param lines: [[ms, text], ...]; empty unless synced.
        :param fetch: The song's LRCLIB lookup, published at the first pass after it.
        """
        self.times = [ms for ms, _ in lines]
        self.fetch = fetch
        self.index = -1  # the line published
        self.moved = (
            None  # (list, item it moves to, monotonic deadline) of the last move
        )

    def tick(self, now: float) -> float:
        """
        Poller step: publish LRCLIB's answer once in, then the line at the playhead,
        and step the list in view.

        :param now: The playhead in seconds.
        :return: Seconds to the next line (1 while paused or after the last), at most
            1, or 0.2 while the visualisation shows.
        """
        if self.fetch:
            if self.fetch.is_alive():
                return ASKING_WAIT
            self.times = [ms for ms, _ in publish(*_found(self.fetch.found))]
            self.fetch = None
        if not self.times:
            return 1
        ms = now * 1000
        if (index := bisect_right(self.times, ms) - 1) != self.index:
            self.index = index
            for key, value in around(index).items():
                window_property(key, value=value)
        self._step(index)
        if index + 1 == len(self.times) or condition("Player.Paused"):
            wait = 1
        else:
            wait = max(MIN_WAIT, (self.times[index + 1] - ms) / 1000)
        return min(wait, SHOWN_WAIT if condition(SHOWN) else 1)

    def _step(self, index: int) -> None:
        """
        Put the list in view on the line whenever it isn't (a step a dialog took, a
        list reloaded or shown again), by its distance from the selected item: the
        OSD's browse list unless it has focus, else the visualisation's follow list.

        :param index: The current line; -1 before the first (the first item then).
        """
        if condition("Window.IsActive(musicosd)"):
            target = 0 if condition(f"Control.HasFocus({BROWSE})") else BROWSE
        else:
            target = FOLLOW if condition(SHOWN) else 0
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
