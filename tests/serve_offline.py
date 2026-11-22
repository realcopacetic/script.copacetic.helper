"""
Offline checks for the served focus calls (resources/lib/service/serve.py): a ring
names its kind, region, known lists and mark, other senders and kinds are ignored; a
probe's params are handled (a plugin prefix dropped) and bound with the request's
current, none binds one blank item, an empty probe nothing, wait is read again; under
a dialog the request waits, and a newer ring, a window change or a moved cursor drops
it unbound; a list a dialog covered mid-run is owed again; a repeat does nothing; a
move with no lists serves the window's last request; again() serves one list of it; a
guard's superseded test comes first; a bind sets each item's path and uses a new
Window; SQLite keeps one connection per thread, and cache_only holds one thread only.
Run from the helper root: python tests/serve_offline.py
"""

import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event, Thread
from unittest.mock import Mock, patch

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
from resources.lib.plugin import handlers  # noqa: E402
from resources.lib.service import serve  # noqa: E402
from resources.lib.shared import sqlite  # noqa: E402

PARAMS = "info=progressbar&label=A, B"
CURSOR = "54/3/12/09:01:02Next"
SETTLE = serve.Request("settle", "primary", (9010,), CURSOR)


def _server(*probes: str) -> serve.Server:
    """A Server without its threads, its probe reading probes in turn (the last stays)."""
    server = object.__new__(serve.Server)
    server.request, server.rung, server.stopped = None, Event(), False
    server.heard, server.last, server.finished = 0.0, {}, None
    server._handle = Mock(return_value=[("plugin://x/1", Mock(), False)])
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
        listener.onNotification(sender, f"Other.settle/primary/9010.9300/{CURSOR}", "")
        listener.onNotification(sender, "Other.move//9010/m1", "")
        listener.onNotification(sender, "Other.move///m2", "")
        listener.onNotification(
            "other.addon", f"Other.settle/primary/9010/{CURSOR}", ""
        )
        listener.onNotification(sender, "Other.clashes/answers", "")
        self.assertEqual(
            heard,
            [
                serve.Request("settle", "primary", (9010,), CURSOR),
                serve.Request("move", "", (9010,), "m1"),
                serve.Request("move", "", (), "m2"),
            ],
        )

    def test_current_names_the_arrival(self) -> None:
        self.assertEqual(SETTLE.current, "54/3/12/")  # no visit: a kept item matches
        self.assertEqual(serve.Request("move", "primary", (9010,), "m1").current, "m1")

    def test_probe_is_handled_and_bound_with_current(self) -> None:
        server = _server(f"{serve.PLUGIN}?{PARAMS}")
        self._run(server, SETTLE)
        params, superseded = server._handle.call_args.args
        self.assertEqual(params, f"{serve.PLUGIN}?{PARAMS}")
        self.assertFalse(superseded())
        server._bind.assert_called_once_with(
            10025, 9010, server._handle.return_value, "54/3/12/", "54/3/12/"
        )
        self.assertEqual(server.finished, SETTLE)

    def test_handle_drops_a_plugin_prefix(self) -> None:
        with patch("resources.lib.plugin.registry.info_handler") as dispatch:
            serve.Server._handle(f"{serve.PLUGIN}?{PARAMS}", bool)
            serve.Server._handle(PARAMS, bool)
        self.assertEqual(dispatch.call_args_list[0], dispatch.call_args_list[1])
        self.assertEqual(dispatch.call_args.args[0]["label"], "A, B")

    def test_none_binds_blank(self) -> None:
        server = _server(serve.NONE)
        self._run(server, SETTLE)
        server._handle.assert_not_called()
        server._bind.assert_called_once_with(10025, 9010, [], "54/3/12/", "54/3/12/")

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

    def test_a_move_is_never_a_repeat(self) -> None:
        server = _server()
        move = serve.Request("move", "primary", (9010,), "m1")
        self._run(server, move)
        self._run(server, move._replace())
        self.assertEqual(server._handle.call_count, 2)

    def test_move_with_no_lists_is_the_last_request(self) -> None:
        server = _server()
        self._run(server, SETTLE)
        move = serve.Request("move", "", (), "m1")
        self._run(server, move)
        self.assertEqual(server._bind.call_args.args[3:], ("m1", ""))
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
        server.last[10025] = SETTLE._replace(lists=(9000, 9010))
        server.again(9300)  # not one of its lists
        server.request = SETTLE._replace(mark="54/4/13/v")  # a newer ring waits
        server.again(9010)
        server.request = server.last[10025]
        server.again(9010)
        server._ring.assert_called_once_with(SETTLE._replace(again=True))

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
            server.finished, serve.Request("move", "primary", (9010,), "m1")
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
            self.assertEqual(serve.Server._handle(PARAMS, bool), [])

    def test_start_rings_a_move(self) -> None:
        with (
            patch.object(serve, "Thread"),
            patch.object(serve, "move_token", return_value="m9") as token,
        ):
            server = serve.Server()
        token.assert_called_once_with()
        self.assertEqual(
            server.request, serve.Request("move", "primary", (9010,), "m9")
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
            ring, f"NotifyAll(script.copacetic.helper,move/primary/9010/{token})"
        )

    def test_bind_sets_paths_and_a_new_window(self) -> None:
        items = [("plugin://x/1", Mock(), False), ("plugin://x/2", Mock(), False)]
        with patch.object(serve, "Window") as window, patch.object(serve, "ListItem"):
            serve.Server._bind(10025, 9010, items, "c", "i")
            serve.Server._bind(10025, 9010, [], "c", "i")
        items[0][1].setPath.assert_called_once_with("plugin://x/1")
        items[1][1].setPath.assert_called_once_with("plugin://x/2")
        items[0][1].setProperties.assert_called_once_with({"current": "c", "item": "i"})
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


if __name__ == "__main__":
    unittest.main()
