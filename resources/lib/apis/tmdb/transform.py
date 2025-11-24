# author: realcopacetic
from __future__ import annotations

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
from resources.lib.shared.utilities import ADDON


_CACHE = TmdbCache()

# ---------------------------------------------------------------------------
# Artwork shaping configuration
# ---------------------------------------------------------------------------

# For TMDb image *lists* (e.g. images.posters/backdrops/logos),
# we describe how to split the list into "buckets" and which bucket
# maps to which Kodi art label.
#
# Buckets:
#   - "lang"          → language-matched entries
#   - "none"          → entries with no language tag
#   - "lang_or_none"  → language-matched, else fall back to none
#   - "all"           → entire list (no language split)
#
# Each entry in the list is: (art_label, bucket_name)
IMAGE_LIST_ROLES: dict[str, list[tuple[str, str]]] = {
    # Posters: lang → poster, none → keyart
    "images_posters": [
        ("poster", "lang"),
        ("keyart", "none"),
    ],
    # Backdrops: none → fanart, lang → landscape
    "images_backdrops": [
        ("fanart", "none"),
        ("landscape", "lang"),
    ],
    # Logos: prefer lang, fall back to none → clearlogo
    "images_logos": [
        ("clearlogo", "lang_or_none"),
    ],
    # Any other "images_*" fields will fall back to "all" → label.
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _preferred_iso(language: str | None) -> str:
    """
    Return the two-letter ISO code for an input language like 'en-US'.

    Falls back to an empty string if the language is not provided.
    """
    if not language:
        return ""
    return language.split("-")[0].lower()


def _handle_image_art(
    label: str,
    value: Any,
    art: dict[str, Any],
) -> None:
    """Handle simple 'image' kind artwork (single TMDb path → one URL)."""
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
    Given a bucket name and language-split lists, return the appropriate source list.
    """
    if bucket == "lang":
        return lang_items
    if bucket == "none":
        return none_items
    if bucket == "lang_or_none":
        return lang_items or none_items
    # "all" or unknown => use the raw list value
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
    Generic handler for 'image_list' artwork.

    Uses IMAGE_LIST_ROLES to decide how to map the raw TMDb list to one or more
    Kodi art labels with language-aware prioritisation.
    """
    roles = IMAGE_LIST_ROLES.get(logical_name)

    # If we have a role definition, we need language splitting.
    if roles:
        lang_items, none_items = split_tmdb_images_by_language(
            value,
            preferred_iso,
        )
        for art_label, bucket in roles:
            items = _select_bucket_items(bucket, value, lang_items, none_items)
            urls = build_tmdb_image_url_list(items, limit=limit)
            assign_image_list_to_art(art, art_label, urls)
        return

    # Fallback: no special shaping requested for this logical_name.
    # Just treat the entire list as belonging to the given label.
    urls = build_tmdb_image_url_list(value, limit=limit)
    assign_image_list_to_art(art, label, urls)


def _build_tmdb_canonical_item(
    kind: str,
    tmdb_id: int,
    raw: Mapping[str, Any],
    language: str,
) -> dict[str, Any]:
    """
    Build the canonical TMDb payload from raw logical TMDb fields.

    Canonical format:

        {
            "file": "tmdb",
            "art": {...},
            "properties": {...},
            <info fields...>
        }

    Artwork shaping (posters/backdrops/logos) is handled by generic helpers
    with configuration in IMAGE_LIST_ROLES.
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
            log.debug(
                f"tmdb_to_canonical → unsupported target={target} "
                f"for field={logical_name}"
            )
            continue

        kind_hint = spec.get("kind")

        # Simple single-path image.
        if kind_hint == "image":
            _handle_image_art(label, value, art)
            continue

        # Image lists with language awareness and shaping described in IMAGE_LIST_ROLES.
        if kind_hint == "image_list":
            limit = spec.get("limit")
            _handle_image_list_art(
                logical_name=logical_name,
                label=label,
                value=value,
                art=art,
                preferred_iso=preferred_iso,
                limit=limit,
            )
            continue

        # Fallback: unexpected art kind, just store as string.
        art[label] = str(value)

    return item


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def tmdb_to_canonical(
    kind: str,
    tmdb_id: int,
    language: str | None = None,
) -> dict[str, Any]:
    """
    Fetch TMDb data and normalise to the JSON-style canonical dict.

    :param kind: Logical kind name (e.g. "movie", "tvshow").
    :param tmdb_id: TMDb numeric identifier.
    :param language: Optional TMDb language code (e.g. "en-US"). If not provided,
                     falls back to the addon "tmdb_language" setting or "en-US".
    :return: Canonical item dict compatible with json_to_canonical() and set_items().
    """
    if tmdb_id <= 0:
        log.debug(f"tmdb_to_canonical → invalid tmdb_id={tmdb_id} for kind={kind}")
        return {}

    language_key = language or ADDON.getSetting("tmdb_language") or "en-US"

    # ---- 1) Try cache -------------------------------------------------------
    cached = _CACHE.get(kind, tmdb_id, language_key)
    if cached:
        log.debug(
            f"tmdb_to_canonical (cache): kind={kind}, tmdb_id={tmdb_id} → {cached}"
        )
        return cached

    # ---- 2) Fresh fetch -----------------------------------------------------
    raw = fetch_tmdb_fields(
        kind=kind,
        tmdb_id=tmdb_id,
        fields=None,
        language=language_key,
    )
    if not raw:
        return {}

    item = _build_tmdb_canonical_item(
        kind=kind,
        tmdb_id=tmdb_id,
        raw=raw,
        language=language_key,
    )

    # ---- 3) Store full canonical payload in cache ---------------------------
    _CACHE.set(kind, tmdb_id, language_key, item)

    log.debug(f"tmdb_to_canonical (fresh): kind={kind}, tmdb_id={tmdb_id} → {item}")
    return item