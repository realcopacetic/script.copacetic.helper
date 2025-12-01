# author: realcopacetic

from typing import Any, Mapping

from resources.lib.apis.tmdb.cache import TmdbCache
from resources.lib.apis.tmdb.client import fetch_tmdb_fields
from resources.lib.apis.tmdb.fields import (
    TMDB_FIELD_MAP,
    apply_tmdb_transform,
    build_tmdb_image_url,
    build_tmdb_image_url_list,
    assign_image_list_to_art,
    split_tmdb_images_by_language,
)
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import ADDON, pretty_print


_CACHE = TmdbCache()
IMAGE_LIST_ROLES: dict[str, list[tuple[str, str]]] = {
    "images_posters": [
        ("poster", "lang"),
        ("keyart", "none"),
    ],
    "images_backdrops": [
        ("fanart", "none"),
        ("landscape", "lang"),
    ],
    "images_logos": [
        ("clearlogo", "lang_or_none"),
    ],
}


def tmdb_to_canonical(
    kind: str,
    tmdb_id: int,
    season_number: int | None = None,
    language: str | None = None,
    append_artwork: bool = True,
) -> dict[str, Any]:
    """
    Fetch TMDb data and normalise it into canonical Kodi item format.

    :param kind: TMDb logical kind (for example, 'movie', 'tvshow').
    :param tmdb_id: TMDb numeric identifier.
    :param season_number: Optional season number when kind == "season".
    :param language: Optional TMDb language override.
    :param append_artwork: If False, skip TMDb 'images' append block.
    :return: Canonical TMDb item dict or empty dict.
    """
    if tmdb_id <= 0:
        log.debug(f"TmdbClient → invalid {tmdb_id=} for {kind=}")
        return {}

    language_key = language or ADDON.getSetting("tmdb_language") or "en-US"
    cache_language = language_key if append_artwork else f"{language_key}|noart"
    cache_kind = (
        f"season_{season_number}"
        if kind == "season" and season_number is not None
        else kind
    )

    cached = _CACHE.get(cache_kind, tmdb_id, cache_language)
    if cached:
        log.debug(
            f"tmdb_to_canonical → Cache returned → {pretty_print(cached)}",
        )
        return cached

    raw = fetch_tmdb_fields(
        kind=kind,
        tmdb_id=tmdb_id,
        season_number=season_number,
        fields=None,
        language=language_key,
        append_artwork=append_artwork,
    )
    if not raw:
        return {}

    log.debug(f"tmdb_to_canonical → Fresh payload returned → {pretty_print(raw)}")
    item = _build_tmdb_canonical_item(
        kind=kind,
        tmdb_id=tmdb_id,
        raw=raw,
        language=language_key,
    )
    _CACHE.set(cache_kind, tmdb_id, cache_language, item)

    return item


def _build_tmdb_canonical_item(
    kind: str,
    tmdb_id: int,
    raw: Mapping[str, Any],
    language: str,
) -> dict[str, Any]:
    """
    Convert raw TMDb fields into canonical Kodi-compatible structure.

    :param kind: Logical TMDb kind ('movie', 'tvshow').
    :param tmdb_id: TMDb numeric identifier.
    :param raw: Resolved TMDb logical fields.
    :param language: TMDb language key used for fetching.
    :return: Canonical item dict for downstream handlers.
    """
    item: dict[str, Any] = {
        "file": "tmdb",
        "art": {},
        "properties": {},
    }

    art = item["art"]
    preferred_iso = _preferred_iso(language)

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
            item[label] = value
            continue

        if target == "property":
            item["properties"][label] = str(value)
            continue

        if target != "art":
            log.debug(f"tmdb_to_canonical → unsupported {target=} for {logical_name=}")
            continue

        kind_hint = spec.get("kind")

        if kind_hint == "image":
            _handle_image_art(label, value, art)
            continue

        if kind_hint == "image_list":
            _handle_image_list_art(
                logical_name=logical_name,
                label=label,
                value=value,
                art=art,
                preferred_iso=preferred_iso,
                limit=spec.get("limit"),
            )
            continue

        art[label] = str(value)

    return item


def _preferred_iso(language: str | None) -> str:
    """
    Extract a two-letter ISO language code.

    :param language: TMDb language code (e.g. 'en-US').
    :return: ISO code (e.g. 'en') or empty string.
    """
    if not language:
        return ""
    return language.split("-")[0].lower()


def _handle_image_art(
    label: str,
    value: Any,
    art: dict[str, Any],
) -> None:
    """
    Handle simple single-path TMDb images.

    :param label: Kodi art label to assign.
    :param value: Raw TMDb file_path string.
    :param art: Artwork dict to update in place.
    :return: None.
    """
    url = build_tmdb_image_url(str(value))
    if url:
        art[label] = url


def _select_bucket_items(
    bucket: str,
    value: Any,
    lang_items: list[Any],
    none_items: list[Any],
) -> list[Any]:
    """
    Select TMDb image entries for a named bucket.

    :param bucket: 'lang', 'none', 'lang_or_none', or 'all'.
    :param value: Raw TMDb list value.
    :param lang_items: Language-matched image entries.
    :param none_items: Language-none image entries.
    :return: Selected list of items.
    """
    if bucket == "lang":
        return lang_items
    if bucket == "none":
        return none_items
    if bucket == "lang_or_none":
        return lang_items or none_items
    return value or []


def _handle_image_list_art(
    logical_name: str,
    label: str,
    value: Any,
    art: dict[str, Any],
    preferred_iso: str,
    limit: int | None = None,
) -> None:
    """
    Handle TMDb image lists with language-aware shaping.

    :param logical_name: Logical TMDb field name (e.g. 'images_posters').
    :param label: Default Kodi art label for fallback behaviour.
    :param value: Raw TMDb images list.
    :param art: Artwork dict to update in place.
    :param preferred_iso: Two-letter ISO language code.
    :param limit: Optional maximum URL count.
    :return: None.
    """
    roles = IMAGE_LIST_ROLES.get(logical_name)

    if roles:
        lang_items, none_items = split_tmdb_images_by_language(value, preferred_iso)
        for art_label, bucket in roles:
            items = _select_bucket_items(bucket, value, lang_items, none_items)
            urls = build_tmdb_image_url_list(items, limit=limit)
            assign_image_list_to_art(art, art_label, urls)
        return

    urls = build_tmdb_image_url_list(value, limit=limit)
    assign_image_list_to_art(art, label, urls)
