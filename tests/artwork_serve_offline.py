"""
Offline checks for the artwork serve (PluginHandlers.artwork) with Kodi's reads
stubbed and the image work faked: the logo from clearlogo_source, with and without
a favourite's multiart_target, and the icon from icon_source (a cut band label the
item's own); a held serve names its position only for a move that stamped no visit.
Run from the helper root:
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
ICON = "https://x/poster.jpg|User-Agent=k"
ICON_SOURCE = "Container(50).ListItem(0).Art(poster)"
FAMILY = {"multiart": "fav0.jpg", "multiart1": "fav1.jpg"}


class ArtworkServe(unittest.TestCase):
    """A serve of the focused item in view 50, its window on top unless a menu is."""

    def serve(self, params: dict, on_top: bool = True) -> dict:
        """
        Run artwork() and report what it saw: logo, icon and label (the clearlogo and
        icon URLs and band label the image work got), family (the item the family was
        read from), seeded (the family seed_multiart got) and items (what it returned).

        :param params: The URL's params past the fixed ones.
        :param on_top: Whether the serve's window is topmost (else a menu is).
        :return: What it saw, by logo, icon, label, family, seeded and items.
        """
        seen = {}
        labels = {
            SOURCE: LOGO,
            ICON_SOURCE: ICON,
            "Container(50).CurrentItem": "3",
            "Container(50).ListItem.Label": "Title",
        }
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
            seen["icon"] = art_opts["icon"].url
            seen["label"] = art_opts["icon"].darken.label
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
                lambda self, through_info=False: SimpleNamespace(
                    alive=lambda: True, lost_to=""
                ),
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

    def test_icon_source_cut_reads_icon_and_label(self):
        out = self.serve({"clearlogo_source": SOURCE, "icon_source": ICON_SOURCE})
        self.assertEqual((out["logo"], out["icon"]), (LOGO, ICON))
        self.assertEqual(out["label"], "Title")

    def test_icon_source_keeps_a_label_that_arrived(self):
        params = {"icon_source": ICON_SOURCE, "icon_darken_label": "Title • 2024"}
        out = self.serve(params | {"icon_url": "poster.jpg"})
        self.assertEqual((out["icon"], out["label"]), (ICON, "Title • 2024"))

    def test_empty_icon_source_keeps_the_url(self):
        out = self.serve({"icon_source": "", "icon_url": "black.png"})
        self.assertEqual((out["icon"], out["label"]), ("black.png", None))

    def test_no_icon_source_no_label_read(self):
        self.assertIsNone(self.serve({"icon_url": "poster.jpg"})["label"])

    def test_menu_on_top_icon_source_cut(self):
        out = self.serve({"icon_source": ICON_SOURCE}, on_top=False)
        self.assertEqual((out["icon"], out["label"]), (None, None))
        self.assertTrue(out["items"])


class HeldNaming(unittest.TestCase):
    """A held serve names its position only for a move that stamped no visit."""

    def hold(
        self,
        params: dict | None = None,
        lost_to: str = "9",
        visit: str = "v1",
        on_top: bool = True,
        cursor: str | None = None,
        serve: bool = False,
    ) -> tuple[str, str, str | None]:
        """
        Hold a serve of position 7 in view 50 and report Home's counts after.

        :param params: Params replacing the defaults.
        :param lost_to: The identity the failed guard read; empty for another failure.
        :param visit: The live visit stamp (the URL carries v1).
        :param on_top: Whether the serve's window is topmost.
        :param cursor: The cursor stamp; None for 50/3/12/v1, empty for cleared.
        :param serve: Run artwork(), whose real guard reads lost_to, not the hold alone.
        :return: (artwork_holds, artwork_holds_unstamped, artwork_held_primary).
        """
        home = {
            "artwork_visit": visit,
            "artwork_holds": "4",
            "artwork_holds_unstamped": "2",
            "artwork_cursor_primary": "50/3/12/v1" if cursor is None else cursor,
        }
        # The cursor is back already; a serve's guard reads where it went instead.
        here = {"Container(50).CurrentItem": lost_to if serve else "7"}

        def infolabel(label):
            if label.startswith("Window(home).Property("):
                return home.get(label[22:-1], "")
            return here.get(label, "")

        def window_property(name, value=None, *args):
            home[name] = str(value)

        handler = handlers.PluginHandlers(
            {
                "info": "artwork",
                "target": "50",
                "prop_key": "9300",
                "focus_guard": "7",
                "cursor_key": "primary",
                "visit": "v1",
            }
            | (params or {})
        )
        handler.__dict__["window_id"] = WINDOW
        with mock.patch.multiple(
            handlers,
            infolabel=infolabel,
            window_property=window_property,
            topmost_window_id=lambda: WINDOW if on_top else MENU,
            set_items=lambda items: items,
            plugin_path=lambda name: name,
            focused_control_id=lambda window_id: 50,
            getCurrentWindowDialogId=lambda: 9999,
        ):
            if serve:
                handler.artwork()
            else:
                handler._artwork_held(lost_to)
        return (
            home["artwork_holds"],
            home["artwork_holds_unstamped"],
            home.get("artwork_held_primary"),
        )

    NAMED, UNNAMED = ("5", "3", "7"), ("5", "2", None)

    def test_jumpbar_move_named_though_the_cursor_is_back(self):
        self.assertEqual(self.hold(), self.NAMED)

    def test_serve_names_the_position_its_guard_lost(self):
        self.assertEqual(self.hold(serve=True), self.NAMED)

    def test_list_move_new_visit(self):
        self.assertEqual(self.hold(visit="v2"), self.UNNAMED)

    def test_under_a_dialog(self):
        self.assertEqual(self.hold(on_top=False), self.UNNAMED)

    def test_not_a_move(self):
        self.assertEqual(self.hold(lost_to=""), self.UNNAMED)

    def test_cursor_container_in_another_window(self):
        cursor = "51/3/12/v1"  # Home over a trailer: Videos' view isn't here
        self.assertEqual(self.hold(cursor=cursor), self.UNNAMED)

    def test_cursor_cleared(self):
        self.assertEqual(self.hold(cursor=""), self.UNNAMED)

    def test_player_serve(self):
        params = {"target": "player", "cursor_key": ""}  # no cursor
        self.assertEqual(self.hold(params), self.UNNAMED)

    def test_identity_labels(self):
        params = {"identity_labels": "Container(50).ListItem.DBID"}
        self.assertEqual(self.hold(params), self.UNNAMED)


if __name__ == "__main__":
    unittest.main()
