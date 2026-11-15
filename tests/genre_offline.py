"""
Offline checks for the genre buckets (shared/genres.py): any case, a whole
ListItem.Genre of several genres, exceptions before the terms they'd fall to,
MusicBrainz subgenres by their parent's bucket, unknown genres; every MusicBrainz
genre as the last snapshot left it; the music_genres mapping, a row a term in order.
Run from the helper root: python tests/genre_offline.py
"""

import json
import sys
import unittest
from pathlib import Path

HELPER = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HELPER))

from resources.lib.shared import genres  # noqa: E402
from resources.lib.shared.genres import genre_bucket  # noqa: E402

FIXTURE = HELPER / "tests/fixtures/genre_buckets.json"  # genre_snapshot.py writes it
REGGAE = {"genre_bucket": "Reggae"}


class Lookup(unittest.TestCase):
    def test_any_case(self):
        for genre in ("hip hop", "Hip Hop", "HIP HOP", "Hip-Hop"):
            self.assertEqual(genre_bucket(genre), "HipHop")
        # ASCII alone, as Kodi lower-cases (StringUtils::ToLower)
        self.assertEqual(genre_bucket("Forró"), "Latin")
        self.assertIsNone(genre_bucket("FORRÓ"))

    def test_several_genres_the_first_row_found(self):
        # Indie's row comes before Alternative's and Rock's, as the icon picks it
        self.assertEqual(genre_bucket("Indie Rock / Alternative"), "Indie")
        self.assertEqual(genre_bucket("Alternative / Indie Rock"), "Indie")
        self.assertEqual(genre_bucket("Jazz / Rock"), "Jazz")

    def test_exceptions_first(self):
        self.assertEqual(genre_bucket("Dancehall"), "Reggae")  # not dance's Electronic
        self.assertEqual(genre_bucket("Happy Hardcore"), "Electronic")  # not Hardcore
        self.assertIsNone(genre_bucket("Maskanda"))  # not ska's: the fallback

    def test_a_subgenre_takes_its_parents_bucket(self):
        self.assertEqual(genre_bucket("Phonk"), "HipHop")  # subgenre of hip hop
        self.assertEqual(genre_bucket("No Wave"), "Rock")  # not wave's Electronic
        self.assertIsNone(genre_bucket("Doina"))  # in none, though oi is Punk

    def test_a_subgenre_as_a_whole_tag_only(self):
        self.assertEqual(genre_bucket("Oi"), "Punk")
        self.assertEqual(genre_bucket("Phonk / Gqom"), "Electronic")  # gqom's row first
        self.assertEqual(genre_bucket("Soul / Phonk"), "Soul")  # keywords first
        self.assertEqual(genre_bucket("Drift Phonk"), "Electronic")  # its own row
        self.assertIsNone(genre_bucket("Brazilian Phonk Mix"))  # not a whole tag

    def test_common_tags_take_no_subgenres_bucket(self):
        # each holds a short subgenre name: oi, rage, plugg, mod, rave, isa, mass …
        for tag in (
            "Choir",
            "Voice",
            "Noir",
            "Garage",
            "Unplugged",
            "Modern",
            "Modal",
            "Travel",
            "Improvisation",
            "Massive",
            "Nomad",
            "Retrowave",
            "Vocal",
            "Instrumental",
            "Visual",
            "Clubbing",
            "Surfing",
            "Marching",
            "Snapshot",
            "Lieder / Choir",
        ):
            self.assertIsNone(genre_bucket(tag), tag)

    def test_unknown(self):
        self.assertIsNone(genre_bucket("Zzyzx"))
        self.assertIsNone(genre_bucket(""))

    def test_every_musicbrainz_genre_as_the_snapshot_left_it(self):
        table = json.loads(FIXTURE.read_text())
        changed = {g: b for g, b in table.items() if genre_bucket(g) != b}
        self.assertEqual(changed, {}, "the rules changed: run tests/genre_snapshot.py")


class Mapping(unittest.TestCase):
    def test_a_row_a_term_in_order(self):
        mapping = genres.genre_mapping()
        terms = [t for _, row in genres.rows() for t in row]
        self.assertEqual(mapping["items"], [*terms, *genres.SUBGENRES])
        self.assertEqual(len(mapping["items"]), len({*mapping["items"]}))  # by term
        meta = mapping["metadata"]
        self.assertEqual(meta["dancehall"], {"genre_match": "contains"} | REGGAE)
        self.assertEqual(meta["maskanda"]["genre_bucket"], "none")
        self.assertEqual(
            meta["phonk"], {"genre_match": "tag", "genre_bucket": "HipHop"}
        )
        self.assertLess(terms.index("dancehall"), terms.index("dance"))

    def test_the_skins_47_buckets(self):
        self.assertEqual(len(genres.KEYWORDS), 47)
        self.assertLessEqual(
            {b for b, _ in genres.EXCEPTIONS} - {None}, {*genres.KEYWORDS}
        )


if __name__ == "__main__":
    unittest.main()
