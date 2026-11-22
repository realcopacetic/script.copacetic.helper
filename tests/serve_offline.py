"""
Offline checks for the served focus calls spike (resources/lib/service/serve.py): a
ring names known lists only and other senders are ignored; a probe's plugin URL is
handled and bound with its cursor, the empty folder binds one blank item, an unmounted
probe nothing; under a dialog the request waits, and a newer ring or a window change
drops it unbound; a bind sets each item's path and uses a new Window.
Run from the helper root: python tests/serve_offline.py
"""

import sys
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import Mock, patch

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
sys.modules["xbmc"].Monitor = type("Monitor", (), {"__init__": lambda self: None})
sys.path.insert(0, str(HELPER))

from resources.lib.service import serve  # noqa: E402

URL = f"{serve.PLUGIN}?info=metadata&label=A, B"


def _server(probe: str = URL) -> serve.Server:
    """A Server without its threads, its probe reading probe."""
    server = object.__new__(serve.Server)
    server.request, server.rung, server.stopped = None, Event(), False
    server._handle = Mock(return_value=[("plugin://x/1", Mock(), False)])
    server._bind = Mock()
    server.probe = probe
    return server


class ServeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.patches = [
            patch.object(serve, "getCurrentWindowId", return_value=10025),
            patch.object(serve, "topmost_window_id", return_value=10025),
        ]
        for p in self.patches:
            p.start()

    def tearDown(self) -> None:
        for p in self.patches:
            p.stop()

    def _run(self, server: serve.Server, request: serve.Request) -> None:
        server.request = request
        with patch.object(serve, "infolabel", return_value=server.probe):
            server._serve(request)

    def test_ring_parses_known_lists_only(self) -> None:
        heard = []
        listener = serve._Listener(heard.append)
        listener.onNotification(
            "script.copacetic.helper", "Other.settle/9002.9300/50/3/12/09:01:02", ""
        )
        listener.onNotification("other.addon", "Other.settle/9002/50/3/12/v", "")
        self.assertEqual(len(heard), 1)
        self.assertEqual(heard[0].lists, (9002,))
        self.assertEqual(heard[0].cursor, "50/3/12/09:01:02")

    def test_plugin_url_is_handled_and_bound(self) -> None:
        server = _server()
        request = serve.Request((9002,), "50/3/12/v", 0.0)
        self._run(server, request)
        server._handle.assert_called_once_with(URL)
        server._bind.assert_called_once_with(
            10025, 9002, server._handle.return_value, "50/3/12/v"
        )

    def test_empty_folder_binds_blank(self) -> None:
        server = _server(serve.EMPTY)
        self._run(server, serve.Request((9002,), "c", 0.0))
        server._handle.assert_not_called()
        server._bind.assert_called_once_with(10025, 9002, [], "c")

    def test_unmounted_probe_binds_nothing(self) -> None:
        server = _server("")
        self._run(server, serve.Request((9002,), "c", 0.0))
        server._bind.assert_not_called()

    def test_dialog_waits_and_a_new_ring_drops(self) -> None:
        server = _server()
        server.rung.set()  # a newer ring while the dialog is up
        with patch.object(serve, "topmost_window_id", return_value=10106):
            self._run(server, serve.Request((9002,), "c", 0.0))
        server._bind.assert_not_called()

    def test_dialog_waits_and_a_window_change_drops(self) -> None:
        server = _server()
        with (
            patch.object(serve, "topmost_window_id", return_value=10106),
            patch.object(serve, "getCurrentWindowId", side_effect=[10025, 10000]),
            patch.object(serve, "OWED_POLL", 0),
        ):
            self._run(server, serve.Request((9002,), "c", 0.0))
        server._bind.assert_not_called()

    def test_superseded_while_handling_binds_nothing(self) -> None:
        server = _server()
        request = serve.Request((9002,), "c", 0.0)
        newer = serve.Request((9002,), "d", 0.0)
        server._handle.side_effect = lambda url: setattr(server, "request", newer) or []
        self._run(server, request)
        server._bind.assert_not_called()

    def test_bind_sets_paths_and_a_new_window(self) -> None:
        items = [("plugin://x/1", Mock(), False), ("plugin://x/2", Mock(), False)]
        with patch.object(serve, "Window") as window, patch.object(serve, "ListItem"):
            serve.Server._bind(10025, 9002, items, "c")
            serve.Server._bind(10025, 9002, [], "c")
        items[0][1].setPath.assert_called_once_with("plugin://x/1")
        items[1][1].setPath.assert_called_once_with("plugin://x/2")
        items[0][1].setProperty.assert_called_once_with("current", "c")
        self.assertEqual(window.call_count, 2)
        bound = window.return_value.getControl.return_value.addItems.call_args_list
        self.assertEqual(bound[0].args[0], [items[0][1], items[1][1]])
        self.assertEqual(len(bound[1].args[0]), 1)  # the blank item


if __name__ == "__main__":
    unittest.main()
