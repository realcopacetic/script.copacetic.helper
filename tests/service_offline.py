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
(STAGE / "addon.xml").write_text('<addon id="skin.test" />')
MAPPINGS = STAGE / "extras" / "templates" / "mappings"
MAPPINGS.mkdir(parents=True)
(MAPPINGS / "mappings_test.json").write_text(
    '{"test": {"mode": "dynamic", "items": ["row"]}}'
)
sys.modules["xbmc"].Monitor = type("Monitor", (), {"abortRequested": lambda self: True})
_module("resources.lib.art.slideshow", Slideshow=Mock)
_module("resources.lib.service.player", PlayerMonitor=Mock)
sys.path.insert(0, str(HELPER))

from resources.lib.builders.runtime import RuntimeStateManager  # noqa: E402
from resources.lib.builders.substitution import TokenError  # noqa: E402
from resources.lib.service import monitor  # noqa: E402
from resources.lib.shared.utilities import (  # noqa: E402
    RESOLVER_CACHE,
    RUNTIME_STATE,
    window_property,
)

CACHE, STATE = Path(RESOLVER_CACHE), Path(RUNTIME_STATE)
RAISES = Mock(side_effect=TokenError("unknown token"))
REAL = monitor.BuildElements


def built(written: bool) -> Mock:
    """A BuildElements whose seeded state forces a full build, returning ``written``."""
    build = Mock()
    build.return_value.runtime_manager.initialize_runtime_state.return_value = True
    build.return_value.run.return_value = written
    return build


class BuildBoundary(unittest.TestCase):
    def setUp(self):
        self.errors = COUNTS["ERROR"]
        self.start()

    def start(self):
        """A fresh service, as after a Kodi restart."""
        window_property(monitor.ACTIVE_PROPERTY)
        self.service = monitor.Monitor()
        self.service._reload = Mock()

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

    def builds_on_start(self):
        """Start the service with the real builder; return how many builds ran."""
        self.start()
        with patch.object(REAL, "run", autospec=True, side_effect=REAL.run) as run:
            self.follow(REAL)
        return run.call_count

    def seed(self):
        """Saved state and current cache, then drop the state: next start seeds."""
        STATE.unlink(missing_ok=True)
        CACHE.unlink(missing_ok=True)
        self.assertEqual(self.builds_on_start(), 1)
        self.assertEqual(self.builds_on_start(), 0)
        STATE.unlink()

    def test_seeded_failed_build_retries_next_start(self):
        self.seed()
        self.start()
        raises = TokenError("unknown token")
        with patch.object(REAL, "_process_builders", side_effect=raises):
            self.follow(REAL)
        self.assertTrue(STATE.exists())
        self.assertFalse(CACHE.exists())
        self.assertEqual(self.builds_on_start(), 1)
        self.assertTrue(CACHE.exists())
        self.assertEqual(self.builds_on_start(), 0)

    def test_seeded_then_mirrors_raise_retries_next_start(self):
        self.seed()
        self.start()
        raises = TokenError("unknown token")
        with patch.object(
            RuntimeStateManager, "reconcile_skin_mirrors", side_effect=raises
        ):
            self.follow(REAL)
        self.assertEqual(COUNTS["ERROR"], self.errors + 1)
        self.assertTrue(STATE.exists())
        self.assertFalse(CACHE.exists())
        self.assertEqual(self.builds_on_start(), 1)

    def test_run_seeding_for_itself_retries_next_start(self):
        self.seed()
        raises = TokenError("unknown token")
        with patch.object(REAL, "_process_builders", side_effect=raises):
            with self.assertRaises(TokenError):
                REAL().run()
        self.assertTrue(STATE.exists())
        self.assertFalse(CACHE.exists())
        self.assertEqual(self.builds_on_start(), 1)

    def test_seeded_good_build_needs_no_extra_build(self):
        self.seed()
        self.assertEqual(self.builds_on_start(), 1)
        self.assertTrue(CACHE.exists())
        self.assertEqual(self.builds_on_start(), 0)


if __name__ == "__main__":
    unittest.main()
