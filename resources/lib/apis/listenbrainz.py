# author: realcopacetic

from typing import Any, Callable

from resources.lib.apis import http
from resources.lib.apis.cache import DAY, cached
from resources.lib.shared.utilities import ADDON, DETAILS, json_call

API = "https://api.listenbrainz.org/1/"
NEXT_CALL = "copacetic.listenbrainz_next"  # home property: epoch of the next free slot
TTL_HIT, TTL_EMPTY = 14 * DAY, 3 * DAY
SIMILAR = 20  # similar artists asked of LB Radio
_MBIDS = {  # MusicBrainz entity and AudioLibrary field per library type
    "album": ("release-group", "musicbrainzreleasegroupid"),
    "artist": ("artist", "musicbrainzartistid"),
    "song": ("recording", "musicbrainztrackid"),
}


def _token() -> str:
    """The user's ListenBrainz token; empty turns ListenBrainz off."""
    return ADDON.getSetting("listenbrainz_token").strip()


def musicbrainz_id(type: str, dbid: int, parent: str) -> tuple[str, str]:
    """
    A library album, artist or song's MusicBrainz entity and id: its release group,
    first artist id or recording (Picard's "MusicBrainz Track Id").

    :param type: album, artist or song.
    :param dbid: Library id.
    :param parent: Caller name for logging.
    :return: (entity, MBID), the MBID empty when untagged.
    """
    entity, field = _MBIDS[type]
    mbid = json_call(
        DETAILS[type],
        properties=[field],
        params={f"{type}id": dbid},
        parent=parent,
    )["result"][f"{type}details"][field]
    # An artist's is a one-id list, [""] when untagged
    return entity, mbid[0] if type == "artist" else mbid


def enabled() -> bool:
    """True when the user gave a ListenBrainz token, which is their consent."""
    return bool(_token())


def get_json(path: str, body: Any = None, params: dict | None = None) -> Any:
    """
    GET (POST with a body) a ListenBrainz endpoint with the user's token.

    :param path: Endpoint path after /1/.
    :param body: POST body; None for a GET.
    :param params: Query parameters.
    :return: Decoded JSON.
    :raises HttpError: On an HTTP error status, no connection or bad JSON.
    """
    headers = {"Authorization": f"Token {_token()}"}
    return http.get_json(f"{API}{path}", params, headers=headers, body=body)


def _cached(
    key: str,
    path: str,
    shape: Callable[[Any], Any],
    body: Any = None,
    params: dict | None = None,
) -> Any:
    """
    The answer for key from path, shaped; cached and queued (cache.cached).

    :param key: api_cache key.
    :param path: Endpoint path after /1/.
    :param shape: Turns the decoded JSON into the cached payload.
    :param body: POST body; None for a GET.
    :param params: Query parameters.
    :return: The payload, None when unknown or not fetched.
    """
    return cached(
        key,
        lambda: shape(get_json(path, body, params)),
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


def top_release_groups(mbid: str) -> list[list[str]]:
    """
    Artist mbid's release groups (albums, singles, EPs), most listened first.

    :param mbid: Artist MusicBrainz id.
    :return: [release group MBID, title] pairs, possibly empty.
    """
    return (
        _cached(
            f"listenbrainz:top-release-groups:{mbid}",
            f"popularity/top-release-groups-for-artist/{mbid}",
            lambda rows: [
                [row["release_group_mbid"], row["release_group"]["name"]]
                for row in rows
            ],
        )
        or []
    )


def similar_artists(mbid: str) -> list[str]:
    """
    Names of the artists most like artist mbid, by LB Radio's closest ("easy") mode,
    in its order.

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


def listeners(entity: str, mbid: str) -> int | None:
    """
    How many people have listened to an artist, release group or recording.

    :param entity: artist, release-group or recording.
    :param mbid: Its MusicBrainz id.
    :return: Listener count; None when ListenBrainz has none or wasn't asked.
    """
    return _cached(
        f"listenbrainz:listeners:{entity}:{mbid}",
        f"popularity/{entity}",
        lambda rows: rows[0]["total_user_count"],
        {f"{entity.replace('-', '_')}_mbids": [mbid]},
    )
