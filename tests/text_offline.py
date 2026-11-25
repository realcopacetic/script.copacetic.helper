"""
Offline checks for the text image (art/text.py TextRenderer, shared/helpers.py
gui_scale): the scale from the GUI height, a 1x image drawn 2x and shrunk, a 2x image
drawn 1:1, both reporting the same height in skin pixels, cached apart and from cache.
Needs Pillow and the skin's fonts.
Run from the helper root: python tests/text_offline.py [../skin.copacetic2]
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from build_offline import HELPER, install_stubs

SKIN = Path(sys.argv.pop(1) if len(sys.argv) > 1 else HELPER.parent / "skin.copacetic2")
FONT = str(SKIN.resolve() / "fonts" / "Onest-SemiBold.ttf")
STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)


class File:
    """xbmcvfs.File over a local path, writable as Kodi's is."""

    def __init__(self, path, mode="r"):
        self.fh = open(path, mode)

    def __enter__(self):
        return self.fh

    def __exit__(self, *exc):
        self.fh.close()
        return False


xbmcvfs = sys.modules["xbmcvfs"]
translate = xbmcvfs.translatePath
xbmcvfs.translatePath = lambda path: path if path.startswith("/") else translate(path)
xbmcvfs.mkdirs = lambda path: os.makedirs(path, exist_ok=True) or True
xbmcvfs.File = File
sys.modules["xbmc"].Monitor = None  # imported by shared/helpers.py
sys.path.insert(0, str(HELPER))

from PIL import Image  # noqa: E402

from resources.lib.art.text import TextRenderer  # noqa: E402
from resources.lib.shared import helpers  # noqa: E402

PLOT = (
    "When a young boy vanishes, a small town uncovers a mystery involving secret "
    "experiments, terrifying supernatural forces and one strange little girl."
)


class GuiScaleTest(unittest.TestCase):
    def scale(self, height: str) -> int:
        with mock.patch.object(helpers, "infolabel", lambda label: height):
            return helpers.gui_scale()

    def test_rounds_up_from_the_skin_height(self):
        self.assertEqual([self.scale(h) for h in ("720", "1080")], [1, 1])
        self.assertEqual([self.scale(h) for h in ("1440", "2160")], [2, 2])

    def test_no_height_is_1x(self):
        self.assertEqual(self.scale(""), 1)


class RenderTest(unittest.TestCase):
    def render(self, scale: int) -> tuple[str, int]:
        return TextRenderer().render(
            text=PLOT,
            font_path=FONT,
            font_size=46,
            box_width=1280,
            max_height=580,
            line_height=1.1,
            letter_spacing=-1.5,
            scale=scale,
        )

    def test_2x_image_is_twice_the_box_at_the_same_skin_height(self):
        path_1x, height_1x = self.render(1)
        path_2x, height_2x = self.render(2)
        self.assertNotEqual(path_1x, path_2x)
        with Image.open(path_1x) as im_1x, Image.open(path_2x) as im_2x:
            self.assertEqual(im_1x.width, 1280)
            self.assertEqual(im_2x.width, 2560)
            self.assertEqual(height_1x, im_1x.height)
            self.assertEqual(height_2x, -(-im_2x.height // 2))
        self.assertLessEqual(abs(height_1x - height_2x), 1)

    def test_cache_hit_reports_skin_pixels(self):
        self.assertEqual(self.render(2), self.render(2))


if __name__ == "__main__":
    unittest.main(verbosity=2)
