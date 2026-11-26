# author: realcopacetic

import time
from collections import deque
from collections.abc import Hashable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial
from threading import Lock, Thread
from typing import Any, Callable, Protocol

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
            if Monitor().waitForAbort(slot - now) or held(queue):
                return payload  # Kodi's exit, or a 429 held the queue while waiting
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
        if holding := exc.status == 429 and queue and exc.code != ONE_MEDIA:
            home.setProperty(queue, f"{slot + wait}")
            home.setProperty(f"{queue}.held", f"{slot + wait}")
        # A racing call's fresh answer stands; its failure row holds the same stale
        # read as this call's payload, so that one is simply stored again
        if (row := cache.get(key)) and row[1] and row[0] != payload:
            return row[0]
        # The queue holds this key with the rest: no row, so a call waiting the queue
        # out asks again once it frees, not a row that outlives the slot
        if not holding:
            cache.put(key, payload, wait)  # keeps a stale answer, else a negative one
        return payload
    cache.put(key, payload, ttl[0] if payload else ttl[1])
    return payload


def hold(queue: str) -> str:
    """The end of a queue's last 429 hold, as cached recorded it; "" for none."""
    return Window(10000).getProperty(f"{queue}.held")


def held(queue: str) -> bool:
    """Whether a 429 holds a queue now."""
    return float(hold(queue) or 0) > time.time()


def busy(queue: str) -> bool:
    """Whether a queue's next free slot is over MAX_WAIT away: cached skips a call."""
    return float(Window(10000).getProperty(queue) or 0) - time.time() > MAX_WAIT


class Asker(Protocol):
    """A served call's re-serve once its late answer lands (serve.py's Again)."""

    def __call__(self) -> None: ...

    def current(self) -> bool: ...


class Asides:
    """
    Fetches for served calls, on threads of their own: one per key while it is queued
    or running, its askers told when it brings news or is dropped, its followers when
    it ends. At most `workers` daemon threads, which end with the queue: a dead
    network queues, holds no exit.
    """

    def __init__(
        self, fetch: Callable[[Hashable, Callable[[], bool]], Any], workers: int = 1
    ) -> None:
        """
        A queue with no worker yet.

        :param fetch: Fetches a key's answer, given a test of its askers; None for none.
        :param workers: Threads at most.
        """
        self.fetch, self.workers, self.running = fetch, workers, 0
        self.asked = {}  # key → (its askers, the answer they were served meanwhile)
        self.followers = {}  # key → the askers told when it ends, news or not
        self.queue = deque()
        self.lock = Lock()

    def ask(self, key: Hashable, asker: Asker, stale: Any = None) -> None:
        """
        Queue a key's fetch, once while it is queued or running, starting a worker if
        fewer than `workers` run; an asker meanwhile joins it.

        :param key: What to fetch.
        :param asker: The served call's re-serve; an equal one asks once.
        :param stale: The answer the asker served meanwhile: one equal to it is no news.
        """
        with self.lock:
            if key in self.asked:
                self.asked[key][0].add(asker)
                return
            self.asked[key] = {asker}, stale
            self.queue.append(key)
            if self.running == self.workers:
                return
            self.running += 1
        Thread(target=self._drain, daemon=True).start()

    def join(self, key: Hashable, asker: Asker) -> bool:
        """
        Follow a key's fetch while it is queued or running: told once it ends, news or
        not, so a serve that masked its wait can show; none starts for it.

        :param key: What is fetched.
        :param asker: A served call's re-serve.
        :return: Whether it joined one.
        """
        with self.lock:
            if joined := key in self.asked:
                self.followers.setdefault(key, set()).add(asker)
        return joined

    def _drain(self) -> None:
        """A worker: fetch queued keys in turn; it ends, in one hold, with the queue."""
        while True:
            with self.lock:
                if not self.queue:
                    self.running -= 1
                    return
                key = self.queue.popleft()
            try:
                self._turn(key)
            except Exception:  # anything _turn's own tries miss: the worker goes on
                log.exception(f"Asides → {key!r}")

    def _turn(self, key: Hashable) -> None:
        """
        One key's fetch, skipped once no asker's arrival is still current (the service
        stopping ends them all); then its askers, told once on news or when none
        wanted it any more, which owes them their lists (serve.py's again), and its
        followers, told whatever came.

        :param key: What to fetch.
        """
        answer, skipped = None, False
        try:
            with self.lock:  # the skip and its drop in one hold: none joins between
                if skipped := not any(asker.current() for asker in self.asked[key][0]):
                    askers, stale = self.asked.pop(key)
                    followers = self.followers.pop(key, set())
            if not skipped:
                answer = self.fetch(key, partial(self._wanted, key))
        except Exception:  # its own thread: nothing above it would log
            log.exception(f"Asides → {key!r}")
        if not skipped:
            with self.lock:  # a later ask of the key, after this, queues its own fetch
                askers, stale = self.asked.pop(key)
                followers = self.followers.pop(key, set())
        # News; or none for want of a current asker: each records its list as owed, and
        # its arrival's next ring serves it, asking again (a current one failing isn't)
        news = (answer is not None and answer != stale) or (
            answer is None and (skipped or not any(asker.current() for asker in askers))
        )
        for asker in (askers if news else set()) | followers:
            try:
                asker()
            except Exception:  # one asker's error: the others are still told
                log.exception(f"Asides → {key!r}: an asker")

    def _wanted(self, key: Hashable) -> bool:
        """Whether any asker of a running key still wants it: a fetch's live test."""
        with self.lock:
            return any(asker.current() for asker in self.asked[key][0])
