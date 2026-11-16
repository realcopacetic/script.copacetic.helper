"""
Offline checks for the live channel list's guide (plugin/pvr.py and the broadcasts
handler): programmes from the one on air on, start and end as local clock times,
time left from Kodi's progress, the state icon's order, and the handler's calls;
and the smart select on a later programme (script/actions.py pvr_smart_select).
Run from the helper root:
python tests/pvr_offline.py
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
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
os.environ["TZ"] = "Europe/London"
time.tzset()

from resources.lib.plugin import handlers, pvr  # noqa: E402
from resources.lib.script import actions  # noqa: E402


def row(n: int, start: str, end: str, **flags) -> dict:
    """A PVR.GetBroadcasts row with BROADCAST_FIELDS, every flag off unless given."""
    return {
        "broadcastid": n,
        "title": f"Programme {n}",
        "thumbnail": f"https://x/{n}.jpg",
        "starttime": start,
        "endtime": end,
        "runtime": 60,
        "progresspercentage": 0.0,
        "isactive": False,
        "wasactive": False,
        "hastimer": False,
        "hastimerrule": False,
        "hasreminder": False,
        "hasrecording": False,
    } | flags


# 16 Nov 2026 is GMT; 16 Jul 2026 is BST (UTC+1)
PAST = row(1, "2026-11-16 19:00:00", "2026-11-16 20:00:00", wasactive=True)
NOW = row(
    2,
    "2026-11-16 20:00:00",
    "2026-11-16 21:30:00",
    runtime=90,
    isactive=True,
    progresspercentage=57.5,
)
LATER = row(3, "2026-11-16 21:30:00", "2026-11-16 22:00:00", runtime=30)


class Items(unittest.TestCase):
    """broadcast_items: what each guide row carries."""

    def items(self, *rows: dict, logo: str = "image://logo.png/") -> list[dict]:
        return pvr.broadcast_items(list(rows), 7, logo)

    def test_from_the_one_on_air(self):
        self.assertEqual(
            [i["label"] for i in self.items(PAST, NOW, LATER)],
            ["Programme 2", "Programme 3"],
        )

    def test_times_local_without_seconds(self):
        props = self.items(NOW)[0]["properties"]
        self.assertEqual((props["start"], props["end"]), ("20:00", "21:30"))
        summer = row(4, "2026-07-16 20:00:00", "2026-07-16 21:00:00")
        props = self.items(summer)[0]["properties"]
        self.assertEqual((props["start"], props["end"]), ("21:00", "22:00"))

    def test_time_left_from_progress_on_air_only(self):
        now, later = (i["properties"] for i in self.items(NOW, LATER))
        # 90 minutes, 42.5 % left: 38.25, rounded up
        self.assertEqual((now["on_air"], now["time_left"]), ("true", "39m"))
        self.assertEqual((later["on_air"], later["time_left"]), ("", ""))
        long = row(5, "2026-11-16 20:00:00", "2026-11-16 23:00:00", isactive=True)
        self.assertEqual(self.items(long)[0]["properties"]["time_left"], "3h")

    def test_rows_name_their_channel_and_broadcast(self):
        now, later = self.items(NOW, LATER)
        self.assertEqual(now["properties"]["channelid"], 7)
        self.assertEqual(later["properties"]["runtime"], 30)
        self.assertNotEqual(now["file"], later["file"])

    def test_art_thumb_the_programme_icon_the_logo(self):
        self.assertEqual(
            self.items(NOW)[0]["art"],
            {"icon": "image://logo.png/", "thumb": "https://x/2.jpg"},
        )
        self.assertEqual(
            self.items(NOW, logo="")[0]["art"]["icon"], "DefaultTVShows.png"
        )

    def test_series_from_a_rule(self):
        ruled = row(6, LATER["starttime"], LATER["endtime"], hastimerrule=True)
        self.assertEqual(self.items(ruled)[0]["properties"]["series"], "true")
        self.assertEqual(self.items(LATER)[0]["properties"]["series"], "")


class State(unittest.TestCase):
    """broadcast_state: first true wins, as the guide grid's icon."""

    def test_order(self):
        cases = [
            ({}, ""),
            ({"hasrecording": True}, "recorded"),
            ({"hastimer": True}, "timer"),
            ({"hastimer": True, "isactive": True}, "recording"),
            ({"hastimer": True, "hasreminder": True, "isactive": True}, "reminder"),
            ({"hastimer": True, "hasrecording": True}, "timer"),
        ]
        for flags, state in cases:
            with self.subTest(flags=flags):
                self.assertEqual(pvr.broadcast_state(LATER | flags), state)


class Handler(unittest.TestCase):
    """PluginHandlers.broadcasts with json_call stubbed."""

    def serve(self, params: dict, broadcasts: list | None) -> tuple[list, list]:
        calls = []

        def json_call(method, properties=None, params=None, parent=None):
            calls.append((method, params))
            if method == "PVR.GetBroadcasts":
                return {"result": {"broadcasts": broadcasts}} if broadcasts else {}
            return {"result": {"channeldetails": {"thumbnail": "image://logo/"}}}

        with mock.patch.multiple(
            handlers, json_call=json_call, set_items=lambda items: items
        ):
            items = handlers.PluginHandlers(
                {"info": "broadcasts"} | params
            ).broadcasts()
        return items, calls

    def test_channel_id_as_int_both_calls(self):
        items, calls = self.serve({"channelid": "12"}, [NOW, LATER])
        self.assertEqual(
            calls,
            [
                ("PVR.GetBroadcasts", {"channelid": 12}),
                ("PVR.GetChannelDetails", {"channelid": 12}),
            ],
        )
        self.assertEqual(items[0]["art"]["icon"], "image://logo/")

    def test_limit(self):
        items, _ = self.serve({"channelid": "12", "limit": "1"}, [PAST, NOW, LATER])
        self.assertEqual([i["label"] for i in items], ["Programme 2"])

    def test_no_programmes_no_logo_call(self):
        items, calls = self.serve({"channelid": "12"}, None)
        self.assertIsNone(items)
        self.assertEqual([m for m, _ in calls], ["PVR.GetBroadcasts"])

    def test_no_channel_no_call(self):
        items, calls = self.serve({}, [NOW])
        self.assertIsNone(items)
        self.assertEqual(calls, [])


class SmartSelect(unittest.TestCase):
    """pvr_smart_select with JSON-RPC, the dialogs and builtins stubbed."""

    def select(
        self,
        choices: list[int],
        *,
        recordable: bool = True,
        result: str = "OK",
        **flags,
    ) -> dict:
        """
        Run the action on broadcast 9, answering each yes/no with the next choice.

        :param choices: yesnocustom answers in turn (-1 Back, 0 No, 1 Yes).
        :param recordable: Whether its client supports recordings and timers.
        :param result: What PVR.AddTimer and PVR.ToggleTimer answer.
        :param flags: Its timer fields (hastimer, hasreminder, hastimerrule).
        :return: dialogs (heading, message, no, yes), calls, builtins, ok, stamp.
        """
        seen = {"dialogs": [], "calls": [], "builtins": [], "ok": [], "stamp": None}
        details = {
            "title": "News",
            "clientid": 3,
            "hastimer": False,
            "hasreminder": False,
            "hastimerrule": False,
        } | flags
        answers = iter(choices)

        def json_call(method, properties=None, params=None, parent=None):
            if method == "PVR.GetBroadcastDetails":
                # Kodi's timers catch up on the second read after a change
                hastimer = details["hastimer"] ^ (
                    sum(m == "PVR.GetBroadcastDetails" for m, _ in seen["calls"]) > 1
                )
                seen["calls"].append((method, params))
                return {
                    "result": {"broadcastdetails": details | {"hastimer": hastimer}}
                }
            seen["calls"].append((method, params))
            if method == "PVR.GetClients":
                client = {"supportsrecordings": recordable, "supportstimers": True}
                return {
                    "result": {"clients": [{"clientid": 2}, {"clientid": 3} | client]}
                }
            return {"result": result}

        def yesnocustom(heading, message, custom, no, yes):
            seen["dialogs"].append((heading, message, no, yes))
            return next(answers)

        dialog = mock.Mock(yesnocustom=yesnocustom, ok=lambda *a: seen["ok"].append(a))
        with mock.patch.multiple(
            actions,
            json_call=json_call,
            window_property=lambda key, value, window_id: seen.update(
                stamp=(key, window_id)
            ),
        ), mock.patch.object(
            actions.xbmcgui, "Dialog", lambda: dialog
        ), mock.patch.object(
            actions.xbmc, "getLocalizedString", str, create=True
        ), mock.patch.object(
            actions.xbmc,
            "Monitor",
            lambda: mock.Mock(waitForAbort=lambda s: False),
            create=True,
        ), mock.patch.object(
            actions.log, "execute", seen["builtins"].append
        ):
            actions.pvr_smart_select(
                "9",
                switch="SetFocus(11)|Action(Select,pvrosdchannels)",
                stamp="pvrosd_guide_timers",
                window_id="10608",
            )
        return seen

    def methods(self, seen: dict) -> list:
        return [m for m, _ in seen["calls"]]

    def test_record_or_switch_as_kodi(self):
        seen = self.select([0])
        self.assertEqual(seen["dialogs"], [("19096", "19302", "264", "19165")])
        self.assertIn(
            ("PVR.AddTimer", {"broadcastid": 9, "reminder": False}), seen["calls"]
        )
        self.assertEqual(seen["stamp"], ("pvrosd_guide_timers", 10608))

    def test_reminder_where_the_channel_cant_record(self):
        seen = self.select([0], recordable=False)
        self.assertEqual(seen["dialogs"], [("19096", "19344", "826", "19165")])
        self.assertIn(
            ("PVR.AddTimer", {"broadcastid": 9, "reminder": True}), seen["calls"]
        )

    def test_switch_runs_the_skins_builtins(self):
        seen = self.select([1])
        self.assertEqual(
            seen["builtins"], ["SetFocus(11)", "Action(Select,pvrosdchannels)"]
        )
        self.assertNotIn("PVR.AddTimer", self.methods(seen))
        self.assertIsNone(seen["stamp"])

    def test_back_does_nothing(self):
        seen = self.select([-1])
        self.assertEqual(
            self.methods(seen), ["PVR.GetBroadcastDetails", "PVR.GetClients"]
        )
        self.assertEqual(seen["builtins"], [])

    def test_a_timer_offers_delete_never_a_second(self):
        seen = self.select([0], hastimer=True)
        self.assertEqual(seen["dialogs"], [("19096", "19034", "19060", "19165")])
        self.assertNotIn("PVR.AddTimer", self.methods(seen))
        self.assertIn(
            ("PVR.ToggleTimer", {"broadcastid": 9, "timerrule": False}), seen["calls"]
        )
        self.assertEqual(seen["stamp"], ("pvrosd_guide_timers", 10608))

    def test_a_reminder_offers_delete_reminder(self):
        seen = self.select([-1], hastimer=True, hasreminder=True)
        self.assertEqual(seen["dialogs"][0][2], "827")

    def test_a_rules_timer_asks_only_this_or_all(self):
        seen = self.select([0, 1], hastimer=True, hastimerrule=True)
        self.assertEqual(seen["dialogs"][1], ("122", "840\n\nNews", "841", "593"))
        self.assertIn(
            ("PVR.ToggleTimer", {"broadcastid": 9, "timerrule": True}), seen["calls"]
        )
        seen = self.select([0, -1], hastimer=True, hastimerrule=True)
        self.assertNotIn("PVR.ToggleTimer", self.methods(seen))

    def test_a_failed_delete_says_so_and_stamps_nothing(self):
        seen = self.select([0], hastimer=True, result="")
        self.assertEqual(seen["ok"], [("257", "19110")])
        self.assertIsNone(seen["stamp"])

    def test_waits_for_kodis_timers_before_the_stamp(self):
        seen = self.select([0])
        reads = self.methods(seen).count("PVR.GetBroadcastDetails")
        self.assertEqual(reads, 3)  # the first, then until hastimer flips


if __name__ == "__main__":
    unittest.main()
