# author: realcopacetic

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

ART_FIELD_CACHE_KEY = "cache_key"
ART_FIELD_SOURCE_URL = "source_url"
ART_FIELD_PROCESS = "process"
ART_FIELD_HASH = "cached_file_hash"
ART_FIELD_PROCESSED = "processed_path"
ART_FIELD_WIDTH = "width"
ART_FIELD_HEIGHT = "height"
ART_FIELD_BLUR_RADIUS = "blur_radius"
ART_FIELD_EDGE_TRIM = "edge_trim"
ART_FIELD_DARKEN = "darken"
ART_FIELD_DARKEN_FRAME = "darken_frame"
ART_FIELD_DARKEN_RECTS = "darken_rects"
ART_FIELD_DARKEN_LABEL = "darken_label"
ART_FIELD_DARKEN_LABEL1 = "darken_label1"
ART_FIELD_DARKEN_LABEL2 = "darken_label2"
ART_FIELD_DARKEN_LABEL_PX = "darken_label_px"
ART_FIELD_DARKEN_LABEL_WIDTH = "darken_label_width"
ART_FIELD_DARKEN_LABEL_WIDTH1 = "darken_label_width1"
ART_FIELD_DARKEN_LABEL_WIDTH2 = "darken_label_width2"
ART_FIELD_MEASURE = "measure"
ART_FIELD_RATIO = "ratio"
ART_FIELD_ELEMENT_COLORS = "element_colors"
ART_FIELD_ELEMENT_COLOR = "element_color"
ART_FIELD_BAND = "band"
ART_FIELD_PALETTE_PRIMARY = "palette_primary"
ART_FIELD_PALETTE_SECONDARY = "palette_secondary"
ART_FIELD_PALETTE_LOGO = "palette_logo"
ART_FIELD_PALETTE_DARKEN = "palette_darken"
ART_FIELD_PALETTE_LOGO_DARKEN = "palette_logo_darken"

ART_FIELDS_PALETTE = (
    ART_FIELD_PALETTE_PRIMARY,
    ART_FIELD_PALETTE_SECONDARY,
    ART_FIELD_PALETTE_LOGO,
    ART_FIELD_PALETTE_DARKEN,
    ART_FIELD_PALETTE_LOGO_DARKEN,
)

ART_FIELDS_DARKEN_LABEL = (
    ART_FIELD_DARKEN_LABEL,
    ART_FIELD_DARKEN_LABEL1,
    ART_FIELD_DARKEN_LABEL2,
)

ART_FIELDS_DARKEN_LABEL_WIDTH = (
    ART_FIELD_DARKEN_LABEL_WIDTH,
    ART_FIELD_DARKEN_LABEL_WIDTH1,
    ART_FIELD_DARKEN_LABEL_WIDTH2,
)

ART_DB_SCHEMA = (
    (ART_FIELD_CACHE_KEY, "TEXT NOT NULL"),
    (ART_FIELD_SOURCE_URL, "TEXT NOT NULL"),
    (ART_FIELD_PROCESS, "TEXT NOT NULL"),
    (ART_FIELD_PROCESSED, "TEXT"),
    (ART_FIELD_HASH, "TEXT"),
    (ART_FIELD_WIDTH, "INTEGER"),
    (ART_FIELD_HEIGHT, "INTEGER"),
    (ART_FIELD_BLUR_RADIUS, "INTEGER"),
    (ART_FIELD_EDGE_TRIM, "REAL"),
    (ART_FIELD_DARKEN_FRAME, "TEXT"),
    (ART_FIELD_DARKEN_RECTS, "TEXT"),
    *((field, "TEXT") for field in ART_FIELDS_DARKEN_LABEL),
    (ART_FIELD_DARKEN_LABEL_PX, "REAL"),
    *((field, "INTEGER") for field in ART_FIELDS_DARKEN_LABEL_WIDTH),
    (ART_FIELD_MEASURE, "TEXT"),
    (ART_FIELD_RATIO, "REAL"),
    (ART_FIELD_ELEMENT_COLORS, "TEXT"),
    (ART_FIELD_ELEMENT_COLOR, "TEXT"),
)
ART_DB_UNIQUE = (ART_FIELD_CACHE_KEY,)

ART_DB_INDEXES = (("idx_source_url", (ART_FIELD_SOURCE_URL,)),)

ART_DB_FIELDS = tuple(name for name, _ in ART_DB_SCHEMA)

ART_FIELDS_INPUT = {
    "crop": (),
    "blur": (ART_FIELD_BLUR_RADIUS,),
    "darken": (
        ART_FIELD_DARKEN_RECTS,
        *ART_FIELDS_DARKEN_LABEL,
        ART_FIELD_DARKEN_LABEL_PX,
        ART_FIELD_DARKEN_FRAME,
        ART_FIELD_BLUR_RADIUS,
        ART_FIELD_EDGE_TRIM,
    ),
    "band": (),  # one band per art: a rewrite evicts every band of the source
}

ART_FIELDS_RESULT = {
    "crop": (ART_FIELD_PROCESSED, ART_FIELD_WIDTH, ART_FIELD_HEIGHT),
    "blur": (ART_FIELD_PROCESSED, ART_FIELD_BLUR_RADIUS),
    "darken": (ART_FIELD_MEASURE,),
}

ART_LISTITEM_KEYS = (
    ART_FIELD_PROCESSED,
    ART_FIELD_WIDTH,
    ART_FIELD_HEIGHT,
    ART_FIELD_BLUR_RADIUS,
    ART_FIELD_DARKEN,
    ART_FIELD_ELEMENT_COLOR,
    ART_FIELD_BAND,
    *ART_FIELDS_PALETTE,
    *ART_FIELDS_DARKEN_LABEL_WIDTH,
)

ART_SOURCE_KEYS = {
    "fanart": ("fanart", "tvshow.fanart", "artist.fanart", "thumb"),
    "clearlogo": ("clearlogo", "clearlogo-alt", "clearlogo-billboard"),
}

ART_PROCESS_MAP = {
    "clearlogo": ("crop", "darken"),
    "background": ("blur", "darken"),
    "icon": ("blur", "darken"),
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
    records: Iterable[tuple[str, dict[str, Any]]],
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

    # --- Sizing & Scaling ---
    bg_frame: tuple[int, int] = (1920, 1080)  # Default fallback UI coordinate size
    crop_target_size: tuple[int, int] = (1600, 620)  # Downsample bounds for cropping
    blur_target_size: tuple[int, int] = (480, 270)  # Downsample bounds before blurring

    # --- Image Processing ---
    blur_radius: int = 50  # Default Gaussian blur radius in pixels
    matte: str = "ff121217"  # Transparent art is composited on this (skin squidink)
    jpeg_quality: int = 90  # JPEG export quality (1-95)
    jpeg_optimize: bool = False  # Enable JPEG optimization (slower save, smaller file)
    jpeg_progressive: bool = False  # Enable progressive JPEG encoding
    jpeg_subsampling: str = "4:4:4"  # Chroma subsampling ("4:4:4" for max detail)
    png_optimize: bool = False  # Enable PNG optimization
    png_compress_level: int = 3  # PNG zlib compression (0 fastest, 9 smallest)

    # --- Sampling & Extraction ---
    palette_size: int = 8  # Colors in the adaptive palette (lower is faster)
    sample_size: int = 64  # Downsampled square size for palette extraction
    avg_downsample: int = 32  # Downsampled square size for luminance/mean sampling
    bg_sampling_topk: float = 0.10  # Fraction of brightest pixels used for background L

    # --- Color Filtering ---
    alpha_opaque_min: int = 65  # Alpha channel threshold to consider a pixel opaque
    skip_whites: bool = True  # Ignore near-white swatches during dominance extraction
    skip_blacks: bool = True  # Ignore near-black swatches during dominance extraction
    near_white: int = 245  # RGB threshold (per channel) to trigger skip_whites
    near_black: int = 10  # RGB threshold (per channel) to trigger skip_blacks
    dominance_allow_threshold: float = 0.70  # Override skips if swatch covers >70%

    # --- Accent Colour Rules ---
    accent_weight: dict[str, float] = (
        field(  # weights for accent scoring: freq, sat, dist
            default_factory=lambda: {"freq": 0.5, "sat": 0.3, "dist": 0.2}
        )
    )
    accent_freq_exponent: float = 0.5  # Gamma curve to flatten dominance (0.5 = sqrt)
    accent_freq_floor: float = 0.06  # Minimum pixel share (6%) required to be an accent
    accent_min_dist: int = 28  # Minimum RGB distance (0-441) from the dominant color
    accent_stdev_floor: float = 3.0  # Fast-exit standard deviation for uniform images
    accent_dom_share_cutoff: float = 0.85  # Fast-exit if dominant covers >85%

    # --- Contrast & Readability ---
    ratio: float = 3.0  # Default contrast target for darken, element and palette
    element_overlay_color: str = "fff0efef"  # Default element colour for the darken
    band_tolerance: float = 0.05  # Pull limits widened for 8-bit rounding, grey model
    band_feather: int = 120  # The band's pull fades out over this, frame px
    palette_luminance: float = 0.45  # Relative luminance of the palette's colours
    palette_chroma: float = 0.15  # A base below this chroma is neutral: no palette
    palette_secondary_luminance: float = 0.6  # The secondary is lighter...
    palette_secondary_saturation: float = 0.5  # ...and softer (share of saturation)
    darken_label_px_per_char: float = 14  # Est. glyph width (px); skinner overrides
