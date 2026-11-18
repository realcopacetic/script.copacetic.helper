"""
Offline checks for add-ons that clash (resources/lib/service/clashes.py), Kodi's reads
stubbed: an add-on doing a feature's job is asked about once Home settles; Switch off
switches it off, Keep both leaves it, Not now, Back or a close without a click asks
again next time; an answer applies at each entry without asking, but one switched back
on elsewhere is kept, unless an update did it; a feature turned off, a skin left or a
reset gives it back, at once while a check waits; questions stop when the skin is
left; two checks at once ask once and only the service writes; a switch Kodi refuses
isn't recorded; the service queues the check on entering a skin and gives add-ons back
on leaving.
Run from the helper root: python tests/clashes_offline.py
"""

import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from threading import Thread
from unittest.mock import Mock, call, patch

from build_offline import HELPER, _module, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
sys.modules["xbmc"].Monitor = type(
    "Monitor",
    (),
    {"abortRequested": lambda self: True, "waitForAbort": lambda self, secs: False},
)
sys.modules["xbmc"].getSkinDir = lambda: "skin.test"
_module("resources.lib.art.slideshow", Slideshow=Mock)
_module("resources.lib.service.player", PlayerMonitor=Mock)
sys.path.insert(0, str(HELPER))

from resources.lib.service import clashes, monitor  # noqa: E402

LRC, UPNEXT, TIDB = clashes.CLASHES
LYRICS, PLAYNEXT, SKIP = (
    "Skin.HasSetting(lyrics)",
    "Skin.HasSetting(playnext_enabled)",
    "Skin.HasSetting(skip_segments)",
)


class Clashes(unittest.TestCase):
    def setUp(self):
        clashes.STATE.unlink(missing_ok=True)
        # What reads true: the skin active and settled, CU LRC on, the lyrics feature on
        self.true = {clashes.ACTIVE, clashes.SETTLED, LYRICS}
        self.enabled, self.refused, self.installed = {LRC}, set(), set(clashes.CLASHES)
        self.versions = dict.fromkeys(clashes.CLASHES, "1.0")
        self.cached = None  # what System.AddonIsEnabled holds this frame: as enabled
        self.dialog = Mock()
        self.dialog.return_value.yesnocustom.return_value = 1
        self.json = Mock(side_effect=self.json_rpc)
        for target, name, value in (
            (clashes, "condition", self.condition),
            (clashes, "infolabel", self.infolabel),
            (clashes, "json_call", self.json),
            (clashes.xbmcgui, "Dialog", self.dialog),
            # RunScript, run at once
            (monitor.log, "execute", lambda builtin: clashes.check()),
        ):
            patcher = patch.object(target, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        clashes.ADDON.getLocalizedString = str
        self.service = object.__new__(monitor.Monitor)
        self.service.player_monitor = Mock()  # the skin active
        self.service.slideshow, self.service.waitForAbort = Mock(), Mock()
        self.service.prune_due = float("inf")
        patcher = patch.object(monitor, "release_refresh", Mock())
        patcher.start()
        self.addCleanup(patcher.stop)

    def condition(self, text: str) -> bool:
        """Each `|` alternative true when listed, add-ons by self.enabled/installed."""
        if text.startswith("System.AddonIsEnabled("):
            return text[22:-1] in (self.enabled if self.cached is None else self.cached)
        if text.startswith("System.HasAddon("):
            return text[16:-1] in self.installed
        return any(part.strip() in self.true for part in text.split("|"))

    def infolabel(self, label: str) -> str:
        """System.AddonVersion from self.versions, "" while off; others as written."""
        if label.startswith("System.AddonVersion("):
            addon_id = label[20:-1]
            return self.versions[addon_id] if addon_id in self.enabled else ""
        return label

    def json_rpc(self, method, params, parent):
        """
        JSONRPC.NotifyAll, handed to the service; Addons.SetAddonEnabled, applied to
        self.enabled unless refused.
        """
        if method == "JSONRPC.NotifyAll":
            self.service.onNotification(
                params["sender"],
                f"Other.{params['message']}",
                json.dumps(params["data"]),
            )
        elif params["addonid"] in self.refused:
            return {"error": {"code": -32602, "message": "Invalid params."}}
        else:
            (self.enabled.add if params["enabled"] else self.enabled.discard)(
                params["addonid"]
            )
        return {"result": "OK"}

    def enter(self):
        """The service's check: on entering the skin, or on a feature change."""
        self.service._check_clashes()

    def poll(self):
        """One pass of the service's poll loop."""
        self.service.poller()

    def switches(self) -> list[dict]:
        """The Addons.SetAddonEnabled params sent so far."""
        return [
            c.kwargs["params"]
            for c in self.json.call_args_list
            if c.args[0] == "Addons.SetAddonEnabled"
        ]

    def asked(self) -> list[str]:
        """The headings of the questions asked so far."""
        return [c.args[0] for c in self.dialog.return_value.yesnocustom.call_args_list]

    def test_switch_off_switches_it_off_and_remembers(self):
        self.enter()
        self.assertEqual(self.asked(), [f"System.AddonTitle({LRC})"])
        self.assertNotIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": {LRC: "1.0"}})

    def test_on_or_off_is_read_fresh_not_from_the_frames_cache(self):
        # InfoBool::Get holds a condition's value until the frame's refresh counter
        # moves; the version label is read fresh
        self.cached = set()
        self.enter()
        self.assertEqual(self.asked(), [f"System.AddonTitle({LRC})"])
        self.assertNotIn(LRC, self.enabled)

    def test_question_names_the_addon_and_the_skin(self):
        self.enter()
        message = self.dialog.return_value.yesnocustom.call_args.args[1]
        self.assertEqual(
            message,
            "32236"
            % {
                "addon": f"System.AddonTitle({LRC})",
                "skin": "System.AddonTitle(skin.test)",
            },
        )
        self.assertEqual(
            self.dialog.return_value.yesnocustom.call_args.args[2:],
            ("32235", "32239", "32234"),  # custom Keep both, no Not now, yes
        )

    def test_keep_both_leaves_it_and_never_asks_again(self):
        self.dialog.return_value.yesnocustom.return_value = 2
        self.enter()
        self.enter()
        self.assertEqual(len(self.asked()), 1)
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: False}, "off": {}})

    def test_back_asks_again_next_time(self):
        self.dialog.return_value.yesnocustom.return_value = -1
        self.enter()
        self.enter()
        self.assertEqual(len(self.asked()), 2)
        self.assertIn(LRC, self.enabled)

    def test_not_now_or_a_close_without_a_click_asks_again_next_time(self):
        # GUIDialogYesNo::GetResult: no button pressed reads as DIALOG_RESULT_NO
        self.dialog.return_value.yesnocustom.return_value = 0
        self.enter()
        self.enter()
        self.assertEqual(len(self.asked()), 2)
        self.assertIn(LRC, self.enabled)
        self.assertFalse(clashes.STATE.exists())

    def test_an_answer_applies_at_each_entry_without_asking(self):
        self.enter()
        clashes.restore()  # another skin gives it back
        self.enter()
        self.assertEqual(len(self.asked()), 1)
        self.assertNotIn(LRC, self.enabled)
        self.assertEqual(clashes._load()["off"], {LRC: "1.0"})

    def test_switched_back_on_elsewhere_is_kept(self):
        self.enter()
        self.enabled.add(LRC)  # the Add-ons browser, or Kodi for a dependency
        self.enter()
        self.assertEqual(len(self.asked()), 1)
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: False}, "off": {}})

    def test_an_update_switching_it_back_on_is_switched_off_again(self):
        self.enter()
        # A manual update or a reinstall: LoadAddon enables a disabled add-on
        self.enabled.add(LRC)
        self.versions[LRC] = "1.1"
        self.enter()
        self.assertEqual(len(self.asked()), 1)
        self.assertNotIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": {LRC: "1.1"}})

    def test_switched_on_by_hand_is_kept_within_a_poll_before_an_update(self):
        self.enter()
        self.poll()
        self.enabled.add(LRC)  # by hand
        self.poll()
        self.versions[LRC] = "1.1"  # then an automatic update: enabled add-ons update
        self.enter()
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: False}, "off": {}})

    def test_an_update_switching_it_back_on_is_caught_within_a_poll(self):
        self.enter()
        self.enabled.add(LRC)
        self.versions[LRC] = "1.1"
        self.poll()
        self.assertNotIn(LRC, self.enabled)

    def test_its_own_switches_and_answers_ask_nothing_more(self):
        self.enabled = {LRC, UPNEXT}
        self.true |= {PLAYNEXT}
        self.dialog.return_value.yesnocustom.side_effect = [1, 0]  # Up Next: Not now
        self.enter()
        self.poll()
        self.assertEqual(len(self.asked()), 2)

    def test_a_list_written_before_versions_were_kept_still_loads(self):
        clashes.JSONHandler(clashes.STATE).write_json(
            {"answers": {LRC: True}, "off": [LRC]}
        )
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": {LRC: None}})
        self.enabled = set()  # off when this lands
        self.enter()
        self.enabled.add(LRC)  # then switched on by hand: its version unknown
        self.enter()
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: False}, "off": {}})

    def test_nothing_to_ask_writes_nothing(self):
        self.enabled = set()
        self.enter()
        self.assertFalse(clashes.STATE.exists())

    def test_feature_off_asks_nothing(self):
        self.true.discard(LYRICS)
        self.enter()
        self.assertEqual(self.asked(), [])

    def test_feature_turned_off_gives_it_back(self):
        self.enter()
        self.true.discard(LYRICS)
        self.enter()
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": {}})

    def test_one_of_two_features_is_enough(self):
        self.enabled = {TIDB}
        self.true |= {PLAYNEXT}
        self.enter()
        self.assertEqual(self.asked(), [f"System.AddonTitle({TIDB})"])

    def test_each_addon_asked_in_turn(self):
        self.enabled = {LRC, UPNEXT}
        self.true |= {PLAYNEXT}
        self.dialog.return_value.yesnocustom.side_effect = [1, 2]
        self.enter()
        self.assertEqual(self.enabled, {UPNEXT})
        self.assertEqual(
            clashes._load(),
            {"answers": {LRC: True, UPNEXT: False}, "off": {LRC: "1.0"}},
        )

    def test_questions_stop_when_the_skin_is_left_or_the_guard_changes_hands(self):
        home = clashes.xbmcgui.Window(10000)
        self.addCleanup(home.clearProperty, clashes.ASKING)
        for change in (
            lambda: self.true.discard(clashes.ACTIVE),
            lambda: home.setProperty(clashes.ASKING, "new"),  # a helper restart
        ):
            with self.subTest(change=change):
                self.enabled, self.true = {LRC, UPNEXT}, self.true | {PLAYNEXT}
                self.dialog.return_value.yesnocustom.reset_mock()
                self.dialog.return_value.yesnocustom.side_effect = lambda *args: (
                    change() or 0
                )
                clashes.check()
                self.assertEqual(self.asked(), [f"System.AddonTitle({LRC})"])
                self.true.add(clashes.ACTIVE)
                home.clearProperty(clashes.ASKING)

    def test_outside_a_helper_skin_nothing_runs(self):
        self.true.discard(clashes.ACTIVE)
        clashes.check()
        self.assertEqual(self.asked(), [])
        self.assertFalse(clashes.STATE.exists())

    def test_skin_left_before_home_settles_asks_nothing(self):
        self.true.discard(clashes.SETTLED)
        with patch.object(clashes.xbmc, "Monitor") as kodi:
            kodi.return_value.waitForAbort.side_effect = [False, True]
            clashes.check()
        self.assertEqual(self.asked(), [])

    def test_restore_gives_back_and_keeps_answers(self):
        self.enter()
        clashes.restore()
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": {}})

    def test_restore_with_nothing_off_writes_nothing(self):
        clashes.restore()
        self.json.assert_not_called()
        self.assertFalse(clashes.STATE.exists())

    def test_reset_forgets_and_asks_again(self):
        self.enter()
        clashes.restore(forget=True)
        self.assertIn(LRC, self.enabled)
        self.enter()
        self.assertEqual(len(self.asked()), 2)

    def test_a_second_check_while_one_asks_asks_nothing(self):
        # Ask again pressed twice: both settle together
        self.dialog.return_value.yesnocustom.side_effect = lambda *args: (
            clashes.check() or 1
        )
        clashes.check()
        self.assertEqual(len(self.asked()), 1)
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": {LRC: "1.0"}})
        self.assertEqual(clashes.xbmcgui.Window(10000).getProperty(clashes.ASKING), "")

    def test_a_check_queued_under_the_question_asks_nothing_after_not_now(self):
        # B starts under A's dialog (Home covered), so it would still be waiting for
        # Home when A's Not now (0) lets Home settle again
        waiting = []

        def dialog(*args):
            if not waiting:
                self.true.discard(clashes.SETTLED)
                waiting.append(Thread(target=clashes.check))
                waiting[0].start()
                waiting[0].join(0.2)
                self.true.add(clashes.SETTLED)
            return 0

        self.dialog.return_value.yesnocustom.side_effect = dialog
        clashes.check()
        waiting[0].join(5)
        self.assertEqual(len(self.asked()), 1)

    def test_a_check_started_while_another_waits_for_home_leaves_it_to_that_one(self):
        waits = []

        def settled(token):
            waits.append(None)
            if len(waits) == 1:  # another check starts while this one waits
                clashes.check()
            return True

        with patch.object(clashes, "_settled", settled):
            clashes.check()
        self.assertEqual(len(waits), 1)
        self.assertEqual(len(self.asked()), 1)
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": {LRC: "1.0"}})

    def test_a_check_outlived_by_a_helper_restart_stops_and_leaves_the_new_guard(self):
        home = clashes.xbmcgui.Window(10000)
        self.addCleanup(home.clearProperty, clashes.ASKING)

        def restart(secs):
            # Within one wait: the service clears the guard, the new check sets its own
            home.setProperty(clashes.ASKING, "new")
            return False

        with patch.object(clashes.xbmc, "Monitor") as kodi:
            kodi.return_value.waitForAbort.side_effect = restart
            clashes.check()
        self.assertEqual(self.asked(), [])
        self.assertEqual(home.getProperty(clashes.ASKING), "new")

    def test_the_answer_is_merged_into_the_state_as_it_is_after_the_question(self):
        self.enter()  # CU LRC switched off
        self.enabled.add(UPNEXT)
        self.true.add(PLAYNEXT)
        # Ask again pressed under the question about Up Next: CU LRC back, forgotten
        self.dialog.return_value.yesnocustom.side_effect = lambda *args: (
            clashes.restore(forget=True) or 2
        )
        self.enter()
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {UPNEXT: False}, "off": {}})

    def test_two_checks_at_once_and_a_feature_off_and_on_keep_switch_off(self):
        self.enter()  # CU LRC switched off
        self.enabled.add(UPNEXT)
        self.true |= {PLAYNEXT}
        self.true.discard(clashes.SETTLED)
        self.dialog.return_value.yesnocustom.return_value = 2
        waiting = Thread(target=clashes.check)  # waits for Home to ask about Up Next
        waiting.start()
        self.addCleanup(waiting.join, 5)
        self.addCleanup(self.true.add, clashes.SETTLED)
        while not clashes.xbmcgui.Window(10000).getProperty(clashes.ASKING):
            time.sleep(0.01)
        # Lyrics off then on while it waits: each queues a second check
        self.true.discard(LYRICS)
        self.enter()
        self.assertIn(LRC, self.enabled)  # given back at once
        self.true.add(LYRICS)
        self.enter()
        self.assertNotIn(LRC, self.enabled)
        self.true.add(clashes.SETTLED)
        waiting.join(5)
        self.assertEqual(len(self.asked()), 2)
        self.assertEqual(
            clashes._load(),
            {"answers": {LRC: True, UPNEXT: False}, "off": {LRC: "1.0"}},
        )

    def test_a_check_only_asks_the_service_writes(self):
        self.enter()
        clashes.restore()  # another skin gives it back
        self.json.reset_mock()
        clashes.check()  # nothing to ask
        self.json.assert_not_called()
        self.assertIn(LRC, self.enabled)

    def test_a_reset_is_handed_to_the_service(self):
        self.enter()
        self.service.clash_features = clashes.features()
        clashes.notify(clashes.RESET)
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {}, "off": {}})
        self.assertEqual(self.service.clash_features, ())  # checked again next pass

    def test_an_answer_after_the_skin_is_left_is_not_applied(self):
        def leave(*args):
            self.service.player_monitor = None
            return 1

        self.dialog.return_value.yesnocustom.side_effect = leave
        self.enter()
        self.assertIn(LRC, self.enabled)
        self.assertFalse(clashes.STATE.exists())  # asked again on return

    def test_no_answer_clicked_hands_the_service_nothing(self):
        self.dialog.return_value.yesnocustom.return_value = 0
        self.enter()
        self.assertNotIn("JSONRPC.NotifyAll", [c.args[0] for c in self.json.mock_calls])

    def test_a_switch_kodi_refuses_is_not_recorded(self):
        self.refused = {LRC}  # CanAddonBeDisabled false: InvalidParams
        self.enter()
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": {}})

    def test_restore_keeps_one_kodi_refuses_listed(self):
        self.enter()
        self.refused = {LRC}  # EnableAddon failed
        clashes.restore()
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": {LRC: "1.0"}})

    def test_one_uninstalled_while_off_is_dropped(self):
        self.enter()
        self.installed.discard(LRC)
        self.enter()
        self.assertEqual(len(self.switches()), 1)  # the switch-off: no give-back tried
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": {}})

    def test_restore_drops_one_uninstalled(self):
        self.enter()
        self.installed.discard(LRC)
        clashes.restore()
        self.assertEqual(len(self.switches()), 1)
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": {}})


class Service(unittest.TestCase):
    def setUp(self):
        self.service = monitor.Monitor()
        self.service._builder_elements = Mock()

    def test_entering_a_skin_applies_and_queues_the_question(self):
        home = clashes.xbmcgui.Window(10000)
        home.setProperty(clashes.ASKING, "true")  # left by a check killed mid-run
        with (
            patch.object(monitor, "skin_uses_builder", lambda: True),
            patch.object(monitor, "PlayerMonitor", Mock()),
            patch.object(monitor.clashes, "apply", return_value=[LRC]) as apply,
            patch.object(monitor.log, "execute") as execute,
        ):
            self.service._follow("skin", "1")
        apply.assert_called_once_with(None)
        execute.assert_called_once_with(
            "RunScript(script.copacetic.helper,action=check_clashes)"
        )
        self.assertEqual(home.getProperty(clashes.ASKING), "")

    def test_any_skin_not_opting_in_gets_addons_back(self):
        with (
            patch.object(monitor, "skin_uses_builder", lambda: False),
            patch.object(monitor.clashes, "restore") as restore,
        ):
            self.service._follow("estuary", "1")
            self.service._follow("estuary", "")  # unregistered: installing
        self.assertEqual(restore.mock_calls, [call()])


if __name__ == "__main__":
    unittest.main()
