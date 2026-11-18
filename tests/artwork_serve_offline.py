"""
Offline checks for the artwork serve (PluginHandlers.artwork) with Kodi's reads
stubbed and the image work faked: the logo from clearlogo_source and the icon from
icon_source (a cut band label the item's own); a background read whole by a skin
variable's name, standing only where the URL's raw value is it or it cut at "&" or
"|" (a cut-off URL only on top, an empty one never); the parser keeps art URLs raw and url_decode_path
leaves a bare URL; a held serve names its position only for a move that stamped no
visit; under Kodi's slideshow a run stops once its picture has moved on;
the TV guide's time left (epg_time_left) from the programme's start and runtime,
across midnight too, only while the URL's channel is on air and before its end.
Run from the helper root:
python tests/artwork_serve_offline.py
"""

import sys
import tempfile
import unittest
from datetime import datetime
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
from resources.lib.plugin import handlers, opts  # noqa: E402
from resources.lib.shared.parser import parse_plugin_argv  # noqa: E402
from resources.lib.shared.utilities import url_decode_path  # noqa: E402

WINDOW, MENU, PICTURES = 10025, 10106, 10002
LOGO = "https://x/logo.png|User-Agent=k"
SOURCE = "Container(50).ListItem.Art(clearlogo)"
ICON = "https://x/poster.jpg|User-Agent=k"
ICON_SOURCE = "Container(50).ListItem(0).Art(poster)"
VAR = "art_background_primary"
PLEX = "https://plex/photo/x.jpg?width=500&X-Plex-Token=a%2Bb"


class ArtworkServe(unittest.TestCase):
    """A serve of the focused item in view 50, its window on top unless a menu is."""

    def serve(self, params: dict, on_top: bool = True, visit_ends: str = "") -> dict:
        """
        Run artwork() and report what it saw: logo, icon and label (the clearlogo and
        icon URLs and band label the image work got), background, register
        (seed_multiart's fadelabel_id) and items (what it returned).

        :param params: The URL's params past the fixed ones.
        :param on_top: Whether the serve's window is topmost (else a menu is).
        :param visit_ends: Where visit v1 gives way to v2: "images" or "seed".
        :return: What it saw, by logo, icon, label, background, register and items.
        """
        seen = {}
        visit = "Window(home).Property(artwork_visit)"
        labels = {
            visit: "v1",
            SOURCE: LOGO,
            ICON_SOURCE: ICON,
            f"$VAR[{VAR}]": PLEX,
            "Container(50).CurrentItem": "3",
            "Container(50).ListItem.Label": "Title",
            "Player.Title": "Song",
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
            seen["background"] = art_opts["background"].url
            seen["label"] = art_opts["icon"].darken.label
            if visit_ends == "images":
                labels[visit] = "v2"
            return {"background": "blur.png"}

        def family(self, multiart_type):
            self._tmdb_missed = None
            return {}

        def seed(**kwargs):  # seed_multiart: None when its guard dies mid-seed
            seen["register"] = kwargs["fadelabel_id"]
            if visit_ends == "seed":
                labels[visit] = "v2"
            return kwargs["art"] if kwargs["alive"]() else None

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
        self.assertTrue(out["items"])

    def test_source_over_a_header_less_url(self):
        url = LOGO.partition("|")[0]  # the URL's value, cut at Kodi's "|"
        out = self.serve({"clearlogo_source": SOURCE, "clearlogo_url": url})
        self.assertEqual(out["logo"], LOGO)

    def test_a_read_the_url_disagrees_with_stands_down(self):
        # the label moved on since Kodi built the URL (or a dialog answered)
        out = self.serve({"clearlogo_source": SOURCE, "clearlogo_url": "logo.png"})
        self.assertEqual(out["logo"], "logo.png")

    def test_empty_source_no_logo(self):
        out = self.serve({"clearlogo_source": ""})
        self.assertIsNone(out["logo"])
        self.assertTrue(out["items"])

    def test_no_source_keeps_the_url(self):
        self.assertEqual(self.serve({"clearlogo_url": "logo.png"})["logo"], "logo.png")

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

    def test_player_icon_source_cut_reads_the_title(self):
        out = self.serve({"target": "player", "icon_source": ICON_SOURCE})
        self.assertEqual((out["icon"], out["label"]), (ICON, "Song"))

    def test_icon_source_keeps_a_label_that_arrived(self):
        params = {"icon_source": ICON_SOURCE, "icon_darken_label": "Title • 2024"}
        out = self.serve(params | {"icon_url": "https://x/poster.jpg"})
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

    def plex(self, on_top: bool = True, **params: str) -> dict:
        """Serve the URL Kodi passes for the Plex fanart, parsed as main.py does."""
        query = f"?info=artwork&background_var={VAR}&background_url={PLEX}"
        parsed = parse_plugin_argv(["plugin://x/", "1", query], raw=opts.ART_URLS)
        return self.serve(parsed | params, on_top)

    def test_a_variable_read_whole(self):
        self.assertEqual(self.plex()["background"], PLEX)

    def test_under_a_menu_a_read_the_url_vouches_for(self):
        self.assertEqual(self.plex(on_top=False)["background"], PLEX)

    def test_under_a_menu_an_empty_url_reads_nothing(self):
        out = self.serve({"background_var": VAR, "background_url": ""}, on_top=False)
        self.assertNotIn("background", out)  # no art: no image work at all

    VISIT = {"visit": "v1", "multiart_fadelabel": "3400"}

    def held(self, out: dict) -> bool:
        """Whether the serve returned a hold."""
        return out["items"][0]["properties"]["current"].startswith("held/")

    def test_a_live_visit_seeds_its_register(self):
        out = self.serve(self.VISIT)
        self.assertEqual(out["register"], "3400")
        self.assertFalse(self.held(out))

    def test_a_visit_ended_before_the_seed_leaves_the_register(self):
        # A→B→A: back in the same window, the new visit's register is live
        self.assertIsNone(self.serve(self.VISIT, visit_ends="images")["register"])

    def test_a_visit_ending_mid_seed_holds(self):
        out = self.serve(self.VISIT, visit_ends="seed")
        self.assertEqual(out["register"], "3400")
        self.assertTrue(self.held(out))


class ArtUrls(unittest.TestCase):
    """The parser, the reads and url_decode_path keep an art URL as Kodi holds it."""

    def test_the_parser_keeps_art_urls_raw(self):
        query = f"?background_url={PLEX}&label=a%20b"
        parsed = parse_plugin_argv(["plugin://x/", "1", query], raw=opts.ART_URLS)
        self.assertEqual(parsed["background_url"], PLEX.partition("&")[0])
        self.assertEqual(parsed["label"], "a b")

    def test_reads_by_infolabel_or_variable_name(self):
        params = {"clearlogo_source": SOURCE, "icon_var": "v", "background_var": ""}
        self.assertEqual(
            opts.art_reads(params),
            {"clearlogo_url": SOURCE, "icon_url": "$VAR[v]"},
        )

    def test_a_source_outranks_a_variable(self):
        params = {"icon_source": ICON_SOURCE, "icon_var": "v"}
        self.assertEqual(opts.art_reads(params), {"icon_url": ICON_SOURCE})

    def reads(self, url: str | None, read: str, on_top: bool = True) -> dict:
        """read_art_urls of a background_var whose label reads ``read``."""
        params = {"background_var": VAR} | (
            {} if url is None else {"background_url": url}
        )
        return opts.read_art_urls(params, {f"$VAR[{VAR}]": read}.get, on_top)

    def test_a_read_must_extend_the_urls_value(self):
        self.assertEqual(self.reads("https://plex/other.jpg", PLEX), {})

    def test_an_ampersand_extension_stands(self):
        self.assertEqual(
            self.reads(PLEX.partition("&")[0], PLEX), {"background_url": PLEX}
        )

    def test_a_pipe_extension_stands(self):
        self.assertEqual(
            self.reads(LOGO.partition("|")[0], LOGO), {"background_url": LOGO}
        )

    def test_a_longer_name_is_another_image(self):
        self.assertEqual(self.reads("https://x/art/12", "https://x/art/123"), {})
        self.assertEqual(self.reads("https://x/f.jpg", "https://x/f.jpg.1"), {})

    def test_a_present_empty_url_is_no_image(self):
        # a clearlogo-only item: its neighbour's fanart, read after a move, never lands
        self.assertEqual(self.reads("", "https://x/neighbour.jpg"), {})

    def test_a_cut_off_url_reads_on_top_only(self):
        self.assertEqual(self.reads(None, PLEX), {"background_url": PLEX})
        self.assertEqual(self.reads(None, PLEX, on_top=False), {})

    def test_a_bare_url_is_kodis_key_as_it_stands(self):
        self.assertEqual(url_decode_path(PLEX), PLEX)
        self.assertEqual(url_decode_path("/media/a%20b.jpg"), "/media/a%20b.jpg")

    def test_a_wrapped_url_unwraps(self):
        wrapped = "image://https%3a%2f%2fx%2fa%20b.jpg/"
        self.assertEqual(url_decode_path(wrapped), "https://x/a b.jpg")


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
        key: str = "primary",
    ) -> tuple[str, str, str | None]:
        """
        Hold a serve of position 7 in view 50 and report Home's counts after.

        :param params: Params replacing the defaults.
        :param lost_to: The identity the failed guard read; empty for another failure.
        :param visit: The live visit stamp (the URL carries v1).
        :param on_top: Whether the serve's window is topmost.
        :param cursor: The cursor stamp; None for 50/3/12/v1, empty for cleared.
        :param serve: Run artwork(), whose real guard reads lost_to, not the hold alone.
        :param key: The held name read back (artwork_held_<key>).
        :return: (artwork_holds, artwork_holds_unstamped, artwork_held_<key>).
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
            home.get(f"artwork_held_{key}"),
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

    def test_list_without_cursor_names_its_hold(self):
        params = {"cursor_key": "", "hold_key": "editor_50"}  # the playlist editor
        self.assertEqual(self.hold(params, cursor="", key="editor_50"), self.NAMED)
        self.assertEqual(self.hold(params, serve=True, key="editor_50"), self.NAMED)


class SlideshowGuard(unittest.TestCase):
    """Under Kodi's slideshow a run follows its picture; under another modal it holds."""

    def alive(
        self, live: str, modal: int = 12007, params: dict | None = None
    ) -> tuple[bool, str]:
        """
        Guard a run of picture 12/340 (or params' run) from Pictures, under a modal.

        :param live: The slide index Kodi shows now.
        :param modal: The topmost modal dialog.
        :param params: Guard params replacing the picture's.
        :return: (alive, lost_to).
        """
        handler = handlers.PluginHandlers(
            {"info": "artwork"}
            | (
                params
                or {
                    "focus_guard": "12/340",
                    "identity_labels": "Slideshow.SlideIndex",
                }
            )
        )
        handler.__dict__["window_id"] = PICTURES
        labels = {"Slideshow.SlideIndex": live}  # Container reads answer empty
        with mock.patch.multiple(
            handlers,
            infolabel=lambda label: labels.get(label, ""),
            getCurrentWindowId=lambda: PICTURES,
            getCurrentWindowDialogId=lambda: modal,
            _info_open=lambda: False,
        ):
            guard = handler._guard(through_info=True)
            return guard.alive(), guard.lost_to

    def test_the_same_picture_carries_on(self):
        self.assertEqual(self.alive("12/340"), (True, ""))

    def test_a_step_stops_the_run(self):
        self.assertEqual(self.alive("13/340"), (False, "13/340"))

    def test_another_modal_still_holds(self):
        self.assertEqual(self.alive("13/340", modal=MENU), (True, ""))

    def test_a_dual_rail_under_the_slideshow_holds(self):
        # Home's two-label guard reads "," at context 0 under the slideshow
        dual = {
            "focus_guard": "3,5",
            "identity_labels": "Container(32060).CurrentItem,Container(3206).CurrentItem",
        }
        self.assertEqual(self.alive("13/340", params=dual), (True, ""))


class EpgTimeLeft(unittest.TestCase):
    """A guide programme from its URL, against a fixed clock (UTC)."""

    def serve(
        self,
        now: str = "2026-11-16 20:22:05",
        start: str = "2026-11-16 20:00:00",
        runtime: int = 3600,
    ) -> list | None:
        """
        Run epg_time_left() with the clock stubbed; it reads nothing from Kodi.

        :param now: The clock.
        :param start: The programme's start, as its path holds it.
        :param runtime: The programme's runtime in seconds.
        :return: What it returned.
        """

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.fromisoformat(now).replace(tzinfo=tz)

        params = {
            "programme": f"pvr://guide/0012/{start}.epg",
            "runtime": str(runtime),
            "visit": "20:14:05",
        }
        with mock.patch.multiple(
            handlers,
            datetime=Clock,
            set_items=lambda items: items,
            plugin_path=lambda name: name,
        ):
            return handlers.PluginHandlers(params).epg_time_left()

    def test_time_left(self):
        (item,) = self.serve()
        self.assertEqual(item["label"], "pvr://guide/0012/2026-11-16 20:00:00.epg")
        self.assertEqual(item["properties"], {"time_left": "38m", "visit": "20:14:05"})

    def test_over_an_hour(self):
        (item,) = self.serve(now="2026-11-16 20:00:30", runtime=7200)
        self.assertEqual(item["properties"]["time_left"], "2h")

    def test_across_midnight(self):
        (item,) = self.serve(
            now="2026-11-17 00:05:00", start="2026-11-16 23:30:00", runtime=5400
        )
        self.assertEqual(item["properties"]["time_left"], "55m")

    def test_timeshifted_past_its_end(self):
        self.assertIsNone(self.serve(now="2026-11-16 21:00:10"))


class CoverSize(unittest.TestCase):
    """The visualisation's serve publishes its song's cover size, keyed by its file."""

    def publish(
        self,
        art: dict,
        params: dict | None = None,
        playing: str = "a.flac",
        alive: bool = True,
    ) -> list[tuple]:
        """
        Run _cover_size for a serve that started on a.flac and report its writes.

        :param art: The serve's art.
        :param params: The URL's params, the visualisation's by default.
        :param playing: Player.Filenameandpath at the write.
        :param alive: Whether the serve's guard holds.
        :return: The window_property calls, in order.
        """
        writes = []
        params = params or {"target": "player", "prop_key": "visualisation"}
        handler = handlers.PluginHandlers(
            {"info": "artwork", "icon_shape": "true"} | params
        )
        with mock.patch.multiple(
            handlers,
            infolabel=lambda label: playing,
            window_property=lambda *a: writes.append(a),
        ):
            handler._cover_size(art, "a.flac", lambda: alive)
        return writes

    def test_large(self):
        out = self.publish({"icon_width": "600", "icon_height": "700"})
        self.assertEqual(
            out,
            [
                ("cover_small_visualisation", False),
                ("cover_file_visualisation", "a.flac"),
            ],
        )

    def test_small_on_its_short_side(self):
        out = self.publish({"icon_width": "900", "icon_height": "499"})
        self.assertEqual(out[0], ("cover_small_visualisation", True))

    def test_no_cover_is_small(self):
        self.assertEqual(self.publish({})[0], ("cover_small_visualisation", True))

    def test_no_prop_key_no_suffix(self):
        out = self.publish({}, params={"target": "player"})
        self.assertEqual(out, [("cover_small", True), ("cover_file", "a.flac")])

    def test_song_moved_on(self):
        self.assertEqual(self.publish({}, playing="b.flac"), [])

    def test_guard_lost(self):
        self.assertEqual(self.publish({}, alive=False), [])

    def test_osd_serve_without_shape(self):
        params = {"target": "player", "prop_key": "musicosd", "icon_shape": "false"}
        self.assertEqual(self.publish({}, params), [])

    def test_not_the_player(self):
        params = {"target": "50", "prop_key": "9300"}
        self.assertEqual(self.publish({}, params), [])


if __name__ == "__main__":
    unittest.main()
