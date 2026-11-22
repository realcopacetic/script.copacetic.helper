# author: realcopacetic

import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable

from xbmc import Monitor
from xbmcgui import Window

from resources.lib.apis.http import HttpError
from resources.lib.shared import logger as log
from resources.lib.shared.sqlite import ApiCacheHandler

MAX_WAIT = 3  # seconds a queued call waits for its slot before giving up
DAY = 86400
TTL_INVALID, TTL_DOWN = 7 * DAY, 300
# TheIntroDB's 429 for one film or episode: its wait holds that key, not the queue
ONE_MEDIA = "specific_media_usage_limit_exceeded"
# cache_only holds it: answers come from the cache alone. Per thread, as a new one
# starts with the default: one thread's hold leaves the service's others online
_offline = ContextVar("cache_only", default=False)


@contextmanager
def cache_only() -> Iterator[None]:
    """
    While held, cached answers whatever their age and fetches nothing: for a plugin
    call (its own interpreter) that must not wait on the network.
    """
    token = _offline.set(True)
    try:
        yield
    finally:
        _offline.reset(token)


# A failed request, or an answer of another shape than the fetch expects
FAILURES = (HttpError, LookupError, TypeError, AttributeError, ValueError)


def failure_ttl(exc: HttpError, invalid: int = TTL_INVALID) -> int:
    """
    Seconds before asking again after a failed request.

    :param exc: The failure.
    :param invalid: Seconds a bad or unknown id (400, 404) waits.
    :return: invalid for a bad id, 429's wait, else (token refused too) 5 minutes.
    """
    if exc.status in (400, 404):
        return invalid
    if exc.status == 429:
        return exc.retry_after or 60
    return TTL_DOWN


def cached(
    key: str, fetch: Callable[[], Any], ttl: tuple[int, int], queue: str = ""
) -> Any:
    """
    The answer for key, fetched when stale (never under cache_only) and cached per
    answer kind; a failure, or an answer of another shape, keeps a stale answer, or
    a different one a racing call stored. With a queue, one request a second.

    :param key: api_cache key, "<source>:<kind>:<id>".
    :param fetch: Returns the shaped payload; raises HttpError.
    :param ttl: Seconds an answer stays fresh: (answer, empty answer).
    :param queue: Home property holding the epoch of the next free slot; "" for none.
    :return: The payload, None when unknown or not fetched.
    """
    cache = ApiCacheHandler()
    payload, fresh = cache.get(key) or (None, False)
    if fresh or _offline.get():
        return payload
    source = key.partition(":")[0]
    if queue:
        home, now = Window(10000), time.time()
        slot = max(now, float(home.getProperty(queue) or 0))
        if slot - now > MAX_WAIT:
            log.debug(f"{source} → busy for {slot - now:.0f}s, skipped {key}")
            return payload
        home.setProperty(queue, f"{slot + 1}")
        if slot > now:
            log.debug(f"{source} → queued {slot - now:.1f}s {key}")
            if Monitor().waitForAbort(slot - now):
                return payload
            payload, fresh = cache.get(key) or (payload, False)
            if fresh:  # another plugin call fetched it while this one waited
                return payload
    try:
        payload = fetch()
    except FAILURES as exc:
        if not isinstance(exc, HttpError):  # an answer of another shape
            log.warning(f"{source} → unexpected answer for {key}: {exc!r}")
            exc = HttpError(None)
        if exc.status == 401:  # the one failure the user can fix
            log.warning(f"{source} → refused the token (401)")
        wait = failure_ttl(exc)
        if exc.status == 429 and queue and exc.code != ONE_MEDIA:
            home.setProperty(queue, f"{slot + wait}")
        # A racing call's fresh answer stands; its failure row holds the same stale
        # read as this call's payload, so that one is simply stored again
        if (row := cache.get(key)) and row[1] and row[0] != payload:
            return row[0]
        cache.put(key, payload, wait)  # keeps a stale answer, else a negative one
        return payload
    cache.put(key, payload, ttl[0] if payload else ttl[1])
    return payload
