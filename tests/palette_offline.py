"""
Offline checks for the palette and the darken that carries it (art/compose.py,
ImageEditor._compose), on synthetic measurements: a logo with colour gets a lighter,
softer secondary of its own hue, a white one none; the darken is the art's alone
either way; without palette_ratio the palette darkens at the ratio, as before; with it
palette_darken is the accent's floor, the larger of the darken and the accent's need at
its own ratio (the logo's when it has colour, else the art's primary; neutral art with
a white logo leaves it the darken), uncapped by darken_max as before.
Run from the helper root: python tests/palette_offline.py
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
sys.path.insert(0, str(HELPER))

from resources.lib.art import compose, policy  # noqa: E402
from resources.lib.art.color import from_hex, luminance  # noqa: E402
from resources.lib.art.editor import ImageEditor  # noqa: E402
from resources.lib.plugin.opts import ArtOpts  # noqa: E402

CFG = policy.ColorConfig()
GHOSTED = CFG.element_overlay_color
ZONES = [{"art": [0.04, 0.6], "blur": [0.05, 0.22]}]  # the blur reads 0.05-0.22
RED, BLUE, GREY = "ffc81e1e", "ff1e50c8", "ff808080"
PARAMS = {
    "background_url": "fanart.jpg",
    "background_darken": "true",
    "background_darken_surface": "blur",
    "background_ratio": "5",
    "background_palette": "true",
}


def serve(art: str, logo: str | None, **params: str) -> dict:
    """
    Compose one background (accent ``art``) under a logo of colour ``logo``.

    :param art: The art's accent and dominant colour, hex.
    :param logo: The clearlogo's dominant colour, hex, or None for no logo.
    :return: The background's composed record.
    """
    measure = {"zones": ZONES, "accent": art, "dominant": art, "band": []}
    records = {"background": {policy.ART_FIELD_MEASURE: json.dumps(measure)}}
    if logo:
        records["clearlogo"] = {
            policy.ART_FIELD_MEASURE: json.dumps({"dominant": logo})
        }
    args = PARAMS | {f"background_{k}": v for k, v in params.items()}
    art_opts = {t: ArtOpts.from_params(args, t) for t in records}
    editor = ImageEditor.__new__(ImageEditor)
    editor.cfg = CFG
    editor._compose(records, art_opts, {})
    return records["background"]


def need(color: str, ratio: float) -> int:
    """The % black the blur needs for ``color`` at ``ratio``."""
    return compose.darken(ZONES, [(color, ratio)], "blur")


class Palette(unittest.TestCase):
    """The logo's secondary, and the accent's floor beside the page's darken."""

    def test_logo_secondary(self) -> None:
        got = serve(BLUE, RED)
        primary, secondary = compose.tones(from_hex(RED), CFG)
        self.assertEqual(got[policy.ART_FIELD_PALETTE_LOGO], primary)
        self.assertEqual(got[policy.ART_FIELD_PALETTE_LOGO_SECONDARY], secondary)
        self.assertGreater(luminance(from_hex(secondary)), luminance(from_hex(primary)))
        self.assertNotIn(policy.ART_FIELD_PALETTE_LOGO_SECONDARY, serve(BLUE, GHOSTED))

    def test_without_palette_ratio(self) -> None:
        got = serve(BLUE, RED)
        self.assertEqual(got[policy.ART_FIELD_DARKEN], need(GHOSTED, 5))
        self.assertEqual(
            got[policy.ART_FIELD_PALETTE_LOGO_DARKEN], need(got["palette_logo"], 5)
        )

    def test_logo_leads(self) -> None:
        got = serve(BLUE, RED, palette_ratio="3")
        logo = need(got[policy.ART_FIELD_PALETTE_LOGO], 3)
        self.assertEqual(got[policy.ART_FIELD_PALETTE_LOGO_DARKEN], logo)
        self.assertGreater(logo, need(GHOSTED, 5))  # the accent at 3:1 needs more here
        self.assertEqual(got[policy.ART_FIELD_DARKEN], need(GHOSTED, 5))
        self.assertEqual(got[policy.ART_FIELD_PALETTE_DARKEN], logo)

    def test_art_leads(self) -> None:
        got = serve(BLUE, GHOSTED, palette_ratio="3")
        art = need(got[policy.ART_FIELD_PALETTE_PRIMARY], 3)
        self.assertGreater(art, need(GHOSTED, 5))
        self.assertEqual(got[policy.ART_FIELD_DARKEN], need(GHOSTED, 5))
        self.assertEqual(got[policy.ART_FIELD_PALETTE_DARKEN], art)

    def test_neutral(self) -> None:
        got = serve(GREY, None, palette_ratio="3")
        self.assertEqual(got[policy.ART_FIELD_PALETTE_PRIMARY], GHOSTED)
        self.assertEqual(got[policy.ART_FIELD_PALETTE_DARKEN], need(GHOSTED, 5))
        logo = serve(GREY, RED, palette_ratio="3")  # neutral art: the logo still leads
        self.assertEqual(
            logo[policy.ART_FIELD_PALETTE_DARKEN], logo["palette_logo_darken"]
        )

    def test_floor(self) -> None:
        got = serve(BLUE, RED, palette_ratio="3", darken_max="10")
        self.assertEqual(got[policy.ART_FIELD_DARKEN], 10)
        self.assertGreater(got[policy.ART_FIELD_PALETTE_DARKEN], 10)  # never below it
        low = serve(
            BLUE, RED, palette_ratio="1"
        )  # an accent needing less than the page
        self.assertEqual(low[policy.ART_FIELD_PALETTE_DARKEN], need(GHOSTED, 5))

    def test_opt_in(self) -> None:
        self.assertIsNone(ArtOpts.from_params(PARAMS, "background").palette_ratio)
        args = PARAMS | {"background_palette_ratio": "3"}
        self.assertEqual(ArtOpts.from_params(args, "background").palette_ratio, 3.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
