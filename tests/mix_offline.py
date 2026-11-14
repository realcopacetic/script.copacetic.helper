"""
Offline checks for mixes (shared/mix.py) and the endless queue (service/player.py)
with Kodi's library faked: a random draw leaves the song id order Kodi lists it in;
a mix grown from seed songs leaves out what it's told, leans on the artists they
count for (their own albums), plays its familiar seeds first and keeps to keep;
daily mixes: genres by songs played, kept until midnight and replayed as kept,
redrawn once a lead's similar artists answer otherwise; the cards name the list's
artists in play order; the queue grows below ten songs left, only from the queue.
Run from the helper root: python tests/mix_offline.py
"""

import sys
from collections import Counter
from datetime import datetime, timedelta
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
    {
        "songid": n,
        "file": f"/m/{n}.flac",
        "artist": [a],
        "albumartist": [a],
        "genre": [g],
    }
    for n, (a, g) in enumerate(
        [("Kyuss", "Stoner")] * 8
        + [("Sleep", "Stoner")] * 30
        + [("Low", "Slowcore")] * 5
    )
]
# Song 43: Kyuss guesting on Low's album
SONGS += [
    {
        "songid": 43,
        "file": "/m/43.flac",
        "artist": ["Low", "Kyuss"],
        "albumartist": ["Low"],
        "genre": ["Slowcore"],
    }
]


def library(method: str, query_filter: dict, limit: int | None = None, **kwargs):
    """AudioLibrary.GetSongs over SONGS for the rules a mix sends, in id order."""

    def keep(song: dict, rule: dict) -> bool:
        if "and" in rule:
            return all(keep(song, r) for r in rule["and"])
        values = rule["value"] if isinstance(rule["value"], list) else [rule["value"]]
        hit = bool(set(song[rule["field"]]) & set(values))
        return hit if rule["operator"] == "is" else not hit

    songs = [s for s in SONGS if keep(s, query_filter)]
    return {"result": {"songs": songs[:limit]}}


def artists(songs: list[dict]) -> Counter:
    return Counter(s["artist"][0] for s in songs)


class Mix(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(mix, "json_call", library)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_random_draw_leaves_id_order(self):
        # the fake answers in song id order, as Kodi does once artist is asked for
        mix.random.seed(1)
        drawn = [s["songid"] for s in mix.random_songs({"and": []})]
        self.assertEqual(sorted(drawn), [s["songid"] for s in SONGS])
        self.assertNotEqual(drawn, sorted(drawn))

    def test_leaves_out_and_leans(self):
        songs = mix.mix_songs([SONGS[2]], 10, exclude={0, 1, 8})
        self.assertEqual(len(songs), 10)
        self.assertFalse({0, 1, 8} & {s["songid"] for s in songs})
        self.assertEqual(artists(songs), {"Kyuss": 2, "Sleep": 8})  # 25 %, then Stoner

    def test_similar_then_genres(self):
        songs = mix.mix_songs([SONGS[2]], 10, similar=["Low"])
        self.assertEqual(artists(songs), {"Kyuss": 2, "Low": 6, "Sleep": 2})

    def test_similar_capped(self):
        songs = mix.mix_songs([SONGS[2]], 20, similar=["Sleep"])
        # capped, the genre has no one else, then topped up: all eight Kyuss songs
        self.assertEqual(artists(songs), {"Kyuss": 8, "Sleep": mix.SIMILAR_CAP})

    def test_by_an_artist_means_their_own_albums(self):
        songs = mix.mix_songs([SONGS[2]], 20, similar=["Sleep"])
        self.assertNotIn(43, {s["songid"] for s in songs})  # Kyuss guests on Low's
        guest = SONGS[43]
        self.assertEqual(mix.credits(guest), ["Low"])

    def test_keep_holds_every_song_to_it(self):
        keep = mix.genre_rule(["Stoner"])
        songs = mix.mix_songs(
            [SONGS[2]], 10, share=0.2, similar=["Low", "Sleep"], keep=keep
        )
        # Low's songs are all Slowcore: none
        self.assertEqual(artists(songs), {"Kyuss": 4, "Sleep": mix.SIMILAR_CAP})

    def test_familiar_seeds_first_in_their_order(self):
        seeds = [SONGS[7], SONGS[0], SONGS[4]]
        songs = mix.mix_songs(seeds, 10, share=0.6, familiar=3)
        kyuss = [s["songid"] for s in songs if s["artist"] == ["Kyuss"]]
        self.assertEqual(kyuss[:3], [7, 0, 4])
        self.assertEqual(len(kyuss), 6)

    def test_a_fair_share_each(self):
        seeds = [SONGS[8], SONGS[9], SONGS[10], SONGS[7]]  # Sleep thrice, Kyuss once
        songs = mix.mix_songs(seeds, 6, share=1, familiar=3)
        # three each: Sleep's three seeds, then Kyuss's, though Sleep has 27 more
        self.assertEqual([s["songid"] for s in songs][:3], [8, 9, 10])
        self.assertEqual(artists(songs), {"Kyuss": 3, "Sleep": 3})

    def test_artists_alone_without_others_in_genre(self):
        songs = mix.mix_songs([SONGS[38]], 10)
        self.assertEqual(artists(songs), {"Low": 6})

    def test_keep_alone(self):  # a year's mix, or a genre with nothing played
        songs = mix.mix_songs([], 10, keep=mix.genre_rule(["Slowcore"]))
        self.assertEqual({s["songid"] for s in songs}, {38, 39, 40, 41, 42, 43})

    def test_a_seed_with_no_genre_takes_its_artists(self):
        seed = SONGS[2] | {"genre": []}
        songs = mix.mix_songs([seed], 10)
        self.assertEqual(artists(songs), {"Kyuss": 2, "Sleep": 8})


def ago(days: float) -> str:
    """A lastplayed as Kodi gives it, days ago."""
    return f"{datetime.now() - timedelta(days=days):%Y-%m-%d %H:%M:%S}"


def played(*rows: tuple) -> list[dict]:
    """Played songs: (songid, artist, genres "A/B"[, days ago, 2 by default])."""
    return [
        {
            "songid": n,
            "file": f"/p/{n}.flac",
            "artist": [a],
            "albumartist": [a],
            "genre": g.split("/"),
            "lastplayed": ago(days[0] if days else 2),
        }
        for n, a, g, *days in rows
    ]


PLAYED = played(
    (1, "Kyuss", "Stoner/Desert"),
    (2, "Kyuss", "Stoner/Desert"),
    (3, "Sleep", "Stoner/Desert"),
    (4, "Fu Manchu", "Stoner/Desert"),
    (5, "Fu Manchu", "Stoner"),
    (6, "Low", "Slowcore"),
    (7, "Codeine", "Slowcore"),
    (8, "Duster", "Slowcore", 0),  # the last played: its card leads
    (9, "Mogwai", "Post-rock"),  # two artists only: no mix
    (10, "Slint", "Post-rock"),
    (11, "Mogwai", "Post-rock"),
    (12, "Slint", "Post-rock"),
    (13, "Mogwai", "Post-rock"),
    (14, "Earth", "Drone"),  # one song seeds Stoner too: most of it is its own
    (15, "Earth", "Drone"),
    (16, "Sleep", "Drone/Stoner"),
    (17, "Low", "Drone"),
)


class Daily(unittest.TestCase):
    def setUp(self):
        self.cache = {}
        store = mock.Mock()
        store.get.side_effect = lambda key: self.cache.get(key)
        store.put.side_effect = lambda key, payload, ttl: self.cache.update(
            {key: (payload, True)}
        )
        store.expire.side_effect = lambda key: self.cache.update(
            {key: (self.cache[key][0], False)}
        )
        self.like = ["Om", "Yob"]
        self.similar = mock.Mock(side_effect=lambda names, parent: self.like)
        self.draws = mock.Mock(
            side_effect=lambda *a, **k: [{"songid": len(self.cache)}]
        )
        patches = (
            mock.patch.object(mix, "ApiCacheHandler", lambda: store),
            mock.patch.object(mix, "mix_songs", self.draws),
            mock.patch.object(mix, "played_songs", lambda genres: PLAYED),
            mock.patch.object(music, "similar_to", self.similar),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_genres_by_weight_the_last_played_first(self):
        genres = [genre for genre, _ in mix.leading_genres(PLAYED)]
        # Desert's songs all seed Stoner: passed over; Post-rock has two artists
        self.assertEqual(genres, ["Slowcore", "Stoner", "Drone"])

    def test_the_newest_listening_leads(self):  # N88: a month of hip hop, then this
        rap = [(n, f"MC{n % 4}", "Hip Hop", 25) for n in range(20)]
        rap += [
            (20, "MC0", "Hip Hop/Classical", 25),
            (21, "MC1", "Hip Hop/Classical", 25),
        ]
        bach = [(30 + n, f"Composer{n % 3}", "Classical", 0) for n in range(6)]
        genres = [genre for genre, _ in mix.leading_genres(played(*rap, *bach))]
        self.assertEqual(genres, ["Classical", "Hip Hop"])  # its rappers don't block it

    def test_by_weight_the_newest_likeliest_first(self):
        mix.random.seed(2)
        songs = played((1, "Low", "Slowcore", 0), (2, "Low", "Slowcore", 28))
        firsts = Counter(mix.by_weight(songs)[0]["songid"] for _ in range(2000))
        self.assertAlmostEqual(firsts[1] / 2000, 1 / (1 + 0.5**4), delta=0.02)

    def test_a_genre_mix_keeps_to_it_and_leans_on_its_leads(self):
        seeds = dict(mix.leading_genres(PLAYED))["Stoner"]
        drawn = mix.genre_mix("Stoner", seeds)
        self.similar.assert_called_with(["Kyuss", "Sleep", "Fu Manchu"], "mix")
        kwargs = self.draws.call_args.kwargs
        self.assertEqual(kwargs["keep"], mix.genre_rule(["Stoner"]))
        self.assertEqual(kwargs["similar"], ["Om", "Yob"])
        self.assertEqual(drawn["leads"], ["Kyuss", "Sleep", "Fu Manchu"])

    def test_kept_until_midnight_and_replayed(self):
        first = mix.kept_mix("Stoner", PLAYED[:5])
        ttl = mix.ApiCacheHandler().put.call_args.args[2]
        self.assertLessEqual(ttl, 86401)
        self.assertEqual(mix.kept_mix("Stoner"), first)  # the click: as the card's
        self.assertEqual(self.draws.call_count, 1)

    def test_redrawn_once_similar_answers_otherwise(self):
        kept = mix.kept_mix("Stoner", PLAYED[:5])
        mix.recheck_similar("Stoner", kept)  # as drawn: still fresh
        self.assertEqual(mix.kept_mix("Stoner"), kept)
        self.like = ["Om", "Yob", "Weedeater"]  # a lead looked up at the click
        mix.recheck_similar("Stoner", kept)
        self.assertNotEqual(mix.kept_mix("Stoner"), kept)
        self.assertEqual(self.draws.call_count, 2)


class Card(unittest.TestCase):
    STRINGS = {
        32838: "%s mix",
        32839: "Daily mix · %s songs",
        32840: "%s and %s.",
        32841: "%s and more.",
    }

    def card(self, names: list[str]) -> mock.Mock:
        songs = [{"artist": [n], "albumartist": [n]} for n in names]
        kept = {"songs": songs + songs[:2], "leads": names[:3], "similar": []}
        rows = [  # the library's order, not the mix's; Om has no thumb
            {"artist": n, "art": {"thumb": f"{n}.jpg"} if n != "Om" else {}}
            for n in sorted(names)
        ]
        with (
            mock.patch.object(music, "ListItem") as list_item,
            mock.patch.object(
                music, "json_call", return_value={"result": {"artists": rows}}
            ),
            mock.patch.object(music, "genre_ids", lambda: {"Stoner": 10}),
            mock.patch.object(music, "ADDON") as addon,
        ):
            addon.getLocalizedString = self.STRINGS.get
            [(path, _, folder)] = music.mix_cards([("Stoner", kept)])
        self.assertEqual((path, folder), ("musicdb://genres/10/", True))
        return list_item.return_value

    def test_artists_in_play_order(self):
        li = self.card(
            ["Kyuss", "Om", "Sleep", "Yob", "Earth", "Boris", "Sunn", "Low", "Melvins"]
        )
        props = li.setProperties.call_args.args[0]
        self.assertEqual(
            props["Artist_Description"],
            "Kyuss, Om, Sleep, Yob, Earth, Boris, Sunn, Low and more.",
        )
        self.assertEqual(props["eyebrow"], "Daily mix · 11 songs")  # the list's count
        self.assertEqual(props["mix_genreid"], "10")
        art = li.setArt.call_args.args[0]
        self.assertEqual(
            [art["square"], art["square1"], art["square2"]],
            ["Kyuss.jpg", "Sleep.jpg", "Yob.jpg"],
        )
        li.getMusicInfoTag.return_value.setGenres.assert_called_with(["Stoner"])

    def test_eight_or_fewer_and_no_more(self):
        for names, described in (
            (["Kyuss", "Sleep", "Om"], "Kyuss, Sleep and Om."),
            ([*"ABCDEFGH"], "A, B, C, D, E, F, G and H."),
        ):
            props = self.card(names).setProperties.call_args.args[0]
            self.assertEqual(props["Artist_Description"], described)

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


PLAYING = {"songid": 5, "artist": ["Kyuss"], "artistid": [1]}
PLAYING |= {"albumartist": ["Kyuss"], "genre": ["Stoner"]}


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
            mock.patch.object(music, "similar_artists", lambda *a: ["Sleep"]),
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
            monitor._extend_queue(PLAYING)
        return playlist, monitor, mixed

    def test_grows_below_ten_left(self):
        playlist, monitor, mixed = self.grow(20, 10)  # 9 left
        self.assertEqual(playlist.size(), 30)
        self.assertEqual(mixed.call_args.args[:3], ([PLAYING], 10, set(range(20))))
        self.assertEqual(mixed.call_args.kwargs, {"similar": ["Sleep"]})
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
