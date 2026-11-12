"""
Offline checks for mixes (shared/mix.py) and the endless queue (service/player.py)
with Kodi's library faked: a mix leaves out what it's told, leans on its artists;
today's mixes rank genres by plays, pass over a lead already leading, hold for the
day; the queue grows below ten songs left, only from the queue, as the same queue.
Run from the helper root: python tests/mix_offline.py
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
vars(sys.modules["xbmc"]).update(
    Player=object, InfoTagVideo=None, Monitor=None, getLocalizedString=None
)
sys.path.insert(0, str(HELPER))

from resources.lib.service import player  # noqa: E402
from resources.lib.shared import mix  # noqa: E402

SONGS = [
    {"songid": n, "file": f"/m/{n}.flac", "artist": [a], "genre": [g]}
    for n, (a, g) in enumerate(
        [("Kyuss", "Stoner")] * 8
        + [("Sleep", "Stoner")] * 30
        + [("Low", "Slowcore")] * 5
    )
]


def library(method: str, query_filter: dict, limit: int | None = None, **kwargs):
    """AudioLibrary.GetSongs over SONGS for the rules mix_songs sends, in order."""

    def keep(song: dict, rule: dict) -> bool:
        if "and" in rule:
            return all(keep(song, r) for r in rule["and"])
        hit = bool(set(song[rule["field"]]) & set(rule["value"]))
        return hit if rule["operator"] == "is" else not hit

    songs = [s for s in SONGS if keep(s, query_filter)]
    return {"result": {"songs": songs[:limit]}}


class Mix(unittest.TestCase):
    def test_leaves_out_and_leans(self):
        with mock.patch.object(mix, "json_call", library):
            songs = mix.mix_songs(["Kyuss"], ["Stoner"], 10, exclude={0, 1, 8})
        ids = [s["songid"] for s in songs]
        self.assertEqual(len(ids), 10)
        self.assertFalse({0, 1, 8} & set(ids))
        self.assertEqual(sum(s["artist"] == ["Kyuss"] for s in songs), 2)

    def test_artists_alone_without_genres(self):
        with mock.patch.object(mix, "json_call", library):
            songs = mix.mix_songs(["Low"], [], 10)
        self.assertEqual({s["artist"][0] for s in songs}, {"Low"})


PLAYED = [  # artistid, artist, genreid, genre, playcount
    (1, "Kyuss", 10, "Stoner", 9),
    (2, "Sleep", 10, "Stoner", 5),
    (3, "Fu Manchu", 10, "Stoner", 4),
    (1, "Kyuss", 11, "Desert", 9),  # led by Kyuss again: passed over
    (2, "Sleep", 11, "Desert", 1),
    (3, "Fu Manchu", 11, "Desert", 1),
    (4, "Low", 12, "Slowcore", 3),
    (5, "Codeine", 12, "Slowcore", 2),
    (6, "Duster", 12, "Slowcore", 2),
    (7, "Mogwai", 13, "Post-rock", 30),  # two artists only: no mix
    (8, "Slint", 13, "Post-rock", 30),
]


class Today(unittest.TestCase):
    def setUp(self):
        rows = [
            {
                "artistid": [a],
                "artist": [n],
                "genreid": [g],
                "genre": [gn],
                "playcount": p,
            }
            for a, n, g, gn, p in PLAYED
        ]
        self.calls = mock.Mock(return_value={"result": {"songs": rows}})
        self.cache = {}
        handler = mock.Mock()
        handler.get.side_effect = lambda key: (
            (self.cache[key], True) if key in self.cache else None
        )
        handler.put.side_effect = lambda key, payload, ttl: self.cache.update(
            {key: payload}
        )
        patches = (
            mock.patch.object(mix, "json_call", self.calls),
            mock.patch.object(mix, "ApiCacheHandler", lambda: handler),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_genres_by_plays(self):
        mixes = mix.todays_mixes()
        self.assertEqual([m["genre"] for m in mixes], ["Stoner", "Slowcore"])
        self.assertEqual(mixes[0]["artists"], ["Kyuss", "Sleep", "Fu Manchu"])

    def test_held_for_the_day(self):
        mix.todays_mixes()
        mix.todays_mixes()
        self.assertEqual(self.calls.call_count, 1)


class Playlist:
    """The music playlist: items by path; add appends."""

    def __init__(self, size: int):
        self.paths = [f"/q/{n}.flac" for n in range(size)]

    def size(self) -> int:
        return len(self.paths)

    def __getitem__(self, i: int):
        return mock.Mock(getPath=lambda: self.paths[i])

    def add(self, path: str, properties: dict) -> None:
        self.paths.append(path)
        self.properties = properties


class EndlessQueue(unittest.TestCase):
    def grow(self, size: int, position: int) -> tuple[Playlist, object, mock.Mock]:
        playlist = Playlist(size)
        monitor = object.__new__(player.PlayerMonitor)
        monitor._queue_songs = (player._queue_key(playlist), set(range(size)))
        monitor._dial_queue = player._queue_key(playlist)
        answer = {"result": {"position": position}}
        with (
            mock.patch.object(player, "PlayList", lambda kind: playlist),
            mock.patch.object(player, "json_call", lambda *a, **k: answer),
            mock.patch.object(
                player,
                "add_songs",
                lambda pl, songs, **props: [pl.add(s["file"], props) for s in songs],
            ),
            mock.patch.object(
                player,
                "mix_songs",
                mock.Mock(
                    return_value=[
                        {"songid": 100 + n, "file": f"/m/{n}"} for n in range(10)
                    ]
                ),
            ) as mixed,
        ):
            monitor._extend_queue(["Kyuss"], ["Stoner"])
        return playlist, monitor, mixed

    def test_grows_below_ten_left(self):
        playlist, monitor, mixed = self.grow(20, 10)  # 9 left
        self.assertEqual(playlist.size(), 30)
        self.assertEqual(mixed.call_args.args[3], set(range(20)))  # none queued again
        self.assertEqual(monitor._dial_queue, player._queue_key(playlist))
        self.assertEqual(monitor._queue_songs[0], monitor._dial_queue)
        self.assertIn(109, monitor._queue_songs[1])
        self.assertEqual(playlist.properties, {"added_from": "Kyuss"})

    def test_ten_left_holds(self):
        playlist, _, mixed = self.grow(20, 9)
        self.assertEqual(playlist.size(), 20)
        mixed.assert_not_called()

    def test_not_from_the_queue(self):
        playlist, _, mixed = self.grow(1, -1)
        self.assertEqual(playlist.size(), 1)
        mixed.assert_not_called()


if __name__ == "__main__":
    unittest.main()
