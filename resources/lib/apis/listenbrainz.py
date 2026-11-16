# author: realcopacetic

from typing import Any, Callable

from resources.lib.apis import http
from resources.lib.apis.cache import DAY, cached
from resources.lib.shared.utilities import ADDON

API = "https://api.listenbrainz.org/1/"
NEXT_CALL = "copacetic.listenbrainz_next"  # home property: epoch of the next free slot
TTL_HIT, TTL_EMPTY = 14 * DAY, 3 * DAY
SIMILAR = 20  # similar artists asked of LB Radio


def _token() -> str:
    """The user's ListenBrainz token; empty turns ListenBrainz off."""
    return ADDON.getSetting("listenbrainz_token").strip()


def enabled() -> bool:
    """True when the user gave a ListenBrainz token, which is their consent."""
    return bool(_token())


def get_json(path: str, params: dict | None = None) -> Any:
    """
    GET a ListenBrainz endpoint with the user's token.

    :param path: Endpoint path after /1/.
    :param params: Query parameters.
    :return: Decoded JSON.
    :raises HttpError: On an HTTP error status, no connection or bad JSON.
    """
    headers = {"Authorization": f"Token {_token()}"}
    return http.get_json(f"{API}{path}", params, headers=headers)


def _cached(
    key: str, path: str, shape: Callable[[Any], Any], params: dict | None = None
) -> Any:
    """
    The answer for key from path, shaped; cached and queued (cache.cached).

    :param key: api_cache key.
    :param path: Endpoint path after /1/.
    :param shape: Turns the decoded JSON into the cached payload.
    :param params: Query parameters.
    :return: The payload, None when unknown or not fetched.
    """
    return cached(
        key,
        lambda: shape(get_json(path, params)),
        (TTL_HIT, TTL_EMPTY),
        NEXT_CALL,
    )


def top_recordings(mbid: str) -> list[list[str]]:
    """
    Artist mbid's recordings, most listened first.

    :param mbid: Artist MusicBrainz id.
    :return: [recording MBID, title] pairs, possibly empty.
    """
    return (
        _cached(
            f"listenbrainz:top-recordings:{mbid}",
            f"popularity/top-recordings-for-artist/{mbid}",
            lambda rows: [
                [row["recording_mbid"], row["recording_name"]] for row in rows
            ],
        )
        or []
    )


def similar_artists(mbid: str) -> list[str]:
    """
    Names of artists like artist mbid: LB Radio's closest ("easy") mode, a random
    pick from its similarity bands, unordered.

    :param mbid: Artist MusicBrainz id.
    :return: Artist names, possibly empty.
    """
    return (
        _cached(
            f"listenbrainz:similar-artists:{mbid}",
            f"lb-radio/artist/{mbid}",
            lambda groups: [
                rows[0]["similar_artist_name"]
                for artist, rows in groups.items()
                if rows and artist != mbid
            ],
            params={
                "mode": "easy",
                "max_similar_artists": SIMILAR,
                "max_recordings_per_artist": 1,
                "pop_begin": 0,
                "pop_end": 100,
            },
        )
        or []
    )
