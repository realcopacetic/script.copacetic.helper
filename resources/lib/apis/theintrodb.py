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


def _spans(kind: str, rows: list[dict]) -> list[list[int | None]]:
    """
    One kind's segments, most trusted first (confidence, then submissions), each kept
    unless it overlaps one kept: a rival take on it. A film's credits can be several.

    :param kind: intro, recap, credits or preview.
    :param rows: TheIntroDB's segments of that kind.
    :return: [start_ms, end_ms] pairs by start, end None for one running to the end.
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

    kept = []
    for *_, start, end in sorted(
        filter(valid, map(span, rows)), key=itemgetter(0, 1), reverse=True
    ):
        if all(
            end is not None and end <= s or e is not None and e <= start
            for s, e in kept
        ):
            kept.append([start, end])
    return sorted(kept, key=itemgetter(0))


def _shape(data: dict[str, Any]) -> dict[str, Any]:
    """
    TheIntroDB's answer as the cached payload.

    :param data: GET /media's decoded JSON.
    :return: {kind: [[start_ms, end_ms], ...]} and the answering release's "duration".
    """
    found = {
        kind: spans for kind in KINDS if (spans := _spans(kind, data.get(kind) or []))
    }
    if found and (duration := data.get("group_duration_ms")):
        found["duration"] = int(duration)
    return found


def _fetch(params: dict[str, Any]) -> dict[str, Any] | list:
    """
    GET /media, shaped; a "no submissions" 404 as {}, ending the lookup (records are
    keyed by TVDB id, so any TVDB miss answers so), any other 404 (nothing under this
    id or numbering) as [], which tells segments to ask by the next.

    :param params: The query.
    :return: _shape's payload, or [] for an id or numbering TheIntroDB doesn't know.
    :raises HttpError: On any other failure.
    """
    try:
        return _shape(http.get_json(API, params, timeout=3))
    except HttpError as exc:
        if exc.status != 404:
            raise
        return {} if exc.code == "no_submissions" else []


def segments(
    ids: dict[str, str],
    duration_ms: int,
    season: int | None = None,
    episode: int | None = None,
) -> dict[str, Any]:
    """
    A film's skip segments, or an episode's by its show's ids, from the first id
    TheIntroDB knows, in IDS order; each answer cached, queued one call a second.

    :param ids: The film's or show's uniqueid, by type.
    :param duration_ms: The file's length, for the release nearest it; 0 unknown.
    :param season: An episode's season, in the library's order; None for a film.
    :param episode: An episode's number.
    :return: _shape's payload; empty when none.
    """
    seconds = duration_ms // 1000
    media, which = (
        ("movie", "") if season is None else ("episode", f":{season}x{episode}")
    )
    for id_type in IDS:
        if not (value := ids.get(id_type)):
            continue
        params = {f"{id_type}_id": value}
        if season is not None:
            params |= {"season": season, "episode": episode}
        params["details"] = "true"  # confidence, and the answering release's length
        if duration_ms:
            params["duration_ms"] = duration_ms
        found = cached(
            f"theintrodb:{media}:{id_type}:{value}{which}:{seconds}",
            lambda: _fetch(params),
            (TTL_HIT, TTL_EMPTY),
            NEXT_CALL,
        )
        if found != []:  # an answer, or a failure (the other ids would fail alike)
            return found or {}
    return {}
