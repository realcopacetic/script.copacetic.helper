# author: realcopacetic

import time
from typing import Any, Callable

from xbmcgui import Window

from resources.lib.apis.http import HttpError, get_json
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import ADDON

POPULARITY = "https://api.listenbrainz.org/1/popularity/"
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
    :return: 7 days when refused (bad MBID, token wanted), 429's wait, else 5 minutes.
    """
    if exc.status in (400, 401, 404):
        return TTL_INVALID
    if exc.status == 429:
        return exc.retry_after or 60
    return TTL_DOWN


def _cached(key: str, url: str, shape: Callable[[Any], Any], body: Any = None) -> Any:
    """
    The answer for key, fetched from url and shaped when stale, cached per answer
    kind; at most one request a second across plugin calls, else the stale answer.

    :param key: api_cache key.
    :param url: Endpoint URL.
    :param shape: Turns the decoded JSON into the cached payload.
    :param body: POST body; None for a GET.
    :return: The payload, None when unknown or not fetched.
    """
    cache = ApiCacheHandler()
    payload, fresh = cache.get(key) or (None, False)
    home, now = Window(10000), time.time()
    if fresh or now < float(home.getProperty(NEXT_CALL) or 0):
        return payload
    home.setProperty(NEXT_CALL, f"{now + 1}")
    try:
        payload = shape(get_json(url, body=body))
    except HttpError as exc:
        ttl = _failure_ttl(exc)
        if exc.status == 429:
            home.setProperty(NEXT_CALL, f"{now + ttl}")
        cache.put(key, payload, ttl)  # keeps a stale answer, else a negative one
        return payload
    cache.put(key, payload, TTL_HIT if payload else TTL_EMPTY)
    return payload


def top_recordings(mbid: str) -> list[list[str]]:
    """
    Artist mbid's recordings, most listened first.

    :param mbid: Artist MusicBrainz id.
    :return: [recording MBID, title] pairs, possibly empty.
    """
    return (
        _cached(
            f"listenbrainz:top:{mbid}",
            f"{POPULARITY}top-recordings-for-artist/{mbid}",
            lambda rows: [
                [row["recording_mbid"], row["recording_name"]] for row in rows
            ],
        )
        or []
    )


def top_release_groups(mbid: str) -> list[list[str]]:
    """
    Artist mbid's release groups (albums, singles, EPs), most listened first.

    :param mbid: Artist MusicBrainz id.
    :return: [release group MBID, title] pairs, possibly empty.
    """
    return (
        _cached(
            f"listenbrainz:albums:{mbid}",
            f"{POPULARITY}top-release-groups-for-artist/{mbid}",
            lambda rows: [
                [row["release_group_mbid"], row["release_group"]["name"]]
                for row in rows
            ],
        )
        or []
    )


def listeners(entity: str, mbid: str) -> int | None:
    """
    How many people have listened to an artist, release group or recording.

    :param entity: artist, release-group or recording.
    :param mbid: Its MusicBrainz id.
    :return: Listener count; None when ListenBrainz has none or wasn't asked.
    """
    return _cached(
        f"listenbrainz:listeners:{entity}:{mbid}",
        f"{POPULARITY}{entity}",
        lambda rows: rows[0]["total_user_count"],
        {f"{entity.replace('-', '_')}_mbids": [mbid]},
    )
