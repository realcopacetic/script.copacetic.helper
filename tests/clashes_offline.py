"""
Offline checks for add-ons that clash (resources/lib/service/clashes.py), Kodi's reads
stubbed: an add-on doing a feature's job is asked about once Home settles; Switch off
switches it off, Keep both leaves it, Not now, Back or a close without a click asks
again next time; an answer applies at each entry without asking, but one switched back
on elsewhere is kept; a feature turned off, a skin left or a reset gives it back; two
checks at once ask once; a switch Kodi refuses isn't recorded; the service queues the
check on entering a skin and gives add-ons back on leaving.
Run from the helper root: python tests/clashes_offline.py
"""

import sys
import tempfile
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
        self.dialog = Mock()
        self.dialog.return_value.yesnocustom.return_value = 1
        self.json = Mock(side_effect=self.set_enabled)
        for name, value in (
            ("condition", self.condition),
            ("infolabel", lambda label: label),
            ("json_call", self.json),
        ):
            patcher = patch.object(clashes, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(clashes.xbmcgui, "Dialog", self.dialog, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        clashes.ADDON.getLocalizedString = str

    def condition(self, text: str) -> bool:
        """Each `|` alternative true when listed, add-ons by self.enabled/installed."""
        if text.startswith("System.AddonIsEnabled("):
            return text[22:-1] in self.enabled
        if text.startswith("System.HasAddon("):
            return text[16:-1] in self.installed
        return any(part.strip() in self.true for part in text.split("|"))

    def set_enabled(self, method, params, parent):
        """Addons.SetAddonEnabled, applied to self.enabled unless refused."""
        if params["addonid"] in self.refused:
            return {"error": {"code": -32602, "message": "Invalid params."}}
        (self.enabled.add if params["enabled"] else self.enabled.discard)(
            params["addonid"]
        )
        return {"result": "OK"}

    def asked(self) -> list[str]:
        """The headings of the questions asked so far."""
        return [c.args[0] for c in self.dialog.return_value.yesnocustom.call_args_list]

    def test_switch_off_switches_it_off_and_remembers(self):
        clashes.check()
        self.assertEqual(self.asked(), [f"System.AddonTitle({LRC})"])
        self.assertNotIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": [LRC]})

    def test_question_names_the_addon_and_the_skin(self):
        clashes.check()
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
        clashes.check()
        clashes.check()
        self.assertEqual(len(self.asked()), 1)
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: False}, "off": []})

    def test_back_asks_again_next_time(self):
        self.dialog.return_value.yesnocustom.return_value = -1
        clashes.check()
        clashes.check()
        self.assertEqual(len(self.asked()), 2)
        self.assertIn(LRC, self.enabled)

    def test_not_now_or_a_close_without_a_click_asks_again_next_time(self):
        # GUIDialogYesNo::GetResult: no button pressed reads as DIALOG_RESULT_NO
        self.dialog.return_value.yesnocustom.return_value = 0
        clashes.check()
        clashes.check()
        self.assertEqual(len(self.asked()), 2)
        self.assertIn(LRC, self.enabled)
        self.assertFalse(clashes.STATE.exists())

    def test_an_answer_applies_at_each_entry_without_asking(self):
        clashes.check()
        clashes.restore()  # another skin gives it back
        clashes.check()
        self.assertEqual(len(self.asked()), 1)
        self.assertNotIn(LRC, self.enabled)
        self.assertEqual(clashes._load()["off"], [LRC])

    def test_switched_back_on_elsewhere_is_kept(self):
        clashes.check()
        self.enabled.add(LRC)  # the Add-ons browser, or Kodi for a dependency
        clashes.check()
        self.assertEqual(len(self.asked()), 1)
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: False}, "off": []})

    def test_nothing_to_ask_writes_nothing(self):
        self.enabled = set()
        clashes.check()
        self.assertFalse(clashes.STATE.exists())

    def test_feature_off_asks_nothing(self):
        self.true.discard(LYRICS)
        clashes.check()
        self.assertEqual(self.asked(), [])

    def test_feature_turned_off_gives_it_back(self):
        clashes.check()
        self.true.discard(LYRICS)
        clashes.check()
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": []})

    def test_one_of_two_features_is_enough(self):
        self.enabled = {TIDB}
        self.true |= {PLAYNEXT}
        clashes.check()
        self.assertEqual(self.asked(), [f"System.AddonTitle({TIDB})"])

    def test_each_addon_asked_in_turn(self):
        self.enabled = {LRC, UPNEXT}
        self.true |= {PLAYNEXT}
        self.dialog.return_value.yesnocustom.side_effect = [1, 2]
        clashes.check()
        self.assertEqual(self.enabled, {UPNEXT})
        self.assertEqual(
            clashes._load(), {"answers": {LRC: True, UPNEXT: False}, "off": [LRC]}
        )

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
        clashes.check()
        clashes.restore()
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": []})

    def test_restore_with_nothing_off_writes_nothing(self):
        clashes.restore()
        self.json.assert_not_called()
        self.assertFalse(clashes.STATE.exists())

    def test_reset_forgets_and_asks_again(self):
        clashes.check()
        clashes.restore(forget=True)
        self.assertIn(LRC, self.enabled)
        clashes.check()
        self.assertEqual(len(self.asked()), 2)

    def test_a_second_check_while_one_asks_asks_nothing(self):
        # Ask again pressed twice: both settle together
        self.dialog.return_value.yesnocustom.side_effect = lambda *args: (
            clashes.check() or 1
        )
        clashes.check()
        self.assertEqual(len(self.asked()), 1)
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": [LRC]})
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

        def settled():
            waits.append(None)
            if len(waits) == 1:  # another check starts while this one waits
                clashes.check()
            return True

        with patch.object(clashes, "_settled", settled):
            clashes.check()
        self.assertEqual(len(waits), 1)
        self.assertEqual(len(self.asked()), 1)
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": [LRC]})

    def test_the_answer_is_merged_into_the_state_as_it_is_after_the_question(self):
        clashes.check()  # CU LRC switched off
        self.enabled.add(UPNEXT)
        self.true.add(PLAYNEXT)
        # Ask again pressed under the question about Up Next: CU LRC back, forgotten
        self.dialog.return_value.yesnocustom.side_effect = lambda *args: (
            clashes.restore(forget=True) or 2
        )
        clashes.check()
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {UPNEXT: False}, "off": []})

    def test_no_answer_clicked_applies_nothing_after_the_question(self):
        # A same-frame read would see one just switched off as still on (cached)
        self.dialog.return_value.yesnocustom.return_value = 0
        with patch.object(clashes, "_apply", wraps=clashes._apply) as apply:
            clashes.check()
        self.assertEqual(apply.call_count, 2)  # before and after Home settles

    def test_a_switch_kodi_refuses_is_not_recorded(self):
        self.refused = {LRC}  # CanAddonBeDisabled false: InvalidParams
        clashes.check()
        self.assertIn(LRC, self.enabled)
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": []})

    def test_restore_keeps_one_kodi_refuses_listed(self):
        clashes.check()
        self.refused = {LRC}  # EnableAddon failed
        clashes.restore()
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": [LRC]})

    def test_one_uninstalled_while_off_is_dropped(self):
        clashes.check()
        self.installed.discard(LRC)
        clashes.check()
        self.json.assert_called_once()  # the switch-off only: no give-back tried
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": []})

    def test_restore_drops_one_uninstalled(self):
        clashes.check()
        self.installed.discard(LRC)
        clashes.restore()
        self.json.assert_called_once()
        self.assertEqual(clashes._load(), {"answers": {LRC: True}, "off": []})


class Service(unittest.TestCase):
    def setUp(self):
        self.service = monitor.Monitor()
        self.service._builder_elements = Mock()

    def test_entering_a_skin_queues_the_check(self):
        home = clashes.xbmcgui.Window(10000)
        home.setProperty(clashes.ASKING, "true")  # left by a check killed mid-run
        with (
            patch.object(monitor, "skin_uses_builder", lambda: True),
            patch.object(monitor, "PlayerMonitor", Mock()),
            patch.object(monitor.log, "execute") as execute,
        ):
            self.service._follow("skin", "1")
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
