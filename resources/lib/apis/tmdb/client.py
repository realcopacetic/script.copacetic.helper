# author: realcopacetic

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Iterable, Mapping, Sequence

from urllib.error import HTTPError, URLError

from resources.lib.apis.tmdb.fields import (
    TMDB_PROPERTIES,
    TMDB_FIELD_MAP,
    apply_tmdb_transform,
    build_tmdb_image_url,
    build_tmdb_image_url_list,
    assign_image_list_to_art,
    split_tmdb_images_by_language,
)
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import ADDON

TMDB_API_BASE = "https://api.themoviedb.org/3"


def get_tmdb_client(language: str = "en-US") -> "TmdbClient | None":
    """Build and return a TmdbClient if configuration is valid.

    :param language: TMDb language code (e.g. "en-US").
    :return: TmdbClient instance or None if disabled or misconfigured.
    """
    enabled = ADDON.getSetting("tmdb_access") == "true"
    token = (ADDON.getSetting("tmdb_access_token") or "").strip()

    if not enabled or not token:
        log.warning("TMDb disabled or missing token.")
        return None

    return TmdbClient(token=token, language=language)


def _extract_path(data: Mapping[str, Any], path: Sequence[str]) -> Any:
    """Safely walk a nested dict by a sequence of keys.

    :param data: TMDb JSON response mapping.
    :param path: Sequence of keys, e.g. ("tagline",).
    :return: Value at path or None if missing or incompatible.
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
    """Convert a list of field specs into a logical_name → path mapping.

    :param field_specs: Iterable of "field" or (logical_name, path_tuple) specs.
    :return: Mapping of logical field names to JSON key paths.
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
) -> dict[str, Any]:
    """Fetch selected TMDb fields for a given kind/id.

    :param kind: Logical kind, e.g. "tvshow" or "movie".
    :param tmdb_id: TMDb numeric identifier.
    :param fields: Iterable of logical field names to fetch, or None for all.
    :param language: Optional TMDb language code (e.g. "en-US").
    :return: Dict of {logical_field_name: value} for resolved fields.
    """
    if tmdb_id <= 0:
        log.debug(f"fetch_tmdb_fields → invalid tmdb_id={tmdb_id} for kind={kind}",)
        return {}

    client = get_tmdb_client(language=language or "en-US")
    if not client:
        return {}

    kind_map = TMDB_PROPERTIES.get(kind)
    if not kind_map:
        log.debug(f"fetch_tmdb_fields → unknown kind={kind}, skipping TMDB lookup.")
        return {}

    endpoint = kind_map["endpoint"].format(id=tmdb_id)
    field_specs = kind_map["fields"]
    field_map = _build_field_map(field_specs)
    append_blocks = list(kind_map.get("append") or [])

    if fields is None:
        requested = list(field_map.keys())
    else:
        requested = [name for name in fields if name in field_map]
        unknown = sorted(set(fields) - set(field_map))
        if unknown:
            log.debug(f"fetch_tmdb_fields → unknown fields for kind={kind}: {unknown}")

    if not requested:
        log.debug(f"fetch_tmdb_fields → no valid fields requested for kind={kind}")
        return {}

    params = {}
    if append_blocks:
        params["append_to_response"] = ",".join(sorted(set(append_blocks)))

    lang_for_images = language or client.language
    preferred_iso = None
    if lang_for_images:
        preferred_iso = lang_for_images.split("-")[0].lower()

    if preferred_iso:
        params["include_image_language"] = f"{preferred_iso},null"

    data = client.get_json(endpoint, params=params)
    if not data:
        return {}

    result = {}
    for name in requested:
        path = field_map[name]
        value = _extract_path(data, path)
        if value is not None:
            result[name] = value

    log.debug(f"fetch_tmdb_fields(kind={kind}, tmdb_id={tmdb_id}) → {result}")
    return result


def tmdb_to_canonical(
    kind: str,
    tmdb_id: int,
    allowed: set[str] | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Fetch TMDb data and normalise to the JSON-style canonical dict.

    :param kind: Logical kind name (e.g. "movie", "tvshow").
    :param tmdb_id: TMDb numeric identifier.
    :param allowed: Optional whitelist of VideoInfoTag keys to include.
    :param language: Optional TMDb language code (e.g. "en-US").
    :return: Canonical item dict compatible with json_to_canonical().
    """
    raw = fetch_tmdb_fields(kind=kind, tmdb_id=tmdb_id, fields=None, language=language)
    if not raw:
        return {}

    item = {
        "file": "tmdb",
        "art": {},
        "properties": {},
    }

    # Use two-letter ISO code for image language matching (e.g. "en" from "en-US").
    # Always fall back to a sane default ("en-US") so we never drop valid EN artwork.
    effective_lang = language or ADDON.getSetting("tmdb_language") or "en-US"
    preferred_iso = effective_lang.split("-")[0].lower()

    for logical_name, value in raw.items():
        if value is None:
            continue

        spec = TMDB_FIELD_MAP.get(logical_name)
        if not spec:
            continue

        target = spec["target"]
        label = spec["label"]

        transform_name = spec.get("transform")
        if transform_name:
            value = apply_tmdb_transform(transform_name, value)

        if target == "info":
            if allowed and label not in allowed:
                continue
            item[label] = value
            continue

        if target == "property":
            item["properties"][label] = str(value)
            continue

        if target != "art":
            log.debug(f"tmdb_to_canonical → unsupported target={target} for field={logical_name}")
            continue

        # ---------- Artwork handling ----------
        kind_hint = spec.get("kind")

        # Simple image fields (poster_path / backdrop_path).
        if kind_hint == "image":
            url = build_tmdb_image_url(str(value))
            if url:
                item["art"][label] = url
            continue

        # Language-aware image lists for images.* fields.
        if kind_hint == "image_list":
            limit = spec.get("limit")

            # Posters: lang → poster; None → keyart.
            if logical_name == "images_posters":
                lang_items, none_items = split_tmdb_images_by_language(
                    value, preferred_iso
                )
                poster_urls = build_tmdb_image_url_list(lang_items, limit=limit)
                keyart_urls = build_tmdb_image_url_list(none_items, limit=limit)
                assign_image_list_to_art(item["art"], "poster", poster_urls)
                assign_image_list_to_art(item["art"], "keyart", keyart_urls)
                continue

            # Backdrops: None → fanart; lang → landscape.
            if logical_name == "images_backdrops":
                lang_items, none_items = split_tmdb_images_by_language(
                    value, preferred_iso
                )
                fanart_urls = build_tmdb_image_url_list(none_items, limit=limit)
                landscape_urls = build_tmdb_image_url_list(lang_items, limit=limit)
                assign_image_list_to_art(item["art"], "fanart", fanart_urls)
                assign_image_list_to_art(item["art"], "landscape", landscape_urls)
                continue

            # Logos: prefer language-matched, fall back to language-none.
            if logical_name == "images_logos":
                lang_items, none_items = split_tmdb_images_by_language(
                    value, preferred_iso
                )
                logo_items = lang_items or none_items
                logo_urls = build_tmdb_image_url_list(logo_items, limit=limit)
                assign_image_list_to_art(item["art"], "clearlogo", logo_urls)
                continue

            # Fallback: treat as a simple image list for the given label.
            urls = build_tmdb_image_url_list(value, limit=limit)
            assign_image_list_to_art(item["art"], label, urls)
            continue

        # Fallback: unexpected art kind, just store as string.
        item["art"][label] = str(value)

    # Sensible defaults for labels if not set by caller.
    if "Title" in item and not item.get("label"):
        item["label"] = str(item["Title"])
    if "TagLine" in item and not item.get("label2"):
        item["label2"] = str(item["TagLine"])

    log.debug(f"tmdb_to_canonical: (kind={kind}, tmdb_id={tmdb_id}) → {item}")
    return item


class TmdbClient:
    """Thin TMDb HTTP client supporting v3 and v4 authentication."""

    def __init__(self, token: str, language: str = "en-US") -> None:
        """Initialise the client with authentication and language.

        :param token: API key (v3) or read access token (v4).
        :param language: Default TMDb language parameter.
        """
        self.token = token.strip()
        self.language = language
        self.is_v4 = self.token.startswith("eyJ")  # JWT → v4 read token

        log.debug(f"{self.__class__.__name__} → using {'v4' if self.is_v4 else 'v3'} auth")

    def _build_request(
        self,
        path: str,
        params: dict | None = None,
    ) -> urllib.request.Request:
        """Build an authenticated HTTP request for a TMDb endpoint.

        :param path: TMDb path starting with "/3/...".
        :param params: Optional query parameter mapping.
        :return: Prepared urllib Request instance.
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

    def get_json(self, path: str, params: dict | None = None) -> dict:
        """Send a GET request and decode the JSON response.

        :param path: TMDb path starting with "/3/...".
        :param params: Optional query parameter mapping.
        :return: Parsed JSON dict or empty dict on error.
        """
        request = self._build_request(path, params)
        try:
            with urllib.request.urlopen(request, timeout=10) as resp:
                data = resp.read().decode("utf-8")
                return json.loads(data)
        except HTTPError as exc:
            log.error(
                f"{ self.__class__.__name__}: TMDb HTTPError {exc.code} for {path}: {exc.reason}"
            )
        except URLError as exc:
            log.error(
                f"{self.__class__.__name__}: TMDb URLError for {path}: {exc.reason}"
            )
        except Exception as exc:  # noqa: BLE001
            log.error(
                f"{self.__class__.__name__}: TMDb unexpected error for {path}: {exc}"
            )

        return {}
