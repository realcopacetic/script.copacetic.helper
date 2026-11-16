# author: realcopacetic

from collections.abc import Callable
from typing import Any

from resources.lib.apis import http
from resources.lib.apis.cache import DAY, FAILURES, cached
from resources.lib.apis.http import HttpError
from resources.lib.shared import logger as log
from resources.lib.shared.lrc import parse
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import ADDON

API = "https://lrclib.net/api"
# Lyrics rarely change once posted: a long life covers replays and offline playback;
# a song with none may gain them. A song LRCLIB doesn't know (404) waits 7 days
TTL_HIT, TTL_EMPTY = 180 * DAY, 30 * DAY
NEAR = 2  # seconds a search hit's length may sit from the file's
SEARCH = ("track_name", "artist_name")  # /search's fallback query: no album or length
TIMEOUT = 3  # seconds a request waits: one fits inside Kodi's 5 s for a script's exit


def enabled() -> bool:
    """True when the user left LRCLIB on, which is their consent."""
    return ADDON.getSettingBool("lrclib")


def _shape(record: dict[str, Any]) -> dict[str, Any]:
    """
    An LRCLIB record as the cached payload; the plain text only without synced.

    :param record: A /get or /search record.
    :return: {"synced", "plain", "instrumental"}; empty when it holds none.
    """
    synced = parse(record.get("syncedLyrics") or "") or None
    plain = None if synced else (record.get("plainLyrics") or "").strip() or None
    instrumental = bool(record.get("instrumental"))
    if synced or plain or instrumental:
        return {"synced": synced, "plain": plain, "instrumental": instrumental}
    return {}


class Aborted(Exception):
    """Kodi is exiting: a lookup stopped short; outside cache.FAILURES, so uncached."""


def _fetch(params: dict[str, Any], aborted: Callable[[], bool]) -> dict[str, Any]:
    """
    GET /get, shaped; on a 404, the /search hit nearest the song's length within
    NEAR seconds, one with synced lyrics first.

    :param params: /get's query.
    :param aborted: The service thread's Monitor.abortRequested.
    :return: _shape's payload.
    :raises HttpError: On a failure, or a 404 no search hit is near.
    :raises Aborted: Kodi is exiting, before the search.
    """
    try:
        return _shape(http.get_json(f"{API}/get", params, timeout=TIMEOUT))
    except HttpError as exc:
        if exc.status != 404:
            raise
        # Kodi waits on a script's threads at exit and kills it after 5 s
        if aborted():
            raise Aborted from None
        seconds = params["duration"]
        best = min(
            http.get_json(
                f"{API}/search", {k: params[k] for k in SEARCH}, timeout=TIMEOUT
            ),
            key=lambda hit: (abs(hit["duration"] - seconds), not hit["syncedLyrics"]),
            default={"duration": seconds + NEAR + 1},
        )
        if abs(best["duration"] - seconds) > NEAR:
            raise
        return _shape(best)


def lyrics(
    artist: str, title: str, album: str, seconds: int, aborted: Callable[[], bool]
) -> dict[str, Any] | None:
    """
    A song's lyrics on LRCLIB, by its tags and length, cached. No queue: LRCLIB
    sets no rate limit.

    :param artist: The song's artist string.
    :param title: Its title.
    :param album: Its album; "" when none.
    :param seconds: Its length in whole seconds.
    :param aborted: The service thread's Monitor.abortRequested.
    :return: _shape's payload; empty when none, None when unknown or not fetched.
    :raises Aborted: Kodi is exiting; nothing cached.
    """
    key, params = _query(artist, title, album, seconds)
    return cached(key, lambda: _fetch(params, aborted), (TTL_HIT, TTL_EMPTY))


def saved(artist: str, title: str, album: str, seconds: int) -> tuple[Any, bool] | None:
    """
    A song's cached LRCLIB answer, fresh or not, with no request.

    :param artist: The song's artist string.
    :param title: Its title.
    :param album: Its album; "" when none.
    :param seconds: Its length in whole seconds.
    :return: (payload, fresh), payload None for a failure; None when never asked.
    """
    return ApiCacheHandler().get(_query(artist, title, album, seconds)[0])


def prefetch(
    artist: str, title: str, album: str, seconds: int, aborted: Callable[[], bool]
) -> dict[str, Any] | None:
    """
    A queued song's lyrics into the cache ahead of its start. Only an answer is
    kept: after a failure (a 404 too) the song's start asks itself.

    :param artist: The song's artist string.
    :param title: Its title.
    :param album: Its album; "" when none.
    :param seconds: Its length in whole seconds.
    :param aborted: The service thread's Monitor.abortRequested.
    :return: _shape's payload; None after a failure.
    :raises Aborted: Kodi is exiting; nothing cached.
    """
    key, params = _query(artist, title, album, seconds)
    try:
        payload = _fetch(params, aborted)
    except FAILURES as exc:
        log.debug(f"lrclib → prefetch kept nothing for {key}: {exc!r}")
        return None
    ApiCacheHandler().put(key, payload, TTL_HIT if payload else TTL_EMPTY)
    return payload


def _query(
    artist: str, title: str, album: str, seconds: int
) -> tuple[str, dict[str, Any]]:
    """
    A song's api_cache key and /get query.

    :param artist: The song's artist string.
    :param title: Its title.
    :param album: Its album; "" when none.
    :param seconds: Its length in whole seconds.
    :return: (key, params).
    """
    return f"lrclib:lyrics:{artist}|{title}|{album}|{seconds}", {
        "track_name": title,
        "artist_name": artist,
        "album_name": album,
        "duration": seconds,
    }
