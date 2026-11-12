# author: realcopacetic

from typing import Any

from resources.lib.apis import http
from resources.lib.apis.cache import DAY, cached
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

    def valid(row: dict) -> bool:
        end = row.get("end_ms")
        return kind in OPEN_ENDED if end is None else end > (row.get("start_ms") or 0)

    if not (rows := [row for row in rows if valid(row)]):
        return None
    best = max(
        rows,
        key=lambda row: (row.get("confidence") or 0, row.get("submission_count") or 0),
    )
    return [best.get("start_ms") or 0, best.get("end_ms")]


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
        found["duration"] = duration
    return found


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
            lambda: _shape(http.get_json(API, params, timeout=3)),
            (TTL_HIT, TTL_EMPTY),
            NEXT_CALL,
        )
        if found is not None:  # an answer, empty or not; None: unknown under this id
            return found
    return {}
