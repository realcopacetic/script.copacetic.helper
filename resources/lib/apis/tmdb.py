# author: realcopacetic

import json
import urllib.request
import urllib.parse
from urllib.error import HTTPError, URLError

from resources.lib.shared.utilities import ADDON, DEBUG, ERROR, log

TMDB_API_BASE = "https://api.themoviedb.org/3"


def _get_tmdb_config():
    """Return (enabled, token) from addon settings."""
    enabled = ADDON.getSetting("tmdb_access") == "true"
    token = (ADDON.getSetting("tmdb_access_token") or "").strip()
    if not enabled or not token:
        return False, ""
    return True, token


def get_tmdb_client(language: str = "en-US") -> TmdbClient | None:
    enabled = ADDON.getSetting("tmdb_access") == "true"
    token = (ADDON.getSetting("tmdb_access_token") or "").strip()
    if not enabled or not token:
        log("TMDb disabled or missing token.", level=2)
        return None
    # You can memoize the client if you want, but keep it simple first
    return TmdbClient(token=token, language=language)


class TmdbClient:
    def __init__(self, token: str, language: str = "en-US"):
        self.token = token.strip()
        self.language = language
        self.is_v4 = self.token.startswith("eyJ")  # JWT → v4 read token
        log(f"TmdbClient → using {'v4' if self.is_v4 else 'v3'} auth", level=DEBUG)

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
            log(f"TMDb HTTPError {exc.code} for {path}: {exc.reason}", level=ERROR)
        except URLError as exc:
            log(f"TMDb URLError for {path}: {exc.reason}", level=ERROR)
        except Exception as exc:
            log(f"TMDb unexpected error for {path}: {exc}", level=ERROR)
