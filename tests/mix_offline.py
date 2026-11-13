"""
Offline checks for mixes (shared/mix.py) and the endless queue (service/player.py)
with Kodi's library faked: a mix leaves out what it's told, leans on its artists (a
daily one on their songs played lately, then the unplayed); today's mixes rank
genres by plays, pass over a lead already leading, are the leads alone until the
service keeps them with the artists like their leads (a lookup a seed; a second
pass fills a miss; an abort keeps nothing), then hold for the day; the queue grows
below ten songs left, only from the queue, as the same queue.
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
# Plays: songid → (playcount, days since last played); the rest unplayed. Kyuss's
# 0-7, then Sleep's 8-11, played more than any of Kyuss's
PLAYS = {0: (5, 3), 2: (9, 40), 4: (2, 1), 7: (7, 10)}
PLAYS |= {n: (20 - n, 1) for n in range(8, 12)}


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

    def test_played_a_fair_share_each(self):
        with mock.patch.object(mix, "json_call", library):
            songs = mix.mix_songs(["Kyuss", "Sleep"], [], 10, share=0.6, played="30")
        ids = [s["songid"] for s in songs]
        # three familiar, at most two each: Sleep's top two, then Kyuss's top one
        self.assertEqual(ids[:3], [8, 9, 7])
        by = Counter(s["artist"][0] for s in songs[3:6])  # three new, two at most
        self.assertEqual(by, {"Kyuss": 2, "Sleep": 1})

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
        self.like = {1: ["Sleep", "Om", "Kyuss"], 2: ["Om", "Yob"], 3: ["Yob", "Om"]}
        self.similar = mock.Mock(
            side_effect=lambda artistid, parent, owned: self.like.get(artistid, [])
        )
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
        self.assertTrue(mix.keep_todays_mixes(lambda: True))
        # Om is like all three leads, Yob like two; the leads themselves are left out
        self.assertEqual(mix.todays_mixes()[0]["similar"], ["Om", "Yob"])

    def test_each_seed_looked_up_once(self):
        mix.keep_todays_mixes(lambda: True)
        seeds = [call.args[0] for call in self.similar.call_args_list]
        self.assertEqual(sorted(seeds), [1, 2, 3, 4, 5, 6, 9])  # Sleep, Codeine once

    def test_second_pass_fills_a_miss(self):
        self.like[4] = []  # Low's lookup unanswered: kept with what did answer
        self.assertTrue(mix.keep_todays_mixes(lambda: True))
        self.assertEqual(mix.todays_mixes()[1]["similar"], [])
        self.like[4] = ["Galaxie 500"]
        self.assertTrue(mix.keep_todays_mixes(lambda: True))  # changed: a new URL
        self.assertEqual(mix.todays_mixes()[1]["similar"], ["Galaxie 500"])
        self.assertFalse(mix.keep_todays_mixes(lambda: True))  # as kept
        self.assertEqual(self.calls.call_count, 1)  # the kept leads, not today's

    def test_stops_on_abort(self):
        self.assertIsNone(mix.keep_todays_mixes(lambda: False))
        self.similar.assert_not_called()
        self.assertEqual(self.cache, {})

    def test_abort_during_the_last_lead_keeps_nothing(self):
        alive = mock.Mock(side_effect=[True] * 7 + [False])  # 7 leads, then the save
        self.assertIsNone(mix.keep_todays_mixes(alive))
        self.assertEqual(self.similar.call_count, 7)
        self.assertEqual(self.cache, {})

    def test_a_lead_gone_from_the_library_has_none(self):
        def similar(artistid: int, parent: str, owned: dict) -> list[str]:
            if artistid == 2:  # Sleep: artist_identity finds no details
                raise KeyError("result")
            return self.like.get(artistid, [])

        self.similar.side_effect = similar
        self.assertTrue(mix.keep_todays_mixes(lambda: True))
        self.assertEqual(mix.todays_mixes()[0]["similar"], ["Om", "Yob"])  # 1 and 3

    def test_no_plays_keeps_nothing(self):
        self.calls.return_value = {"result": {"songs": []}}
        self.assertIsNone(mix.keep_todays_mixes(lambda: True))

    def test_held_for_the_day(self):
        mix.keep_todays_mixes(lambda: True)
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
