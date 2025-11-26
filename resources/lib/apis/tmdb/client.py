# author: realcopacetic

import json
import urllib.parse
import urllib.request
from typing import Any, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError

from resources.lib.apis.tmdb.fields import TMDB_PROPERTIES
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import ADDON

TMDB_API_BASE = "https://api.themoviedb.org/3"


def get_tmdb_client(language: str = "en-US") -> "TmdbClient | None":
    """
    Create a TmdbClient instance if TMDb access is enabled.

    :param language: TMDb language code (e.g. "en-US").
    :return: TmdbClient or None if disabled or misconfigured.
    """
    enabled = ADDON.getSetting("tmdb_access") == "true"
    token = (ADDON.getSetting("tmdb_access_token") or "").strip()

    if not enabled or not token:
        log.warning("TMDb disabled or missing token.")
        return None

    return TmdbClient(token=token, language=language)


def _extract_path(data: Mapping[str, Any], path: Sequence[str]) -> Any:
    """
    Walk a nested mapping by key sequence.

    :param data: TMDb JSON response data.
    :param path: Iterable of nested keys.
    :return: Extracted value or None.
    """
    current: Any = data
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
    kind: str,
    tmdb_id: int,
    fields: Iterable[str] | None = None,
    language: str | None = None,
    append_artwork: bool = False,
) -> dict[str, Any]:
    """
    Fetch specific TMDb fields for a given kind/id.

    :param kind: TMDb media kind ("movie", "tvshow", etc.).
    :param tmdb_id: TMDb item identifier.
    :param fields: Logical fields to extract or None for all known.
    :param language: Optional TMDb language override.
    :param append_artwork: If False, skip heavy image append blocks (e.g. "images").
    :return: Mapping of field name → extracted value.
    """
    if tmdb_id <= 0:
        log.debug(
            f"fetch_tmdb_fields → invalid {tmdb_id=} for {kind=}",
        )
        return {}

    client = get_tmdb_client(language=language or "en-US")
    if not client:
        return {}

    kind_map = TMDB_PROPERTIES.get(kind)
    if not kind_map:
        log.debug(f"fetch_tmdb_fields → unknown {kind=}")
        return {}

    endpoint = kind_map["endpoint"].format(id=tmdb_id)
    field_specs = kind_map["fields"]
    field_map = _build_field_map(field_specs)

    append_blocks = list(kind_map.get("append") or [])
    if not append_artwork:
        append_blocks = [b for b in append_blocks if b != "images"]

    if fields is None:
        requested = list(field_map.keys())
    else:
        requested = [f for f in fields if f in field_map]
        unknown = sorted(set(fields) - set(field_map))
        if unknown:
            log.debug(f"fetch_tmdb_fields → unknown fields for {kind=}: {unknown!r}")

    if not requested:
        log.debug(f"fetch_tmdb_fields → no valid fields requested for {kind=}")
        return {}

    params: dict[str, Any] = {}
    if append_blocks:
        params["append_to_response"] = ",".join(sorted(set(append_blocks)))

    # Include image language hints if we know the preferred ISO code.
    lang = language or client.language
    if lang:
        iso = lang.split("-")[0].lower()
        params["include_image_language"] = f"{iso},null"

    data = client.get_json(endpoint, params=params)
    if not data:
        return {}

    result: dict[str, Any] = {}
    for name in requested:
        path = field_map[name]
        value = _extract_path(data, path)
        if value is not None:
            result[name] = value

    return result


class TmdbClient:
    """
    Minimal TMDb HTTP client with v3/v4 authentication support.
    """

    def __init__(self, token: str, language: str = "en-US") -> None:
        """
        Initialize the client with API authentication + default language.

        :param token: API key (v3) or read access token (v4).
        :param language: Default TMDb language.
        """
        self.token = token.strip()
        self.language = language
        self.is_v4 = self.token.startswith("eyJ")  # JWT → v4 read token
        log.debug(
            f"{self.__class__.__name__} → using " f"{'v4' if self.is_v4 else 'v3'} auth"
        )

    def _build_request(
        self,
        path: str,
        params: Mapping[str, Any] | None = None,
    ) -> urllib.request.Request:
        """
        Build an authenticated TMDb HTTP Request.

        :param path: TMDb REST path beginning with "/".
        :param params: Query parameters mapping.
        :return: Prepared urllib Request.
        """
        if params is None:
            params = {}
        params.setdefault("language", self.language)

        headers: dict[str, str] = {}

        if self.is_v4:
            # v4 read access token via Bearer header.
            headers["Authorization"] = f"Bearer {self.token}"
        else:
            # v3 API key via query parameter.
            params["api_key"] = self.token

        query = urllib.parse.urlencode(params)
        url = f"{TMDB_API_BASE}{path}"
        if query:
            url = f"{url}?{query}"

        return urllib.request.Request(url, headers=headers)

    def get_json(self, path: str, params: Mapping[str, Any] | None = None) -> dict:
        """
        GET a TMDb endpoint and decode its JSON response.

        :param path: TMDb path beginning with "/".
        :param params: Optional query parameters.
        :return: Parsed dict, or empty dict on failure.
        """
        request = self._build_request(path, params)

        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)

        except HTTPError as exc:
            log.error(
                f"{self.__class__.__name__}: HTTPError {exc.code} "
                f"for URL={request.full_url!r}: {exc.reason}"
            )

        except URLError as exc:
            log.error(
                f"{self.__class__.__name__}: URLError for URL={request.full_url!r}: "
                f"{exc.reason}"
            )

        except Exception as exc:  # noqa: BLE001
            log.error(
                f"{self.__class__.__name__}: Unexpected TMDb error "
                f"for URL={request.full_url!r}: {exc!r}"
            )

        return {}
