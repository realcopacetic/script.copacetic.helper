"""
Offline checks for the gallery tiles' share-out (resources/lib/art/multiart.py):
an image shows in one tile only (matched by the helper's image identity, a TMDb
file name in any size) unless a tile has no other image free. Run from the helper root:
python tests/multiart_offline.py
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
sys.modules["xbmc"].Monitor = None  # imported by multiart; share_out never calls it
sys.path.insert(0, str(HELPER))

from resources.lib.art import multiart  # noqa: E402
from resources.lib.art.multiart import build_multiart_dict, share_out  # noqa: E402

TMDB = "https://image.tmdb.org/t/p"


class ShareOut(unittest.TestCase):
    def test_distinct_mains_kept(self):
        families = {3402: ["p", "p1"], 3404: ["k", "k1"]}
        self.assertEqual(share_out(families), families)

    def test_later_duplicate_falls_back_to_free_extra(self):
        families = {3402: ["p", "p1"], 3404: ["p", "k1", "k2"]}
        self.assertEqual(share_out(families), {3402: ["p", "p1"], 3404: ["k1", "k2"]})

    def test_same_tmdb_file_in_another_size(self):
        families = {
            3402: [f"{TMDB}/w780/x.jpg"],
            3404: [f"{TMDB}/original/x.jpg", "k1"],
        }
        self.assertEqual(share_out(families)[3404], ["k1"])

    def test_fallback_skips_images_held_elsewhere(self):
        families = {3402: ["p", "s"], 3404: ["p", "s", "k2"], 3405: ["s"]}
        shared = share_out(families)
        self.assertEqual(shared, {3402: ["p"], 3404: ["k2"], 3405: ["s"]})

    def test_fallback_claims_before_turns(self):
        families = {3402: ["p", "x"], 3404: ["p", "x"]}
        self.assertEqual(share_out(families), {3402: ["p"], 3404: ["x"]})

    def test_duplicate_without_extra_keeps_its_main(self):
        families = {3402: ["p", "p1"], 3404: ["p"]}
        self.assertEqual(share_out(families), {3402: ["p", "p1"], 3404: ["p"]})

    def test_duplicate_whose_extras_are_held_keeps_its_main(self):
        families = {3402: ["p", "s"], 3404: ["p", "s"], 3405: ["s"]}
        self.assertEqual(share_out(families), {3402: ["p"], 3404: ["p"], 3405: ["s"]})


class JoinedFamily(unittest.TestCase):
    """A comma-separated multiart reads each type in turn, each image once."""

    ART = {
        "Player.Art(thumb)": "cover",
        "Player.Art(artist.thumb)": "cover",
        "Player.Art(artist.fanart)": "f",
        "Player.Art(artist.fanart2)": "f2",
    }

    def family(self, multiart_type, tmdb_art={}):
        labels = lambda target, keys: {k: self.ART.get(f"{target}.{k}") for k in keys}
        with mock.patch.object(multiart, "get_infolabels", labels):
            return build_multiart_dict(
                target="Player",
                multiart_type=multiart_type,
                max_items=15,
                tmdb_art=tmdb_art,
            )

    def test_types_join_in_order_without_repeats(self):
        self.assertEqual(
            self.family("thumb,artist.thumb,artist.fanart"),
            {"multiart": "cover", "multiart1": "f", "multiart2": "f2"},
        )

    def test_one_type_is_unchanged(self):
        self.assertEqual(
            self.family("artist.fanart"), {"multiart": "f", "multiart1": "f2"}
        )

    def test_tmdb_extends_one_type_only(self):
        tmdb = {"artist.fanart": "t", "thumb": "t"}
        self.assertEqual(self.family("artist.fanart", tmdb)["multiart2"], "t")
        self.assertNotIn("t", self.family("thumb,artist.fanart", tmdb).values())


if __name__ == "__main__":
    unittest.main()
