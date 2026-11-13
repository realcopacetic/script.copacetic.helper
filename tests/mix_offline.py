"""
Offline checks for mixes (shared/mix.py) and the endless queue (service/player.py)
with Kodi's library faked: a mix leaves out what it's told, leans on its artists (a
daily one on their songs played lately, then the unplayed); today's mixes rank
genres by plays, pass over a lead already leading, are the leads alone until the
service keeps them with the artists like their leads (a lookup a seed, not after a
miss), then hold for the day; the queue grows below ten songs left, only from the queue,
as the same queue.
Run from the helper root: python tests/mix_offline.py
"""

import sys
from collections import Counter
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
vars(sys.modules["xbmc"]).update(
    Player=object,
    InfoTagVideo=None,
    Monitor=None,
    getLocalizedString=None,
    VideoStreamDetail=None,
    AudioStreamDetail=None,
    SubtitleStreamDetail=None,
)
sys.path.insert(0, str(HELPER))

from resources.lib.apis import cache  # noqa: E402
from resources.lib.plugin import music  # noqa: E402
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
# Kyuss's plays: songid → (playcount, days since last played); the rest unplayed
PLAYS = {0: (5, 3), 2: (9, 40), 4: (2, 1), 7: (7, 10)}


def library(
    method: str, query_filter: dict, limit: int | None = None, sort=None, **kwargs
):
    """AudioLibrary.GetSongs over SONGS for the rules mix_songs sends, in order."""

    def keep(song: dict, rule: dict) -> bool:
        if "and" in rule:
            return all(keep(song, r) for r in rule["and"])
        plays, days = PLAYS.get(song["songid"], (0, None))
        if rule["field"] == "lastplayed":  # inthelast
            return days is not None and days < int(rule["value"])
        if rule["field"] == "playcount":  # is
            return plays == int(rule["value"])
        hit = bool(set(song[rule["field"]]) & set(rule["value"]))
        return hit if rule["operator"] == "is" else not hit

    songs = [s for s in SONGS if keep(s, query_filter)]
    if sort["method"] == "playcount":  # descending
        songs.sort(key=lambda s: PLAYS.get(s["songid"], (0,))[0], reverse=True)
    return {"result": {"songs": songs[:limit]}}


class Mix(unittest.TestCase):
    def test_leaves_out_and_leans(self):
        with mock.patch.object(mix, "json_call", library):
            songs = mix.mix_songs(["Kyuss"], ["Stoner"], 10, exclude={0, 1, 8})
        ids = [s["songid"] for s in songs]
        self.assertEqual(len(ids), 10)
        self.assertFalse({0, 1, 8} & set(ids))
        self.assertEqual(sum(s["artist"] == ["Kyuss"] for s in songs), 2)  # 25 %

    def test_similar_then_genres(self):
        with mock.patch.object(mix, "json_call", library):
            songs = mix.mix_songs(["Kyuss"], ["Stoner"], 10, similar=["Low"])
        by = Counter(s["artist"][0] for s in songs)
        self.assertEqual(by, {"Kyuss": 2, "Low": 5, "Sleep": 3})

    def test_similar_capped(self):
        with mock.patch.object(mix, "json_call", library):
            songs = mix.mix_songs(["Kyuss"], [], 20, similar=["Sleep"])
        by = Counter(s["artist"][0] for s in songs)
        # capped, then topped up by the seed artist: all eight Kyuss songs
        self.assertEqual(by, {"Kyuss": 8, "Sleep": mix.SIMILAR_CAP})

    def test_played_lately_then_unplayed(self):
        with mock.patch.object(mix, "json_call", library):
            songs = mix.mix_songs(["Kyuss"], [], 10, share=0.6, played="30")
        ids = [s["songid"] for s in songs]
        # half of six: the most played in 30 days first (2 was 40 days ago)
        self.assertEqual(ids[:3], [7, 0, 4])
        self.assertLessEqual({*ids[3:6]}, {1, 3, 5, 6})  # then never played

    def test_played_short_tops_up(self):
        with mock.patch.object(mix, "json_call", library):
            songs = mix.mix_songs(["Kyuss"], [], 8, share=1, played="30")
        # three played lately, four never played, then the one played long ago
        self.assertEqual([s["songid"] for s in songs][:3], [7, 0, 4])
        self.assertEqual({s["songid"] for s in songs}, set(range(8)))

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
    (9, "Earth", 14, "Drone", 2),  # Sleep and Codeine seed a second mix
    (2, "Sleep", 14, "Drone", 1),
    (5, "Codeine", 14, "Drone", 1),
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
        like = {1: ["Sleep", "Om", "Kyuss"], 2: ["Om", "Yob"], 3: ["Yob", "Om"]}
        self.missed = set()  # artistids whose lookup fails

        def similar(artistid: int, parent: str, owned: dict) -> list[str]:
            if artistid in self.missed:
                cache._missed(f"deezer:related:{artistid}")
            return like.get(artistid, [])

        self.similar = mock.Mock(side_effect=similar)
        patches = (
            mock.patch.object(mix, "json_call", self.calls),
            mock.patch.object(mix, "ApiCacheHandler", lambda: handler),
            mock.patch.object(music, "similar_artists", self.similar),
            mock.patch.object(music, "artist_names", lambda parent: {}),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_genres_by_plays(self):
        mixes = mix.todays_mixes()
        self.assertEqual([m["genre"] for m in mixes], ["Stoner", "Slowcore", "Drone"])
        self.assertEqual(mixes[0]["artists"], ["Kyuss", "Sleep", "Fu Manchu"])

    def test_leads_alone_until_kept(self):
        # the plugin's read: no lookups, nothing kept
        self.assertEqual(mix.todays_mixes()[0]["similar"], [])
        self.similar.assert_not_called()
        self.assertEqual(self.cache, {})

    def test_similar_fused_without_leads(self):
        self.assertTrue(mix.keep_todays_mixes())
        # Om is like all three leads, Yob like two; the leads themselves are left out
        self.assertEqual(mix.todays_mixes()[0]["similar"], ["Om", "Yob"])

    def test_each_seed_looked_up_once(self):
        mix.keep_todays_mixes()
        seeds = [call.args[0] for call in self.similar.call_args_list]
        self.assertEqual(sorted(seeds), [1, 2, 3, 4, 5, 6, 9])  # Sleep, Codeine once

    def test_not_kept_on_a_miss(self):
        self.missed = {5}
        self.assertFalse(mix.keep_todays_mixes())
        self.assertEqual(self.cache, {})
        self.missed = set()
        self.assertTrue(mix.keep_todays_mixes())  # the next pass

    def test_held_for_the_day(self):
        mix.keep_todays_mixes()
        mix.keep_todays_mixes()
        mix.todays_mixes()
        self.assertEqual(self.calls.call_count, 1)


class Card(unittest.TestCase):
    STRINGS = {
        32838: "%s mix",
        32839: "Daily mix · %s songs",
        32840: "%s and %s",
        32841: "%s, and more",
    }

    def card(self, similar: list[str]) -> mock.Mock:
        today = {
            "genreid": 10,
            "genre": "Stoner",
            "artistids": [1, 2, 3],
            "artists": ["Kyuss", "Sleep", "Fu Manchu"],
            "similar": similar,
        }
        rows = [  # the library's order, not the mix's; Om has no thumb
            {"artist": n, "art": {"thumb": f"{n}.jpg"} if n != "Om" else {}}
            for n in sorted([*today["artists"], *similar])
        ]
        with (
            mock.patch.object(music, "ListItem") as list_item,
            mock.patch.object(
                music, "json_call", return_value={"result": {"artists": rows}}
            ),
            mock.patch.object(music, "ADDON") as addon,
        ):
            addon.getLocalizedString = self.STRINGS.get
            path, _, folder = music.mix_card(today)
        self.assertEqual((path, folder), ("musicdb://genres/10/", True))
        return list_item.return_value

    def test_artists_leads_first(self):
        li = self.card(["Om", "Yob", "Weedeater"])
        props = li.setProperties.call_args.args[0]
        self.assertEqual(
            props["Artist_Description"],
            "Kyuss, Sleep, Fu Manchu, Om and Yob, and more",
        )
        self.assertEqual(props["eyebrow"], f"Daily mix · {mix.MIX_SIZE} songs")
        art = li.setArt.call_args.args[0]
        self.assertEqual(
            [art["square"], art["square1"], art["square2"], art["square3"]],
            ["Kyuss.jpg", "Sleep.jpg", "Fu Manchu.jpg", "Yob.jpg"],
        )
        li.getMusicInfoTag.return_value.setGenres.assert_called_with(["Stoner"])

    def test_five_or_fewer_and_no_more(self):
        li = self.card(["Om"])
        props = li.setProperties.call_args.args[0]
        self.assertEqual(props["Artist_Description"], "Kyuss, Sleep, Fu Manchu and Om")

    def test_slides_capped(self):
        li = self.card([f"A{n:02}" for n in range(30)])
        self.assertEqual(len(li.setArt.call_args.args[0]), music.MIX_SLIDES + 1)


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
        monitor._growing = False
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
            monitor._extend_queue(["Kyuss"], [], ["Stoner"])
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
