"""
Offline checks for the artwork serve (PluginHandlers.artwork) with Kodi's reads
stubbed and the image work faked: the logo from clearlogo_source, with and without
a favourite's multiart_target. Run from the helper root:
python tests/artwork_serve_offline.py
"""

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
vars(sys.modules["xbmc"]).update(  # imported names; nothing here calls them
    Monitor=None,
    getCacheThumbName=None,
    getLocalizedString=None,
    AudioStreamDetail=None,
    SubtitleStreamDetail=None,
    VideoStreamDetail=None,
)
sys.modules["xbmcplugin"].SORT_METHOD_LASTPLAYED = 0
sys.path.insert(0, str(HELPER))

from resources.lib.art import editor, multiart  # noqa: E402
from resources.lib.plugin import handlers  # noqa: E402

WINDOW, MENU = 10025, 10106
LOGO = "https://x/logo.png|User-Agent=k"
SOURCE = "Container(50).ListItem.Art(clearlogo)"
FAMILY = {"multiart": "fav0.jpg", "multiart1": "fav1.jpg"}


class ArtworkServe(unittest.TestCase):
    """A serve of the focused item in view 50, its window on top unless a menu is."""

    def serve(self, params: dict, on_top: bool = True) -> dict:
        """
        Run artwork() and report what it saw and returned.

        :param params: The URL's params past the fixed ones.
        :param on_top: Whether the serve's window is topmost (else a menu is).
        :return: logo (the clearlogo URL the image work got), family (the item the
            family was read from), seeded (the family seed_multiart got), items.
        """
        seen = {}
        labels = {SOURCE: LOGO, "Container(50).CurrentItem": "3"}
        handler = handlers.PluginHandlers(
            {
                "info": "artwork",
                "target": "50",
                "focus_guard": "3",
                "prop_key": "9300",
                "background_url": "fanart.jpg",
            }
            | params
        )
        handler.__dict__["window_id"] = WINDOW

        def images(jobs, art_opts, source):
            seen["logo"] = art_opts["clearlogo"].url
            return {"background": "blur.png"}

        def family(self, item, multiart_type):
            seen["family"] = item
            self._tmdb_missed = None
            return FAMILY if item.startswith("Container(9040)") else {}

        def seed(**kwargs):
            seen["seeded"] = kwargs["multiart_dict"]
            return kwargs["art"]

        with (
            mock.patch.multiple(
                handlers,
                infolabel=lambda label: labels.get(label, ""),
                topmost_window_id=lambda: WINDOW if on_top else MENU,
                focused_control_id=lambda window_id: 50,
                window_property=lambda *a, **k: None,
                set_items=lambda items: items,
                plugin_path=lambda name: name,
                _info_open=lambda: False,
            ),
            mock.patch.object(
                handlers.PluginHandlers,
                "_guard",
                lambda self, through_info=False: SimpleNamespace(alive=lambda: True),
            ),
            mock.patch.object(handlers.PluginHandlers, "_multiart_dict", family),
            mock.patch.object(
                editor, "ImageEditor", lambda: SimpleNamespace(image_processor=images)
            ),
            mock.patch.object(multiart, "seed_multiart", seed),
        ):
            seen["items"] = handler.artwork()
        return seen

    def test_source_read_headers_kept(self):
        out = self.serve({"clearlogo_source": SOURCE})
        self.assertEqual(out["logo"], LOGO)
        self.assertEqual(out["family"], "Container(50).ListItem")
        self.assertTrue(out["items"])

    def test_source_over_a_header_less_url(self):
        out = self.serve({"clearlogo_source": SOURCE, "clearlogo_url": "logo.png"})
        self.assertEqual(out["logo"], LOGO)

    def test_empty_source_no_logo(self):
        out = self.serve({"clearlogo_source": ""})
        self.assertIsNone(out["logo"])
        self.assertTrue(out["items"])

    def test_no_source_keeps_the_url(self):
        self.assertEqual(self.serve({"clearlogo_url": "logo.png"})["logo"], "logo.png")

    def test_favourite_family_with_a_source(self):
        fav = {"multiart_target": "9040", "multiart": "fanart"}
        out = self.serve(fav | {"clearlogo_source": SOURCE})
        self.assertEqual(out["family"], "Container(9040).ListItem")
        self.assertEqual(out["seeded"], FAMILY)
        self.assertEqual(out["logo"], LOGO)

    def test_favourite_family_with_an_empty_source(self):
        fav = {"multiart_target": "9040", "multiart": "fanart"}
        out = self.serve(fav | {"clearlogo_source": ""})
        self.assertEqual(out["family"], "Container(9040).ListItem")
        self.assertEqual(out["seeded"], FAMILY)

    def test_menu_on_top_keeps_the_url(self):
        params = {"clearlogo_source": SOURCE, "clearlogo_url": "logo.png"}
        self.assertEqual(self.serve(params, on_top=False)["logo"], "logo.png")

    def test_menu_on_top_cut_serves_without_a_logo(self):
        out = self.serve({"clearlogo_source": SOURCE}, on_top=False)
        self.assertIsNone(out["logo"])
        self.assertTrue(out["items"])


if __name__ == "__main__":
    unittest.main()
