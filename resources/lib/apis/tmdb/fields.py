# author: realcopacetic

from typing import Any, Iterable, Mapping

from resources.lib.shared import logger as log


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
            "created_by",
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
    "season": {
        "endpoint": "/tv/{id}/season/{season_number}",
        "append": [],
        "fields": [
            ("season_overview", ("overview",)),
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
    "created_by": {
        "target": "info",
        "label": "Writers",
        "transform": "extract_creator_names",
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
    "season_overview": {
        "target": "info",
        "label": "Plot",
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
YOUTUBE_PLUGIN_BASE = "plugin://plugin.video.youtube/play/?video_id="
TMDB_TRANSFORMS: tuple[str, ...] = (
    "year_from_date",
    "first_runtime_from_list",
    "pick_best_trailer",
    "extract_creator_names",
)


def apply_tmdb_transform(name: str, value: Any) -> Any:
    """
    Apply a named TMDb transform function to a value.

    :param name: Transform identifier (for example, "year_from_date").
    :param value: Raw value extracted from TMDb JSON.
    :return: Transformed value, or original value if unknown or invalid.
    """
    if name not in TMDB_TRANSFORMS:
        log.debug(f"apply_tmdb_transform → unknown {name=}, {value=}")
        return value

    func = globals().get(name)
    if callable(func):
        return func(value)

    log.debug(f"apply_tmdb_transform → missing callable for {name=}, {value=}")
    return value


def extract_creator_names(value: Any) -> list[str]:
    """
    Extract a list of creator names from a TMDb created_by array.

    :param value: Raw created_by field value from TMDb JSON.
    :return: List of non-empty creator name strings.
    """
    if not isinstance(value, list):
        return []

    names: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        name = item.get("name")
        if isinstance(name, str) and name:
            names.append(name)
    return names


def year_from_date(value: Any) -> int:
    """
    Convert a 'YYYY-MM-DD' or 'YYYY' date string into an integer year.

    :param value: Raw date string from TMDb JSON.
    :return: Parsed year as an int, or 0 if parsing fails.
    """
    if not isinstance(value, str) or not value:
        return 0

    year = value.split("-")[0]
    try:
        return int(year)
    except ValueError:
        return 0


def first_runtime_from_list(value: Any) -> int:
    """
    Extract the first runtime value (in minutes) from a list or scalar.

    :param value: List of runtimes or a single runtime value.
    :return: First runtime as an int, or 0 if conversion fails.
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
    """
    Select the best trailer URL from a TMDb videos.results list.

    :param value: List of TMDb video dicts (videos.results).
    :return: YouTube plugin URL or raw key string, or empty string if none.
    """
    if not isinstance(value, list) or not value:
        return ""
    
    log.debug(f'FUCK DEBUG trailers {value=}')

    def score(item: Mapping[str, Any]) -> tuple[int, int, int, str]:
        site = str(item.get("site", "")).lower()
        type_ = str(item.get("type", "")).lower()
        official = bool(item.get("official", False))
        published = str(item.get("published_at", ""))

        is_youtube = 1 if site == "youtube" else 0
        is_trailer = 1 if type_ == "trailer" else 0
        is_official = 1 if official else 0

        return (is_youtube, is_trailer, is_official, published)

    best = max(value, key=score)

    key = best.get("key")
    site = str(best.get("site", "")).lower()
    if not key or not isinstance(key, str):
        return ""

    if site == "youtube":
        return f"{YOUTUBE_PLUGIN_BASE}{key}"

    return str(key)


def build_tmdb_image_url(path: str | None, size: str = "original") -> str:
    """
    Build a full TMDb image URL from a path fragment.

    :param path: File path from TMDb JSON (for example, "/abc123.jpg").
    :param size: TMDb size segment (for example, "original" or "w780").
    :return: Fully qualified image URL or empty string if path is falsy.
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
    """
    Build a list of TMDb image URLs from an images.* array.

    :param items: List of TMDb image dicts (each with a file_path).
    :param size: TMDb size segment applied to all URLs.
    :param limit: Optional maximum number of URLs to include.
    :return: List of resolved TMDb image URLs.
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
    """
    Split image dicts into language-matched and language-none buckets.

    :param items: List of TMDb image dicts with iso_639_1 keys.
    :param preferred_iso: Two-letter ISO code (for example, "en") or None.
    :return: Tuple of (language-matched list, language-none list).
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
    """
    Assign image URLs into an art dict using label, label1, label2, etc.

    :param art: Mutable art dictionary to update in place.
    :param label: Base artwork key name (for example, "fanart").
    :param urls: Iterable of image URLs to assign.
    """
    urls_list = [u for u in urls if u]
    if not urls_list:
        return

    if label not in art:
        art[label] = urls_list[0]

    for index, url in enumerate(urls_list[1:], start=1):
        art[f"{label}{index}"] = url
