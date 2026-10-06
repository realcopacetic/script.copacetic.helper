# author: realcopacetic

import time
from collections import defaultdict
from pathlib import Path

from resources.lib.shared.json import JSONHandler
from resources.lib.shared.utilities import (
    ADDONDATA,
    condition,
    infolabel,
    json_call,
    window_property,
)

RECENT_MAX = 30
SOURCE_PROPERTY = "speed_dial_source"
VERSION_PROPERTY = "speed_dial_version"  # widgets put it in their URL to refetch
HELD_PROPERTY = "speed_dial_held"  # a version waiting for focus to leave speed dial
LIBRARY_TYPES = ("album", "artist", "song")
PLAYLIST_SUFFIXES = (".xsp", ".m3u")
PLAYLISTS = "special://profile/playlists/music/"
PLAYLISTS_ALIAS = "special://musicplaylists/"  # same folder, as library nodes say it
# addon.xml's Pin/Unpin rows test one property per type and ID length (IDs to 7 digits)
PIN_KEYS = (*(f"{t}{n}" for t in LIBRARY_TYPES for n in range(1, 8)), "playlist")


def entry(type: str, id: str = "", path: str = "") -> dict:
    """
    A speed dial entry: a library item by type and ID, or a playlist by path,
    spelled one way whichever folder alias it was reached through.

    :param type: album, artist or song; anything else is a playlist.
    :param id: Library ID.
    :param path: Playlist path.
    :return: Dict with type and ref.
    """
    if type in LIBRARY_TYPES:
        return {"type": type, "ref": str(id)}
    return {"type": "playlist", "ref": path.replace(PLAYLISTS_ALIAS, PLAYLISTS, 1)}


def mark_source(source: dict | None) -> None:
    """
    Tells the service what the next playback was started from, before it starts;
    None records nothing (a genre or year mix).

    :param source: Speed dial entry, or None.
    """
    window_property(
        SOURCE_PROPERTY, value=f"{source['type']}|{source['ref']}" if source else "-"
    )


def take_source() -> dict | None | bool:
    """
    Reads and clears the source a helper action marked.

    :return: The entry, None when marked as nothing, False when unmarked.
    """
    if not (marked := infolabel(f"Window(home).Property({SOURCE_PROPERTY})")):
        return False
    window_property(SOURCE_PROPERTY)
    type, _, ref = marked.partition("|")
    return {"type": type, "ref": ref} if ref else None


def focused() -> bool:
    """
    True while focus is on a speed dial list: its items carry Property(speed_dial).

    :return: Whether the focused item is a speed dial item.
    """
    return bool(infolabel("ListItem.Property(speed_dial)"))


def refresh(hold: bool = False) -> None:
    """
    Bumps the version token speed dial widgets refetch on. With hold, the token
    waits for release_refresh instead, so a focused list doesn't reload.

    :param hold: Hold the token back while a speed dial list has focus.
    """
    token = str(time.time_ns())
    window_property(HELD_PROPERTY if hold else VERSION_PROPERTY, value=token)
    if not hold:
        window_property(HELD_PROPERTY)


def release_refresh() -> None:
    """Publishes a held version token once no speed dial list has focus."""
    if (held := infolabel(f"Window(home).Property({HELD_PROPERTY})")) and not focused():
        window_property(VERSION_PROPERTY, value=held)
        window_property(HELD_PROPERTY)


def queue_source(songid: int) -> dict:
    """
    Infers what a playback was started from: a playlist open in the music
    window, else the album or artist every queued song shares, else the song.

    :param songid: Library ID of the playing song.
    :return: Speed dial entry.
    """
    if condition("Window.IsActive(music)") and (
        path := next(
            (
                p
                for p in (
                    infolabel("Container.FolderPath"),
                    infolabel("ListItem.FolderPath"),
                )
                if p.endswith(PLAYLIST_SUFFIXES)
            ),
            "",
        )
    ):
        return entry("playlist", path=path)
    songs = json_call(
        "Playlist.GetItems",
        params={"playlistid": 0, "properties": ["albumid", "artistid"]},
        parent="speed_dial",
    )["result"].get("items", [])
    if len(songs) > 1:
        if len({s["albumid"] for s in songs}) == 1:
            return entry("album", songs[0]["albumid"])
        if shared := set.intersection(*(set(s.get("artistid", [])) for s in songs)):
            return entry("artist", min(shared))
    return entry("song", songid)


class SpeedDial:
    """
    Pinned entries first, in pin order, then the sources played most recently.
    Stored in speed_dial.json; writes that change the list call refresh.
    """

    def __init__(self) -> None:
        self._file = JSONHandler(Path(ADDONDATA) / "speed_dial.json")
        data = self._file.data.get(self._file.path, {})
        self.pinned = data.get("pinned", [])
        self.recent = data.get("recent", [])

    def items(self) -> list[tuple[dict, tuple[int, ...] | None]]:
        """
        Everything speed dial shows, pinned first; a pinned entry isn't repeated.
        Each comes with the moves it can make: -1 (up) unless first, 1 unless last.

        :return: (entry, offsets) pairs in display order; recent entries get None.
        """
        last = len(self.pinned) - 1
        return [
            *(
                (e, (-1,) * (i > 0) + (1,) * (i < last))
                for i, e in enumerate(self.pinned)
            ),
            *((e, None) for e in self.recent if e not in self.pinned),
        ]

    def played(self, source: dict) -> None:
        """
        Moves a source to the front of the recent list. Widgets refresh only if
        what they show changed, and not while a speed dial list has focus.

        :param source: Speed dial entry.
        """
        shown = self.items()
        self.recent = [source, *(e for e in self.recent if e != source)][:RECENT_MAX]
        self._write()
        if self.items() != shown:
            refresh(hold=focused())

    def pin(self, source: dict) -> None:
        """
        Pins an entry at the front; pinning a pinned entry moves it to the front.

        :param source: Speed dial entry.
        """
        self.pinned = [source, *(e for e in self.pinned if e != source)]
        self._save()

    def unpin(self, source: dict) -> None:
        """
        Unpins an entry; it stays in the recent list if it was played.

        :param source: Speed dial entry.
        """
        self.pinned = [e for e in self.pinned if e != source]
        self._save()

    def move(self, source: dict, offset: int) -> None:
        """
        Moves a pinned entry up (negative offset) or down, clamped to the list.

        :param source: Speed dial entry.
        :param offset: Positions to move.
        """
        index = self.pinned.index(source)
        self.pinned.insert(
            max(0, min(index + offset, len(self.pinned) - 1)), self.pinned.pop(index)
        )
        self._save()

    def publish(self) -> None:
        """
        Publishes the pinned keys addon.xml tests with String.Contains: IDs by type
        and length, so an ID can only match a whole pinned ID, and playlist paths
        in both spellings. Window(home).Property(speed_dial_<key>), "|"-joined.
        """
        keys = defaultdict(list)
        for e in self.pinned:
            if e["type"] == "playlist":
                alias = e["ref"].replace(PLAYLISTS, PLAYLISTS_ALIAS, 1)
                keys["playlist"] += e["ref"], alias
            else:
                keys[f"{e['type']}{len(e['ref'])}"].append(e["ref"])
        for key in PIN_KEYS:
            window_property(f"speed_dial_{key}", value="|".join(keys[key]))

    def _save(self) -> None:
        """Writes the file and the pinned keys, then refreshes widgets at once."""
        self._write()
        self.publish()
        refresh()

    def _write(self) -> None:
        """Writes speed_dial.json."""
        self._file.write_json({"pinned": self.pinned, "recent": self.recent})
