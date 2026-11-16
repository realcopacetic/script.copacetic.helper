"""
Offline checks for the live channel list's guide (plugin/pvr.py and the broadcasts
handler): programmes from the one on air on, start and end as local clock times,
time left from Kodi's progress, the state icon's order, and the handler's calls.
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


if __name__ == "__main__":
    unittest.main()
