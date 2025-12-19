# author: realcopacetic

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping


ART_FIELD_CATEGORY: str = "category"
ART_FIELD_URL: str = "url"
ART_FIELD_HASH: str = "cached_file_hash"
ART_FIELD_PROCESSED: str = "processed_path"

ART_DB_FIELDS: tuple[str, ...] = (
    ART_FIELD_CATEGORY,
    ART_FIELD_URL,
    ART_FIELD_HASH,
    ART_FIELD_PROCESSED,
    "color",
    "accent",
    "contrast",
    "luminosity",
)

ART_LISTITEM_KEYS: tuple[str, ...] = (
    ART_FIELD_CATEGORY,
    ART_FIELD_PROCESSED,
    "color",
    "accent",
    "contrast",
    "luminosity",
    "darken",
)
ART_LISTITEM_PREFIXES: tuple[str, ...] = (
    "element_darken",  # element_darken1, element_darken2, ...
)

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
    return {
        k: v
        for k, v in row.items()
        if v is not None
        and (
            k in ART_LISTITEM_KEYS
            or any(k.startswith(p) for p in ART_LISTITEM_PREFIXES)
        )
    }


def flatten_art_attributes(
    records: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """
    Flatten canonical records into ListItem.Art-style keys.
    processed_path -> "{category}"
    others         -> "{category}_{key}"
    """
    return {
        (
            d[ART_FIELD_CATEGORY]
            if k == ART_FIELD_PROCESSED
            else f"{d[ART_FIELD_CATEGORY]}_{k}"
        ): v
        for d in records or ()
        for k, v in filter_listitem_payload(d).items()
        if k != ART_FIELD_CATEGORY
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
    palette_size: int = 8  # no. colours in adaptive palette (lower = faster, smoother)
    sample_size: int = 64  # downsample size for palette sampling (square SxS)
    avg_downsample: int = 32  # downsample size used when averaging RGB for luminance
    avg_grid: int = 6  # Resolution (GxG) used to locate brightest cell before averaging
    crop_target_size: tuple[int, int] = (1600, 620)  # Downsample res for crop
    blur_target_size: tuple[int, int] = (480, 270)  # Downsample res for blur
    blur_radius: int = 50  # Guassian blur strength (in pixels) for fanart blur

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

    # --- Readability (text overlay) ---
    text_overlay_colour: str = "fff0efef"  # colour for readability checks (ARGB hex)
    text_overlay_rect: tuple[int, int, int, int] = (
        120,
        660,
        1680,
        360,
    )  # (x, y, w, h) region
    target_contrast_ratio: float = 4.5  # WCAG target (4.5 normal, 3.0 large)
    overlay_default_frame: tuple[int, int] = (1920, 1080)  # Fallback artwork size
    text_complexity_stddev: float = 20.0

    # --- Red leniency / guard rails ---
    red_relax_enable: bool = True  # enable hue-aware leniency for reds on dark bg
    red_hue_center: float = 0.0  # 0.0 == red hue in [0..1] (colorsys)
    red_hue_window: float = 0.06  # ± hue window around red (~±22°)
    red_min_target: float = 2.7  # never demand higher ratio when red rule applies
    red_relax_cap: float = 3.0  # max target when relaxing reds on dark bg
    red_bg_floor: float = 0.06  # if L_bg below this, treat as “already dark”
    max_darken_cap: int = 85  # cap darken percent to avoid over-darkening

    # --- Save settings ---
    jpeg_quality: int = 80  # quality (1–95); higher = better, slower
    jpeg_optimize: bool = False  # smaller files, slower saves
    jpeg_progressive: bool = False  # progressive encoding; slower
    jpeg_subsampling: str = "4:2:0"  # color detail vs size ("4:4:4" = best)
    png_optimize: bool = False  # smaller files, slower saves
    png_compress_level: int = 3  # 0–9 (0 fastest, 9 smallest)
