# author: realcopacetic

from operator import itemgetter
from typing import Any, Callable

from resources.lib.apis import http
from resources.lib.apis.cache import DAY, cached
from resources.lib.apis.http import HttpError
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import ADDON, fold

API = "https://api.deezer.com/"
TTL_ARTIST, TTL_NO_ARTIST, TTL_TOP, TTL_NO_TOP = 90 * DAY, 7 * DAY, 7 * DAY, DAY
CANDIDATES = 3  # same-named artists tried, most followed first
LEAD = 10  # times the next one's fans the most followed needs, unconfirmed by songs
RELATED = 20  # related artists asked for
# Deezer answers its errors with a 200 and a code: as the HTTP status meaning the same
_STATUS = {
    4: 429,  # quota
    501: 400,  # parameter missing
    600: 400,  # invalid query
    700: 503,  # service busy
    800: 404,  # no data
}
TITLE = 500  # characters kept of a title: Deezer's answer is not ours to trust


def enabled() -> bool:
    """True while Rank music with Deezer is on (the default); off sends nothing."""
    return ADDON.getSettingBool("deezer")


def get_json(path: str, **params: Any) -> Any:
    """
    GET a Deezer endpoint; Deezer's error answers raised as HTTP's.

    :param path: Endpoint path after the host.
    :param params: Query parameters.
    :return: Decoded JSON.
    :raises HttpError: On Deezer's error, an HTTP error, no connection or bad JSON.
    """
    data = http.get_json(f"{API}{path}", params, timeout=3)
    if error := data.get("error"):
        raise HttpError(_STATUS.get(error.get("code")))
    return data


def artist_key(mbid: str, name: str) -> str:
    """
    How a library artist's Deezer rows are keyed: its MBID, else its folded name.

    :param mbid: MusicBrainz artist id; empty when untagged.
    :param name: Artist name.
    :return: Key part.
    """
    return mbid or fold(name)


def _top(artist: int) -> list[list[str]]:
    """
    A Deezer artist's top 100 tracks, in Deezer's order (what is streamed now).

    :param artist: Deezer artist id.
    :return: ["", title without version, album title] rows, like ListenBrainz's.
    """
    rows = get_json(f"artist/{artist}/top", limit=100)["data"][:100]
    return [
        ["", title[:TITLE], album[:TITLE]]
        for row in rows
        if isinstance(title := row["title_short"], str)
        and isinstance(album := row["album"]["title"], str)
    ]


def _artist(key: str, name: str, accept: Callable[[list], bool]) -> tuple:
    """
    A library artist's Deezer artist: the first of its most followed same-named
    Deezer artists whose top tracks accept takes as the library's, else the most
    followed with LEAD times the next one's fans.

    :param key: artist_key of the library artist.
    :param name: Its name, searched for.
    :param accept: Whether a candidate's top-track rows are this artist's.
    :return: (Deezer id or None, {id: top rows} fetched by this search).
    """
    accepted = {}
    if not (folded := fold(name)):  # it would match every such name
        return None, accepted

    def find() -> int | None:
        found = get_json("search/artist", q=name, limit=10)["data"][:10]
        named = [row for row in found if fold(row["name"]) == folded]
        named.sort(key=itemgetter("nb_fan"), reverse=True)
        tops = {}
        for row in named[:CANDIDATES]:
            artist = int(row["id"])
            try:
                tops[artist] = _top(artist)
            except HttpError as exc:
                if exc.status == 404:  # no data for this one: try the next
                    continue
                raise  # the search can't finish: asked again soon
            if accept(tops[artist]):
                accepted[artist] = tops[artist]
                return artist
        # The library's songs confirm none: the most followed, if far ahead
        fans = [row["nb_fan"] for row in named[:2]]
        if fans and fans[0] > LEAD * sum(fans[1:]):
            artist = int(named[0]["id"])
            if artist in tops:  # Deezer has its tracks
                accepted[artist] = tops[artist]
                return artist

    return cached(f"deezer:artist:{key}", find, (TTL_ARTIST, TTL_NO_ARTIST)), accepted


def top_tracks(key: str, name: str, accept: Callable[[list], bool]) -> list[list]:
    """
    A library artist's Deezer top tracks (_artist finds its Deezer artist).

    :param key: artist_key of the library artist.
    :param name: Its name, searched for.
    :param accept: Whether a candidate's top-track rows are this artist's.
    :return: ["", title, album title] rows; empty for a name of symbols only.
    """
    artist, accepted = _artist(key, name, accept)
    if not artist:
        return []
    return (
        cached(
            f"deezer:top:{artist}",
            lambda: accepted.pop(artist, None) or _top(artist),
            (TTL_TOP, TTL_NO_TOP),
        )
        or []
    )


def related(key: str, name: str, accept: Callable[[list], bool]) -> list[str]:
    """
    Names of a library artist's related Deezer artists, closest first.

    :param key: artist_key of the library artist.
    :param name: Its name, searched for.
    :param accept: Whether a candidate's top-track rows are this artist's.
    :return: Artist names, possibly empty.
    """
    if not (artist := _artist(key, name, accept)[0]):
        return []
    return (
        cached(
            f"deezer:related:{artist}",
            lambda: [
                similar[:TITLE]
                for row in get_json(f"artist/{artist}/related", limit=RELATED)["data"]
                if isinstance(similar := row["name"], str)
            ][:RELATED],
            (TTL_TOP, TTL_NO_TOP),
        )
        or []
    )


def patterns(key: str) -> list[str]:
    """
    LIKE patterns for one library artist's rows: its Deezer id, that id's tracks and
    related artists.

    :param key: artist_key of the library artist.
    :return: Patterns for ApiCacheHandler.expire.
    """
    artist = (ApiCacheHandler().get(f"deezer:artist:{key}") or (None,))[0]
    by_id = [f"deezer:{kind}:{artist}" for kind in ("top", "related")] if artist else []
    return [f"deezer:artist:{key}", *by_id]
