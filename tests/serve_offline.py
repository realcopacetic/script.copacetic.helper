"""
Offline checks for the served focus calls (resources/lib/service/serve.py): a ring
names its lists and their probes, the mark and its value (is), its wait, dialogs, item
and echo; other senders and verbs are ignored, and a bare serve is the net's; a probe's
params are handled (a plugin prefix dropped) and bound with the ring's is, the item
before its visit and the probe text, none binds one blank item, an empty probe nothing,
wait is read again (5 s at most); under a dialog the request waits (a probe, line or
slide read a new dialog answered too; a handler that stopped is read again once), and a
newer ring, a window change or a moved mark drops it unbound; a list a dialog covered
mid-run is owed again; a list bound for the arrival from the same probe text
(Property(params)) is not served again, any other list is; the net's bare serve serves
the window on top's last request, is let be while a request waits or runs, and lets be
a list whose handler stopped twice on the same text, and a bind clears its quiet (an
info dialog's swap back is served); a ring with no lists serves the
window's last request under its own mark; again() serves one list of it (the whole
arrival once its serve stopped short, beside an again's own lists, only for the arrival
that asked, as a handler's late answer asks, once per list and arrival; one asked
mid-serve cuts nothing and serves its list after, unless the serve has yet to reach
it; one refused while a newer ring has the window is owed to its arrival's next ring);
a window names the list it served with a handler (an album's bar); a ring's item is
its container's, read before its handler; the start serves the window's load ring
under a new token, and a ring from Python writes its token first; a dialog's ring is
served in the dialog it names, waited for under a menu until one it names is on top, is
dropped once that dialog closes, and binds its echo; clean_name reads the query it was
served with, not argv; a favourite with no library item answers the blank item; a
guard's superseded test comes first; Font.xml is read once per version, and a clamp is
keyed by the font's file and size; a bind sets each item's path and uses a new Window;
SQLite keeps one connection per thread, and cache_only holds one thread only; served
artwork fetches TMDb's extras aside, noting no miss; a thumb's digest is kept by its
file's identity; a serve's opened images are closed; an artwork row naming slides hands
the rotation its family (one image stops it; an again of the same family keeps the
turn), which turns from slide 1, each slide made from the slides probe on top LEAD
before its beat and bound with the artwork list's identity on it, none under a dialog,
none on a short rest, none that won't open, and a late bind pushes the next beats back;
a new family or an error ends a turn, not the thread; a repeat keeps a turn, or turns
the family again once its turn ended; a newer ring, a moved mark or a
slide probe that moved on ends it, a move during the beat's read on top too. The line
(an ongoing handler's, the typewriter) starts on a thread of its own and answers at
once (a plugin call types it inline); only the service's stop ends a line from here
(its lease and guard do the rest); the same line, item and label, stands through a new
mark until its lease is no longer its run's (a stopped line hands it back), binds under
a dialog too, and a repeat serves only a retired line; an again asks the line too,
after a serve that has passed it, and a late answer while the line waits serves its
lists before the line; a repeat whose line probe waits is served alone; a claim and a
hand-back share one lock; live() reads the kept Home. A music OSD rail's settle is
served in the OSD over the visualisation, its echo bound; the OSD closing (its unload
clears the cursor) binds nothing more, in it or in the window under it, drops a ring
and ends a slide's turn; back from Info over a rail, the OSD's repeat turns its slides
again; a dialog serve reads its dialog, never the window under it.
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
from resources.lib.plugin import handlers, registry  # noqa: E402
from resources.lib.service import serve  # noqa: E402
from resources.lib.shared import helpers, sqlite, text  # noqa: E402
from resources.lib.shared.hash import HashManager  # noqa: E402

PARAMS = "info=progressbar&label=A, B"
CURSOR = "54/3/12/09:01:02Next"
# A skin's lists and probes, as Copacetic 2's rings name them
PROBES = {
    9040: 6904,
    9000: 6900,
    9100: 6901,
    9010: 6910,
    9300: 6930,
    9301: 6931,
    9020: 6920,
    9030: 6903,
    9360: 6936,
    9370: 6937,
}
INFO = (12003, 10135, 12001, 10146)


def _lists(*ids: int) -> tuple[tuple[int, int], ...]:
    """Lists and their probes, as a ring names them."""
    return tuple((list_id, PROBES[list_id]) for list_id in ids)


BAR = _lists(9010)
SETTLE = serve.Request(BAR, "artwork_cursor_primary", CURSOR)
MOVE = serve.Request(BAR, "moved_primary", "m1", 0.225)


def _server(*probes: str) -> serve.Server:
    """A Server without its threads, its probe reading probes in turn (the last stays)."""
    server = object.__new__(serve.Server)
    server.request, server.rung, server.stopped = serve.Request(), Event(), False
    server.lock = RLock()
    server.heard, server.last, server.finished = 0.0, {}, None
    server.ahead, server.asked = None, set()
    server.busy, server.net, server.failed = False, False, {}
    server.owed, server.lines, server.infos = {}, {}, {}
    server.binds, server.quiet = 0, {}
    server.turn, server.handed, server.kept = None, Event(), {}
    blank = Mock(**{"getArt.return_value": ""})  # no family
    server._handle = Mock(return_value=[("plugin://x/1", blank, False)])
    server._bind = Mock()
    server.probes = list(probes or (PARAMS,))
    server.bound = {}  # list → the properties its bind reads back
    server._bind.side_effect = lambda w, i, items, current, item, echo="", params="": (
        server.bound.update({i: {"current": current, "item": item, "params": params}})
    )
    return server


def _reads(server: serve.Server) -> Callable[[str], str]:
    """
    Kodi's reads: a list's bound properties, else the probes' texts in turn (the last
    stays), by probe id when server.probes maps each to its own.
    """

    def read(label: str) -> str:
        if label.startswith("Container("):  # Container(9010).ListItem.Property(x)
            return server.bound.get(int(label[10:14]), {}).get(label[34:-1], "")
        probes = server.probes
        if isinstance(probes, dict):  # Control.GetLabel(6910)
            probes = probes[int(label[17:-1])]
        return probes.pop(0) if len(probes) > 1 else probes[0]

    return read


class ServeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.props = {"artwork_cursor_primary": CURSOR, "moved_primary": "m1"}
        home = Mock(getProperty=lambda key: self.props.get(key, ""))
        self.patches = [
            patch.object(serve, "getCurrentWindowId", return_value=10025),
            patch.object(serve, "topmost_window_id", return_value=10025),
            patch.object(serve, "Window", return_value=home),
            patch.object(serve, "home_property", lambda k: self.props.get(k, "")),
            patch.object(serve, "POLL", 0),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()

    def _run(
        self, server: serve.Server, request: serve.Request, net: bool = False
    ) -> None:
        server.request = request
        with patch.object(serve, "infolabel", side_effect=_reads(server)):
            server._serve(request, net)

    def test_a_ring_parses_its_fields(self) -> None:
        heard = []
        listener = serve._Listener(heard.append)
        sender = "script.copacetic.helper"
        rang = (
            f"serve?lists=9010:6910.9300:6930&mark=artwork_cursor_primary&is={CURSOR}",
            "serve?lists=9370:6937&mark=moved_preview&is=m1&wait=225&window=13001"
            "&item=54/3/12/v&echo=m7",
            "serve?mark=moved_primary&is=m2&wait=225",
            "serve",
        )
        for message in rang:
            listener.onNotification(sender, f"Other.{message}", "")
        listener.onNotification("other.addon", "Other.serve?mark=x&is=y", "")
        listener.onNotification(sender, f"Other.settle/primary/9010/{CURSOR}", "")
        self.assertEqual(
            heard,
            [
                serve.Request(_lists(9010, 9300), "artwork_cursor_primary", CURSOR),
                serve.Request(
                    _lists(9370),
                    "moved_preview",
                    "m1",
                    0.225,
                    (13001,),
                    "54/3/12/v",
                    "m7",
                ),
                serve.Request((), "moved_primary", "m2", 0.225),
                serve.Request(),  # the net's
            ],
        )

    def test_a_bind_names_the_arrival_and_its_item(self) -> None:
        self.assertEqual(serve.Server._item(SETTLE), "54/3/12/")  # a kept item's
        self.assertEqual(serve.Server._item(MOVE), "")  # a token names none
        self.assertEqual(SETTLE.cursors, {"artwork_cursor_primary": CURSOR})

    def test_probe_is_handled_and_bound_with_current(self) -> None:
        server = _server(f"{serve.PLUGIN}{PARAMS}")
        self._run(server, SETTLE)
        params, superseded, again, cursors = server._handle.call_args.args
        self.assertEqual(params, f"{serve.PLUGIN}{PARAMS}")
        self.assertFalse(superseded())
        self.assertEqual(again, serve.Again(server, 9010, CURSOR, 10025))
        self.assertEqual(cursors, {"artwork_cursor_primary": CURSOR})
        server._bind.assert_called_once_with(
            10025,
            9010,
            server._handle.return_value,
            CURSOR,
            "54/3/12/",
            "",
            f"{serve.PLUGIN}{PARAMS}",
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
            10025, 9010, [], CURSOR, "54/3/12/", "", serve.NONE
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
        self.assertEqual(serve.WAIT_MAX, 5)  # the net serves a rail that lands later

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
        newer = SETTLE._replace(value="54/4/13/v")
        server._handle.side_effect = lambda *a: setattr(server, "request", newer) or []
        self._run(server, SETTLE)
        server._bind.assert_not_called()

    def test_a_guard_stop_binds_nothing(self) -> None:
        server = _server()
        server._handle.return_value = None
        self._run(server, SETTLE)
        server._bind.assert_not_called()

    def test_a_window_list_whose_handler_stopped_is_read_again_once(self) -> None:
        server = _server()
        server._handle.side_effect = [None, [("plugin://x/1", Mock(), False)]]
        self._run(server, SETTLE)  # a dialog flashed by inside its run
        self.assertEqual(server._handle.call_count, 2)
        server._bind.assert_called_once()

    def test_covered_mid_run_is_owed_again(self) -> None:
        server = _server()
        # turn and its read, bind test, owed, turn and its read, bind
        tops = iter([10025, 10025, 10106, 10106, 10025, 10025, 10025])
        with patch.object(serve, "topmost_window_id", side_effect=lambda: next(tops)):
            self._run(server, SETTLE)
        self.assertEqual(server._handle.call_count, 2)
        server._bind.assert_called_once()

    def test_a_probe_read_under_a_new_dialog_is_read_again(self) -> None:
        server = _server("", PARAMS)  # the menu's empty answer, then the probe's
        tops = iter([10025, 10106, 10106, 10025, 10025, 10025])  # opened mid-read
        with patch.object(serve, "topmost_window_id", side_effect=lambda: next(tops)):
            self._run(server, SETTLE)
        server._handle.assert_called_once()
        server._bind.assert_called_once()

    def test_a_repeat_does_nothing(self) -> None:
        server = _server()
        self._run(server, SETTLE)
        self._run(server, SETTLE._replace())
        server._handle.assert_called_once()

    def test_a_list_holds_its_answer_only_from_its_probes_text(self) -> None:
        server = _server(serve.NONE)  # art not yet loaded (a skin reload): none
        self._run(server, SETTLE)
        self.assertEqual(server.bound[9010]["params"], serve.NONE)
        self._run(server, SETTLE._replace())  # still none: a repeat
        server._bind.assert_called_once()
        server.probes = [PARAMS]  # the art landed: the same cursor rings again
        self._run(server, SETTLE._replace())
        server._handle.assert_called_once()
        self._run(server, SETTLE._replace())  # answered now: a repeat
        server._handle.assert_called_once()

    def test_a_repeat_serves_only_the_lists_that_dont_hold_it(self) -> None:
        server = _server()
        settle = SETTLE._replace(lists=_lists(9000, 9010))
        self._run(server, settle)
        del server.bound[9010]  # emptied by a skin reload
        self._run(server, settle._replace())
        handled = [c.args[2].list_id for c in server._handle.call_args_list]
        self.assertEqual(handled, [9000, 9010, 9010])
        server.bound[9000]["current"] = "54/3/12/v0"  # another visit's bind
        self._run(server, settle._replace())
        self.assertEqual(server._handle.call_count, 4)

    def test_the_net_serves_the_last_request_on_top(self) -> None:
        server = _server()
        served = []

        def serve_(request: serve.Request, net: bool) -> None:
            served.append((request, net, server.request))
            server.stopped = True
            server.rung.set()

        server._serve = serve_
        server.last = {10025: SETTLE}
        server._ring(serve.Request())
        worker = Thread(target=server._work)
        with patch.dict(sys.modules, {"resources.lib.plugin.handlers": Mock()}):
            worker.start()
            worker.join(2)
        self.assertEqual(served, [(SETTLE, True, SETTLE)])  # its request, as it was

    def _worker(self, server: serve.Server, rings: list, probe: list) -> None:
        """
        Ring each in turn into a running worker, waiting until it is served or let
        be; a str sets probe 6910's text first. Patches stay for the worker's thread.
        """
        worker = Thread(target=server._work)
        with (
            patch.dict(sys.modules, {"resources.lib.plugin.handlers": Mock()}),
            patch.object(serve, "infolabel", side_effect=lambda label: probe[0]),
        ):
            worker.start()
            for ring in rings:
                if isinstance(ring, str):
                    probe[0] = ring
                    continue
                server._ring(ring)
                while server.rung.is_set() or server.busy:  # served, or let be
                    time.sleep(0.005)
            server.stopped = True
            server.rung.set()
            worker.join(2)

    def test_a_net_serve_that_binds_nothing_lets_the_window_be(self) -> None:
        server = _server()
        served = []
        server._serve = lambda request, net: served.append(net)  # binds nothing
        server.last = {10025: SETTLE}
        net = serve.Request()
        self._worker(server, [net, net, "T2", net, SETTLE, net], [PARAMS])
        # The net; one let be (no probe moved); one after the probe moved; a ring;
        # the net once the ring has cleared it
        self.assertEqual(served, [True, True, False, True])

    def test_a_ring_during_a_net_serve_keeps_its_window_netted(self) -> None:
        server = _server()
        served = []
        moved = SETTLE._replace(value="54/4/13/v")

        def serve_(request: serve.Request, net: bool) -> None:
            served.append(request.value)
            if net and len(served) == 1:
                server.last[10025] = moved  # a move lands as the net serve runs
                server._ring(moved)

        server._serve = serve_
        server.last = {10025: SETTLE}
        net = serve.Request()
        self._worker(server, [net, net], [PARAMS])
        # The cut net serve quiets nothing: the moved arrival's net still serves
        self.assertEqual(served, [CURSOR, moved.value, moved.value])

    def test_a_probe_that_moves_during_an_empty_net_serve_quiets_nothing(self) -> None:
        server = _server()
        served, probe = [], [PARAMS]

        def serve_(request: serve.Request, net: bool) -> None:
            served.append(net)
            probe[0] = "T2" if len(served) == 1 else probe[0]  # a swap as it runs

        server._serve = serve_
        server.last = {10025: SETTLE}
        net = serve.Request()
        self._worker(server, [net, PARAMS, net, net], probe)
        # Back to the text read before the first: not quiet, so served, then let be
        self.assertEqual(served, [True, True])
        self.assertEqual(server.quiet, {10025: (PARAMS,)})

    def _net_world(self, server: serve.Server, handle: Callable) -> dict:
        """
        Wire a Server's serve to labels (probes and bound properties) and the
        handler given; returns the labels, which binds write back to.
        """
        labels = {}

        def bind(window_id, list_id, items, current, item, echo="", params=""):
            server.binds_seen.append((list_id, params))
            prop = f"Container({list_id}).ListItem.Property"
            labels.update({f"{prop}(params)": params, f"{prop}(current)": current})

        server.binds_seen = []
        server._bind, server._handle = bind, handle
        return labels

    def _drive(self, server: serve.Server, labels: dict, steps: list) -> None:
        """Run the worker through steps: a ring, or a callable run between them."""
        worker = Thread(target=server._work)
        with (
            patch.dict(sys.modules, {"resources.lib.plugin.handlers": Mock()}),
            patch.object(serve, "infolabel", side_effect=lambda t: labels.get(t, "")),
        ):
            worker.start()
            for step in steps:
                if callable(step):
                    step()
                    continue
                server._ring(step)
                while server.rung.is_set() or server.busy:
                    time.sleep(0.005)
            server.stopped = True
            server.rung.set()
            worker.join(2)

    def test_a_probe_that_moves_during_a_net_serve_still_heals(self) -> None:
        server = _server()
        settle = SETTLE._replace(lists=_lists(9000, 9300))

        def handle(params, superseded, again, cursors):
            if params.endswith("stop"):  # 9300's guard stops; 9000's late art lands
                labels["Control.GetLabel(6900)"] = "info=metadata&art=late"
                return None
            return []

        labels = self._net_world(server, handle)
        labels |= {
            "Control.GetLabel(6900)": "info=metadata",
            "Control.GetLabel(6930)": "a",
        }
        stop = lambda: labels.update({"Control.GetLabel(6930)": "a&stop"})
        net = serve.Request()
        self._drive(server, labels, [settle, stop, net, net])
        self.assertIn((9000, "info=metadata&art=late"), server.binds_seen)

    def test_a_net_serve_goes_on_past_a_list_whose_handler_stopped(self) -> None:
        server = _server()
        settle = SETTLE._replace(lists=_lists(9300, 9301))
        handle = lambda params, superseded, again, cursors: (
            None if params.endswith("stop") else []
        )
        labels = self._net_world(server, handle)
        labels |= {"Control.GetLabel(6930)": "a", "Control.GetLabel(6931)": "logo"}
        late = lambda: labels.update(  # 9300 now stops; 9301's art landed late
            {"Control.GetLabel(6930)": "a&stop", "Control.GetLabel(6931)": "logo&late"}
        )
        self._drive(server, labels, [settle, late, serve.Request()])
        self.assertIn((9301, "logo&late"), server.binds_seen)
        self.assertEqual(server.failed, {(10025, 9300): "a&stop"})

    def test_a_bind_clears_the_net_quiet(self) -> None:
        server = _server()
        settle = SETTLE._replace(lists=_lists(9000))
        labels = self._net_world(server, lambda params, superseded, again, cursors: [])
        show = lambda item: lambda: labels.update(
            {"Control.GetLabel(6900)": f"info=metadata&item={item}"}
        )
        show("a")()
        net = serve.Request()
        # A net on a binds nothing (it holds a); Information swaps to b, then back
        self._drive(server, labels, [settle, net, show("b"), net, show("a"), net])
        served = [params for _, params in server.binds_seen]
        self.assertEqual(served, [f"info=metadata&item={i}" for i in "aba"])

    def test_a_net_ring_as_the_worker_wakes_never_replaces_the_arrival(self) -> None:
        server = _server()
        served = []

        class Rung(Event):
            def clear(self) -> None:  # the net rings as the worker takes the request
                super().clear()
                server._ring(serve.Request())

        def serve_(request: serve.Request, net: bool) -> None:
            served.append((request, net))
            server.stopped = True
            server.rung.set()

        server.rung, server._serve = Rung(), serve_
        server.last = {10025: SETTLE._replace(value="54/1/1/v")}  # an older arrival
        server._ring(SETTLE)
        worker = Thread(target=server._work)
        with patch.dict(sys.modules, {"resources.lib.plugin.handlers": Mock()}):
            worker.start()
            worker.join(2)
        self.assertEqual(served, [(SETTLE, False)])

    def test_the_net_is_let_be_while_a_request_waits_or_runs(self) -> None:
        server = _server()
        server.busy = True  # a serve in hand answers the net itself
        server._ring(serve.Request())
        self.assertFalse(server.net or server.rung.is_set())
        server.busy = False
        server.rung.set()  # a request waits: so does the net
        server._ring(serve.Request())
        self.assertFalse(server.net)
        server.rung.clear()
        server._ring(serve.Request())
        self.assertTrue(server.net and server.rung.is_set())
        server._ring(SETTLE)  # a ring after it wins
        self.assertFalse(server.net)
        self.assertIs(server.request, SETTLE)

    def test_a_list_whose_handler_stopped_twice_is_let_be_by_the_net(self) -> None:
        server = _server()
        server._handle.return_value = None
        self._run(server, SETTLE)
        self.assertEqual(server.failed, {(10025, 9010): PARAMS})
        self._run(server, SETTLE._replace(), net=True)  # the same text: let be
        self.assertEqual(server._handle.call_count, 2)
        self._run(server, SETTLE._replace())  # a ring tries it again
        self.assertEqual(server._handle.call_count, 4)
        server._handle.return_value = [("plugin://x/1", Mock(), False)]
        server.probes = ["info=progressbar&id=2"]  # its text changed
        self._run(server, SETTLE._replace(), net=True)
        self.assertEqual(server.failed, {})
        server._bind.assert_called_once()

    def test_a_mark_that_flips_back_records_no_failure(self) -> None:
        server = _server()
        marks = []  # the mark after the handler: moved, then back

        def handle(params, superseded, again, cursors):
            marks.extend(("m2", CURSOR))
            return None

        home = lambda key: (
            marks.pop(0) if key == SETTLE.mark and marks else self.props.get(key, "")
        )
        server._handle = handle
        with patch.object(serve, "home_property", home):
            self._run(server, SETTLE)  # stale() reads True, then False
        self.assertEqual(server.failed, {})

    def test_a_finished_again_leaves_the_next_one_its_own_list(self) -> None:
        server = _server()
        arrival = SETTLE._replace(lists=_lists(9000, 9010))
        self._run(server, arrival)
        self._run(server, arrival._replace(lists=BAR, again=True))
        self.assertIs(server.request, arrival)  # done: the window's last arrival
        server._ring = Mock()
        server.again(9000)  # not 9010 again: that again has ended
        server._ring.assert_called_once_with(
            arrival._replace(lists=_lists(9000), again=True)
        )

    def _dialog(self, server: serve.Server, request: serve.Request) -> None:
        """Serve an info dialog's ring, on top in 12003."""
        with (
            patch.object(serve, "getCurrentWindowDialogId", return_value=12003),
            patch.object(serve, "topmost_window_id", return_value=12003),
        ):
            self._run(server, request)

    def test_a_dialogs_ring_again_serves_only_what_has_changed(self) -> None:
        self.props["moved_item"] = "m1"
        server = _server()
        item = serve.Request(BAR, "moved_item", "m1", windows=INFO)
        self._dialog(server, item)
        self._dialog(server, item._replace())  # 9010 still answers m1
        self.assertEqual(server._handle.call_count, 1)
        server.bound[9010]["current"] = "3200/4/7/v"  # a rail's settle bound it since
        self._dialog(server, item._replace())
        self._dialog(server, item._replace(again=True))  # an again always serves
        self.assertEqual(server._handle.call_count, 3)

    def test_a_ring_with_no_lists_is_the_last_request(self) -> None:
        server = _server()
        self._run(server, SETTLE)
        back = serve.Request((), "moved_primary", "m1", 0.225)
        self._run(server, back)
        self.assertEqual(server._bind.call_args.args[3:], ("m1", "", "", PARAMS))
        self.assertEqual(server.finished, back._replace(lists=BAR))

    def test_a_ring_with_no_lists_and_no_last_serves_nothing(self) -> None:
        server = _server()
        self._run(server, serve.Request((), "moved_primary", "m1"))
        server._handle.assert_not_called()
        self.assertEqual(server.last, {})

    def test_a_moved_token_drops(self) -> None:
        server = _server()
        self._run(server, MOVE._replace(value="m0"))
        server._handle.assert_not_called()

    def test_again_serves_one_list_of_the_last(self) -> None:
        server = _server()
        server._ring = Mock()
        server.again(9010)  # nothing served yet in this window
        server.last[10025] = server.finished = SETTLE._replace(lists=_lists(9000, 9010))
        server.again(9300)  # not one of its lists
        server.request = SETTLE._replace(value="54/4/13/v")  # a newer ring waits
        server.again(9010)
        server.request = server.last[10025]
        server.again(9010, value="54/4/13/v")  # asked by an arrival that has gone
        server.again(9010)
        server.again(9010, value=CURSOR)
        self.assertEqual(
            server._ring.call_args_list, [call(SETTLE._replace(again=True))] * 2
        )

    def test_again_after_a_serve_stopped_short_serves_the_arrival_whole(self) -> None:
        server = _server()
        server._ring = Mock()
        server.last[10025] = server.request = SETTLE._replace(lists=_lists(9000, 9010))
        server.again(9010)  # not finished (a guard stopped it), and none runs
        server._ring.assert_called_once_with(
            SETTLE._replace(lists=_lists(9000, 9010), again=True)
        )

    def test_an_again_mid_serve_serves_its_list_after_it(self) -> None:
        server = _server()
        arrival = SETTLE._replace(lists=_lists(9000, 9010))
        late = iter([True])

        def handle(params, superseded, again, cursors) -> list:
            if again.list_id == 9000 and next(late, False):
                again()  # TMDb's answer lands while 9000 is being served
            return []

        server._handle.side_effect = handle
        self._run(server, arrival)
        bound = [c.args[1] for c in server._bind.call_args_list]
        self.assertEqual(bound, [9000, 9010])  # not cut
        self.assertEqual(
            server.request, arrival._replace(lists=_lists(9000), again=True)
        )
        self._run(server, server.request)
        handled = [c.args[2].list_id for c in server._handle.call_args_list]
        self.assertEqual(handled, [9000, 9010, 9000])
        self.assertIs(server.request, arrival)

    def test_a_late_answer_during_an_again_serves_its_list_from_the_arrival(
        self,
    ) -> None:
        server = _server()
        arrival = SETTLE._replace(lists=_lists(9000, 9010, 9020))
        server.last[10025] = server.finished = arrival
        server.lines = {10025: 9020}
        again = arrival._replace(lists=BAR, again=True)  # 9010's again, in flight

        def handle(params, superseded, again_, cursors) -> list:
            server.again(9000, CURSOR, 10025)  # 9000's answer lands meanwhile
            return []

        server._handle.side_effect = handle
        server._ring = Mock()
        self._run(server, again)
        server._ring.assert_called_once_with(
            arrival._replace(lists=_lists(9000, 9020), again=True)
        )

    def test_an_again_for_a_list_not_yet_reached_adds_nothing(self) -> None:
        server = _server()
        arrival = SETTLE._replace(lists=_lists(9000, 9010))

        def handle(params, superseded, again, cursors) -> list:
            if again.list_id == 9000:
                again.server.again(9010, again.value, again.window_id)
            return []

        server._handle.side_effect = handle
        self._run(server, arrival)
        handled = [c.args[2].list_id for c in server._handle.call_args_list]
        self.assertEqual(handled, [9000, 9010])  # 9010 read the answer itself
        self.assertIs(server.request, arrival)
        self.assertIsNone(server.ahead)

    def test_again_beside_an_again_keeps_its_lists(self) -> None:
        server = _server()
        server._ring = Mock()
        arrival = SETTLE._replace(lists=_lists(9040, 9000, 9010))
        server.last[10025] = server.finished = arrival
        server.request = arrival._replace(lists=BAR, again=True)  # in flight
        server.again(9000)
        server._ring.assert_called_once_with(
            arrival._replace(lists=_lists(9000, 9010), again=True)
        )

    def test_an_again_keeps_the_arrival_for_the_next_ring(self) -> None:
        server = _server()
        arrival = SETTLE._replace(lists=_lists(9000, 9010))
        self._run(server, arrival)
        self._run(server, arrival._replace(lists=BAR, again=True))
        self.assertIs(server.last[10025], arrival)
        self.assertIs(server.finished, arrival)
        self._run(server, serve.Request((), "moved_primary", "m1"))
        self.assertEqual(server.finished.ids, (9000, 9010))

    def test_a_late_answer_serves_its_list_again_while_current(self) -> None:
        server = _server()
        server._handle.side_effect = lambda *a: setattr(server, "late", a[2]) or []
        self._run(server, SETTLE)
        self.assertIs(server.finished, SETTLE)
        server._ring = Mock()
        server.late()  # TMDb's answer landed: the arrival is still the last one
        server._ring.assert_called_once_with(SETTLE._replace(again=True))
        moved = SETTLE._replace(value="54/4/13/v")
        server.last[10025] = server.request = server.finished = moved
        server.late()  # it has moved on: the new arrival serves its own
        server._ring.assert_called_once()

    def test_a_late_answer_a_newer_ring_had_is_owed_to_its_arrival(self) -> None:
        self.props["moved_item"] = "m1"
        server = _server()
        server._ring = Mock()
        item = serve.Request(_lists(9000, 9030), "moved_item", "m1", windows=INFO)
        rail = serve.Request(
            _lists(9100), "artwork_cursor_primary", CURSOR, windows=INFO
        )
        server.last = {12003: rail}
        server.request = rail  # a rail had focus as TMDb answered the item's 9030
        server.again(9030, "m1", 12003)
        server._ring.assert_not_called()
        self.assertEqual(server.owed, {(12003, 9030): "m1"})
        del server._ring
        held = {"current": "m1", "params": PARAMS}  # every list still answers m1
        server.bound = {i: dict(held) for i in (9000, 9030)}
        self._dialog(server, item)  # the tabs' return: what was owed alone
        self.assertEqual([c.args[1] for c in server._bind.call_args_list], [9030])
        self.assertEqual(server.owed, {})

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
        server.request = SETTLE._replace(value="54/4/13/v")  # a newer ring waits
        self.assertFalse(again.current())

    def test_an_again_is_never_current_once_the_service_stops(self) -> None:
        server = _server()
        self._run(server, SETTLE)
        again = serve.Again(server, 9010, CURSOR, 10025)
        server.stop()  # Kodi exiting: an aside fetch for it is skipped
        self.assertFalse(again.current())

    def test_again_is_never_a_repeat(self) -> None:
        server = _server()
        self._run(server, SETTLE)
        self._run(server, SETTLE._replace(again=True))
        self.assertEqual(server._handle.call_count, 2)

    def test_a_repeat_whose_list_was_emptied_serves(self) -> None:
        server = _server()
        self._run(server, SETTLE)
        server.bound.clear()  # a skin reload rebuilt the window
        self._run(server, SETTLE._replace())
        self.assertEqual(server._handle.call_count, 2)

    def test_a_window_names_the_list_it_served_with_a_handler(self) -> None:
        server = _server()
        self._run(server, SETTLE)
        self.assertEqual(server.served("progressbar"), 9010)  # an album's bar
        self.assertEqual(server.served("artwork"), 0)

    def test_a_line_is_an_ongoing_handlers(self) -> None:
        self.assertTrue(registry.runs_on("typewriter"))
        self.assertFalse(registry.runs_on("progressbar"))
        self.assertFalse(registry.runs_on(""))

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

    def test_start_serves_the_windows_load_ring_once_it_hears(self) -> None:
        self.props[serve.LOAD] = "serve?lists=9010:6910&mark=moved_primary&wait=225"
        order = []
        listener = Mock(waitForAbort=Mock(return_value=True))
        with (
            patch.object(serve, "Thread"),
            patch.object(serve, "_token", return_value="m9") as token,
            patch.object(
                serve, "_Listener", side_effect=lambda ring: order.append("hears")
            ),
        ):
            server = serve.Server()
            self.assertEqual(server.request, serve.Request())  # not before it hears
            serve._Listener.side_effect = lambda ring: order.append("hears") or listener
            server._ring = Mock(side_effect=lambda r: order.append(r))
            server._listen()
            token.assert_called_once_with("moved_primary")
            self.assertEqual(order, ["hears", MOVE._replace(value="m9")])
            del self.props[serve.LOAD]  # no window has loaded: nothing to serve
            server._ring.reset_mock()
            server._listen()
        server._ring.assert_not_called()

    def test_a_ring_from_python_writes_its_token_first(self) -> None:
        calls = []
        home = Mock(setProperty=lambda key, value: calls.append((key, value)))
        message = "serve?lists=9370:6937&mark=moved_preview&wait=225"
        with (
            patch.object(serve, "_home", return_value=home),
            patch.object(serve.xbmc, "executebuiltin", calls.append, create=True),
        ):
            serve.ring(message, window="13001")
        (key, token), rang = calls
        self.assertEqual(key, "moved_preview")
        self.assertEqual(
            rang,
            f"NotifyAll(script.copacetic.helper,{message}&window=13001&is={token})",
        )

    def test_a_dialogs_ring_is_served_in_it(self) -> None:
        self.props["moved_preview"] = "m1"
        server = _server()
        read = []
        move = serve.Request(_lists(9370), "moved_preview", "m1", windows=(13001,))
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
            [
                "Control.GetLabel(6937)",
                "Container(9370).ListItem.Property(params)",
                "Container(9370).ListItem.Property(current)",  # not this move's
            ],
        )
        server._bind.assert_called_once_with(
            13001, 9370, server._handle.return_value, "m1", "", "", PARAMS
        )
        self.assertEqual(server.last, {13001: move})

    def test_a_rails_settle_in_a_dialog_answers_the_cursor_it_names(self) -> None:
        rail = serve.Request(
            _lists(9100), "artwork_cursor_primary", CURSOR, windows=INFO
        )
        self.assertTrue(rail.live())
        self.props["artwork_cursor_primary"] = "3207/2/9/v"
        self.assertFalse(rail.live())

    def test_a_dialogs_window_is_the_one_on_top_waited_for_under_a_menu(self) -> None:
        server = _server()
        rail = serve.Request(
            _lists(9100), "artwork_cursor_primary", CURSOR, windows=INFO
        )
        server.request = rail
        self.assertEqual(server._window(SETTLE), 10025)  # no dialogs: the active window
        # Add-on info over video info, a menu over both: the one on top once it closes
        tops = iter([10106, 10106, 10146])
        with (
            patch.object(
                serve, "getCurrentWindowDialogId", side_effect=lambda: next(tops)
            ),
            patch.object(serve, "condition", return_value=True),
        ):
            self.assertEqual(server._window(rail), 10146)
        with (
            patch.object(serve, "getCurrentWindowDialogId", return_value=10106),
            patch.object(serve, "condition", return_value=False),  # all closed
        ):
            self.assertEqual(server._window(rail), 0)
        server.rung.set()  # a newer ring while the menu is up
        with (
            patch.object(serve, "getCurrentWindowDialogId", return_value=10106),
            patch.object(serve, "condition", return_value=True),
        ):
            self.assertEqual(server._window(rail), 0)
        self.assertTrue(server.rung.is_set())

    def test_an_info_dialogs_item_binds_in_it(self) -> None:
        self.props["moved_item"] = "m1movie:7"
        server = _server()
        move = serve.Request(
            _lists(9000, 9360), "moved_item", "m1movie:7", windows=INFO
        )
        self._dialog(server, move)
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
        item = serve.Request(_lists(9000, 9030), "moved_item", "m1", windows=INFO)
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
            [call(item._replace(lists=_lists(9030), again=True))] * 2,
        )

    def test_a_ring_rung_again_rings(self) -> None:
        server = _server()
        item = serve.Request(_lists(9000), "moved_item", "m1", windows=INFO)
        server._ring(item)
        server.rung.clear()
        server._ring(item._replace())  # a recovery: what it bound already is skipped
        self.assertTrue(server.rung.is_set())

    def test_a_dialog_list_whose_guard_read_a_menu_is_read_again_once(self) -> None:
        self.props["moved_item"] = "m1"
        server = _server()
        server._handle.side_effect = [None, [("plugin://x/1", Mock(), False)]]
        plot = serve.Request(_lists(9360), "moved_item", "m1", windows=INFO)
        self._dialog(server, plot)
        self.assertEqual(server._handle.call_count, 2)
        server._bind.assert_called_once()
        server._handle.side_effect = [None, None]  # twice: the serve ends
        self._dialog(server, plot._replace(again=True))
        self.assertEqual(server._handle.call_count, 4)
        server._bind.assert_called_once()

    def test_a_dialog_bind_names_its_echo(self) -> None:
        self.props.update(moved_item="m1", artwork_cursor_primary="3207/2/9/v")
        server = _server()
        rail = serve.Request(
            _lists(9100),
            "artwork_cursor_primary",
            "3207/2/9/v",
            windows=INFO,
            echo="m1",
        )
        self._dialog(server, rail)
        self.assertEqual(
            server._bind.call_args.args[3:],
            ("3207/2/9/v", "3207/2/9/", "m1", PARAMS),
        )

    def test_a_closed_dialog_drops(self) -> None:
        self.props["moved_preview"] = "m1"
        server = _server()
        move = serve.Request(_lists(9370), "moved_preview", "m1", windows=(13001,))
        with (
            patch.object(serve, "getCurrentWindowDialogId", return_value=13001),
            patch.object(serve, "condition", return_value=False) as visible,
        ):
            self._run(server, move)
        visible.assert_called_once_with("Window.IsVisible(13001)")
        server._bind.assert_not_called()

    def test_a_rings_item_is_its_containers_now(self) -> None:
        labels = {
            "Container(54).CurrentItem": "7",
            "Container(54).ListItem.DBID": "20",
            "Container(3200).CurrentItem": "2",
            "Container(3200).ListItem.DBID": "",
        }
        with patch.object(serve, "infolabel", side_effect=labels.get):
            self.assertEqual(  # a cursor names its list (the view)
                serve.Server._item(MOVE._replace(item=CURSOR)), "54/7/20/"
            )
            self.assertEqual(serve.Server._item(MOVE._replace(item="3200")), "3200/2//")
            self.assertEqual(serve.Server._item(MOVE), "")
            self.assertEqual(serve.Server._item(MOVE._replace(item="/")), "")
        self.assertEqual(serve.Server._item(SETTLE), "54/3/12/")

    def test_a_rings_item_is_read_before_its_handler(self) -> None:
        server = _server()
        order = []
        server._item = Mock(side_effect=lambda r: order.append("item") or "54/7/20/")
        server._handle.side_effect = lambda *a: order.append("handle") or []
        self._run(server, MOVE._replace(item=CURSOR))
        self.assertEqual(order, ["item", "handle"])
        self.assertEqual(server._bind.call_args.args[4], "54/7/20/")

    def test_bind_sets_paths_and_a_new_window(self) -> None:
        items = [("plugin://x/1", Mock(), False), ("plugin://x/2", Mock(), False)]
        with patch.object(serve, "Window") as window, patch.object(serve, "ListItem"):
            serve.Server._bind(10025, 9010, items, "c", "i", "e", "p")
            serve.Server._bind(10025, 9010, [], "c", "i")
        items[0][1].setPath.assert_called_once_with("plugin://x/1")
        items[1][1].setPath.assert_called_once_with("plugin://x/2")
        items[0][1].setProperties.assert_called_once_with(
            {"current": "c", "item": "i", "echo": "e", "params": "p"}
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
                lambda self, **kwargs: (asked.update(kwargs), False),
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
TURN = serve.Turn(SETTLE, 10025, 9300, (9400, 6932), "54/3/12/v", FAMILY)
ART = _lists(9300)
ARTWORK = "info=artwork&slides=9400:6932"  # a row whose family turns on 9400


def _bound(family: tuple[str, ...], identity: str = "54/3/12/v") -> list[tuple]:
    """9300's bound item: its family as multiart keys, its identity."""
    art = dict(zip(["multiart", *(f"multiart{i}" for i in range(1, 9))], family))
    listitem = Mock(getArt=lambda key: art.get(key, ""), getProperty={}.get)
    listitem.getProperty = lambda key: identity if key == "identity" else ""
    return [("plugin://x/artwork", listitem, False)]


TYPED = "info=typewriter&target_id=4020&label=Heat • 1995"
LINE = SETTLE._replace(lists=_lists(9010, 9020))
TYPEWRITER = _lists(9020)


class _Home(dict):
    """Home's properties, as a Window(10000) reads and writes them."""

    def getProperty(self, key: str) -> str:
        return self.get(key, "")

    def setProperty(self, key: str, value: str) -> None:
        self[key] = value


class TypewriterTest(unittest.TestCase):
    """9020 last: its line starts on its own thread and stands while its params do."""

    setUp, tearDown, _run = ServeTest.setUp, ServeTest.tearDown, ServeTest._run

    def _standing(self, retired: bool = False):
        return patch.object(
            helpers.TypewriterAnimation, "retired", return_value=retired
        )

    def test_only_the_services_stop_ends_a_line_here(self) -> None:
        server = _server(PARAMS, TYPED)
        self._run(server, LINE)
        bar, line = (c.args[1] for c in server._handle.call_args_list)
        server.request = SETTLE._replace(value="54/4/13/v")  # the next arrival
        self.props["artwork_cursor_primary"] = "54/4/13/v"
        self.assertTrue(bar())  # a list's serve is over
        self.assertFalse(line())  # the line's lease and guard stop it, not this
        server.stopped = True
        self.assertTrue(line())

    def test_the_same_line_stands_a_new_mark_too(self) -> None:
        server = _server(TYPED)
        self._run(server, LINE._replace(lists=TYPEWRITER))
        self.assertEqual(server.bound[9020]["params"], TYPED)
        server._handle.reset_mock(), server._bind.reset_mock()
        self.props["artwork_cursor_primary"] = "54/3/12/v2"
        with self._standing():  # Search's next key: a new mark, the same item
            self._run(server, LINE._replace(lists=TYPEWRITER, value="54/3/12/v2"))
        server._handle.assert_not_called(), server._bind.assert_not_called()
        server.probes = [TYPED.replace("Heat", "Heat (1995)")]  # its label changed
        with self._standing():
            self._run(server, LINE._replace(lists=TYPEWRITER, value="54/3/12/v2"))
        server._handle.assert_called_once()

    def test_a_started_line_binds_under_a_dialog(self) -> None:
        server = _server(TYPED)
        tops = iter([10025, 10025])  # its probe read on top, a menu at the bind
        with patch.object(
            serve, "topmost_window_id", side_effect=lambda: next(tops, 10106)
        ):
            self._run(server, LINE._replace(lists=TYPEWRITER))
        server._bind.assert_called_once()  # its item holds no reads
        self.assertEqual(server.bound[9020]["params"], TYPED)

    def test_a_started_line_a_move_cuts_binds_nothing(self) -> None:
        server = _server(TYPED)
        server._handle.side_effect = (
            lambda *a: self.props.update(
                artwork_cursor_primary="54/4/13/v"  # a move lands as it starts
            )
            or []
        )
        self._run(server, LINE._replace(lists=TYPEWRITER))
        server._bind.assert_not_called()  # the move's scroll retires it anyway
        self.assertEqual(server.failed, {})

    def test_a_none_binds_the_blank_each_time(self) -> None:
        server = _server(serve.NONE)  # a rail with no line, as Home's daily mixes
        request = LINE._replace(lists=TYPEWRITER)
        for mark in ("54/3/12/v", "54/4/13/v"):
            self.props["artwork_cursor_primary"] = mark
            self._run(server, request._replace(value=mark))
        self.assertEqual(server._bind.call_count, 2)  # a none is no line
        server._handle.assert_not_called()  # a none binds the blank, no handler
        # A real line after it still stands; after a none it types again
        for probe, mark in (
            (TYPED, "54/5/14/v"),
            (TYPED, "54/5/14/v2"),
            (serve.NONE, "54/6/15/v"),
            (TYPED, "54/5/14/v3"),
        ):
            server.probes = [probe]
            self.props["artwork_cursor_primary"] = mark
            with self._standing():
                self._run(server, request._replace(value=mark))
        self.assertEqual(server._handle.call_count, 2)
        self.assertEqual(server.bound[9020]["params"], TYPED)

    def test_a_retired_line_types_again(self) -> None:
        server = _server(TYPED)
        request = LINE._replace(lists=TYPEWRITER)
        self._run(server, request)
        self.props["artwork_cursor_primary"] = "54/3/12/v2"
        with self._standing(retired=True):
            self._run(server, request._replace(value="54/3/12/v2"))
        self.assertEqual(server._handle.call_count, 2)

    def test_a_repeat_serves_only_its_retired_line(self) -> None:
        server = _server()
        server.probes = {6910: [PARAMS], 6920: [TYPED]}
        with self._standing():
            self._run(server, LINE)
        server._handle.reset_mock()
        with self._standing():
            self._run(server, LINE)  # a repeat: nothing
        server._handle.assert_not_called()
        with self._standing(retired=True):
            self._run(server, LINE)
        server._handle.assert_called_once()  # 9020 alone
        self.assertEqual(server._bind.call_args.args[1], 9020)
        self.assertEqual(server.last[10025], LINE)
        self.assertEqual(server.finished, LINE)

    def test_retired_is_any_lease_but_its_runs(self) -> None:
        home = _Home()
        with patch.object(helpers, "Window", return_value=home):
            line = helpers.TypewriterAnimation(control_id=4020, window_id=10025)
            token = line.claim()
            self.assertFalse(serve.Server._retired(f"{serve.PLUGIN}{TYPED}"))
            for lease in ("scroll", "t2"):  # the skin's retire, another run's
                home["typewriter_current_4020"] = lease
                self.assertTrue(serve.Server._retired(TYPED))
            home["typewriter_current_4020"] = token
            self.assertFalse(serve.Server._retired("none"))  # it names no line

    def test_a_stopped_line_hands_its_lease_back(self) -> None:
        home = _Home()
        monitor = Mock(**{"abortRequested.return_value": False})
        monitor.waitForAbort.return_value = False
        windows = {10000: home, 10025: Mock()}
        took = lambda: home.setProperty("typewriter_current_4020", "t2") or False
        with (
            patch.object(helpers, "Window", side_effect=lambda i: windows[i]),
            patch.object(helpers, "Monitor", return_value=monitor),
            patch.object(helpers, "topmost_window_id", return_value=10025),
        ):
            line = helpers.TypewriterAnimation(control_id=4020, window_id=10025)
            line.update(label="A", opts=Mock(), alive=lambda: False)  # lost focus
            self.assertEqual(home["typewriter_current_4020"], "scroll")
            windows[10025].getControl.return_value.setText.assert_called_with("")
            line.update(label="A", opts=Mock(), alive=took)  # another run took it
            self.assertEqual(home["typewriter_current_4020"], "t2")

    def test_an_again_asks_the_line_too(self) -> None:
        server = _server()
        server._ring = Mock()
        server.last[10025] = server.finished = server.request = LINE._replace(
            lists=_lists(9000, 9010, 9020)
        )
        server.lines = {10025: 9020}  # the list its line was served in
        server.again(9000)
        server._ring.assert_called_once_with(
            LINE._replace(lists=_lists(9000, 9020), again=True)
        )

    def test_an_again_while_the_line_waits_serves_it_after_the_answer(self) -> None:
        server = _server()
        server._ring = Mock()
        request = LINE._replace(lists=_lists(9000, 9020))
        server.request = request
        server.probes = {6900: [PARAMS], 6920: [serve.WAIT, TYPED]}
        kodi = _reads(server)

        def reads(label: str) -> str:
            value = kodi(label)
            if value == serve.WAIT:
                server.again(9000)  # TMDb answers 9000 while 9020 waits
            return value

        with patch.object(serve, "infolabel", side_effect=reads):
            server._serve(request)
        self.assertEqual(server._handle.call_count, 1)  # 9000: the line holds off
        server._ring.assert_called_once_with(request._replace(again=True))
        server._handle.reset_mock()
        server.request = again = request._replace(again=True)
        with patch.object(serve, "infolabel", side_effect=kodi), self._standing():
            server._serve(again)
        self.assertEqual(server._handle.call_count, 2)  # 9000, then the line once

    def test_a_late_answer_for_a_list_ahead_leaves_the_line_be(self) -> None:
        server = _server(PARAMS, PARAMS, TYPED)
        server._ring = Mock()
        calls = iter([lambda: server.again(9010)])  # asked at 9000: 9010 is ahead
        server._handle.side_effect = lambda *a: next(calls, lambda: None)() or []
        self._run(server, LINE._replace(lists=_lists(9000, 9010, 9020)))
        self.assertEqual(server._handle.call_count, 3)  # the line typed in turn
        server._ring.assert_not_called()

    def test_a_repeat_whose_line_waits_serves_it_alone(self) -> None:
        server = _server()
        server.probes = {6910: [PARAMS], 6920: [TYPED]}
        self._run(server, LINE)
        server._handle.reset_mock()
        server.probes[6920] = [serve.WAIT, serve.WAIT, TYPED]  # the region's switch
        with self._standing(retired=True):  # the line was cleared meanwhile
            self._run(server, LINE)
        server._handle.assert_called_once()  # 9020 alone, once the wait is out
        self.assertEqual(server._bind.call_args.args[1], 9020)
        server._handle.reset_mock()
        server.probes[6920] = [serve.WAIT, TYPED]
        with self._standing():  # a line that still stands is left be
            self._run(server, LINE)
        server._handle.assert_not_called()

    def test_a_claim_and_a_hand_back_share_one_lock(self) -> None:
        home = _Home()
        lock = Mock(wraps=helpers.TypewriterAnimation.lease_lock)
        lock.__enter__ = Mock(side_effect=lambda *a: lock._mock_wraps.acquire())
        lock.__exit__ = Mock(side_effect=lambda *a: lock._mock_wraps.release())
        windows = {10000: home, 10025: Mock()}
        monitor = Mock(**{"abortRequested.return_value": False})
        monitor.waitForAbort.return_value = False
        with (
            patch.object(helpers.TypewriterAnimation, "lease_lock", lock),
            patch.object(helpers, "Window", side_effect=lambda i: windows[i]),
            patch.object(helpers, "Monitor", return_value=monitor),
        ):
            line = helpers.TypewriterAnimation(control_id=4020, window_id=10025)
            line.update(label="A", opts=Mock(), alive=lambda: False)
        self.assertEqual(lock.__enter__.call_count, 2)  # the claim, the hand-back

    def test_live_reads_the_kept_home(self) -> None:
        with patch.object(serve, "home_property", return_value=CURSOR) as read:
            self.assertTrue(SETTLE.live())
        read.assert_called_once_with("artwork_cursor_primary")


class TypewriterHandlerTest(unittest.TestCase):
    """The handler: served, its line starts on a thread; a plugin call types it inline."""

    def _typewriter(self, superseded: Callable[[], bool] | None, **params: str):
        params = {"info": "typewriter", "target_id": "4020", **params}
        ph = handlers.PluginHandlers(params, superseded)
        guard = Mock(**{"alive.return_value": True})
        with (
            patch.object(handlers, "getCurrentWindowId", return_value=10025),
            patch.object(handlers, "window_property"),
            patch.object(ph, "_guard", return_value=guard),
            patch.object(handlers, "TypewriterAnimation") as animation,
            patch.object(handlers, "Thread") as thread,
        ):
            return ph.typewriter(), animation, thread

    def test_served_it_types_on_its_own_thread(self) -> None:
        items, animation, thread = self._typewriter(Mock(return_value=False), label="A")
        self.assertEqual(items, [])  # 9020 is bound: the arrival is answered
        animation.return_value.update.assert_not_called()
        run, label = thread.call_args.kwargs["args"]
        self.assertEqual(label, "A")
        thread.return_value.start.assert_called_once()
        run()
        animation.return_value.update.assert_called_once()

    def test_a_plugin_call_types_inline(self) -> None:
        items, animation, thread = self._typewriter(None, label="A")
        self.assertEqual(items, [])
        animation.return_value.update.assert_called_once()
        thread.assert_not_called()

    def test_a_reset_or_no_label_answers_a_stop_doesnt(self) -> None:
        self.assertEqual(self._typewriter(Mock(return_value=False))[0], [])
        self.assertEqual(self._typewriter(None, reset="true")[0], [])
        self.assertIsNone(self._typewriter(Mock(return_value=True), label="A")[0])

    def test_a_lines_error_is_logged_on_its_thread(self) -> None:
        ph = handlers.PluginHandlers({"info": "typewriter"}, Mock())
        with patch.object(handlers.log, "exception") as logged:
            ph._type(Mock(side_effect=RuntimeError), "A")
        logged.assert_called_once()


class RotateTest(unittest.TestCase):
    """A family turns on its slides list: one slide a beat, made late in the dwell."""

    def setUp(self) -> None:
        self.props = {"artwork_cursor_primary": CURSOR}
        home = Mock(getProperty=lambda key: self.props.get(key, ""))
        self.patches = [
            patch.object(serve, "getCurrentWindowId", return_value=10025),
            patch.object(serve, "topmost_window_id", return_value=10025),
            patch.object(serve, "Window", return_value=home),
            patch.object(serve, "home_property", lambda k: self.props.get(k, "")),
            patch.object(serve, "infolabel", return_value="q"),  # the slide probe's
            patch.object(serve, "DWELL", 0),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def _serve(self, server: serve.Server, request: serve.Request) -> None:
        server.request = request
        with patch.object(serve, "infolabel", side_effect=_reads(server)):
            server._serve(request)

    def test_a_rows_slides_hand_its_family_and_identity(self) -> None:
        server = _server(ARTWORK)
        server._handle.return_value = _bound(FAMILY)
        request = SETTLE._replace(lists=ART)
        self._serve(server, request)
        self.assertEqual(server.turn, TURN._replace(request=request))
        self.assertTrue(server.handed.is_set())

    def test_a_row_naming_no_slides_hands_nothing_and_stops_its_lists(self) -> None:
        server = _server(PARAMS)
        server._handle.return_value = _bound(FAMILY)
        self._serve(server, SETTLE._replace(lists=ART))
        self.assertIsNone(server.turn)
        self.assertFalse(server.handed.is_set())
        server.turn = TURN  # turning on this list: its next bind stops it
        self.props["artwork_cursor_primary"] = "54/3/12/v2"
        self._serve(server, SETTLE._replace(lists=ART, value="54/3/12/v2"))
        self.assertIsNone(server.turn)
        self.assertTrue(server.handed.is_set())

    def test_a_repeat_turns_its_family_again_once_its_turn_ended(self) -> None:
        server = _server(ARTWORK)
        server._handle.return_value = _bound(FAMILY)
        request = SETTLE._replace(lists=ART)
        self._serve(server, request)
        server.handed.clear()
        self._serve(server, request._replace())  # a repeat while it turns: kept
        self.assertFalse(server.handed.is_set())
        server.turn = None  # a dialog's ring over it ended the turn
        self._serve(server, request._replace())
        server._handle.assert_called_once()  # held: no new serve
        self.assertEqual(server.turn, TURN._replace(request=request))
        self.assertTrue(server.handed.is_set())

    def test_a_family_of_one_or_none_stops_the_turn(self) -> None:
        server = _server()
        for items in (_bound(("a.jpg",)), []):
            server.turn = TURN
            family = serve.Server._family(items)
            server._hand(serve.Turn(SETTLE, 10025, 9300, (9400, 6932), *family))
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
            or (lambda turn, url: made.append(url) or ([("s", url, False)], "q"))
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
            [(10025, 9400, [("s", url, False)], CURSOR, "") for url in made],
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

        def slide(turn: serve.Turn, url: str) -> tuple[list[tuple], str]:
            if turn is TURN:
                server._hand(other)  # 9300 binds the next item mid-dwell
            return [("s", url, False)], "q"

        made = self.turn(server, 3, slide)
        self.assertEqual(made, [])
        self.assertEqual(
            [c.args[2][0][1] for c in server._bind.call_args_list], ["d.jpg", "c.jpg"]
        )

    def test_an_error_costs_the_turn_not_the_thread(self) -> None:
        server = _server()
        server.request, server.turn = SETTLE, TURN
        other = TURN._replace(family=("c.jpg", "d.jpg"))

        def slide(turn: serve.Turn, url: str) -> tuple[list[tuple], str]:
            if turn is TURN:
                server._hand(other)  # handed as the error lands: the thread turns it
                raise ValueError
            return [("s", url, False)], "q"

        self.turn(server, 2, slide)
        self.assertEqual(server._bind.call_args.args[2], [("s", "d.jpg", False)])

    def test_an_again_of_the_same_family_keeps_the_turn(self) -> None:
        server = _server()
        server.turn = TURN
        again = TURN._replace(request=SETTLE._replace(lists=ART, again=True))
        server._hand(again)
        self.assertIs(server.turn, TURN)
        self.assertFalse(server.handed.is_set())
        for changed in (
            again._replace(family=("a.jpg", "c.jpg")),  # TMDb's extras landed
            again._replace(request=SETTLE._replace(value="m2")),  # a new arrival
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

        def slide(turn: serve.Turn, url: str) -> tuple[list[tuple], str]:
            if not bound:
                time.sleep(0.15)  # past its beat: bound late
            return [("s", url, False)], "q"

        with patch.object(serve, "DWELL", 0.05), patch.object(serve, "LEAD", 0.02):
            self.turn(server, 3, slide)
        self.assertEqual(len(bound), 3)
        self.assertGreaterEqual(min(b - a for a, b in zip(bound, bound[1:])), 0.04)

    def test_a_move_during_the_beats_read_on_top_binds_nothing(self) -> None:
        server = _server()
        server.request, server.turn = SETTLE, TURN
        server._slide = Mock(return_value=([("s", "b.jpg", False)], "q"))
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
        server.request = SETTLE._replace(lists=BAR, again=True)  # same arrival
        self.assertTrue(server._turning(TURN))
        self.props["artwork_cursor_primary"] = "54/4/13/v"
        self.assertFalse(server._turning(TURN))
        self.props["artwork_cursor_primary"] = CURSOR
        server.request = SETTLE._replace(value="54/4/13/v")
        self.assertFalse(server._turning(TURN))

    def test_a_turn_ends_when_its_slide_probe_moves_on(self) -> None:
        server = _server()
        server.request, server.turn = SETTLE, TURN

        def read(label: str) -> str:  # the view's params: the service stops after
            server.stopped = True
            server.handed.set()
            return "r"

        with patch.object(serve, "infolabel", side_effect=read):
            made = self.turn(server, 3)
        self.assertEqual(made, ["b.jpg"])  # the rail's slide, never bound
        server._bind.assert_not_called()
        self.assertIsNone(server.turn)

    def test_a_beat_whose_probe_read_a_dialog_answered_binds_nothing(self) -> None:
        server = _server()
        server.request, server.turn = SETTLE, TURN
        tops = iter([10025, 10106])  # on top for the beat, a menu at the probe's read
        with patch.object(
            serve, "topmost_window_id", side_effect=lambda: next(tops, 10025)
        ):
            made = self.turn(server, 2)
        self.assertEqual(made, ["b.jpg", "a.jpg"])  # the turn goes on
        self.assertEqual(server._bind.call_args.args[2], [("s", "a.jpg", False)])

    def test_slide_reads_its_probe_on_top_and_names_9300s_identity(self) -> None:
        source = "ListItem.Art(clearlogo)"
        query = (
            f"background_blur=true&clearlogo_source={source}&icon_darken_label=A & B"
        )
        labels = {"Control.GetLabel(6932)": query, source: "https://x/l.png?a=1&b=2"}
        with (
            patch.object(serve, "infolabel", side_effect=labels.get) as read,
            patch("resources.lib.art.multiart.slide_art") as art,
            patch("resources.lib.plugin.setter.set_items", side_effect=list),
        ):
            art.return_value = {"background": "b.png", "slide": "b.jpg"}
            items, made_with = serve.Server._slide(TURN, "b.jpg")
        self.assertEqual(made_with, query)
        self.assertEqual(read.call_args_list, list(map(call, labels)))
        params, url = art.call_args.args
        self.assertEqual(url, "b.jpg")
        self.assertEqual(
            params["clearlogo_url"], "https://x/l.png?a=1&b=2"
        )  # by source
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

    def test_a_slide_whose_reads_a_new_dialog_answered_makes_none(self) -> None:
        tops = iter([10025, 10106])  # on top before the reads, a menu after
        with (
            patch.object(serve, "topmost_window_id", side_effect=lambda: next(tops)),
            patch.object(serve, "infolabel", return_value=PARAMS),
            patch("resources.lib.art.multiart.slide_art") as art,
        ):
            art.return_value = {"background": "b.png", "slide": "b.jpg"}
            self.assertIsNone(serve.Server._slide(TURN, "b.jpg"))


class MusicOsdTest(unittest.TestCase):
    """The music OSD's rails: a dialog over the visualisation, which stays a plugin."""

    RAIL = "3220/4/77/09:01:02Next"
    SETTLE = serve.Request(
        _lists(9100, 9300, 9020), "artwork_cursor_primary", RAIL, windows=(10120,)
    )

    def setUp(self) -> None:
        self.props = {"artwork_cursor_primary": self.RAIL}
        self.osd = {"top": 10120, "dialog": 10120, "open": True}
        home = Mock(getProperty=lambda key: self.props.get(key, ""))
        self.patches = [
            patch.object(serve, "getCurrentWindowId", return_value=12006),
            patch.object(serve, "getCurrentWindowDialogId", lambda: self.osd["dialog"]),
            patch.object(serve, "topmost_window_id", lambda: self.osd["top"]),
            patch.object(serve, "condition", lambda _: self.osd["open"]),
            patch.object(serve, "Window", return_value=home),
            patch.object(serve, "home_property", lambda k: self.props.get(k, "")),
            patch.object(serve, "POLL", 0),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def close(self, *args) -> list:
        """The OSD closes: its unload clears the cursor; the visualisation is on top."""
        self.osd.update(top=12006, dialog=9999, open=False)
        self.props["artwork_cursor_primary"] = ""
        return []

    def _run(self, server: serve.Server, request: serve.Request) -> None:
        server.request = request
        with patch.object(serve, "infolabel", side_effect=_reads(server)):
            server._serve(request)

    def test_a_rails_settle_binds_in_the_osd_with_its_echo(self) -> None:
        server = _server()
        rail = self.SETTLE._replace(echo="o1")
        self._run(server, rail)
        self.assertEqual(
            [c.args[:2] + c.args[3:6] for c in server._bind.call_args_list],
            [(10120, i, self.RAIL, "3220/4/77/", "o1") for i in (9100, 9300, 9020)],
        )
        self.assertEqual(server.last, {10120: rail})

    def test_the_osd_closing_after_a_bind_binds_nothing_more(self) -> None:
        server = _server()
        bind = server._bind.side_effect
        server._bind.side_effect = lambda *a: bind(*a) or self.close()
        self._run(server, self.SETTLE)
        self.assertEqual(
            [c.args[:2] for c in server._bind.call_args_list], [(10120, 9100)]
        )

    def test_the_osd_closing_during_a_handler_binds_nothing(self) -> None:
        server = _server()
        server._handle.side_effect = self.close
        self._run(server, self.SETTLE)
        server._bind.assert_not_called()
        self.assertIsNone(server.finished)

    def test_a_ring_as_the_osd_closes_is_dropped(self) -> None:
        server = _server()
        self.close()
        self.assertEqual(server._window(self.SETTLE), 0)
        self._run(server, self.SETTLE)
        server._handle.assert_not_called()

    def test_its_slides_turn_in_the_osd_and_end_as_it_closes(self) -> None:
        server = _server()
        server.request = self.SETTLE
        turn = serve.Turn(self.SETTLE, 10120, 9300, (9400, 6932), self.RAIL, FAMILY)
        self.assertTrue(server._turning(turn))
        self.close()
        self.assertFalse(server._turning(turn))
        with patch.object(serve, "infolabel", return_value=PARAMS) as read:
            self.assertIsNone(serve.Server._slide(turn, "b.jpg"))
        read.assert_not_called()

    def test_back_from_info_over_a_rail_the_repeat_turns_its_slides(self) -> None:
        server = _server(ARTWORK)
        server._handle.return_value = _bound(FAMILY, self.RAIL)
        rail = self.SETTLE._replace(lists=ART, echo="o1")
        self._run(server, rail)
        server.turn = None  # the info dialog's ring ended the turn
        self._run(server, rail._replace())  # its close rings the OSD's cursor again
        server._handle.assert_called_once()
        self.assertEqual((server.turn.window_id, server.turn.request), (10120, rail))

    def test_a_dialog_serve_reads_the_osd_never_the_window_under_it(self) -> None:
        params = {"info": "artwork", "dialog": "true", "target": "3220"}
        with (
            patch.object(handlers, "topmost_window_id", return_value=10120),
            patch.object(handlers, "condition", return_value=False),
        ):
            self.assertEqual(handlers.PluginHandlers(params).window_id, 10120)
        with (
            patch.object(handlers, "topmost_window_id", return_value=12006),
            patch.object(handlers, "condition", return_value=False),  # closed
        ):
            self.assertEqual(handlers.PluginHandlers(params).window_id, 9999)


if __name__ == "__main__":
    unittest.main()
