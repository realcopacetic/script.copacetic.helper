# author: realcopacetic

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Iterable, Mapping, Sequence
from urllib.error import HTTPError, URLError

from resources.lib.apis.tmdb.fields import TMDB_FIELD_MAP
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import ADDON

TMDB_API_BASE = "https://api.themoviedb.org/3"


def get_tmdb_client(language: str = "en-US") -> TmdbClient | None:
    """
    Build and return a TmdbClient if configuration is valid.

    :param language: TMDb language code (e.g. 'en-US').
    :returns: TmdbClient instance or None if disabled / misconfigured.
    """
    enabled = ADDON.getSetting("tmdb_access") == "true"
    token = (ADDON.getSetting("tmdb_access_token") or "").strip()

    if not enabled or not token:
        log.warning("TMDb disabled or missing token.")
        return None

    return TmdbClient(token=token, language=language)


def _extract_path(data: Mapping[str, Any], path: Sequence[str]) -> Any:
    """
    Safely walk a nested dict by a sequence of keys.

    :param data: TMDb JSON response.
    :param path: Sequence of keys, e.g. ("tagline",).
    :returns: Value at path or None if missing.
    """
    current = data
    for key in path:
        if not isinstance(current, Mapping):
            return None
        current = current.get(key)
        if current is None:
            return None
    return current


def fetch_tmdb_fields(
    kind: str,
    tmdb_id: int,
    fields: Iterable[str] | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """
    Fetch selected TMDb fields for a given kind/id.

    :param kind: Logical kind, e.g. "tvshow".
    :param tmdb_id: TMDb numeric id.
    :param fields: Iterable of field names to fetch, e.g. ["tagline"].
                   If None, all mapped fields for `kind` will be returned.
    :param language: Optional TMDb language code override (e.g. "en-US").
    :returns: Dict of {field_name: value} for fields that could be resolved.
    """
    if tmdb_id <= 0:
        log.debug(f"fetch_tmdb_fields → invalid tmdb_id={tmdb_id!r} for kind={kind!r}")
        return {}

    client = get_tmdb_client(language=language or "en-US")
    if not client:
        return {}

    kind_map = TMDB_FIELD_MAP.get(kind)
    endpoint: str = kind_map["endpoint"].format(id=tmdb_id)
    field_map = kind_map["fields"]

    if fields is None:
        requested: list[str] = list(field_map.keys())
    else:
        requested = [name for name in fields if name in field_map]
        unknown = sorted(set(fields) - set(field_map))
        if unknown:
            log.debug(
                f"fetch_tmdb_fields → unknown fields for kind={kind!r}: {unknown!r}"
            )

    if not requested:
        log.debug(f"fetch_tmdb_fields → no valid fields requested for kind={kind!r}")
        return {}

    data = client.get_json(endpoint)
    if not data:
        return {}

    result = {}
    for name in requested:
        path = field_map[name]
        value = _extract_path(data, path)
        if value is not None:
            result[name] = value

    log.debug(f"fetch_tmdb_fields(kind={kind!r}, tmdb_id={tmdb_id}) → {result!r}")
    return result


class TmdbClient:
    def __init__(self, token: str, language: str = "en-US"):
        self.token = token.strip()
        self.language = language
        self.is_v4 = self.token.startswith("eyJ")  # JWT → v4 read token
        log.debug(
            f"{self.__class__.__name__} → using {'v4' if self.is_v4 else 'v3'} auth"
        )

    def _build_request(
        self, path: str, params: dict | None = None
    ) -> urllib.request.Request:
        if params is None:
            params = {}

        params.setdefault("language", self.language)

        headers = {}
        if self.is_v4:
            # v4 read access token via Bearer header
            headers["Authorization"] = f"Bearer {self.token}"
        else:
            # v3 API key via query parameter
            params["api_key"] = self.token

        query = urllib.parse.urlencode(params)
        url = f"{TMDB_API_BASE}{path}"
        if query:
            url = f"{url}?{query}"

        return urllib.request.Request(url, headers=headers)

    def get_json(self, path: str, params: dict | None = None) -> dict:
        request = self._build_request(path, params)
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except HTTPError as exc:
            log.error(
                f"{self.__class__.__name__}: TMDb HTTPError {exc.code} for {path}: {exc.reason}",
            )
        except URLError as exc:
            log.error(
                f"{self.__class__.__name__}: TMDb URLError for {path}: {exc.reason}",
            )
        except Exception as exc:
            log.error(
                f"{self.__class__.__name__}: TMDb unexpected error for {path}: {exc}",
            )
