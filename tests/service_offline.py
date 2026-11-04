"""
Offline checks for the service's build boundary (resources/lib/service/monitor.py):
a build that raises is logged, and the player monitor, slideshow and helper_active
still start. Run from the helper root: python tests/service_offline.py
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from build_offline import HELPER, _module, install_stubs

STAGE = Path(tempfile.mkdtemp())
COUNTS = install_stubs(HELPER, STAGE, STAGE, verbose=False)
sys.modules["xbmc"].Monitor = type("Monitor", (), {"abortRequested": lambda self: True})
_module("resources.lib.art.slideshow", Slideshow=Mock)
_module("resources.lib.service.player", PlayerMonitor=Mock)
sys.path.insert(0, str(HELPER))

from resources.lib.builders.substitution import TokenError  # noqa: E402
from resources.lib.service import monitor  # noqa: E402
from resources.lib.shared.utilities import window_property  # noqa: E402

RAISES = Mock(side_effect=TokenError("unknown token"))


def built(written: bool) -> Mock:
    """A BuildElements whose seeded state forces a full build, returning ``written``."""
    build = Mock()
    build.return_value.runtime_manager.initialize_runtime_state.return_value = True
    build.return_value.run.return_value = written
    return build


class BuildBoundary(unittest.TestCase):
    def setUp(self):
        window_property(monitor.ACTIVE_PROPERTY)
        self.service = monitor.Monitor()
        self.service._reload = Mock()
        self.errors = COUNTS["ERROR"]

    def follow(self, build, version="1"):
        with (
            patch.object(monitor, "BuildElements", build),
            patch.object(monitor, "skin_uses_builder", lambda: True),
            patch.object(monitor, "validate_path", lambda path: True),
        ):
            self.service._follow("skin", version)

    def test_raising_build_still_activates(self):
        self.follow(RAISES)
        self.assertTrue(self.service.player_monitor)
        self.assertTrue(self.service.slideshow)
        self.assertEqual(
            sys.modules["xbmcgui"].Window().getProperty(monitor.ACTIVE_PROPERTY),
            "true",
        )
        self.assertEqual(COUNTS["ERROR"], self.errors + 1)
        self.service._reload.assert_not_called()

    def test_raising_build_on_skin_update_keeps_monitors(self):
        self.follow(built(written=False))
        player_monitor = self.service.player_monitor
        self.follow(RAISES, version="2")
        self.assertIs(self.service.player_monitor, player_monitor)
        self.assertEqual(COUNTS["ERROR"], self.errors + 1)
        self.service._reload.assert_not_called()

    def test_kodi_stop_is_not_caught(self):
        with self.assertRaises(SystemExit):
            self.follow(Mock(side_effect=SystemExit))

    def test_written_outputs_reload(self):
        self.follow(built(written=True))
        self.service._reload.assert_called_once()
        self.assertEqual(COUNTS["ERROR"], self.errors)


if __name__ == "__main__":
    unittest.main()
