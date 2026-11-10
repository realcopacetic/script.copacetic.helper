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
# Deezer answers its errors with a 200 and a code: as the HTTP status meaning the same
_STATUS = {4: 429, 700: 503, 800: 404}  # quota, busy, no data


def enabled() -> bool:
    """True when the user turned Deezer on, which is their consent."""
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
    rows = get_json(f"artist/{artist}/top", limit=100)["data"]
    return [["", row["title_short"], row["album"]["title"]] for row in rows]


def top_tracks(key: str, name: str, accept: Callable[[list], bool]) -> list[list]:
    """
    A library artist's Deezer top tracks: those of the first of its most followed
    same-named Deezer artists whose tracks accept takes as the library's.

    :param key: artist_key of the library artist.
    :param name: Its name, searched for.
    :param accept: Whether a candidate's top-track rows are this artist's.
    :return: ["", title, album title] rows, possibly empty.
    """
    accepted = {}

    def find() -> int | None:
        found = get_json("search/artist", q=name, limit=10)["data"]
        named = [row for row in found if fold(row["name"]) == fold(name)]
        for row in sorted(named, key=itemgetter("nb_fan"), reverse=True)[:CANDIDATES]:
            artist = int(row["id"])
            try:
                rows = _top(artist)
            except HttpError as exc:
                if exc.status == 404:  # no data for this one: try the next
                    continue
                raise  # the search can't finish: asked again soon
            if accept(rows):
                accepted[artist] = rows
                return artist

    artist = cached(f"deezer:artist:{key}", find, (TTL_ARTIST, TTL_NO_ARTIST))
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


def patterns(key: str) -> list[str]:
    """
    LIKE patterns for one library artist's rows: its Deezer id and that id's tracks.

    :param key: artist_key of the library artist.
    :return: Patterns for ApiCacheHandler.expire.
    """
    artist = (ApiCacheHandler().get(f"deezer:artist:{key}") or (None,))[0]
    return [f"deezer:artist:{key}", *([f"deezer:top:{artist}"] if artist else [])]
