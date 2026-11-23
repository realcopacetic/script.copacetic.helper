"""
Offline checks for the served focus calls (resources/lib/service/serve.py): a ring names
its kind, region, known lists and mark, other senders and kinds are ignored; a probe's
params are handled (a plugin prefix dropped) and bound with the request's current, none
binds one blank item, an empty probe nothing, wait is read again; under a dialog the
request waits, and a newer ring, a window change or a moved cursor drops it unbound; a
list a dialog covered mid-run is owed again; a repeat does nothing (a list not mounted
here aside), but a none bind whose probe no longer says none serves; a move with no
lists serves the window's last request; again() serves one
list of it (the whole arrival while it is still served, beside an again's own lists,
only for the arrival that asked, as a handler's late answer asks, once per list and
arrival) and leaves the last request as it was; a move's item is read before its
handler; clean_name reads the query it was served with, not argv; a favourite with no
library item answers the blank item; a guard's superseded test comes first; Font.xml is
read once per version, and a clamp is keyed by the font's file and size; a bind sets
each item's path and uses a new Window; SQLite keeps one connection per thread, and
cache_only holds one thread only; a settle hands on its cursor; served artwork fetches
TMDb's extras aside, noting no miss; a thumb's digest is kept by its file's identity;
a serve's opened images are closed; 9300's bind hands the rotation its family (one image
stops it; an again of the same family keeps the turn), which turns from slide 1, each
slide made from probe 6932 on top LEAD before its beat and bound to 9400 with 9300's
identity on it, none under a dialog, none on a short rest, none that won't open, and a
late bind pushes the next beats back; a new family or an error ends a turn, not the
thread; a newer ring, a moved cursor or a rail losing focus ends it, a move during the
beat's read on top too. A dialog's region keeps only its own lists, is served in the
topmost dialog from its own probes, and is dropped once that dialog closes; ring_move
rings a dialog region's lists. An info dialog's rails settle on the primary's cursor
and are served in the info dialog, under a menu too (with two, the one whose open is
Home's); a dialog's binds name its open; an again asks its own window's last arrival,
the topmost served by default; a move rung again rings, and serves only the lists not
bound for its token and those a late answer fills; a dialog list whose guard stopped
is read again once.
Run from the helper root: python tests/serve_offline.py
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Callable
from unittest.mock import Mock, call, patch

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
vars(sys.modules["xbmc"]).update(  # imported names; nothing here calls them
    Monitor=type("Monitor", (), {"__init__": lambda self: None}),
    getCacheThumbName=None,
    getLocalizedString=None,
    AudioStreamDetail=None,
    SubtitleStreamDetail=None,
    VideoStreamDetail=None,
)
sys.modules["xbmcplugin"].SORT_METHOD_LASTPLAYED = 0
sys.path.insert(0, str(HELPER))

from resources.lib.apis import cache  # noqa: E402
from resources.lib.art import editor  # noqa: E402
from resources.lib.plugin import handlers  # noqa: E402
from resources.lib.service import serve  # noqa: E402
from resources.lib.shared import helpers, sqlite, text  # noqa: E402
from resources.lib.shared.hash import HashManager  # noqa: E402

PARAMS = "info=progressbar&label=A, B"
CURSOR = "54/3/12/09:01:02Next"
SETTLE = serve.Request("settle", "primary", (9010,), CURSOR)


def _server(*probes: str) -> serve.Server:
    """A Server without its threads, its probe reading probes in turn (the last stays)."""
    server = object.__new__(serve.Server)
    server.request, server.rung, server.stopped = None, Event(), False
    server.lock = RLock()
    server.heard, server.last, server.finished = 0.0, {}, None
    server.blanks = set()
    server.turn, server.handed = None, Event()
    blank = Mock(**{"getArt.return_value": ""})  # no family
    server._handle = Mock(return_value=[("plugin://x/1", blank, False)])
    server._bind = Mock()
    server.probes = list(probes or (PARAMS,))
    server.bound = ""  # what 9010's Property(current) reads back
    server._bind.side_effect = lambda *args: setattr(server, "bound", args[3])
    return server


class ServeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.props = {"artwork_cursor_primary": CURSOR, "moved_primary": "m1"}
        home = Mock(getProperty=lambda key: self.props.get(key, ""))
        self.patches = [
            patch.object(serve, "getCurrentWindowId", return_value=10025),
            patch.object(serve, "topmost_window_id", return_value=10025),
            patch.object(serve, "Window", return_value=home),
            patch.object(serve, "POLL", 0),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()

    def _run(self, server: serve.Server, request: serve.Request) -> None:
        server.request = request

        def reads(label: str) -> str:
            if "Property(current)" in label:  # the repeat test's read-back
                return server.bound
            return server.probes.pop(0) if len(server.probes) > 1 else server.probes[0]

        with patch.object(serve, "infolabel", side_effect=reads):
            server._serve(request)

    def test_ring_parses_kind_region_lists_mark(self) -> None:
        heard = []
        listener = serve._Listener(heard.append)
        sender = "script.copacetic.helper"
        listener.onNotification(sender, f"Other.settle/primary/9010.9999/{CURSOR}", "")
        listener.onNotification(sender, "Other.move//9010/view/m1", "")
        listener.onNotification(sender, "Other.move////m2", "")
        listener.onNotification(
            "other.addon", f"Other.settle/primary/9010/{CURSOR}", ""
        )
        listener.onNotification(sender, "Other.clashes/answers", "")
        self.assertEqual(
            heard,
            [
                serve.Request("settle", "primary", (9010,), CURSOR),
                serve.Request("move", "", (9010,), "m1", "view"),
                serve.Request("move", "", (), "m2"),
            ],
        )

    def test_current_names_the_arrival(self) -> None:
        self.assertEqual(SETTLE.current, "54/3/12/")  # no visit: a kept item matches
        self.assertEqual(serve.Request("move", "primary", (9010,), "m1").current, "m1")

    def test_a_settle_hands_on_its_cursor_a_move_none(self) -> None:
        self.assertEqual(SETTLE.cursors, {"primary": CURSOR})
        self.assertEqual(serve.Request("move", "primary", (9010,), "m1").cursors, {})

    def test_probe_is_handled_and_bound_with_current(self) -> None:
        server = _server(f"{serve.PLUGIN}{PARAMS}")
        self._run(server, SETTLE)
        params, superseded, again, cursors = server._handle.call_args.args
        self.assertEqual(params, f"{serve.PLUGIN}{PARAMS}")
        self.assertFalse(superseded())
        self.assertEqual(again, serve.Again(server, 9010, CURSOR, 10025))
        self.assertEqual(cursors, {"primary": CURSOR})  # a settle's, by its region
        server._bind.assert_called_once_with(
            10025, 9010, server._handle.return_value, "54/3/12/", "54/3/12/", ""
        )
        self.assertEqual(server.finished, SETTLE)

    def test_handle_drops_a_plugin_prefix(self) -> None:
        with patch("resources.lib.plugin.registry.info_handler") as dispatch:
            serve.Server._handle(f"{serve.PLUGIN}{PARAMS}", bool, bool)
            serve.Server._handle(PARAMS, bool, bool)
        self.assertEqual(dispatch.call_args_list[0], dispatch.call_args_list[1])
        self.assertEqual(dispatch.call_args.args[0]["label"], "A, B")

    def test_none_binds_blank(self) -> None:
        server = _server(serve.NONE)
        self._run(server, SETTLE)
        server._handle.assert_not_called()
        server._bind.assert_called_once_with(
            10025, 9010, [], "54/3/12/", "54/3/12/", ""
        )

    def test_unmounted_probe_binds_nothing(self) -> None:
        server = _server("")
        self._run(server, SETTLE)
        server._bind.assert_not_called()

    def test_wait_is_read_again(self) -> None:
        server = _server(serve.WAIT, serve.WAIT, PARAMS)
        self._run(server, SETTLE)
        server._bind.assert_called_once()

    def test_a_long_wait_counts_as_none(self) -> None:
        server = _server(serve.WAIT)
        with patch.object(serve, "WAIT_MAX", -1):
            self._run(server, SETTLE)
        server._handle.assert_not_called()
        self.assertEqual(server._bind.call_args.args[2], [])

    def test_dialog_waits_and_a_new_ring_drops(self) -> None:
        server = _server()
        server.rung.set()  # a newer ring while the dialog is up
        with patch.object(serve, "topmost_window_id", return_value=10106):
            self._run(server, SETTLE)
        server._bind.assert_not_called()

    def test_dialog_waits_and_a_window_change_drops(self) -> None:
        server = _server()
        with (
            patch.object(serve, "topmost_window_id", return_value=10106),
            patch.object(
                serve, "getCurrentWindowId", side_effect=[10025] * 3 + [10000]
            ),
        ):
            self._run(server, SETTLE)
        server._bind.assert_not_called()

    def test_a_moved_cursor_drops(self) -> None:
        server = _server()
        server._handle.side_effect = (
            lambda *a: self.props.update(artwork_cursor_primary="54/4/13/v") or []
        )
        self._run(server, SETTLE)
        server._bind.assert_not_called()
        self.assertIsNone(server.finished)

    def test_a_newer_ring_while_handling_binds_nothing(self) -> None:
        server = _server()
        newer = SETTLE._replace(mark="54/4/13/v")
        server._handle.side_effect = lambda *a: setattr(server, "request", newer) or []
        self._run(server, SETTLE)
        server._bind.assert_not_called()

    def test_a_guard_stop_binds_nothing(self) -> None:
        server = _server()
        server._handle.return_value = None
        self._run(server, SETTLE)
        server._bind.assert_not_called()

    def test_covered_mid_run_is_owed_again(self) -> None:
        server = _server()
        tops = iter(
            [10025, 10106, 10106, 10025, 10025]
        )  # turn, bind test, owed, turn, bind
        with patch.object(serve, "topmost_window_id", side_effect=lambda: next(tops)):
            self._run(server, SETTLE)
        self.assertEqual(server._handle.call_count, 2)
        server._bind.assert_called_once()

    def test_a_repeat_does_nothing(self) -> None:
        server = _server()
        self._run(server, SETTLE)
        self._run(server, SETTLE._replace())
        server._handle.assert_called_once()

    @patch.dict(serve.PROBES, {9040: 6904})
    def test_a_list_not_mounted_here_doesnt_stop_a_repeat(self) -> None:
        server = _server("", PARAMS)  # 9040: no probe in this window
        settle = SETTLE._replace(lists=(9040, 9010))
        self._run(server, settle)
        labels = {"Control.GetLabel(6904)": "", "Control.GetLabel(6910)": PARAMS}
        reads = lambda label: (
            server.bound if "(9010)" in label else labels.get(label, "")
        )
        with patch.object(serve, "infolabel", side_effect=reads):
            self.assertTrue(server._repeat(settle._replace(), 10025))
            server.bound = ""  # 9010 emptied by a skin reload: serve again
            self.assertFalse(server._repeat(settle._replace(), 10025))

    def test_a_blank_holds_only_a_none_its_probe_still_says(self) -> None:
        server = _server(serve.NONE)  # art not yet loaded (a skin reload): none
        self._run(server, SETTLE)
        self.assertEqual(server.blanks, {(10025, 9010)})
        self._run(server, SETTLE._replace())  # still none: a repeat
        server._handle.assert_not_called()
        server.probes = [PARAMS]  # the art landed: the same cursor rings again
        self._run(server, SETTLE._replace())
        server._handle.assert_called_once()
        self.assertEqual(server.blanks, set())
        self._run(server, SETTLE._replace())  # answered now: a repeat
        server._handle.assert_called_once()

    def test_no_repeat_is_read_under_a_dialog(self) -> None:
        server = _server()
        self._run(server, SETTLE)
        with (
            patch.object(serve, "topmost_window_id", return_value=10106),
            patch.object(serve, "infolabel", return_value=""),  # the menu's probes
        ):
            self.assertFalse(server._repeat(SETTLE._replace(), 10025))

    @patch.dict(serve.PROBES, {9000: 6900})
    def test_a_finished_again_leaves_the_next_one_its_own_list(self) -> None:
        server = _server()
        arrival = SETTLE._replace(lists=(9000, 9010))
        self._run(server, arrival)
        self._run(server, arrival._replace(lists=(9010,), again=True))
        self.assertIs(server.request, arrival)  # done: the window's last arrival
        server._ring = Mock()
        server.again(9000)  # not 9010 again: that again has ended
        server._ring.assert_called_once_with(
            arrival._replace(lists=(9000,), again=True)
        )

    def test_a_move_rung_again_serves_only_what_has_changed(self) -> None:
        self.props["moved_item"] = "m1"
        for name in ("getCurrentWindowDialogId", "topmost_window_id"):
            patcher = patch.object(serve, name, return_value=12003)
            patcher.start()
            self.addCleanup(patcher.stop)
        server = _server()
        move = serve.Request("move", "item", (9010,), "m1")
        self._run(server, move)
        self._run(server, move._replace())  # 9010 still answers m1
        self.assertEqual(server._handle.call_count, 1)
        server.bound = "3200/4/7/"  # a rail's settle bound it since
        self._run(server, move._replace())
        self._run(server, move._replace(again=True))  # an again always serves
        self.assertEqual(server._handle.call_count, 3)

    def test_move_with_no_lists_is_the_last_request(self) -> None:
        server = _server()
        self._run(server, SETTLE)
        move = serve.Request("move", "", (), "m1")
        self._run(server, move)
        self.assertEqual(server._bind.call_args.args[3:], ("m1", "", ""))
        self.assertEqual(
            server.finished, serve.Request("move", "primary", (9010,), "m1")
        )

    def test_a_moved_token_drops(self) -> None:
        server = _server()
        self._run(server, serve.Request("move", "primary", (9010,), "m0"))
        server._handle.assert_not_called()

    def test_again_serves_one_list_of_the_last(self) -> None:
        server = _server()
        server._ring = Mock()
        server.again(9010)  # nothing served yet in this window
        server.last[10025] = server.finished = SETTLE._replace(lists=(9000, 9010))
        server.again(9300)  # not one of its lists
        server.request = SETTLE._replace(mark="54/4/13/v")  # a newer ring waits
        server.again(9010)
        server.request = server.last[10025]
        server.again(9010, mark="54/4/13/v")  # asked by an arrival that has gone
        server.again(9010)
        server.again(9010, mark=CURSOR)
        self.assertEqual(
            server._ring.call_args_list, [call(SETTLE._replace(again=True))] * 2
        )

    def test_again_mid_serve_serves_the_arrival_whole(self) -> None:
        server = _server()
        server._ring = Mock()
        server.last[10025] = server.request = SETTLE._replace(lists=(9000, 9010))
        server.again(9010)  # not finished: its 9010 would be cut
        server._ring.assert_called_once_with(
            SETTLE._replace(lists=(9000, 9010), again=True)
        )

    def test_again_beside_an_again_keeps_its_lists(self) -> None:
        server = _server()
        server._ring = Mock()
        arrival = SETTLE._replace(lists=(9040, 9000, 9010))
        server.last[10025] = server.finished = arrival
        server.request = arrival._replace(lists=(9010,), again=True)  # in flight
        server.again(9000)
        server._ring.assert_called_once_with(
            arrival._replace(lists=(9000, 9010), again=True)
        )

    @patch.dict(serve.PROBES, {9000: 6900})
    def test_an_again_keeps_the_arrival_for_the_next_move(self) -> None:
        server = _server()
        arrival = SETTLE._replace(lists=(9000, 9010))
        self._run(server, arrival)
        self._run(server, arrival._replace(lists=(9010,), again=True))
        self.assertIs(server.last[10025], arrival)
        self.assertIs(server.finished, arrival)
        self._run(server, serve.Request("move", "", (), "m1"))
        self.assertEqual(server.finished.lists, (9000, 9010))

    def test_a_late_answer_serves_its_list_again_while_current(self) -> None:
        server = _server()
        server._handle.side_effect = lambda *a: setattr(server, "late", a[2]) or []
        self._run(server, SETTLE)
        self.assertIs(server.finished, SETTLE)
        server._ring = Mock()
        server.late()  # TMDb's answer landed: the arrival is still the last one
        server._ring.assert_called_once_with(SETTLE._replace(again=True))
        moved = SETTLE._replace(mark="54/4/13/v")
        server.last[10025] = server.request = server.finished = moved
        server.late()  # it has moved on: the new arrival serves its own
        server._ring.assert_called_once()

    def test_an_again_is_one_per_list_and_arrival(self) -> None:
        server = _server()
        asked = {serve.Again(server, 9000, "m1", 10025) for _ in "ab"}
        asked.add(serve.Again(server, 9100, "m1", 10025))
        self.assertEqual(len(asked), 2)  # a repeat serve's asks once

    def test_an_again_is_current_while_its_arrival_is_the_last(self) -> None:
        server = _server()
        self._run(server, SETTLE)
        again = serve.Again(server, 9010, CURSOR, 10025)
        self.assertTrue(again.current())
        server.request = SETTLE._replace(mark="54/4/13/v")  # a newer ring waits
        self.assertFalse(again.current())

    def test_again_is_never_a_repeat(self) -> None:
        server = _server()
        self._run(server, SETTLE)
        self._run(server, SETTLE._replace(again=True))
        self.assertEqual(server._handle.call_count, 2)

    def test_a_repeat_whose_list_was_emptied_serves(self) -> None:
        server = _server()
        self._run(server, SETTLE)
        server.bound = ""  # a skin reload rebuilt the window
        self._run(server, SETTLE._replace())
        self.assertEqual(server._handle.call_count, 2)

    def test_a_move_with_no_last_serves_every_list(self) -> None:
        server = _server()
        self._run(server, serve.Request("move", "", (), "m1"))
        self.assertEqual(
            server.finished, serve.Request("move", "primary", tuple(serve.PROBES), "m1")
        )

    def test_wait_time_under_a_dialog_doesnt_count(self) -> None:
        server = _server(serve.WAIT, PARAMS)
        tops = iter([10106] * 3 + [10025] * 5)
        with (
            patch.object(serve, "topmost_window_id", side_effect=lambda: next(tops)),
            patch.object(serve, "WAIT_MAX", 0.5),
            patch.object(serve.time, "monotonic", side_effect=[0, 0.1, 9, 9]),
        ):
            self._run(server, SETTLE)
        server._handle.assert_called_once()

    def test_a_handler_error_binds_blank(self) -> None:
        with patch(
            "resources.lib.plugin.registry.info_handler", side_effect=ValueError
        ):
            self.assertEqual(serve.Server._handle(PARAMS, bool, bool), [])

    def test_start_rings_a_move(self) -> None:
        with (
            patch.object(serve, "Thread"),
            patch.object(serve, "move_token", return_value="m9") as token,
        ):
            server = serve.Server()
        token.assert_called_once_with("primary", "secondary")
        self.assertEqual(
            server.request, serve.Request("move", "primary", tuple(serve.PROBES), "m9")
        )
        self.assertTrue(server.rung.is_set())

    def test_ring_move_writes_the_token_first(self) -> None:
        calls = []
        home = Mock(setProperty=lambda key, value: calls.append((key, value)))
        with (
            patch.object(serve, "Window", return_value=home),
            patch.object(serve.xbmc, "executebuiltin", calls.append, create=True),
        ):
            serve.ring_move()
        (key, token), ring = calls
        self.assertEqual(key, "moved_primary")
        self.assertEqual(
            ring,
            "NotifyAll(script.copacetic.helper,"
            f"move/primary/9040.9000.9100.9010.9300.9301//{token})",
        )

    def test_a_dialog_region_keeps_its_own_lists(self) -> None:
        heard = []
        listener = serve._Listener(heard.append)
        listener.onNotification(
            "script.copacetic.helper", "Other.move/preview/9370.9010//m1", ""
        )
        self.assertEqual(heard, [serve.Request("move", "preview", (9370,), "m1")])

    def test_a_dialog_region_is_served_in_the_topmost_dialog(self) -> None:
        self.props["moved_preview"] = "m1"
        server = _server()
        read = []
        move = serve.Request("move", "preview", (9370,), "m1")
        with (
            patch.object(serve, "getCurrentWindowDialogId", return_value=13001),
            patch.object(serve, "topmost_window_id", return_value=13001),
            patch.object(
                serve,
                "infolabel",
                side_effect=lambda label: read.append(label) or PARAMS,
            ),
        ):
            server.request = move
            server._serve(move)
        self.assertEqual(
            read,
            ["Container(9370).ListItem.Property(current)", "Control.GetLabel(6937)"],
        )
        server._bind.assert_called_once_with(
            13001, 9370, server._handle.return_value, "m1", "", ""
        )
        self.assertEqual(server.last, {13001: move})

    def test_an_info_rail_settles_on_the_primarys_cursor(self) -> None:
        heard = []
        serve._Listener(heard.append).onNotification(
            "script.copacetic.helper",
            f"Other.settle/infoscreen/9100.9010.9300.9040/{CURSOR}",
            "",
        )
        (settle,) = heard
        self.assertEqual(settle.lists, (9100, 9010, 9300))  # 9040: not a dialog's
        self.assertEqual(settle.cursors, {"primary": CURSOR})
        self.assertTrue(settle.live())  # artwork_cursor_primary
        self.props["artwork_cursor_primary"] = "3207/2/9/v"
        self.assertFalse(settle.live())

    def test_an_info_dialog_under_a_menu_is_its_window(self) -> None:
        with (
            patch.object(serve, "getCurrentWindowDialogId", return_value=10106),
            patch.object(
                serve, "condition", side_effect=lambda c: c.endswith("(12001)")
            ),
        ):
            self.assertEqual(serve.Server._window("infoscreen"), 12001)
            self.assertEqual(serve.Server._window("preview"), 10106)
        with patch.object(serve, "getCurrentWindowDialogId", return_value=12003):
            self.assertEqual(serve.Server._window("item"), 12003)
        self.assertEqual(serve.Server._window("primary"), 10025)
        # Song info over music info, a menu over both: the one whose open is Home's
        tokens = {10000: "m2", 12001: "m1", 10135: "m2"}
        windows = lambda w: Mock(getProperty=lambda key: tokens.get(w, ""))
        with (
            patch.object(serve, "getCurrentWindowDialogId", return_value=10106),
            patch.object(serve, "condition", return_value=True),
            patch.object(serve, "Window", side_effect=windows),
        ):
            self.assertEqual(serve.Server._window("item"), 10135)

    def test_an_info_dialogs_item_binds_in_it(self) -> None:
        self.props["moved_item"] = "m1movie:7"
        server = _server()
        move = serve.Request("move", "item", (9000, 9360), "m1movie:7")
        bound = {}  # each list's Property(current)
        server._bind.side_effect = lambda w, i, items, current, *_: bound.update(
            {i: current}
        )
        reads = lambda label: (
            bound.get(int(label[10:14]), "") if "current" in label else PARAMS
        )
        with (
            patch.object(serve, "getCurrentWindowDialogId", return_value=12003),
            patch.object(serve, "topmost_window_id", return_value=12003),
            patch.object(serve, "infolabel", side_effect=reads),
        ):
            server.request = move
            server._serve(move)
        self.assertEqual(
            [c.args[:2] for c in server._bind.call_args_list],
            [(12003, 9000), (12003, 9360)],
        )
        self.assertEqual(server.last, {12003: move})
        again = server._handle.call_args.args[2]
        self.assertEqual(again, serve.Again(server, 9360, "m1movie:7", 12003))

    def test_again_and_current_ask_their_window(self) -> None:
        server = _server()
        server._ring = Mock()
        item = serve.Request("move", "item", (9000, 9030), "m1")
        server.last = {10025: SETTLE, 12003: item}
        server.request = server.finished = item
        self.assertTrue(server.current("m1", 12003))
        self.assertFalse(server.current("m1", 10025))
        with patch.object(serve, "topmost_window_id", return_value=12003):
            server.again(9030)  # the topmost served: the dialog
        server.again(9030, "m1", 12003)
        server.again(9030, "m1", 10025)  # not that window's arrival
        self.assertEqual(
            server._ring.call_args_list,
            [call(item._replace(lists=(9030,), again=True))] * 2,
        )

    def test_a_move_rung_again_rings(self) -> None:
        server = _server()
        move = serve.Request("move", "item", (9000,), "m1")
        server._ring(move)
        server.rung.clear()
        server._ring(move._replace())  # a recovery: what it bound already is skipped
        self.assertTrue(server.rung.is_set())

    def _dialog(self, server: serve.Server, move: serve.Request) -> None:
        """Serve an info dialog's move, on top in 12003."""
        with (
            patch.object(serve, "getCurrentWindowDialogId", return_value=12003),
            patch.object(serve, "topmost_window_id", return_value=12003),
        ):
            self._run(server, move)

    def test_a_dialog_list_whose_guard_read_a_menu_is_read_again_once(self) -> None:
        self.props["moved_item"] = "m1"
        server = _server()
        server._handle.side_effect = [None, [("plugin://x/1", Mock(), False)]]
        self._dialog(server, serve.Request("move", "item", (9360,), "m1"))
        self.assertEqual(server._handle.call_count, 2)
        server._bind.assert_called_once()
        server._handle.side_effect = [None, None]  # twice: the serve ends
        self._dialog(server, serve.Request("move", "item", (9360,), "m1", again=True))
        self.assertEqual(server._handle.call_count, 4)
        server._bind.assert_called_once()

    def test_a_dialog_bind_names_its_open(self) -> None:
        self.props.update(moved_item="m1", artwork_cursor_primary="3207/2/9/v")
        server = _server()
        self._dialog(
            server, serve.Request("settle", "infoscreen", (9100,), "3207/2/9/v")
        )
        self.assertEqual(
            server._bind.call_args.args[3:], ("3207/2/9/", "3207/2/9/", "m1")
        )

    def test_a_move_rung_again_serves_the_late_answers_lists(self) -> None:
        self.props["moved_item"] = "m1"
        server = _server()
        server.bound = "m1"  # every list still answers m1
        self._dialog(server, serve.Request("move", "item", (9000, 9300, 9030), "m1"))
        self.assertEqual([c.args[1] for c in server._bind.call_args_list], [9000, 9030])

    def test_a_closed_dialog_drops(self) -> None:
        self.props["moved_preview"] = "m1"
        server = _server()
        move = serve.Request("move", "preview", (9370,), "m1")
        with (
            patch.object(serve, "getCurrentWindowDialogId", return_value=13001),
            patch.object(serve, "condition", return_value=False) as visible,
        ):
            self._run(server, move)
        visible.assert_called_once_with("Window.IsVisible(13001)")
        server._bind.assert_not_called()

    def test_ring_move_rings_a_dialog_regions_lists(self) -> None:
        calls = []
        home = Mock(setProperty=lambda key, value: calls.append((key, value)))
        with (
            patch.object(serve, "Window", return_value=home),
            patch.object(serve.xbmc, "executebuiltin", calls.append, create=True),
        ):
            serve.ring_move("preview")
        (key, token), ring = calls
        self.assertEqual(key, "moved_preview")
        self.assertEqual(
            ring, f"NotifyAll(script.copacetic.helper,move/preview/9370//{token})"
        )

    def test_a_moves_item_is_its_containers_now(self) -> None:
        labels = {
            "Container(54).CurrentItem": "7",
            "Container(54).ListItem.DBID": "20",
            "Container(3200).CurrentItem": "2",
            "Container(3200).ListItem.DBID": "",
        }
        move = serve.Request("move", "primary", (9010,), "m1")
        with patch.object(serve, "infolabel", side_effect=labels.get):
            self.assertEqual(
                serve.Server._item(move._replace(container="view")), "54/7/20/"
            )
            self.assertEqual(
                serve.Server._item(move._replace(container="3200")), "3200/2//"
            )
            self.assertEqual(serve.Server._item(move), "")
            self.props["artwork_cursor_primary"] = ""  # cleared: no view to name
            self.assertEqual(serve.Server._item(move._replace(container="view")), "")
        self.assertEqual(serve.Server._item(SETTLE), "54/3/12/")

    def test_a_moves_item_is_read_before_its_handler(self) -> None:
        server = _server()
        order = []
        server._item = Mock(side_effect=lambda r: order.append("item") or "54/7/20/")
        server._handle.side_effect = lambda *a: order.append("handle") or []
        self._run(server, serve.Request("move", "primary", (9010,), "m1", "view"))
        self.assertEqual(order, ["item", "handle"])
        self.assertEqual(server._bind.call_args.args[4], "54/7/20/")

    def test_bind_sets_paths_and_a_new_window(self) -> None:
        items = [("plugin://x/1", Mock(), False), ("plugin://x/2", Mock(), False)]
        with patch.object(serve, "Window") as window, patch.object(serve, "ListItem"):
            serve.Server._bind(10025, 9010, items, "c", "i", "o")
            serve.Server._bind(10025, 9010, [], "c", "i")
        items[0][1].setPath.assert_called_once_with("plugin://x/1")
        items[1][1].setPath.assert_called_once_with("plugin://x/2")
        items[0][1].setProperties.assert_called_once_with(
            {"current": "c", "item": "i", "open": "o"}
        )
        self.assertEqual(window.call_count, 2)
        bound = window.return_value.getControl.return_value.addItems.call_args_list
        self.assertEqual(bound[0].args[0], [items[0][1], items[1][1]])
        self.assertEqual(len(bound[1].args[0]), 1)  # the blank item


class GuardTest(unittest.TestCase):
    def test_superseded_is_the_first_test(self) -> None:
        reads = Mock()
        guard = handlers._FocusGuard(
            "progressbar", "3", reads, 10025, False, superseded=lambda: True
        )
        with patch.object(handlers, "getCurrentWindowDialogId", reads):
            self.assertFalse(guard.alive())
        reads.assert_not_called()

    def test_plugin_handlers_hand_it_to_their_guards(self) -> None:
        superseded = Mock(return_value=False)
        ph = handlers.PluginHandlers({"info": "progressbar"}, superseded)
        with patch.object(handlers, "getCurrentWindowId", return_value=10025):
            self.assertIs(ph._guard().superseded, superseded)


class FavouriteTest(unittest.TestCase):
    def test_no_library_item_is_a_blank_not_a_stop(self) -> None:
        ph = handlers.PluginHandlers({"info": "favourite", "path": "plugin://a/"})
        guard = Mock()
        with (
            patch.object(handlers.PluginHandlers, "_guard", return_value=guard),
            patch("resources.lib.plugin.favourites.library_key", return_value=""),
        ):
            self.assertEqual(ph.favourite(), [])  # served: 9040's blank, then 9000
            guard.alive.return_value = False
            self.assertIsNone(ph.favourite())  # a move: the request stops


class CleanNameTest(unittest.TestCase):
    def test_it_reads_its_query_not_argv(self) -> None:
        query = "info=clean_name&path=/media/Who%20Am%20I%3F.mkv&label=A"
        with (
            patch.object(sys, "argv", [""]),  # a service's (engine law)
            patch.object(handlers, "file_clean_name", return_value={"title": "T"}),
            patch.object(handlers, "set_items", side_effect=lambda items: items),
        ):
            params = serve.parse_plugin_argv(["", "", query])
            items = handlers.PluginHandlers(params, query=query).clean_name()
            handlers.file_clean_name.assert_called_once_with(
                "/media/Who%20Am%20I%3F.mkv"
            )
        self.assertEqual(items[0]["properties"], {"clean_title": "T"})

    def test_the_service_hands_its_query_on(self) -> None:
        with patch("resources.lib.plugin.registry.info_handler") as dispatch:
            serve.Server._handle(f"{serve.PLUGIN}{PARAMS}", bool, bool)
        self.assertEqual(dispatch.call_args.args[3], PARAMS)


class FontsTest(unittest.TestCase):
    FONT = (
        "<fontset id='Default'><font><name>{}</name><filename>{}</filename>"
        "<size>{}</size></font></fontset>"
    )

    def test_skin_font_reads_font_xml_once_per_version(self) -> None:
        xml = STAGE / "fonts" / "16x9" / "Font.xml"
        xml.parent.mkdir(parents=True, exist_ok=True)
        xml.write_text(self.FONT.format("body", "a.ttf", 30))
        with patch.object(text, "skin_path", return_value=str(xml)):
            reads = text._font_spec.cache_info().misses
            self.assertEqual(text.skin_font("body"), ("special://skin/fonts/a.ttf", 30))
            self.assertEqual(text.skin_font("body"), ("special://skin/fonts/a.ttf", 30))
            self.assertEqual(text._font_spec.cache_info().misses, reads + 1)
            xml.write_text(self.FONT.format("body", "b.ttf", 32))  # a skin update
            os.utime(xml, ns=(1, xml.stat().st_mtime_ns + 1))
            self.assertEqual(text.skin_font("body"), ("special://skin/fonts/b.ttf", 32))

    def test_a_clamp_is_keyed_by_the_fonts_file_and_size(self) -> None:
        keys = []
        hit = Mock(return_value="kept")
        with (
            patch.object(helpers, "infolabel", return_value="1920"),
            patch("resources.lib.shared.sqlite.TruncateCacheHandler") as cache,
            patch(
                "resources.lib.shared.hash.HashManager.short_hash_str",
                side_effect=lambda joined, length: keys.append(joined),
            ),
        ):
            cache.return_value.get_entry = hit
            for spec in (("a.ttf", 30), ("b.ttf", 30)):
                with patch.object(helpers, "skin_font", return_value=spec):
                    helpers.clamp_text(text="T", font="body", max_width=9, max_lines=1)
        self.assertNotEqual(*keys)
        self.assertNotIn("body", keys[0])
        self.assertIn("a.ttf|30", keys[0])


class ThreadsTest(unittest.TestCase):
    def test_sqlite_keeps_a_connection_per_thread(self) -> None:
        path = str(STAGE / "threads.db")
        mine = [sqlite.ApiCacheHandler.__new__(sqlite.ApiCacheHandler) for _ in "ab"]
        for handler in mine:
            handler.db_path = path
        theirs = []
        thread = Thread(target=lambda: theirs.append(mine[0]._conn))
        thread.start()
        thread.join()
        self.assertIs(mine[0]._conn, mine[1]._conn)
        self.assertIsNot(mine[0]._conn, theirs[0])

    def test_schema_once_per_process(self) -> None:
        path = str(STAGE / "schema.db")
        with (
            patch.object(sqlite, "create_dir"),
            patch.object(sqlite.ApiCacheHandler, "_initialize_database") as init,
        ):
            sqlite.ApiCacheHandler(path)
            sqlite.ApiCacheHandler(path)
        init.assert_called_once()

    def test_cache_only_holds_its_thread_only(self) -> None:
        seen = []
        with cache.cache_only():
            thread = Thread(target=lambda: seen.append(cache._offline.get()))
            thread.start()
            thread.join()
            seen.append(cache._offline.get())
        self.assertEqual(seen, [False, True])


class ArtworkTest(unittest.TestCase):
    def tmdb_ask(self, again: Mock | None) -> dict:
        """
        What a TMDb-extended family read asks _get_tmdb_item.

        :param again: The served list's re-serve; None for a plugin call.
        :return: The ask's keywords.
        """
        asked = {}
        params = {"info": "artwork", "target": "50", "get_extra_multiart": "true"}
        ph = handlers.PluginHandlers(params, (lambda: False) if again else None, again)
        with (
            patch.object(
                handlers.PluginHandlers,
                "_get_tmdb_item",
                lambda self, **kwargs: asked.update(kwargs),
            ),
            patch.object(handlers, "infolabel", return_value=""),
            patch("resources.lib.art.multiart.build_multiart_dict", return_value={}),
        ):
            ph._multiart_dict("Container(50).ListItem", "fanart")
        return asked

    def test_served_tmdb_extras_are_fetched_aside(self) -> None:
        again = Mock()
        asked = self.tmdb_ask(again)
        self.assertIs(asked["aside"], again)  # its news serves artwork again
        self.assertTrue(asked["cache_only"])

    def test_a_plugin_call_reads_the_cache_only(self) -> None:
        asked = self.tmdb_ask(None)
        self.assertIsNone(asked["aside"])
        self.assertTrue(asked["cache_only"])


class HashTest(unittest.TestCase):
    def test_a_thumbs_digest_is_kept_by_the_files_identity(self) -> None:
        thumb = STAGE / "thumb.jpg"
        thumb.write_bytes(b"one")
        first = HashManager.kept_hash(thumb)
        with patch("builtins.open", side_effect=AssertionError("read again")):
            self.assertEqual(HashManager.kept_hash(thumb), first)
        thumb.write_bytes(b"two")  # Kodi re-caches: a new file
        os.utime(thumb, ns=(1, thumb.stat().st_mtime_ns + 1))
        self.assertNotEqual(HashManager.kept_hash(thumb), first)
        thumb.unlink()  # Refresh removes the copy
        self.assertIsNone(HashManager.kept_hash(thumb))

    def test_the_builders_digest_reads_the_file_each_time(self) -> None:
        output = STAGE / "output.xml"
        output.write_bytes(b"one")
        first = HashManager.compute_hash(output)
        mtime = output.stat().st_mtime_ns
        output.write_bytes(b"two")  # a rewrite of the same size, same mtime
        os.utime(output, ns=(1, mtime))
        self.assertNotEqual(HashManager.compute_hash(output), first)


class ImagesTest(unittest.TestCase):
    def test_a_serves_opened_sources_are_closed(self):
        image = Mock()

        def handle(**kwargs):
            kwargs["shared"]["images"]["u"] = image
            raise ValueError  # closed however the serve ends

        ed = object.__new__(editor.ImageEditor)
        with (
            patch.object(editor.ImageEditor, "_drafts", return_value={}),
            patch.object(editor.ImageEditor, "_handle_jobs", side_effect=handle),
        ):
            self.assertEqual(
                ed.image_processor({"background": ()}, {"background": 1}), {}
            )
        image.close.assert_called_once()


FAMILY = ("a.jpg", "b.jpg")
TURN = serve.Turn(SETTLE, 10025, "54/3/12/v", FAMILY)


def _bound(family: tuple[str, ...], identity: str = "54/3/12/v") -> list[tuple]:
    """9300's bound item: its family as multiart keys, its identity."""
    art = dict(zip(["multiart", *(f"multiart{i}" for i in range(1, 9))], family))
    listitem = Mock(getArt=lambda key: art.get(key, ""), getProperty={}.get)
    listitem.getProperty = lambda key: identity if key == "identity" else ""
    return [("plugin://x/artwork", listitem, False)]


class RotateTest(unittest.TestCase):
    """9300's family turns on 9400: one slide a beat, made late in the dwell before."""

    def setUp(self) -> None:
        self.props = {"artwork_cursor_primary": CURSOR}
        home = Mock(getProperty=lambda key: self.props.get(key, ""))
        self.patches = [
            patch.object(serve, "getCurrentWindowId", return_value=10025),
            patch.object(serve, "topmost_window_id", return_value=10025),
            patch.object(serve, "Window", return_value=home),
            patch.object(serve, "DWELL", 0),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_9300s_bind_hands_its_family_and_identity(self) -> None:
        server = _server(PARAMS)
        server._handle.return_value = _bound(FAMILY)
        request = SETTLE._replace(lists=(9300,))
        server.request = request
        with patch.object(serve, "infolabel", return_value=PARAMS):
            server._serve(request)
        self.assertEqual(server.turn, serve.Turn(request, 10025, "54/3/12/v", FAMILY))
        self.assertTrue(server.handed.is_set())

    def test_a_family_of_one_or_none_stops_the_turn(self) -> None:
        server = _server()
        for items in (_bound(("a.jpg",)), []):
            server.turn = TURN
            server._hand(serve.Turn(SETTLE, 10025, *serve.Server._family(items)))
            self.assertIsNone(server.turn)
            self.assertTrue(server.handed.is_set())

    def turn(
        self, server: serve.Server, beats: int, slide: Callable | None = None
    ) -> list[str]:
        """
        Run the rotation for so many beats, then stop the service: a beat asks
        whether the turn goes on before its slide is made and before its bind.

        :param server: A Server without its threads, its turn handed.
        :param beats: Beats to turn before the stop.
        :param slide: _slide's stand-in; by default each slide made and recorded.
        :return: The slides the default stand-in made, in order.
        """
        made = []
        ticks = iter(range(2 * beats))

        def turning(turn: serve.Turn) -> bool:
            if next(ticks, None) is None:
                server.stopped = True
                server.handed.set()
            return not server.stopped

        server._turning = turning
        server._slide = Mock(
            side_effect=slide
            or (lambda turn, url: made.append(url) or [("s", url, False)])
        )
        server.handed.set()
        server._rotate()
        return made

    def test_turns_from_slide_1_round_again_binding_each(self) -> None:
        server = _server()
        server.request, server.turn = SETTLE, TURN
        made = self.turn(server, 3)
        self.assertEqual(made, ["b.jpg", "a.jpg", "b.jpg"])
        self.assertEqual(
            [c.args for c in server._bind.call_args_list],
            [(10025, 9400, [("s", url, False)], "54/3/12/", "") for url in made],
        )

    def test_a_short_rest_makes_nothing(self) -> None:
        server = _server()
        server.request, server.turn = SETTLE, TURN
        self.assertEqual(self.turn(server, 0), [])
        server._bind.assert_not_called()

    def test_a_beat_under_a_dialog_binds_nothing(self) -> None:
        server = _server()
        server.request, server.turn = SETTLE, TURN
        with patch.object(serve, "topmost_window_id", return_value=10106):
            self.turn(server, 2)
        server._bind.assert_not_called()

    def test_a_slide_not_made_binds_nothing_and_turns_on(self) -> None:
        server = _server()
        server.request, server.turn = SETTLE, TURN
        made = self.turn(server, 2, lambda turn, url: None)
        server._bind.assert_not_called()
        self.assertEqual(server._slide.call_count, 2)
        self.assertEqual(made, [])

    def test_a_new_family_ends_the_turn_and_starts_its_own(self) -> None:
        server = _server()
        server.request, server.turn = SETTLE, TURN
        other = TURN._replace(identity="54/4/13/v", family=("c.jpg", "d.jpg"))

        def slide(turn: serve.Turn, url: str) -> list[tuple]:
            if turn is TURN:
                server._hand(other)  # 9300 binds the next item mid-dwell
            return [("s", url, False)]

        made = self.turn(server, 3, slide)
        self.assertEqual(made, [])
        self.assertEqual(
            [c.args[2][0][1] for c in server._bind.call_args_list], ["d.jpg", "c.jpg"]
        )

    def test_an_error_costs_the_turn_not_the_thread(self) -> None:
        server = _server()
        server.request, server.turn = SETTLE, TURN
        other = TURN._replace(family=("c.jpg", "d.jpg"))

        def slide(turn: serve.Turn, url: str) -> list[tuple]:
            if turn is TURN:
                server._hand(other)  # handed as the error lands: the thread turns it
                raise ValueError
            return [("s", url, False)]

        self.turn(server, 2, slide)
        self.assertEqual(server._bind.call_args.args[2], [("s", "d.jpg", False)])

    def test_an_again_of_the_same_family_keeps_the_turn(self) -> None:
        server = _server()
        server.turn = TURN
        again = TURN._replace(request=SETTLE._replace(lists=(9300,), again=True))
        server._hand(again)
        self.assertIs(server.turn, TURN)
        self.assertFalse(server.handed.is_set())
        for changed in (
            again._replace(family=("a.jpg", "c.jpg")),  # TMDb's extras landed
            again._replace(request=SETTLE._replace(mark="m2")),  # a new arrival
        ):
            server._hand(changed)
            self.assertIs(server.turn, changed)
            self.assertTrue(server.handed.is_set())
            server.handed.clear()

    def test_a_slow_slide_never_bunches_the_next(self) -> None:
        server = _server()
        server.request, server.turn = SETTLE, TURN
        bound = []
        server._bind.side_effect = lambda *args: bound.append(time.monotonic())

        def slide(turn: serve.Turn, url: str) -> list[tuple]:
            if not bound:
                time.sleep(0.15)  # past its beat: bound late
            return [("s", url, False)]

        with patch.object(serve, "DWELL", 0.05), patch.object(serve, "LEAD", 0.02):
            self.turn(server, 3, slide)
        self.assertEqual(len(bound), 3)
        self.assertGreaterEqual(min(b - a for a, b in zip(bound, bound[1:])), 0.04)

    def test_a_move_during_the_beats_read_on_top_binds_nothing(self) -> None:
        server = _server()
        server.request, server.turn = SETTLE, TURN
        server._slide = Mock(return_value=[("s", "b.jpg", False)])
        turning = server._turning

        def stop_when_over(turn: serve.Turn) -> bool:
            if not (going := turning(turn)):
                server.stopped = True
                server.handed.set()
            return going

        def top() -> int:
            self.props["artwork_cursor_primary"] = "54/4/13/v"  # a move lands
            return 10025

        server._turning = stop_when_over
        server.handed.set()
        with patch.object(serve, "topmost_window_id", side_effect=top):
            server._rotate()
        server._slide.assert_called_once()
        server._bind.assert_not_called()

    def test_turning_ends_with_a_newer_ring_or_a_moved_cursor(self) -> None:
        server = _server()
        server.request = SETTLE._replace(lists=(9010,), again=True)  # same mark
        self.assertTrue(server._turning(TURN))
        self.props["artwork_cursor_primary"] = "54/4/13/v"
        self.assertFalse(server._turning(TURN))
        self.props["artwork_cursor_primary"] = CURSOR
        server.request = SETTLE._replace(mark="54/4/13/v")
        self.assertFalse(server._turning(TURN))

    def test_a_rails_turn_ends_as_the_view_takes_focus_back(self) -> None:
        rail = SETTLE._replace(region="secondary", mark="3100/2/9/v")
        server = _server()
        server.request = rail
        self.props |= {
            "artwork_cursor_secondary": rail.mark,
            "focus_region": "secondary",
        }
        self.assertTrue(server._turning(TURN._replace(request=rail)))
        self.props["focus_region"] = "primary"
        self.assertFalse(server._turning(TURN._replace(request=rail)))
        server.request = SETTLE  # a view or widget turn ignores the region's name
        self.props["focus_region"] = "3201"
        self.assertTrue(server._turning(TURN))

    def test_slide_reads_its_probe_on_top_and_names_9300s_identity(self) -> None:
        source = "ListItem.Art(clearlogo)"
        query = (
            f"background_blur=true&clearlogo_source={source}"
            "&clearlogo_url=https://x/l.png?a=1&b=2&icon_darken_label=A & B"
        )
        labels = {"Control.GetLabel(6932)": query, source: "https://x/l.png?a=1&b=2"}
        with (
            patch.object(serve, "infolabel", side_effect=labels.get) as read,
            patch("resources.lib.art.multiart.slide_art") as art,
            patch("resources.lib.plugin.setter.set_items", side_effect=list),
        ):
            art.return_value = {"background": "b.png", "slide": "b.jpg"}
            items = serve.Server._slide(TURN, "b.jpg")
        self.assertEqual(read.call_args_list, list(map(call, labels)))
        params, url = art.call_args.args
        self.assertEqual(url, "b.jpg")
        self.assertEqual(params["clearlogo_url"], "https://x/l.png?a=1&b=2")  # whole
        self.assertEqual(params["icon_darken_label"], "A & B")
        self.assertEqual(items[0]["properties"], {"identity": "54/3/12/v"})
        self.assertEqual(items[0]["art"], {"background": "b.png", "slide": "b.jpg"})

    def test_a_slide_that_wont_open_makes_none(self) -> None:
        with (
            patch.object(serve, "infolabel", return_value=PARAMS),
            patch("resources.lib.art.multiart.slide_art", return_value={"slide": "x"}),
        ):
            self.assertIsNone(serve.Server._slide(TURN, "x"))

    def test_slide_under_a_dialog_or_with_no_params_makes_none(self) -> None:
        with patch.object(serve, "infolabel", return_value=PARAMS) as read:
            with patch.object(serve, "topmost_window_id", return_value=10106):
                self.assertIsNone(serve.Server._slide(TURN, "b.jpg"))
            read.assert_not_called()
            for probe in ("", serve.NONE):
                read.return_value = probe
                self.assertIsNone(serve.Server._slide(TURN, "b.jpg"))


if __name__ == "__main__":
    unittest.main()
