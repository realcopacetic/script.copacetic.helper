# author: realcopacetic

import time

from xbmcgui import Window

from resources.lib.apis.http import HttpError, get_json
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import ADDON

TOP_RECORDINGS = "https://api.listenbrainz.org/1/popularity/top-recordings-for-artist/"
NEXT_CALL = "copacetic.listenbrainz_next"  # home property: epoch before which none
DAY = 86400
TTL_HIT, TTL_EMPTY, TTL_INVALID, TTL_DOWN = 14 * DAY, 3 * DAY, 7 * DAY, 300


def enabled() -> bool:
    """True when the user allowed ListenBrainz access (off by default)."""
    return ADDON.getSettingBool("listenbrainz_access")


def _failure_ttl(exc: HttpError) -> int:
    """
    Seconds before asking again after a failed request.

    :param exc: The failure.
    :return: 7 days for a rejected MBID, the server's wait for 429, else 5 minutes.
    """
    if exc.status in (400, 404):
        return TTL_INVALID
    if exc.status == 429:
        return exc.retry_after or 60
    return TTL_DOWN


def top_recordings(mbid: str) -> list[list[str]]:
    """
    Artist mbid's recordings, most listened first, cached per answer kind; at most
    one request a second across plugin calls, else the stale answer or nothing.

    :param mbid: Artist MusicBrainz id.
    :return: [recording MBID, title] pairs, possibly empty.
    """
    cache, key = ApiCacheHandler(), f"listenbrainz:top:{mbid}"
    payload, fresh = cache.get(key) or (None, False)
    home, now = Window(10000), time.time()
    if fresh or now < float(home.getProperty(NEXT_CALL) or 0):
        return payload or []
    home.setProperty(NEXT_CALL, f"{now + 1}")
    try:
        rows = get_json(TOP_RECORDINGS + mbid)
    except HttpError as exc:
        ttl = _failure_ttl(exc)
        if exc.status == 429:
            home.setProperty(NEXT_CALL, f"{now + ttl}")
        cache.put(key, payload, ttl)  # keeps a stale answer, else a negative one
        return payload or []
    payload = [[row["recording_mbid"], row["recording_name"]] for row in rows]
    cache.put(key, payload, TTL_HIT if payload else TTL_EMPTY)
    return payload
