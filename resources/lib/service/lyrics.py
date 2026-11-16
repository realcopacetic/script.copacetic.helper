# author: realcopacetic

import codecs
import json
import os
import time
from bisect import bisect_right
from threading import Thread
from typing import Any

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
MIN_WAIT = 0.05  # seconds: a playhead that stalls just before a line can't spin
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


def _ask(artist: str, title: str, album: str, seconds: int) -> dict[str, Any] | None:
    """
    LRCLIB's lyrics for a song, while LRCLIB is on and the song's artist, title
    and length are known.

    :param artist: The song's artist string.
    :param title: Its title.
    :param album: Its album; "" when none.
    :param seconds: Its length in whole seconds; 0 when unknown.
    :return: lrclib.lyrics' payload; None when not asked or unknown.
    """
    if lrclib.enabled() and artist and title and seconds:
        return lrclib.lyrics(artist, title, album, seconds)
    return None


def find(path: str) -> tuple[str, list | None, str | None, bool]:
    """
    The playing song's lyrics from the first source holding any: a .lrc beside it,
    its tags (Kodi reads them from the file at play), then LRCLIB.

    :param path: The playing file.
    :return: (source, synced lines, plain text, instrumental); source "" for none.
    """
    for source, text in (
        ("file", _sidecar(path)),
        ("embedded", infolabel("MusicPlayer.Lyrics")),
    ):
        if synced := parse(text):
            return source, synced, None, False
        if text := plain(text):  # a .lrc of only tags holds none
            return source, None, text, False
    if found := _ask(*song()):
        return "lrclib", found["synced"], found["plain"], found["instrumental"]
    return "", None, None, False


def lookup() -> "Lyrics":
    """
    Publish the playing song's lyrics, searching meanwhile, then fetch the next
    queued song's from LRCLIB in the background, for its start.

    :return: Lyrics to follow; with no lines unless synced.
    """
    for key, value in SEARCHING.items():
        window_property(key, value=value)
    source, synced, plain, instrumental = find(infolabel("Player.Filenameandpath"))
    props = {
        LINES: json.dumps(synced) if synced else "",
        "lyrics_revision": f"{time.monotonic_ns()}",
        "lyrics_source": source,
        "lyrics_plain": plain,
        "lyrics_instrumental": "true" if instrumental else "",
        "lyrics_state": "synced" if synced else "plain" if plain else "none",
    }
    if synced:
        props |= around(-1)
    for key in PROPS:
        window_property(key, value=props.get(key) or "")
    Thread(target=_ask, args=song("MusicPlayer.offset(1)."), daemon=True).start()
    return Lyrics(synced or [])


class Lyrics:
    """
    A playing song's synced lines: publishes the line at the playhead with its
    neighbours and steps the skin's list in view to it.
    """

    def __init__(self, lines: list[list]) -> None:
        """
        Hold the lines' times; lookup has published the state before the first.

        :param lines: [[ms, text], ...]; empty unless synced.
        """
        self.times = [ms for ms, _ in lines]
        self.index = -1  # the line published
        self.stepped = None  # (list, line, its item count) last stepped for

    def tick(self, now: float) -> float:
        """
        Poller step: publish the line at the playhead, step the list in view.

        :param now: The playhead in seconds.
        :return: Seconds to the next line, at most 1 (1 while paused or after the last).
        """
        if not self.times:
            return 1
        ms = now * 1000
        if (index := bisect_right(self.times, ms) - 1) != self.index:
            self.index = index
            for key, value in around(index).items():
                window_property(key, value=value)
        self._step(index)
        if index + 1 == len(self.times) or condition("Player.Paused"):
            return 1
        return min(1, max(MIN_WAIT, (self.times[index + 1] - ms) / 1000))

    def _step(self, index: int) -> None:
        """
        Move the list in view to the line by its distance from the list's selected
        item, so a step that missed is made up: the OSD's browse list unless it has
        focus, else the visualisation's follow list.

        :param index: The current line; -1 before the first (the first item then).
        """
        if condition("Window.IsActive(musicosd)"):
            target = 0 if condition(f"Control.HasFocus({BROWSE})") else BROWSE
        else:
            target = FOLLOW if condition("Window.IsActive(visualisation)") else 0
        # Read in the topmost modal dialog: none under another one, as Control.Move
        count = target and to_int(infolabel(f"Container({target}).NumItems"))
        if (key := (target, index, count)) == self.stepped:
            return
        self.stepped = key
        if count:  # one still filling steps once filled: a new key
            selected = to_int(infolabel(f"Container({target}).CurrentItem")) - 1
            if delta := max(index, 0) - selected:
                log.execute(f"Control.Move({target},{delta})")
