# author: realcopacetic

import math
from datetime import datetime, timezone

from xbmc import getRegion

from resources.lib.plugin.helpers import hours_minutes
from resources.lib.shared.utilities import plugin_path

# PVR.GetBroadcasts fields a guide row reads. The timer and recording fields are
# looked up per tag by Kodi's JSON-RPC (FileItemHandler.cpp GetField); the
# activity ones run on the channel's playing time, a timeshift included.
BROADCAST_FIELDS = [
    "title",
    "thumbnail",
    "starttime",
    "endtime",
    "runtime",
    "progresspercentage",
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


def time_left(broadcast: dict) -> str:
    """
    An on-air programme's time left, from Kodi's progress on the playing time.

    :param broadcast: PVR.GetBroadcasts row with BROADCAST_FIELDS.
    :return: "1h 23m", "1h" or "48m".
    """
    start, end = map(
        datetime.fromisoformat, (broadcast["starttime"], broadcast["endtime"])
    )
    left = (end - start).total_seconds() * (100 - broadcast["progresspercentage"])
    return hours_minutes(math.ceil(left / 6000))


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


def broadcast_items(broadcasts: list[dict], channelid: int, logo: str) -> list[dict]:
    """
    A channel's programmes from the one on air, as guide rows: start and end in
    Kodi's time format (seconds dropped, as ListItem.StartTime), time left on air.

    :param broadcasts: PVR.GetBroadcasts rows with BROADCAST_FIELDS, by start.
    :param channelid: The channel's id, echoed so the skin knows whose rows these are.
    :param logo: The channel's logo, each row's icon (the guide's fallback art).
    :return: Canonical item dicts for set_items.
    """
    fmt = getRegion("time").replace(":%S", "")
    return [
        {
            "file": plugin_path(f"broadcast/{broadcast['broadcastid']}"),
            "label": broadcast["title"],
            "art": {
                "icon": logo or "DefaultTVShows.png",
                "thumb": broadcast["thumbnail"],
            },
            "properties": {
                "channelid": channelid,
                "start": local_time(broadcast["starttime"], fmt),
                "end": local_time(broadcast["endtime"], fmt),
                "runtime": broadcast["runtime"],
                "on_air": "true" if broadcast["isactive"] else "",
                "time_left": time_left(broadcast) if broadcast["isactive"] else "",
                "state": broadcast_state(broadcast),
                "series": "true" if broadcast["hastimerrule"] else "",
            },
        }
        for broadcast in broadcasts
        if not broadcast["wasactive"]
    ]
