"""
Offline checks for the gallery tiles' share-out (resources/lib/art/multiart.py):
an image shows in one tile only, matched by the helper's image identity (a TMDb
file name in any size). Run from the helper root: python tests/multiart_offline.py
"""

import sys
import tempfile
import unittest
from pathlib import Path

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, HELPER, STAGE, STAGE, verbose=False)
for name in ("xbmc", "xbmcgui"):  # multiart imports Monitor and Window
    sys.modules[name].__getattr__ = lambda attr: type(attr, (), {})
sys.path.insert(0, str(HELPER))

from resources.lib.art.multiart import share_out  # noqa: E402

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

    def test_duplicate_without_extra_is_empty(self):
        families = {3402: ["p", "p1"], 3404: ["p"]}
        self.assertEqual(share_out(families), {3402: ["p", "p1"], 3404: []})


if __name__ == "__main__":
    unittest.main()
