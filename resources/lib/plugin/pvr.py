# author: realcopacetic

import math
from datetime import datetime, timezone

from xbmc import getRegion

from resources.lib.plugin.helpers import hours_minutes
from resources.lib.shared.utilities import plugin_path

# PVR.GetBroadcasts fields a guide row reads (each row also has its label, the title
# as Kodi shows it). The timer and recording fields are looked up per tag by Kodi's
# JSON-RPC (FileItemHandler.cpp GetField); the activity ones run on the channel's
# playing time, a timeshift included.
BROADCAST_FIELDS = [
    "title",
    "thumbnail",
    "starttime",
    "endtime",
    "runtime",
    "isactive",
    "wasactive",
    "hastimer",
    "hastimerrule",
    "hasreminder",
    "hasrecording",
]


def local_time(utc: str, fmt: str) -> str:
    """
    A JSON-RPC broadcast time (UTC, GetAsDBDateTime) as a local clock time.

    :param utc: "YYYY-MM-DD HH:MM:SS" in UTC.
    :param fmt: strftime format.
    :return: The local time in that format.
    """
    stamp = datetime.fromisoformat(utc).replace(tzinfo=timezone.utc)
    return stamp.astimezone().strftime(fmt)


def time_left(broadcast: dict, now: datetime) -> str:
    """
    A programme's time left to its end by the clock, as the TV guide's: empty once
    it has ended, which a timeshifted channel's on-air one can be.

    :param broadcast: PVR.GetBroadcasts row with BROADCAST_FIELDS.
    :param now: The time now, in UTC.
    :return: "1h 23m", "1h", "48m" or "".
    """
    end = datetime.fromisoformat(broadcast["endtime"]).replace(tzinfo=timezone.utc)
    left = math.ceil((end - now).total_seconds() / 60)
    return hours_minutes(left) if left > 0 else ""


def broadcast_state(broadcast: dict) -> str:
    """
    The guide's state icon, first true wins as in its grid. A listed tag has no
    recording flag, so a recording timer on air stands in for one.

    :param broadcast: PVR.GetBroadcasts row with BROADCAST_FIELDS.
    :return: reminder, recording, timer, recorded or "".
    """
    if broadcast["hasreminder"]:
        return "reminder"
    if broadcast["hastimer"]:
        return "recording" if broadcast["isactive"] else "timer"
    return "recorded" if broadcast["hasrecording"] else ""


def broadcast_items(
    broadcasts: list[dict], channelid: int, logo: str, now: datetime
) -> list[dict]:
    """
    A channel's programmes from the one on air, as guide rows: Kodi's label (masked
    when parental locked, then no image), start and end in Kodi's time format.

    :param broadcasts: PVR.GetBroadcasts rows with BROADCAST_FIELDS, by start.
    :param channelid: The channel's id, echoed so the skin knows whose rows these are.
    :param logo: The channel's logo, each row's icon (the guide's fallback art).
    :param now: The time now, in UTC, for the time left.
    :return: Canonical item dicts for set_items.
    """
    fmt = getRegion("time").replace(":%S", "")
    return [
        {
            "file": plugin_path(f"broadcast/{broadcast['broadcastid']}"),
            "label": broadcast["label"],
            "art": {
                "icon": logo or "DefaultTVShows.png",
                "thumb": (
                    broadcast["thumbnail"]
                    if broadcast["label"] == broadcast["title"]
                    else ""
                ),
            },
            "properties": {
                "broadcastid": broadcast["broadcastid"],
                "channelid": channelid,
                "start": local_time(broadcast["starttime"], fmt),
                "end": local_time(broadcast["endtime"], fmt),
                "runtime": broadcast["runtime"],
                "on_air": "true" if broadcast["isactive"] else "",
                "time_left": time_left(broadcast, now) if broadcast["isactive"] else "",
                "state": broadcast_state(broadcast),
                "series": "true" if broadcast["hastimerrule"] else "",
                # not a favourite: its path is no item (ContextMenus.cpp:79-82)
                "hide_add_remove_favourite": "true",
            },
        }
        for broadcast in broadcasts
        if not broadcast["wasactive"]
    ]
