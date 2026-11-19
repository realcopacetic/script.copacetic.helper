"""
Offline checks for the gallery tiles' share-out (resources/lib/art/multiart.py):
an image shows in one tile only (matched by the helper's image identity, a TMDb
file name in any size) unless a tile has no other image free; a joined family; the
first frame (multiart_first) leading a family; and seed_multiart's blind seed under a
dialog and its seed keys. Run from the helper root:
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
sys.modules["xbmc"].Monitor = None  # imported by multiart; SeedMultiart patches it
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


class FirstFrame(unittest.TestCase):
    """build_multiart_dict's first: it leads a family it isn't the source of."""

    ART = {"ListItem.Art(fanart)": "f", "ListItem.Art(fanart1)": "f1"}

    def family(self, first, art_type="fanart", tmdb_art={}):
        labels = lambda target, keys: {k: self.ART.get(f"{target}.{k}") for k in keys}
        with mock.patch.object(multiart, "get_infolabels", labels):
            art = build_multiart_dict(
                target="ListItem",
                multiart_type=art_type,
                max_items=15,
                tmdb_art=tmdb_art,
                first=first,
            )
        return list(art.values())

    def test_leads_the_family(self):
        self.assertEqual(self.family("thumb"), ["thumb", "f", "f1"])

    def test_dropped_from_later_in_the_family(self):
        self.assertEqual(self.family("f1"), ["f1", "f"])

    def test_empty_or_none_changes_nothing(self):
        self.assertEqual(self.family(""), ["f", "f1"])
        self.assertEqual(self.family(None), ["f", "f1"])

    def test_never_starts_a_family(self):
        self.assertEqual(self.family("thumb", art_type="poster"), [])

    def test_tmdb_copy_in_another_size_dropped(self):
        tmdb = {"fanart": f"{TMDB}/original/x.jpg"}
        out = self.family(f"{TMDB}/w780/x.jpg", tmdb_art=tmdb)
        self.assertEqual(out, [f"{TMDB}/w780/x.jpg", "f", "f1"])

    def test_stays_first_in_the_seeded_order(self):
        art = dict(zip(["multiart", "multiart1", "multiart2"], self.family("thumb")))
        self.assertEqual(multiart.order_multiart(art)[0], "thumb")


class SeedMultiart(unittest.TestCase):
    """Register 3400: the visualisation's (12006) and the music OSD's (10120)."""

    FAMILY = {"multiart": "a", "multiart1": "b"}

    def setUp(self):
        self.props, self.labels, self.reads, self.waits = {}, {}, [], []
        self.top = self.current = 12006
        test = self

        class Control:
            def __init__(self, i):
                self.i = i

            def reset(self):
                test.labels[self.i] = ""

            def addLabel(self, label):  # a FadeLabel shows its first label
                test.labels[self.i] = test.labels[self.i] or label

        class Monitor:
            def waitForAbort(self, seconds):
                test.waits.append(seconds)
                return False

            def abortRequested(self):
                return False

        def infolabel(label):
            self.reads.append(label)
            if label.startswith("Control.GetLabel("):
                return self.labels.get(int(label[17:-1]), "")
            return self.props.get(label.removeprefix("Window(home).Property(")[:-1], "")

        def window_property(key, value=False):
            if value:
                self.props[key] = f"{value}"
            else:
                self.props.pop(key, None)

        window = mock.Mock(getControl=Control)
        patches = mock.patch.multiple(
            multiart,
            Monitor=Monitor,
            Window=lambda window_id: window,
            getCurrentWindowId=lambda: self.current,
            infolabel=infolabel,
            topmost_window_id=lambda: self.top,
            window_property=window_property,
        )
        patches.start()
        self.addCleanup(patches.stop)

    def seed(self, window_id=12006, dialog=False, fadelabel_id="3400", alive=None):
        """seed_multiart's art for a two-image family of item 1, first visit."""
        return multiart.seed_multiart(
            fadelabel_id=fadelabel_id,
            multiart_dict=dict(self.FAMILY),
            art={"multiart": "a"},
            seed_scope="player@",
            seed_item="1//",
            alive=alive or (lambda: True),
            window_id=window_id,
            dialog=dialog,
        )

    def test_blind_seed_waits_a_pass_without_reading(self):
        self.top = 10120  # the OSD over the visualisation: reads would answer for it
        self.assertEqual(self.seed(), {"multiart": "a"})
        self.assertEqual(self.labels, {3400: "a"})
        self.assertEqual(self.waits, [0.04, 0.04])
        self.assertFalse([read for read in self.reads if "GetLabel" in read])
        self.assertEqual(self.props["multiart_seed_scope_3400"], "player@")
        self.assertTrue(self.props["multiart_seed_sig_3400"].startswith("1//:"))
        self.assertNotIn("multiart_frozen_3400", self.props)

    def test_blind_refire_trusts_its_signature(self):
        self.top = 10120
        self.seed()
        self.labels[3400] = "b"  # mid-rotation: a reseed would reset it
        self.seed()
        self.assertEqual(self.labels, {3400: "b"})

    def test_dialog_keys_its_own(self):
        self.props |= {"multiart_seed_scope_3400": "x", "multiart_seed_sig_3400": "y"}
        self.top = 10120
        self.seed(window_id=10120, dialog=True)
        self.assertEqual(self.props["multiart_seed_scope_3400_10120"], "player@")
        self.assertIn("multiart_seed_sig_3400_10120", self.props)
        self.assertEqual(
            (
                self.props["multiart_seed_scope_3400"],
                self.props["multiart_seed_sig_3400"],
            ),
            ("x", "y"),
        )

    def test_window_change_writes_no_keys(self):
        live = {
            "multiart_frozen_3400": "f",
            "multiart_seed_scope_3400": "x",
            "multiart_seed_sig_3400": "y",
        }
        self.props |= live  # the window now active seeded and froze register 3400
        self.current = 10025  # the active window changed during the serve
        self.seed()
        self.assertEqual(self.props, live)

    LIVE = {
        "multiart_frozen_3400": "f",
        "multiart_seed_scope_3400": "x",
        "multiart_seed_sig_3400": "y",
    }

    def test_visit_change_touches_nothing(self):
        # A→B→A: the handler names no register for the old visit's serve
        self.props |= self.LIVE  # the same window's new visit seeded and froze 3400
        self.labels[3400] = "b"
        self.assertEqual(self.seed(fadelabel_id=None), {"multiart": "a"})
        self.assertEqual((self.props, self.labels), (self.LIVE, {3400: "b"}))

    def test_guard_dying_mid_seed_writes_no_keys(self):
        self.props["multiart_seed_sig_3400"] = "y"
        # a visit ending mid-seed: the guard's first read follows the main image
        self.assertIsNone(self.seed(alive=lambda: False))
        self.assertEqual(self.labels, {3400: "a"})
        self.assertEqual(self.props["multiart_seed_sig_3400"], "y")
        self.assertNotIn("multiart_seed_scope_3400", self.props)

    def test_scope_change_clears_the_frame(self):
        self.props |= {"multiart_frozen_3400": "f", "multiart_seed_scope_3400": "x"}
        self.seed()
        self.assertNotIn("multiart_frozen_3400", self.props)
        self.assertEqual(self.props["multiart_seed_scope_3400"], "player@")

    def test_dialog_scope_change_clears_the_frame(self):
        self.props["multiart_frozen_3400"] = "f"  # the window under it froze 3400
        self.top = 10120
        self.seed(window_id=10120, dialog=True)
        self.assertNotIn("multiart_frozen_3400", self.props)


if __name__ == "__main__":
    unittest.main()
