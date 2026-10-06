# author: realcopacetic

from typing import Any, Iterable, Mapping, Sequence

from resources.lib.apis.http import get_json
from resources.lib.apis.tmdb.fields import TMDB_PROPERTIES
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import ADDON

TMDB_API_BASE = "https://api.themoviedb.org/3"


def tmdb_language(language: str | None = None) -> str:
    """
    Language TMDb data is fetched and cached under: the explicit value, else
    the add-on's tmdb_language setting, else "en-US".
    """
    return language or ADDON.getSetting("tmdb_language") or "en-US"


def get_tmdb_client(language: str | None = None) -> "TmdbClient | None":
    """
    A TmdbClient when the user gave a TMDb token, which is their consent: no
    token, TMDb is off and nothing is logged.

    :param language: TMDb language code; None uses tmdb_language()'s default.
    :return: TmdbClient, or None without a token.
    """
    if not (token := ADDON.getSetting("tmdb_access_token").strip()):
        return None
    return TmdbClient(token=token, language=tmdb_language(language))


def _extract_path(data: Mapping[str, Any], path: Sequence[str]) -> Any:
    """
    Walk a nested mapping by key sequence.

    :param data: TMDb JSON response data.
    :param path: Iterable of nested keys.
    :return: Extracted value or None.
    """
    current = data
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def _build_field_map(
    field_specs: Iterable[str | tuple[str, Sequence[str]]],
) -> dict[str, tuple[str, ...]]:
    """
    Normalize TMDB_PROPERTIES field specs to name → JSON path mapping.

    :param field_specs: List of "field" or (name, path_tuple).
    :return: Mapping of logical name to tuple path.
    """
    return {
        (spec if isinstance(spec, str) else spec[0]): (
            (spec,) if isinstance(spec, str) else tuple(spec[1])
        )
        for spec in field_specs
    }


def fetch_tmdb_fields(
    client: "TmdbClient",
    kind: str,
    tmdb_id: int,
    season_number: int | None = None,
    append_artwork: bool = False,
) -> dict[str, Any]:
    """
    Fetch every known TMDb field for a kind/id in one request.

    :param client: Client for the user's token and language.
    :param kind: TMDb media kind ("movie", "tvshow", "season").
    :param tmdb_id: TMDb item identifier.
    :param season_number: Season number for kind == "season".
    :param append_artwork: If False, skip heavy image append blocks (e.g. "images").
    :return: Mapping of field name → extracted value.
    :raises HttpError: When the request fails.
    """
    if not (kind_map := TMDB_PROPERTIES.get(kind)):
        log.debug(f"fetch_tmdb_fields → unknown {kind=}")
        return {}
    endpoint = kind_map["endpoint"]
    if "{season_number}" in endpoint and season_number is None:
        log.debug(f"fetch_tmdb_fields → missing season_number for {kind=}, {tmdb_id=}")
        return {}

    params = {}
    if append := [b for b in kind_map["append"] if append_artwork or b != "images"]:
        params["append_to_response"] = ",".join(append)
    if "images" in append:  # images in the user's language, then language-less
        params["include_image_language"] = (
            f"{client.language.split('-')[0].lower()},null"
        )
    data = client.get_json(
        endpoint.format(id=tmdb_id, season_number=season_number), params=params
    )
    return {
        name: value
        for name, path in _build_field_map(kind_map["fields"]).items()
        if (value := _extract_path(data, path)) is not None
    }


class TmdbClient:
    """
    Minimal TMDb HTTP client with v3/v4 authentication support.
    """

    def __init__(self, token: str, language: str) -> None:
        """
        Initialize the client with API authentication + default language.

        :param token: API key (v3) or read access token (v4).
        :param language: Default TMDb language.
        """
        self.token = token
        self.language = language
        self.is_v4 = self.token.startswith("eyJ")  # JWT → v4 read token
        log.debug(
            f"{self.__class__.__name__} → using " f"{'v4' if self.is_v4 else 'v3'} auth"
        )

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        """
        GET a TMDb endpoint in the client's language and decode its JSON.

        :param path: TMDb path beginning with "/".
        :param params: Optional query parameters.
        :return: Decoded JSON.
        :raises HttpError: On an HTTP error status, no connection or bad JSON.
        """
        query = {"language": self.language, **(params or {})}
        headers = {}
        if self.is_v4:  # v4 read access token as a Bearer header
            headers["Authorization"] = f"Bearer {self.token}"
        else:  # v3 API key as a query parameter; get_json never logs the query
            query["api_key"] = self.token
        return get_json(f"{TMDB_API_BASE}{path}", query, headers)
