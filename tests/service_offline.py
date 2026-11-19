"""
Offline checks for the service's build boundary (resources/lib/service/monitor.py):
a build that raises is logged, and the player monitor, slideshow and helper_active
still start; helper_speed_dial follows the skin naming info=speed_dial; each skin
keeps its own runtime state; a script rebuild sets and clears helper_reloading, and
the editor close and delete_orphans reload only when the build wrote (or for a host
open once the session has closed), else clear it. Under the screensaver only lyrics
follow, while audio plays. played_version moves only for a counted play. A trailer
request that lands under a modal is dropped. A clashing add-on's feature turned on or
off queues the clashes check.
Run from the helper root: python tests/service_offline.py
"""

import json
import sys
import tempfile
import unittest
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from unittest.mock import Mock, call, patch

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
DIALOG = sys.modules["xbmcgui"].Dialog = Mock()


class Editor:
    """DynamicEditor stand-in: closes at once, its state changed if ``changed``."""

    changed = True

    def __init__(self, *args):
        self.runtime_manager = Mock(runtime_state=Editor.changed)
        self._runtime_state_snapshot = False

    def doModal(self):
        pass


_module("resources.lib.windows.dynamiceditor", DynamicEditor=Editor)
_module("resources.lib.art.slideshow", Slideshow=Mock)
_module("resources.lib.service.player", PlayerMonitor=Mock)
sys.path.insert(0, str(HELPER))

from resources.lib.builders.runtime import RuntimeStateManager  # noqa: E402
from resources.lib.builders.substitution import TokenError  # noqa: E402
from resources.lib.script import actions  # noqa: E402
from resources.lib.service import monitor  # noqa: E402
from resources.lib.shared import utilities  # noqa: E402
from resources.lib.shared.utilities import (  # noqa: E402
    resolver_cache_path,
    runtime_state_path,
    window_property,
)
from resources.lib.shared.xml import XMLHandler  # noqa: E402

CACHE, STATE = Path(resolver_cache_path()), Path(runtime_state_path())
RAISES = Mock(side_effect=TokenError("unknown token"))
REAL = monitor.BuildElements
monitor.ADDON.getLocalizedString = str
TOAST = call().notification("32000", "32215", time=8000)


def built(written: bool) -> Mock:
    """A BuildElements whose seeded state forces a full build, returning ``written``."""
    build = Mock()
    build.return_value.runtime_manager.initialize_runtime_state.return_value = True
    build.return_value.run.return_value = written
    return build


def as_skin(skin_id: str) -> AbstractContextManager:
    """The active skin's id reads as ``skin_id`` (the cache stamp keeps skin.test)."""
    return patch.object(utilities, "skin_id", lambda folder: skin_id)


def not_expressions(path: str) -> bool:
    """Every output but the expressions file exists: a partial build."""
    return "expressions" not in path


@contextmanager
def failing_write():
    """A build with an output to write, whose XML save fails on a full disk."""
    with (
        patch.object(
            REAL, "_process_builders", return_value={"expressions": {"a": "b"}}
        ),
        patch.object(XMLHandler, "_save_xml", side_effect=OSError("disk full")),
    ):
        yield


class BuildBoundary(unittest.TestCase):
    def setUp(self):
        self.errors = COUNTS["ERROR"]
        DIALOG.reset_mock()
        self.start()

    def start(self):
        """A fresh service, as after a Kodi restart."""
        window_property(monitor.ACTIVE_PROPERTY)
        window_property(monitor.SPEED_DIAL_PROPERTY)
        self.service = monitor.Monitor()
        self.service._reload = Mock()

    def follow(self, build, version="1", output_exists=lambda path: True):
        with (
            patch.object(monitor, "BuildElements", build),
            patch.object(monitor, "skin_uses_builder", lambda: True),
            patch.object(monitor, "validate_path", output_exists),
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

    def test_pin_items_show_only_while_the_skin_names_speed_dial(self):
        window = sys.modules["xbmcgui"].Window()
        self.follow(built(written=False))
        self.assertEqual(window.getProperty(monitor.SPEED_DIAL_PROPERTY), "")
        widgets = MAPPINGS / "mappings_widgets.json"
        widgets.write_text('{"w": {"content": "plugin://x/?info=speed_dial&v=1"}}')
        self.addCleanup(widgets.unlink)
        self.follow(built(written=False), version="2")
        self.assertEqual(window.getProperty(monitor.SPEED_DIAL_PROPERTY), "true")
        self.service._deactivate()
        self.assertEqual(window.getProperty(monitor.SPEED_DIAL_PROPERTY), "")

    def test_raising_build_on_skin_update_keeps_monitors(self):
        self.follow(built(written=False))
        player_monitor = self.service.player_monitor
        self.follow(RAISES, version="2")
        self.assertIs(self.service.player_monitor, player_monitor)
        self.assertEqual(COUNTS["ERROR"], self.errors + 1)
        self.service._reload.assert_not_called()

    def test_raising_build_shows_a_toast(self):
        self.follow(RAISES)
        self.assertEqual(DIALOG.mock_calls, [call(), TOAST])

    def test_good_build_shows_no_toast(self):
        self.follow(built(written=True))
        DIALOG.assert_not_called()

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

    def current_cache(self):
        """Saved state and a current cache: a start with nothing to do."""
        STATE.unlink(missing_ok=True)
        CACHE.unlink(missing_ok=True)
        self.assertEqual(self.builds_on_start(), 1)
        self.assertEqual(self.builds_on_start(), 0)

    def test_same_stamp_failed_write_retries_next_start(self):
        self.current_cache()
        with failing_write(), self.assertRaises(OSError):
            REAL().run()
        self.assertFalse(CACHE.exists())
        self.assertEqual(self.builds_on_start(), 1)
        self.assertEqual(self.builds_on_start(), 0)

    def test_new_stamp_failed_write_retries_next_start(self):
        self.current_cache()
        stale = json.loads(CACHE.read_text()) | {"stamp": "old"}
        CACHE.write_text(json.dumps(stale))
        self.start()
        with failing_write():
            self.follow(REAL)
        self.assertEqual(COUNTS["ERROR"], self.errors + 1)
        self.service._reload.assert_not_called()
        self.assertFalse(CACHE.exists())
        self.assertEqual(self.builds_on_start(), 1)
        self.assertEqual(self.builds_on_start(), 0)

    def test_partial_build_keeps_a_current_cache(self):
        self.current_cache()
        before = CACHE.read_bytes()
        self.start()
        with patch.object(REAL, "run", autospec=True, side_effect=REAL.run) as run:
            self.follow(REAL, output_exists=not_expressions)
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0].selected, ["expressions"])
        self.assertEqual(CACHE.read_bytes(), before)

    def test_an_output_another_profile_wrote_is_rebuilt(self):
        self.current_cache()
        output = STAGE / monitor.BUILDER_CONFIG["expressions"]["write_path"]
        output.parent.mkdir(exist_ok=True)
        self.addCleanup(output.unlink)
        built = {"expressions": {"a": "b"}}
        with patch.object(REAL, "_process_builders", return_value=built):
            REAL().run()
            ours = output.read_bytes()
            self.assertEqual(self.builds_on_start(), 0)
            output.write_bytes(ours.replace(b">b<", b">c<"))  # profile B's state
            self.assertEqual(self.builds_on_start(), 1)
            self.assertEqual(output.read_bytes(), ours)
            self.assertEqual(self.builds_on_start(), 0)

    def test_a_deleted_output_is_built_alone(self):
        self.current_cache()
        built = {"expressions": {"a": "b"}, "variables": {"v": "w"}}
        includes, kept, deleted = (
            STAGE / monitor.BUILDER_CONFIG[b]["write_path"]
            for b in ("includes", *built)
        )
        includes.parent.mkdir(exist_ok=True)
        includes.write_text("<includes />")  # the build keeps what it doesn't make
        for path in (includes, kept, deleted):
            self.addCleanup(path.unlink, missing_ok=True)
        with patch.object(REAL, "_process_builders", return_value=built):
            REAL().run()
            before = CACHE.read_bytes()
            deleted.unlink()
            self.start()
            with patch.object(REAL, "run", autospec=True, side_effect=REAL.run) as run:
                self.follow(REAL, output_exists=lambda path: Path(path).exists())
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0].selected, ["variables"])
        self.assertTrue(deleted.exists())
        self.assertEqual(CACHE.read_bytes(), before)

    def test_failed_partial_build_is_a_full_build_next_start(self):
        self.current_cache()
        self.start()
        with failing_write():
            self.follow(REAL, output_exists=not_expressions)
        self.assertFalse(CACHE.exists())
        self.assertEqual(self.builds_on_start(), 1)

    def other_skin(self, skin_id: str) -> list[Path]:
        """Files ``skin_id`` will keep, removed after the test."""
        with as_skin(skin_id):
            files = [Path(runtime_state_path()), Path(resolver_cache_path())]
        for path in files:
            self.addCleanup(path.unlink, missing_ok=True)
        return files

    def test_each_skin_keeps_its_own_state(self):
        self.current_cache()
        before = STATE.read_bytes()
        other_state, other_cache = self.other_skin("skin.other")
        with as_skin("skin.other"):
            self.assertEqual(self.builds_on_start(), 1)
        self.assertTrue(other_state.exists() and other_cache.exists())
        self.assertEqual(STATE.read_bytes(), before)
        self.assertEqual(self.builds_on_start(), 0)

    def test_only_copacetic2_adopts_the_shared_state(self):
        self.current_cache()
        shared = [STAGE / "runtime_state.json", STAGE / "resolver_cache.json"]
        for path, own in zip(shared, (STATE, CACHE)):
            path.write_bytes(own.read_bytes())
            self.addCleanup(path.unlink, missing_ok=True)
        before = [path.read_bytes() for path in shared]
        self.assertEqual(self.builds_on_start(), 0)
        self.assertTrue(all(path.exists() for path in shared))
        adopted = self.other_skin(utilities.SHARED_STATE_OWNER)
        with as_skin(utilities.SHARED_STATE_OWNER):
            self.assertEqual(self.builds_on_start(), 0)
        self.assertFalse(any(path.exists() for path in shared))
        self.assertEqual([path.read_bytes() for path in adopted], before)

    def test_a_later_shared_file_never_replaces_copacetic2s_own(self):
        self.current_cache()
        own_state, _ = self.other_skin(utilities.SHARED_STATE_OWNER)
        with as_skin(utilities.SHARED_STATE_OWNER):
            self.builds_on_start()
        before = own_state.read_bytes()
        shared = STAGE / "runtime_state.json"  # a downgrade's fresh seed
        shared.write_text('{"test": [], "shared": []}')
        self.addCleanup(shared.unlink, missing_ok=True)
        with as_skin(utilities.SHARED_STATE_OWNER):
            self.assertEqual(self.builds_on_start(), 0)
        self.assertTrue(shared.exists())
        self.assertEqual(own_state.read_bytes(), before)

    def dev_reset_on(self, skin_id: str) -> Path:
        """Both skins built with a marked state; Reset on next start on in ``skin_id``."""
        self.current_cache()
        other_state, _ = self.other_skin("skin.other")
        with as_skin("skin.other"):
            self.builds_on_start()
        for path in (STATE, other_state):
            path.write_text('{"test": [], "kept": []}')
        self.addCleanup(utilities.DEV_RESET.unlink, missing_ok=True)
        with (
            as_skin(skin_id),
            patch.object(monitor.ADDON, "getSettingBool", lambda key: True),
        ):
            self.service.onSettingsChanged()
        return other_state

    def dev_start(self, skin_id: str) -> Mock:
        """Start the service in ``skin_id`` with dev mode and the reset on."""
        with (
            as_skin(skin_id),
            patch.object(monitor.ADDON, "getSettingBool", lambda key: True),
            patch.object(monitor.ADDON, "setSettingBool", create=True) as setting,
        ):
            self.start()
            self.follow(REAL)
        return setting

    def test_dev_reset_clears_only_the_active_skin(self):
        other_state = self.dev_reset_on("skin.test")
        setting = self.dev_start("skin.test")
        setting.assert_called_once_with("dev_reset", False)
        self.assertFalse(utilities.DEV_RESET.exists())
        self.assertNotIn("kept", json.loads(STATE.read_text()))
        self.assertIn("kept", json.loads(other_state.read_text()))

    def test_dev_reset_waits_for_the_skin_it_was_turned_on_in(self):
        other_state = self.dev_reset_on("skin.other")
        self.dev_start("skin.test").assert_not_called()
        self.assertIn("kept", json.loads(STATE.read_text()))
        self.dev_start("skin.other").assert_called_once_with("dev_reset", False)
        self.assertNotIn("kept", json.loads(other_state.read_text()))
        self.assertIn("kept", json.loads(STATE.read_text()))

    def test_dev_reset_keeps_its_skin_until_turned_off(self):
        self.dev_reset_on("skin.other")
        with (
            as_skin("skin.test"),
            patch.object(monitor.ADDON, "getSettingBool", lambda key: True),
        ):
            self.service.onSettingsChanged()  # another setting saved in skin.test
        self.assertEqual(utilities.DEV_RESET.read_text(), "skin.other")
        with patch.object(monitor.ADDON, "getSettingBool", lambda key: False):
            self.service.onSettingsChanged()
        self.assertFalse(utilities.DEV_RESET.exists())

    def test_dev_reset_runs_in_the_next_builder_skin_followed(self):
        self.current_cache()
        STATE.write_text('{"test": [], "kept": []}')
        self.addCleanup(utilities.DEV_RESET.unlink, missing_ok=True)
        with (
            patch.object(monitor.ADDON, "getSettingBool", lambda key: True),
            patch.object(monitor.ADDON, "setSettingBool", create=True) as setting,
        ):
            with (
                as_skin("skin.estuary"),
                patch.object(utilities, "skin_uses_builder", lambda: False),
            ):
                self.service.onSettingsChanged()
            self.assertFalse(utilities.DEV_RESET.exists())
            with as_skin(""):  # addon.xml unreadable mid-install
                self.service.onSettingsChanged()
            self.assertFalse(utilities.DEV_RESET.exists())
            self.follow(REAL)  # a switch into skin.test, no restart
        setting.assert_called_once_with("dev_reset", False)
        self.assertFalse(utilities.DEV_RESET.exists())
        self.assertNotIn("kept", json.loads(STATE.read_text()))

    def test_a_check_with_dev_mode_off_leaves_a_reset_unpinned(self):
        self.current_cache()
        self.addCleanup(utilities.DEV_RESET.unlink, missing_ok=True)
        with (
            as_skin("skin.test"),
            patch.object(monitor.ADDON, "getSettingBool", "dev_reset".__eq__),
        ):
            self.start()
            self.follow(REAL)
        self.assertFalse(utilities.DEV_RESET.exists())

    def test_rebuild_reset_takes_an_unpinned_reset(self):
        self.current_cache()
        self.addCleanup(utilities.DEV_RESET.unlink, missing_ok=True)
        with (
            patch.object(monitor.ADDON, "getSettingBool", lambda key: True),
            patch.object(monitor.ADDON, "setSettingBool", create=True) as setting,
        ):
            utilities.reset_dev_state()
        setting.assert_called_once_with("dev_reset", False)
        self.assertFalse(utilities.DEV_RESET.exists())

    def test_rebuild_reset_keeps_another_skins_pending_reset(self):
        self.dev_reset_on("skin.other")
        with (
            patch.object(monitor.ADDON, "getSettingBool", lambda key: True),
            patch.object(monitor.ADDON, "setSettingBool", create=True) as setting,
        ):
            utilities.reset_dev_state()
        setting.assert_not_called()
        self.assertFalse(STATE.exists())
        self.assertEqual(utilities.DEV_RESET.read_text(), "skin.other")


class ServiceReload(unittest.TestCase):
    def setUp(self):
        self.addCleanup(window_property, "helper_reloading")
        self.service = monitor.Monitor()
        self.service.skin = "skin", "1"
        self.service._settle = Mock(return_value=True)
        self.service.waitForAbort = Mock(return_value=False)
        for patcher in (
            patch.object(monitor, "skin_path", lambda: "skin"),
            patch.object(monitor, "skin_version", lambda path: "1"),
            patch.object(monitor.xbmc, "executebuiltin"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def reloading(self):
        return sys.modules["xbmcgui"].Window().getProperty("helper_reloading")

    def test_skin_update_raises_the_dots_and_waits_before_the_checks(self):
        self.service.player_monitor = Mock()
        seen = []
        self.service._settle.side_effect = (
            lambda: seen.append(
                (self.reloading(), self.service.waitForAbort.call_count)
            )
            or True
        )
        self.service._reload()
        self.assertEqual(seen, [("reload", 1)])
        self.assertEqual(self.reloading(), "reload")
        monitor.xbmc.executebuiltin.assert_called_once_with("ReloadSkin()")

    def test_fullscreen_video_gets_no_cover(self):
        self.service.player_monitor = Mock()
        with patch.object(monitor, "condition", lambda text: True):
            self.service._reload()
        self.assertEqual(self.reloading(), "")
        self.service.waitForAbort.assert_not_called()
        monitor.xbmc.executebuiltin.assert_called_once_with("ReloadSkin()")

    def test_dropped_reload_clears_the_dots(self):
        self.service.player_monitor = Mock()
        self.service.skin = "other", "1"
        self.service._reload()
        self.service.waitForAbort.assert_called_once()
        self.assertFalse(self.service.reload_due)
        self.assertEqual(self.reloading(), "")
        monitor.xbmc.executebuiltin.assert_not_called()

    def test_start_leaves_the_property_to_the_start_splash(self):
        self.service._reload()
        self.assertEqual(self.reloading(), "")
        self.service.waitForAbort.assert_not_called()
        monitor.xbmc.executebuiltin.assert_called_once_with("ReloadSkin()")

    def test_deferred_reload_clears_the_dots(self):
        self.service.player_monitor = Mock()
        self.service.skin = "skin", "0"
        self.service._reload()
        self.service.waitForAbort.assert_called_once()
        self.assertTrue(self.service.reload_due)
        self.assertEqual(self.reloading(), "")
        monitor.xbmc.executebuiltin.assert_not_called()

    def test_kodi_exiting_during_the_wait_sends_no_reload(self):
        self.service.player_monitor = Mock()
        self.service.waitForAbort.return_value = True
        self.service._reload()
        self.service._settle.assert_not_called()
        monitor.xbmc.executebuiltin.assert_not_called()


class RebuildSplash(unittest.TestCase):
    def reloading(self):
        return sys.modules["xbmcgui"].Window().getProperty("helper_reloading")

    def test_failed_rebuild_clears_the_splash_with_a_toast(self):
        DIALOG.reset_mock()
        with (
            patch.object(REAL, "run", side_effect=OSError("disk full")),
            self.assertRaises(OSError),
        ):
            actions._rebuild()
        self.assertEqual(self.reloading(), "")
        self.assertEqual(DIALOG.mock_calls, [call(), TOAST])

    def test_good_rebuild_keeps_the_splash(self):
        self.addCleanup(window_property, "helper_reloading")
        with patch.object(REAL, "run", return_value=True):
            self.assertTrue(actions._rebuild())
        self.assertEqual(self.reloading(), "rebuild")

    def test_rebuild_that_wrote_nothing_keeps_the_splash(self):
        self.addCleanup(window_property, "helper_reloading")
        with patch.object(REAL, "run", return_value=False):
            self.assertFalse(actions._rebuild())
        self.assertEqual(self.reloading(), "rebuild")


class ReloadGate(unittest.TestCase):
    """
    Editor close and delete_orphans reload only when the build wrote, or for a host
    active once the session has closed; otherwise they clear helper_reloading.
    """

    def outcome(self, action, written, host_active=False, **kwargs):
        """Run ``action``; return (rebuilt, reloaded, helper_reloading cleared)."""
        rebuild, reload = Mock(return_value=written), Mock()
        prop = Mock(wraps=window_property)
        # The host reads as active only once the gate has reopened, so a host check
        # made before that (inside the session) misses it.
        reopened = call("active_editor_name", value="")
        with (
            patch.object(actions, "_rebuild", rebuild),
            patch.object(actions, "_reload_skin", reload),
            patch.object(
                actions,
                "condition",
                lambda text: host_active and reopened in prop.call_args_list,
            ),
            patch.object(actions, "window_property", prop),
        ):
            action(**kwargs)
        cleared = call("helper_reloading") in prop.call_args_list
        return rebuild.called, reload.called, cleared

    def close(self, written, changed=True, **kwargs):
        Editor.changed = changed
        return self.outcome(
            actions.dynamic_settings_window, written, mapping="test", **kwargs
        )

    def orphans(self, written, removed=1):
        manager = Mock(**{"delete_orphans.return_value": removed})
        with patch.object(RuntimeStateManager, "from_templates", return_value=manager):
            return self.outcome(actions.delete_orphans, written, child_mapping="test")

    def test_editor_close(self):
        cases = {
            "written": (self.close(True), (True, True, False)),
            "not written": (self.close(False), (True, False, True)),
            "host left": (self.close(False, host="skinsettings"), (True, False, True)),
            "host entered again": (
                self.close(False, host="skinsettings", host_active=True),
                (True, True, False),
            ),
            "unchanged": (self.close(True, changed=False), (False, False, False)),
        }
        for name, (got, wanted) in cases.items():
            with self.subTest(name):
                self.assertEqual(got, wanted)

    def test_delete_orphans(self):
        self.assertEqual(self.orphans(True), (True, True, False))
        self.assertEqual(self.orphans(False), (True, False, True))
        self.assertEqual(self.orphans(True, removed=0), (False, False, False))

    def test_rebuild_action_always_reloads(self):
        self.assertEqual(self.outcome(actions.rebuild, False), (True, True, False))


class PlayedVersion(unittest.TestCase):
    """played_version moves only when a closed song's play count changed."""

    def bumped(self, closed: dict, counts: dict) -> list:
        service = object.__new__(monitor.Monitor)
        service.closed = closed
        details = lambda method, params, parent: {  # noqa: E731
            "result": {"songdetails": {"playcount": counts[params["songid"]]}}
        }
        with (
            patch.object(monitor, "condition", lambda expression: False),
            patch.object(monitor, "json_call", details),
            patch.object(monitor, "window_property") as prop,
        ):
            service._album_bump()
        self.assertEqual(service.closed, {})
        return [c.args[0] for c in prop.call_args_list]

    def test_a_counted_play_bumps(self):
        self.assertEqual(self.bumped({7: 3}, {7: 4}), ["played_version"])

    def test_a_skipped_song_does_not(self):
        self.assertEqual(self.bumped({7: 3}, {7: 3}), [])

    def test_one_counted_of_a_burst_bumps_once(self):
        self.assertEqual(self.bumped({7: 3, 8: 0}, {7: 3, 8: 1}), ["played_version"])

    def test_an_update_keeps_a_pending_close_waiting(self):
        service = object.__new__(monitor.Monitor)
        service.closed, service.player_monitor = {7: 3}, Mock()
        service._song_update = Mock()
        service.onNotification("xbmc", "AudioLibrary.OnUpdate", '{"type": "song"}')
        service._song_update.assert_not_called()  # its read would beat the write
        service.closed = {}
        service.onNotification("xbmc", "AudioLibrary.OnUpdate", '{"type": "song"}')
        service._song_update.assert_called_once_with()

    def test_overlapping_bumps_share_nothing(self):
        service = object.__new__(monitor.Monitor)
        seen = []

        class Racing(dict):
            """A second Timer takes the songs between the first's count and pop."""

            def popitem(self):
                if not seen:
                    seen.append("raced")
                    service._album_bump()
                return super().popitem()

        def details(method, params, parent):
            seen.append(params["songid"])
            return {"result": {"songdetails": {"playcount": 4}}}

        service.closed = Racing({7: 3})
        with (
            patch.object(monitor, "condition", lambda expression: False),
            patch.object(monitor, "json_call", details),
            patch.object(monitor, "window_property") as prop,
        ):
            service._album_bump()
        self.assertEqual(seen, [7])
        self.assertEqual([c.args[0] for c in prop.call_args_list], ["played_version"])


class LyricsUnderTheScreensaver(unittest.TestCase):
    def test_only_lyrics_follow_while_audio_plays(self):
        service = object.__new__(monitor.Monitor)
        service.idle, service.skin = True, ("skin", "1")
        service.player_monitor = Mock(
            **{
                "isPlayingAudio.side_effect": [True, False],
                "watch_lyrics.return_value": 0.2,
            }
        )
        waits = []
        service.waitForAbort = waits.append
        service.abortRequested = Mock(side_effect=[False, False, True])
        service.poller, service._deactivate = Mock(), Mock()
        with (
            patch.object(monitor, "skin_path", lambda: "skin"),
            patch.object(monitor, "skin_version", lambda skin: "1"),
        ):
            service._run()
        self.assertEqual(waits, [0.2, 2])  # a song, then nothing playing
        service.poller.assert_not_called()


class MultiLanguageSubtitles(unittest.TestCase):
    """Several preferred subtitle languages: stored joined, stepped in turn."""

    def test_a_joined_value_stands_only_with_a_separator(self):
        from resources.lib.builders.runtime import allowed_value

        config = {"items": ["none", "eng", "jpn"], "separator": "|"}
        self.assertTrue(allowed_value("eng|jpn", config))
        self.assertTrue(allowed_value("none", config))
        self.assertFalse(allowed_value("eng|kor", config))
        self.assertFalse(allowed_value("eng|jpn", {"items": ["eng", "jpn"]}))

    def test_subtitles_step_through_the_languages_then_off(self):
        def stream(index, language):
            return {
                "index": index,
                "language": language,
                "name": "",
                "isforced": False,
                "isimpaired": False,
            }

        streams = [stream(0, "fre"), stream(1, "jpn"), stream(2, "eng")]
        shown, item = [], {"inputstream": "", "path": "/films/Heat.mkv"}
        player = Mock(
            setSubtitleStream=lambda i: shown.append(i),
            showSubtitles=lambda on: shown.append(on or None),
            getPlayingItem=lambda: Mock(
                getProperty=item.get, getPath=lambda: item["path"]
            ),
        )

        def press(current, selected):
            with patch.object(
                actions, "player_streams", lambda type: (streams, current, selected)
            ):
                actions.player_stream("subtitle", lang="eng|jpn")

        with (
            patch.object(actions.xbmc, "Player", lambda: player, create=True),
            patch.object(actions, "_iso639_2", lambda lang: lang),
            patch.object(actions, "window_property", lambda *a, **k: None),
        ):
            press(None, streams[0])  # off, French held: English selected
            press(streams[2], streams[2])  # English: Japanese
            press(streams[1], streams[1])  # Japanese: off
            # Off with English held: shown as it is, not selected again (M329)
            press(None, streams[2])
            # An inputstream add-on or PVR client may have stopped it: selected
            item["inputstream"] = "inputstream.adaptive"
            press(None, streams[2])
            item.update(inputstream="", path="pvr://channels/tv/All/1.pvr")
            press(None, streams[2])
        self.assertEqual(shown, [2, 1, None, True, 2, 2])


class TrailerUnderAModal(unittest.TestCase):
    """A play_trailer that lands under a modal is dropped and unstamps its item."""

    def request(self, modal: bool, window: str, stamp: str = "Heat") -> tuple:
        props, flights = {"trailer_played_item": stamp}, []
        with (
            patch.object(
                actions, "condition", lambda c: modal and c == actions._MODAL_OPEN
            ),
            patch.object(
                actions,
                "infolabel",
                lambda label: props.get(label[len("Window(home).Property(") : -1], ""),
            ),
            patch.object(
                actions, "window_property", lambda k, value="": props.update({k: value})
            ),
            patch.object(actions, "start_flight", flights.append),
        ):
            actions.play_trailer("t.mp4", item="Heat", window=window)
        return props.get("trailer_played_item"), props.get("trailer_state"), flights

    def test_modal_drops_the_request_and_clears_the_stamp(self):
        self.assertEqual(self.request(True, "videos"), ("", None, []))

    def test_another_items_stamp_stays(self):
        self.assertEqual(self.request(True, "videos", "Ronin"), ("Ronin", None, []))

    def test_the_info_dialog_and_no_modal_play(self):
        for modal, window in ((True, "infoscreen"), (False, "videos")):
            self.assertEqual(
                self.request(modal, window), ("Heat", "pending", ["t.mp4"])
            )


class ClashesFollowTheFeatures(unittest.TestCase):
    """A clashing add-on's feature turned on or off mid-session queues the check."""

    CHECK = call("RunScript(script.copacetic.helper,action=check_clashes)")

    def setUp(self):
        self.on = {"Skin.HasSetting(lyrics)"}
        self.service = object.__new__(monitor.Monitor)
        self.service.player_monitor, self.service.slideshow = Mock(), Mock()
        self.service.prune_due = float("inf")
        self.service.waitForAbort = Mock()
        for target, name, value in (
            (monitor.clashes, "condition", lambda text: text in self.on),
            (monitor.clashes, "apply", Mock(return_value=["script.cu.lrclyrics"])),
            (monitor, "release_refresh", Mock()),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(monitor.log, "execute")
        self.execute = patcher.start()
        self.addCleanup(patcher.stop)
        self.service._check_clashes()  # on entering the skin

    def test_unchanged_features_queue_nothing_more(self):
        self.service.poller()
        self.service.poller()
        self.assertEqual(self.execute.mock_calls, [self.CHECK])

    def test_a_feature_turned_on_or_off_queues_it_once(self):
        self.on.add("Skin.HasSetting(playnext_enabled)")
        self.service.poller()
        self.service.poller()
        self.on.clear()
        self.service.poller()
        self.assertEqual(self.execute.mock_calls, [self.CHECK] * 3)


if __name__ == "__main__":
    unittest.main()
