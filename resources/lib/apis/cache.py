# author: realcopacetic

import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

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
_recorders: list[set[str]] = []  # open record_misses sets


@contextmanager
def record_misses() -> Iterator[set[str]]:
    """
    Collects, while open, the keys cached() answers without a fetch of its own: a
    failure, a busy queue or an abort (any thread's, which only errs towards a miss).

    :return: The set of keys, filled as they come.
    """
    misses = set()
    _recorders.append(misses)
    try:
        yield misses
    finally:
        _recorders.remove(misses)


def _missed(key: str) -> None:
    """
    Notes key in every open record_misses set.

    :param key: api_cache key left unanswered.
    """
    for misses in _recorders:
        misses.add(key)


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
    The answer for key, fetched when stale and cached per answer kind; a failure,
    or an answer of another shape, keeps a stale answer. With a queue, one request
    a second across plugin calls.

    :param key: api_cache key, "<source>:<kind>:<id>".
    :param fetch: Returns the shaped payload; raises HttpError.
    :param ttl: Seconds an answer stays fresh: (answer, empty answer).
    :param queue: Home property holding the epoch of the next free slot; "" for none.
    :return: The payload, None when unknown or not fetched.
    """
    cache = ApiCacheHandler()
    payload, fresh = cache.get(key) or (None, False)
    if fresh:
        return payload
    source = key.partition(":")[0]
    if queue:
        home, now = Window(10000), time.time()
        slot = max(now, float(home.getProperty(queue) or 0))
        if slot - now > MAX_WAIT:
            log.debug(f"{source} → busy for {slot - now:.0f}s, skipped {key}")
            _missed(key)
            return payload
        home.setProperty(queue, f"{slot + 1}")
        if slot > now:
            log.debug(f"{source} → queued {slot - now:.1f}s {key}")
            if Monitor().waitForAbort(slot - now):
                _missed(key)
                return payload
    try:
        payload = fetch()
    except (HttpError, LookupError, TypeError, AttributeError, ValueError) as exc:
        if not isinstance(exc, HttpError):  # an answer of another shape
            log.warning(f"{source} → unexpected answer for {key}: {exc!r}")
            exc = HttpError(None)
        if exc.status == 401:  # the one failure the user can fix
            log.warning(f"{source} → refused the token (401)")
        wait = failure_ttl(exc)
        if exc.status == 429 and queue and exc.code != ONE_MEDIA:
            home.setProperty(queue, f"{slot + wait}")
        cache.put(key, payload, wait)  # keeps a stale answer, else a negative one
        _missed(key)
        return payload
    cache.put(key, payload, ttl[0] if payload else ttl[1])
    return payload
