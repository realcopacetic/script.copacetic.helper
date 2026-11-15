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


class Lookup(unittest.TestCase):
    def test_any_case(self):
        for genre in ("hip hop", "Hip Hop", "HIP HOP", "Hip-Hop"):
            self.assertEqual(genre_bucket(genre), "HipHop")

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
        self.assertEqual(mapping["items"], terms)
        self.assertEqual(len(terms), len({*terms}))  # metadata is keyed by term
        bucket = {t: mapping["metadata"][t]["genre_bucket"] for t in terms}
        self.assertEqual(bucket["dancehall"], "Reggae")
        self.assertEqual(bucket["maskanda"], "none")
        self.assertLess(terms.index("dancehall"), terms.index("dance"))

    def test_the_skins_47_buckets(self):
        self.assertEqual(len(genres.KEYWORDS), 47)
        self.assertLessEqual(
            {b for b, _ in genres.EXCEPTIONS} - {None}, {*genres.KEYWORDS}
        )


if __name__ == "__main__":
    unittest.main()
