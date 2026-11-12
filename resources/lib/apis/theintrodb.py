# author: realcopacetic

from operator import itemgetter
from typing import Any

from resources.lib.apis import http
from resources.lib.apis.cache import DAY, cached
from resources.lib.apis.http import HttpError
from resources.lib.shared.utilities import ADDON

API = "https://api.theintrodb.org/v4/media"
NEXT_CALL = "copacetic.theintrodb_next"  # home property: epoch of the next free slot
# Times rarely change: a long life covers rewatches and offline playback; an episode
# with none yet gains them within days
TTL_HIT, TTL_EMPTY = 180 * DAY, 3 * DAY
IDS = ("tmdb", "tvdb", "imdb")  # tried in turn: a TMDb id reads TMDb's numbering
KINDS = ("recap", "intro", "credits", "preview")
OPEN_ENDED = frozenset({"credits", "preview"})  # a null end runs to the media's end


def enabled() -> bool:
    """True when the user left TheIntroDB on, which is their consent."""
    return ADDON.getSettingBool("theintrodb")


def _best(kind: str, rows: list[dict]) -> list[int | None] | None:
    """
    The most trusted of one kind's segments: confidence, then submissions.

    :param kind: intro, recap, credits or preview.
    :param rows: TheIntroDB's segments of that kind.
    :return: [start_ms, end_ms], end None for one running to the end; None if none.
    """

    def span(row: dict) -> tuple[float, int, int, int | None]:
        """(confidence, submissions, start, end) as numbers; a bad type raises."""
        end = row.get("end_ms")
        return (
            float(row.get("confidence") or 0),
            int(row.get("submission_count") or 0),
            int(row.get("start_ms") or 0),
            None if end is None else int(end),
        )

    def valid(s: tuple) -> bool:
        """An end after the start, or none for a kind that runs to the end."""
        return kind in OPEN_ENDED if s[3] is None else s[3] > s[2]

    if not (spans := [s for s in map(span, rows) if valid(s)]):
        return None
    return list(max(spans, key=itemgetter(0, 1))[2:])


def _shape(data: dict[str, Any]) -> dict[str, Any]:
    """
    TheIntroDB's answer as the cached payload.

    :param data: GET /media's decoded JSON.
    :return: {kind: [start_ms, end_ms]} and the answering release's "duration" (ms).
    """
    found = {
        kind: span for kind in KINDS if (span := _best(kind, data.get(kind) or []))
    }
    if found and (duration := data.get("group_duration_ms")):
        found["duration"] = int(duration)
    return found


def _fetch(params: dict[str, Any]) -> dict[str, Any] | list:
    """
    GET /media, shaped; a 404 (nothing under this id) as [], an empty answer that
    tells segments to ask by the next id.

    :param params: The query.
    :return: _shape's payload, or [] for an id TheIntroDB doesn't know.
    :raises HttpError: On any other failure.
    """
    try:
        return _shape(http.get_json(API, params, timeout=3))
    except HttpError as exc:
        if exc.status != 404:
            raise
        return []


def segments(
    ids: dict[str, str], season: int, episode: int, duration_ms: int
) -> dict[str, Any]:
    """
    An episode's skip segments from the first of its show's ids TheIntroDB knows,
    in IDS order; each answer cached (cache.cached), queued one call a second.

    :param ids: The show's uniqueid, by type.
    :param season: Season number, in the library's order.
    :param episode: Episode number.
    :param duration_ms: The file's length, for the release nearest it; 0 unknown.
    :return: _shape's payload; empty when none.
    """
    seconds = duration_ms // 1000
    for id_type in IDS:
        if not (value := ids.get(id_type)):
            continue
        params = {f"{id_type}_id": value, "season": season, "episode": episode}
        params["details"] = "true"  # confidence, and the answering release's length
        if duration_ms:
            params["duration_ms"] = duration_ms
        found = cached(
            f"theintrodb:episode:{id_type}:{value}:{season}x{episode}:{seconds}",
            lambda: _fetch(params),
            (TTL_HIT, TTL_EMPTY),
            NEXT_CALL,
        )
        if found != []:  # an answer, or a failure that the other ids would share
            return found or {}
    return {}
