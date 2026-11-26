# author: realcopacetic

from copy import deepcopy
from typing import Any, Mapping

from xbmcgui import Window

from resources.lib.apis.cache import DAY, Asides, Asker, cached, failure_ttl
from resources.lib.apis.http import HttpError
from resources.lib.apis.tmdb.client import (
    fetch_tmdb_fields,
    get_tmdb_client,
    tmdb_language,
)
from resources.lib.apis.tmdb.fields import (
    TMDB_FIELD_MAP,
    apply_tmdb_transform,
    assign_image_list_to_art,
    build_tmdb_image_url,
    build_tmdb_image_url_list,
    filter_tmdb_images_by_size,
    split_tmdb_images_by_language,
)
from resources.lib.shared import logger as log
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import plugin_path, window_property

EPISODE_KEYS = ("file", "art", "properties", "Trailer")  # show-level, fit an episode
TTL_HIT, TTL_MISSING = 7 * DAY, DAY
TOKEN_REFUSED = "tmdb_token_refused"  # Home property: the warning logs once a session
ASIDE_WORKERS = 2  # items fetched aside at once, keyed by tmdb_to_canonical's args


IMAGE_LIST_ROLES = {
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
# Smallest image kept per list, at exactly its shape: TMDb's small or odd-sized
# uploads are mostly poor (Ash, 3 Nov 2026). Logos come in every shape.
IMAGE_LIST_MIN_SIZES = {
    "images_backdrops": (1920, 1080),
    "images_posters": (1000, 1500),
}


def tmdb_to_canonical(
    kind: str,
    tmdb_id: int,
    season_number: int | None = None,
    language: str | None = None,
    append_artwork: bool = True,
    cache_only: bool = False,
    aside: Asker | None = None,
) -> dict[str, Any]:
    """
    Fetch TMDb data and normalise it into canonical Kodi item format, cached in
    api_cache; failures are cached briefly and an expired item is served meanwhile.

    :param kind: TMDb logical kind ('movie', 'tvshow', 'season', 'episode').
    :param tmdb_id: TMDb numeric identifier (the show's for an episode).
    :param season_number: Optional season number when kind == "season".
    :param language: Optional TMDb language override.
    :param append_artwork: If False, skip TMDb 'images' append block.
    :param cache_only: Serve the cached item, even expired; never fetch.
    :param aside: Serve the cached item, fetching aside; it is called on news.
    :return: Canonical TMDb item dict or empty dict.
    """
    return tmdb_lookup(
        kind, tmdb_id, season_number, language, append_artwork, cache_only, aside
    )[0]


def tmdb_lookup(
    kind: str,
    tmdb_id: int,
    season_number: int | None,
    language: str | None,
    append_artwork: bool,
    cache_only: bool,
    aside: Asker | None,
) -> tuple[dict[str, Any], bool]:
    """
    tmdb_to_canonical's item (the same arguments) and whether it was asked aside,
    missing or stale: known as it asks, however soon that fetch ends.
    """
    if tmdb_id <= 0:
        log.debug(f"tmdb_to_canonical → invalid {tmdb_id=} for {kind=}")
        return {}, False
    if kind == "episode":  # no episode lookup: never the show's Title or Plot
        show, asked = tmdb_lookup(
            "tvshow", tmdb_id, None, language, append_artwork, cache_only, aside
        )
        return {key: show[key] for key in EPISODE_KEYS if key in show}, asked

    language_key = tmdb_language(language)
    if not (client := get_tmdb_client(language_key)):  # off: not even the cache
        return {}, False
    cache_kind = (
        f"season_{season_number}"
        if kind == "season" and season_number is not None
        else kind
    )

    cache = ApiCacheHandler()
    key = f"tmdb:{cache_kind}:{tmdb_id}:{language_key}"
    full = None
    if not append_artwork:
        full, fresh = cache.get(key) or (None, False)
        if full and fresh:  # the art-bearing entry is a superset
            return full, False
        key += "|noart"
    payload, fresh = cache.get(key) or (None, False)
    if fresh:
        return payload or full or {}, False
    # Both stale: the art entry, which the metadata serve renews with TMDb multiart on
    # (off, it renews |noart, so an older art entry wins until that one is fresh)
    if cache_only or aside:
        if aside:  # a served call: the network never holds the pipeline
            args = kind, tmdb_id, season_number, language, append_artwork
            # A copy: the caller changes the answer it is handed (metadata's trailers)
            ASIDES.ask(args, aside, deepcopy(full or payload or {}))
        return full or payload or {}, bool(aside)

    try:
        raw = fetch_tmdb_fields(
            client,
            kind=kind,
            tmdb_id=tmdb_id,
            season_number=season_number,
            append_artwork=append_artwork,
        )
    except HttpError as exc:
        if exc.status in (401, 403) and not Window(10000).getProperty(TOKEN_REFUSED):
            window_property(TOKEN_REFUSED, exc.status)  # the failure the user can fix
            log.warning(f"tmdb_to_canonical → TMDb refused the token ({exc.status})")
        # Both stale: the art entry first, as a cache-only read (with multiart off an
        # older one can win until |noart is renewed), kept in |noart for the wait
        payload = full or payload
        # The stale item, else a negative entry
        cache.put(key, payload, failure_ttl(exc, TTL_MISSING))
        return payload or {}, False
    if not raw:
        return {}, False

    log.debug(f"tmdb_to_canonical → fetched {cache_kind}/{tmdb_id}")
    item = _build_tmdb_canonical_item(raw=raw, language=language_key)
    cache.put(key, item, TTL_HIT)
    return item, False


def creator_shows(person_id: str) -> list[dict[str, Any]]:
    """
    The TV shows a TMDb person created (their tv_credits crew credited "Creator"),
    by TMDb id with their names; cached as an item is, empty with TMDb off.

    :param person_id: TMDb person id.
    :return: {"id": TMDb TV show id, "names": [name, original name]} per show.
    """
    if not (client := get_tmdb_client()):
        return []

    def fetch() -> list[dict[str, Any]]:
        crew = client.get_json(f"/person/{person_id}/tv_credits")["crew"]
        shows = {
            show["id"]: sorted({show["name"], show["original_name"]})
            for show in crew
            if show["job"] == "Creator"
        }
        return [{"id": tv, "names": names} for tv, names in sorted(shows.items())]

    return cached(f"tmdb:creator:{person_id}", fetch, (TTL_HIT, TTL_MISSING)) or []


# Items fetched for served calls: tmdb_to_canonical's positional args are the key; a
# dead network keeps the stale answer, which is no news
ASIDES = Asides(lambda args, live: tmdb_to_canonical(*args), ASIDE_WORKERS)


def _build_tmdb_canonical_item(
    raw: Mapping[str, Any],
    language: str,
) -> dict[str, Any]:
    """
    Convert raw TMDb fields into canonical Kodi-compatible structure.

    :param raw: Resolved TMDb logical fields.
    :param language: TMDb language key used for fetching.
    :return: Canonical item dict for downstream handlers.
    """
    item = {
        "file": plugin_path("tmdb"),
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
    Handle TMDb image lists with language-aware shaping, keeping backdrops and
    posters of IMAGE_LIST_MIN_SIZES' shape and size; a backdrop_path or poster_path
    image in the unfiltered list is left to it, any other stays first.

    :param logical_name: Logical TMDb field name (e.g. 'images_posters').
    :param label: Default Kodi art label for fallback behaviour.
    :param value: Raw TMDb images list.
    :param art: Artwork dict to update in place.
    :param preferred_iso: Two-letter ISO language code.
    :param limit: Optional maximum URL count.
    """
    roles = IMAGE_LIST_ROLES.get(logical_name)
    listed = set(build_tmdb_image_url_list(value))
    if minimum := IMAGE_LIST_MIN_SIZES.get(logical_name):
        value = filter_tmdb_images_by_size(value, minimum)

    if roles:
        lang_items, none_items = split_tmdb_images_by_language(value, preferred_iso)
        for art_label, bucket in roles:
            # backdrop_path or poster_path in the list: the filtered list decides
            if minimum and art.get(art_label) in listed:
                art.pop(art_label)
            items = _select_bucket_items(bucket, value, lang_items, none_items)
            urls = build_tmdb_image_url_list(items, limit=limit)
            assign_image_list_to_art(art, art_label, urls)
        return

    urls = build_tmdb_image_url_list(value, limit=limit)
    assign_image_list_to_art(art, label, urls)
