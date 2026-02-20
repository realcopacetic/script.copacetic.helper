# author: realcopacetic

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


ART_FIELD_CACHE_KEY: str = "cache_key"
ART_FIELD_SOURCE_URL: str = "source_url"
ART_FIELD_PROCESS: str = "process"
ART_FIELD_HASH: str = "cached_file_hash"
ART_FIELD_PROCESSED: str = "processed_path"
ART_FIELD_BLUR_RADIUS: str = "blur_radius"
ART_FIELD_COLOR: str = "color"
ART_FIELD_ACCENT: str = "accent"
ART_FIELD_CONTRAST: str = "contrast"
ART_FIELD_LUMINOSITY: str = "luminosity"
ART_FIELD_DARKEN: str = "darken"
ART_FIELD_DARKEN_ELEMENT: str = "darken_element"
ART_FIELD_DARKEN_ELEMENT1: str = "darken_element1"
ART_FIELD_DARKEN_ELEMENT2: str = "darken_element2"
ART_FIELD_DARKEN_FRAME: str = "darken_frame"
ART_FIELD_DARKEN_MODE: str = "darken_mode"
ART_FIELD_DARKEN_RECTS: str = "darken_rects"
ART_FIELD_DARKEN_SOURCE: str = "darken_source"
ART_FIELD_DARKEN_TARGET: str = "darken_target"

ART_FIELDS_DARKEN_ELEMENT: tuple[str, ...] = (
    ART_FIELD_DARKEN_ELEMENT,
    ART_FIELD_DARKEN_ELEMENT1,
    ART_FIELD_DARKEN_ELEMENT2,
)

ART_DB_SCHEMA: tuple[tuple[str, str], ...] = (
    (ART_FIELD_CACHE_KEY, "TEXT NOT NULL"),
    (ART_FIELD_SOURCE_URL, "TEXT NOT NULL"),
    (ART_FIELD_PROCESS, "TEXT NOT NULL"),
    (ART_FIELD_PROCESSED, "TEXT"),
    (ART_FIELD_HASH, "TEXT"),
    (ART_FIELD_BLUR_RADIUS, "INTEGER"),
    (ART_FIELD_COLOR, "TEXT"),
    (ART_FIELD_ACCENT, "TEXT"),
    (ART_FIELD_CONTRAST, "TEXT"),
    (ART_FIELD_LUMINOSITY, "INTEGER"),
    (ART_FIELD_DARKEN, "INTEGER"),
    *((field, "INTEGER") for field in ART_FIELDS_DARKEN_ELEMENT),
    (ART_FIELD_DARKEN_FRAME, "TEXT"),
    (ART_FIELD_DARKEN_MODE, "TEXT"),
    (ART_FIELD_DARKEN_RECTS, "TEXT"),
    (ART_FIELD_DARKEN_SOURCE, "TEXT"),
    (ART_FIELD_DARKEN_TARGET, "TEXT"),
)
ART_DB_UNIQUE: tuple[str, ...] = (ART_FIELD_CACHE_KEY,)

ART_DB_INDEXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("idx_source_url", (ART_FIELD_SOURCE_URL,)),
)

ART_DB_FIELDS: tuple[str, ...] = tuple(name for name, _ in ART_DB_SCHEMA)

ART_LISTITEM_KEYS: tuple[str, ...] = (
    ART_FIELD_PROCESSED,
    ART_FIELD_BLUR_RADIUS,
    ART_FIELD_COLOR,
    ART_FIELD_ACCENT,
    ART_FIELD_CONTRAST,
    ART_FIELD_LUMINOSITY,
    ART_FIELD_DARKEN,
) + ART_FIELDS_DARKEN_ELEMENT

ART_SOURCE_KEYS: dict[str, tuple[str, ...]] = {
    "fanart": ("fanart", "tvshow.fanart", "artist.fanart", "thumb"),
    "clearlogo": ("clearlogo", "clearlogo-alt", "clearlogo-billboard"),
}

ART_PROCESS_MAP: dict[str, tuple[str, ...]] = {
    "clearlogo": ("crop", "analyze"),
    "background": ("blur", "analyze", "darken"),
    "icon": ("blur", "analyze", "darken"),
}


def filter_db_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    """
    Filter a record down to DB-safe fields only.

    :param row: Full record dict.
    :return: Dict restricted to ART_DB_FIELDS with None removed.
    """
    return {k: row.get(k) for k in ART_DB_FIELDS if row.get(k) is not None}


def filter_listitem_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    """
    Filter a record down to ListItem-export fields only.

    :param row: Full record dict.
    :return: Dict restricted to export keys/prefixes with None removed.
    """
    return {k: v for k, v in row.items() if k in ART_LISTITEM_KEYS and v is not None}


def flatten_art_attributes(
    records: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """
    Flatten canonical records into ListItem.Art-style keys.
    processed_path -> "{prefix}"
    others -> "{prefix}_{key}"
    """
    return {
        (prefix if key == ART_FIELD_PROCESSED else f"{prefix}_{key}"): value
        for prefix, record in (records or ())
        for key, value in filter_listitem_payload(record).items()
        if value is not None
    }


def resolve_art_type(art: dict, art_type: str) -> dict[str, str]:
    """
    Choose the best artwork path for a target art_type using ART_SOURCE_KEYS priority,
    with special episode-friendly fanart heuristic.

    :param art: Kodi-style dict of available art {key: path}
    :param art_type: role to resolve (e.g., "fanart", "clearlogo")
    :return: Mapping {published_key: path} or {}.
    """
    keys = ART_SOURCE_KEYS.get(art_type, (art_type,))

    # Episode-friendly heuristic: prefer thumb if fanart mirrors tvshow.fanart
    if art_type == "fanart":
        thumb = art.get("thumb")
        fanart = art.get("fanart")
        tv_fanart = art.get("tvshow.fanart")
        if thumb and (not fanart or (tv_fanart and fanart == tv_fanart)):
            return {"fanart": thumb}

    # Return first valid path from priority list (or from art_type itself)
    path = next((art[k] for k in keys if art.get(k)), art.get(art_type, "")) or ""
    return {art_type: path} if path else {}


@dataclass(frozen=True)
class ColorConfig:
    """Tunable parameters for colour analysis, contrast, and readability."""

    # --- Sampling & Palette ---
    palette_size: int = 8  # Adaptive palette size (lower = faster, smoother)
    sample_size: int = 64  # Downsample size for palette sampling (SxS square)
    avg_downsample: int = 32  # Downsample size for mean RGB/luminance sampling
    avg_grid: int = 6  # Grid resolution (GxG) used to locate brightest cell
    crop_target_size: tuple[int, int] = (1600, 620)  # Downsample size for crop
    blur_target_size: tuple[int, int] = (480, 270)  # Downsample size for blur
    blur_radius: int = 50  # Gaussian blur radius in pixels for blur

    # --- Filtering thresholds ---
    skip_whites: bool = True  # ignore white-ish swatches unless overwhelmingly dominant
    skip_blacks: bool = True  # ignore black-ish swatches unless overwhelmingly dominant
    dominance_allow_threshold: float = 0.70  # allow skipped extremes if ≥70% of pixels
    alpha_opaque_min: int = 65  # alpha cutoff (0–255) for treating pixels as opaque
    near_white: int = 245  # per-channel threshold for considering a swatch “near white”
    near_black: int = 10  # per-channel threshold for considering a swatch “near black”

    # --- Accent extraction ---
    freq_distance_norm: float = 255.0  # normalization factor for RGB distance (Δ/255)
    accent_weight: dict[str, float] = (
        field(  # weights for accent scoring: freq, sat, dist
            default_factory=lambda: {"freq": 0.5, "sat": 0.3, "dist": 0.2}
        )
    )
    accent_freq_exponent: float = 0.5  # gamma exponent to flatten dominance (0.5=sqrt)
    accent_freq_floor: float = 0.06  # ignore swatches contributing <6% of counts
    accent_min_dist: int = 28  # min RGB Euclidean distance from dominant for accent
    accent_stdev_floor: float = 3.0  # px stdev threshold: lower, quicker early exit
    accent_dom_share_cutoff: float = 0.85  # skip accent if dom color covers ≥85% px

    # --- Contrast & Lightness ---
    contrast_shift: float = 0.3  # lightness delta for contrast colour (0.3–0.5 typical)
    contrast_midpoint: float = 0.5  # HLS pivot; lighten if L < pivot else darken
    min_lightness: float = 0.0  # lower clamp for HLS lightness when adjusting contrast
    max_lightness: float = 1.0  # upper clamp for HLS lightness when adjusting contrast

    # --- Background sampling / luminance ---
    bg_frame: tuple[int, int] = (1920, 1080)  # Fallback artwork size
    bg_sampling_topk: float = 0.10  # used when mode == "topk"
    target_contrast_ratio: float = 4.5  # contrast ratio target (4.5 normal, 3.0 large)

    # --- Red leniency / guard rails ---
    red_relax_enable: bool = True  # enable hue-aware leniency for reds on dark bg
    red_hue_center: float = 0.0  # 0.0 == red hue in [0..1] (colorsys)
    red_hue_window: float = 0.06  # ± hue window around red (~±22°)
    red_min_target: float = 2.7  # never demand higher ratio when red rule applies
    red_relax_cap: float = 3.0  # max target when relaxing reds on dark bg
    red_bg_floor: float = 0.06  # if L_bg below this, treat as “already dark”

    # --- Readability (element overlay) ---
    element_overlay_color: str = "fff0efef"  # colour for readability checks (ARGB hex)
    element_overlay_rect: tuple[int, int, int, int] = (
        120,
        660,
        1680,
        360,
    )  # (x, y, w, h) region
    element_complexity_stddev: float = 20.0  # max patch stddev to treat as "simple"

    # --- Save settings ---
    jpeg_quality: int = 80  # quality (1–95); higher = better, slower
    jpeg_optimize: bool = False  # smaller files, slower saves
    jpeg_progressive: bool = False  # progressive encoding; slower
    jpeg_subsampling: str = "4:2:0"  # color detail vs size ("4:4:4" = best)
    png_optimize: bool = False  # smaller files, slower saves
    png_compress_level: int = 3  # 0–9 (0 fastest, 9 smallest)
