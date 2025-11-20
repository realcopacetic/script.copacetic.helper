# author: realcopacetic

from __future__ import annotations

from typing import Any, Iterable, Mapping

from resources.lib.shared import logger as log

"""
TMDb mapping configuration.

TMDB_PROPERTIES:
    Per-kind configuration:
        - endpoint: TMDb path with {id} placeholder.
        - append:   list of TMDb append_to_response block names (optional).
        - fields:   list of field specs, where each element is either:
            * "field_name" → logical name == JSON key, path=("field_name",)
            * ("logical_name", ("path", "to", "value")).

    The logical field names produced by TMDB_PROPERTIES must match the keys
    in TMDB_FIELD_MAP below.

TMDB_FIELD_MAP:
    Mapping of logical field name → spec dict:

        {
            "target":    "info" | "art" | "property",
            "label":     VideoInfoTag key / art key / property name,
            "kind":      optional hint for art ("image" | "image_list"),
            "transform": optional transform name (string),
            "info_label": optional VideoInfoTag label for dual mapping.
        }

    This is the TMDb analogue of JSON_FIELD_MAP on the JSON-RPC side.
"""

TMDB_PROPERTIES: dict[str, dict[str, Any]] = {
    "movie": {
        "endpoint": "/movie/{id}",
        "append": ["images", "videos"],
        "fields": [
            "original_title",
            "title",
            "overview",
            "tagline",
            "release_date",
            "runtime",
            "budget",
            "revenue",
            "backdrop_path",
            "poster_path",
            ("images_backdrops", ("images", "backdrops")),
            ("images_logos", ("images", "logos")),
            ("images_posters", ("images", "posters")),
            ("videos_results", ("videos", "results")),
        ],
    },
    "tvshow": {
        "endpoint": "/tv/{id}",
        "append": ["images", "videos"],
        "fields": [
            "name",
            "original_name",
            "overview",
            "tagline",
            "episode_run_time",
            "first_air_date",
            ("next_episode_air_date", ("next_episode_to_air", "air_date")),
            "backdrop_path",
            "poster_path",
            ("images_backdrops", ("images", "backdrops")),
            ("images_logos", ("images", "logos")),
            ("images_posters", ("images", "posters")),
            ("videos_results", ("videos", "results")),
        ],
    },
}

TMDB_FIELD_MAP: dict[str, dict[str, Any]] = {
    "backdrop_path": {
        "target": "art",
        "label": "fanart",
        "kind": "image",
    },
    "budget": {
        "target": "property",
        "label": "tmdb_budget",
    },
    "episode_run_time": {
        "target": "info",
        "label": "Duration",
        "transform": "first_runtime_from_list",
    },
    "first_air_date": {
        "target": "info",
        "label": "Year",
        "transform": "year_from_date",
    },
    "images_backdrops": {
        "target": "art",
        "label": "fanart",
        "kind": "image_list",
        "limit": 10,
    },
    "images_logos": {
        "target": "art",
        "label": "clearlogo",
        "kind": "image_list",
        "limit": 5,
    },
    "images_posters": {
        "target": "art",
        "label": "keyart",
        "kind": "image_list",
        "limit": 10,
    },
    "name": {
        "target": "info",
        "label": "Title",
    },
    "next_episode_air_date": {
        "target": "property",
        "label": "tmdb_next_air_date",
    },
    "original_name": {
        "target": "info",
        "label": "OriginalTitle",
    },
    "original_title": {
        "target": "info",
        "label": "OriginalTitle",
    },
    "overview": {
        "target": "info",
        "label": "Plot",
    },
    "poster_path": {
        "target": "art",
        "label": "poster",
        "kind": "image",
    },
    "release_date": {
        "target": "info",
        "label": "Year",
        "transform": "year_from_date",
    },
    "revenue": {
        "target": "property",
        "label": "tmdb_revenue",
    },
    "runtime": {
        "target": "info",
        "label": "Duration",
    },
    "tagline": {
        "target": "info",
        "label": "TagLine",
    },
    "title": {
        "target": "info",
        "label": "Title",
    },
    "videos_results": {
        "target": "info",
        "label": "Trailer",
        "transform": "pick_best_trailer",
    },
}
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"
YOUTUBE_BASE_URL = "https://www.youtube.com/watch"


def apply_tmdb_transform(name: str, value: Any) -> Any:
    """Apply a named TMDb transform to a value.

    :param name: Transform identifier (e.g. "year_from_date").
    :param value: Raw value from TMDb JSON.
    :return: Transformed value or original if name is unknown.
    """
    if name == "year_from_date":
        return year_from_date(value)
    if name == "first_runtime_from_list":
        return first_runtime_from_list(value)
    if name == "pick_best_trailer":
        return pick_best_trailer(value)

    log.debug(f"apply_tmdb_transform → unknown transform={name}, value={value}")
    return value


def year_from_date(value: Any) -> int:
    """Convert 'YYYY-MM-DD' or 'YYYY' to an integer year.

    :param value: Date string from TMDb JSON.
    :return: Parsed year as int, or 0 if parsing fails.
    """
    if not isinstance(value, str) or not value:
        return 0

    year = value.split("-")[0]
    try:
        return int(year)
    except ValueError:
        return 0


def first_runtime_from_list(value: Any) -> int:
    """Extract the first runtime in minutes from a list.

    :param value: TMDb episode_run_time list or raw numeric value.
    :return: First runtime as int, or 0 on error.
    """
    if isinstance(value, (list, tuple)) and value:
        first = value[0]
        try:
            return int(first)
        except (TypeError, ValueError):
            return 0

    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def pick_best_trailer(value: Any) -> str:
    """Select the best trailer URL from a TMDb videos.results list.

    :param value: List of video dicts from TMDb (videos.results).
    :return: Trailer URL string or empty string if none can be built.
    """
    if not isinstance(value, list) or not value:
        return ""

    def score(item: Mapping[str, Any]) -> tuple[int, int, int, str]:
        site = str(item.get("site", "")).lower()
        type_ = str(item.get("type", "")).lower()
        official = bool(item.get("official", False))
        published = str(item.get("published_at", ""))

        is_youtube = 1 if site == "youtube" else 0
        is_trailer = 1 if type_ == "trailer" else 0
        is_official = 1 if official else 0
        # ISO 8601 strings sort lexicographically; later date = bigger string.
        return (is_youtube, is_trailer, is_official, published)

    best = max(value, key=score)

    key = best.get("key")
    site = str(best.get("site", "")).lower()

    if not key or not isinstance(key, str):
        return ""

    if site == "youtube":
        return f"{YOUTUBE_BASE_URL}?v={key}"

    return str(key)


def build_tmdb_image_url(path: str | None, size: str = "original") -> str:
    """Build a full TMDb image URL from a path fragment.

    :param path: Image path string from TMDb (e.g. "/abc123.jpg").
    :param size: TMDb size segment (e.g. "original", "w780").
    :return: Full image URL or empty string if path is falsy.
    """
    if not path:
        return ""
    if not path.startswith("/"):
        path = "/" + path
    return f"{TMDB_IMAGE_BASE}/{size}{path}"


def build_tmdb_image_url_list(
    items: Any,
    size: str = "original",
    limit: int | None = None,
) -> list[str]:
    """Build a list of TMDb image URLs from an images.* list.

    :param items: List of image dicts from TMDb (each with file_path).
    :param size: TMDb size segment for all URLs.
    :param limit: Optional maximum number of URLs to include.
    :return: List of full image URLs.
    """
    if not isinstance(items, list):
        return []

    urls: list[str] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        file_path = item.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            continue
        urls.append(build_tmdb_image_url(file_path, size=size))
        if limit is not None and len(urls) >= limit:
            break
    return urls


def split_tmdb_images_by_language(
    items: Any,
    preferred_iso: str | None,
) -> tuple[list[Mapping[str, Any]], list[Mapping[str, Any]]]:
    """Split TMDb image items into language-matched and language-none lists.

    :param items: List of TMDb image dicts (with iso_639_1 and file_path).
    :param preferred_iso: Two-letter language code (e.g. "en") or None.
    :return: Tuple of (lang_items, none_items).
    """
    if not isinstance(items, list):
        return ([], [])

    lang_items: list[Mapping[str, Any]] = []
    none_items: list[Mapping[str, Any]] = []

    pref = (preferred_iso or "").lower()

    for item in items:
        if not isinstance(item, Mapping):
            continue

        iso = item.get("iso_639_1")
        if iso is None:
            none_items.append(item)
            continue

        iso_str = str(iso).lower()
        if pref and iso_str == pref:
            lang_items.append(item)

    return (lang_items, none_items)


def assign_image_list_to_art(
    art: dict[str, str],
    label: str,
    urls: Iterable[str],
) -> None:
    """Assign image URLs into the art dict as label, label1, label2, ....

    :param art: Artwork dictionary to modify in place.
    :param label: Base art key (e.g. "fanart", "clearlogo").
    :param urls: Iterable of image URLs to assign.
    :return: None.
    """
    urls_list = [u for u in urls if u]
    if not urls_list:
        return

    if label not in art:
        art[label] = urls_list[0]

    for index, url in enumerate(urls_list[1:], start=1):
        art[f"{label}{index}"] = url
