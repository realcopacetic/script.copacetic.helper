# author: realcopacetic

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

from resources.lib.shared.utilities import log

# Fields produced by analysis/processing that we want to persist/export
ART_FIELD_PROCESSED: str = "processed_path"
ART_FIELD_HASH: str = "cached_file_hash"
ART_VALUE_FIELDS: tuple[str, ...] = (
    "color",
    "accent",
    "contrast",
    "luminosity",
)
ART_RUNTIME_FIELDS: tuple[str, ...] = ("darken",)

ART_SOURCE_KEYS: dict[str, tuple[str, ...]] = {
    "fanart": ("fanart", "tvshow.fanart", "artist.fanart", "thumb"),
    "clearlogo": ("clearlogo", "clearlogo-alt", "clearlogo-billboard"),
}

# Keys exported to ListItem.Art: processed_path maps to "{category}"; others map to "{category}_{key}"
ART_LISTITEM_EXPORT_KEYS: tuple[str, ...] = (
    (ART_FIELD_PROCESSED,) + ART_VALUE_FIELDS + ART_RUNTIME_FIELDS
)

# DB column order for inserts/updates (tuple order matters)
ART_DB_COLUMNS: tuple[str, ...] = (
    (
        "category",
        "original_url",
        ART_FIELD_HASH,
    )
    + (ART_FIELD_PROCESSED,)
    + ART_VALUE_FIELDS
)


@dataclass
class AnalyzerConfig:
    """Tunable parameters for colour analysis, contrast, and readability."""

    # --- Sampling & Palette ---
    palette_size: int = 8  # no. colours in adaptive palette (lower = faster, smoother)
    sample_size: int = 64  # downsample size for palette sampling (square SxS)
    avg_downsample: int = 32  # downsample size used when averaging RGB for luminance
    avg_grid: int = 6  # Resolution (GxG) used to locate brightest cell before averaging
    logo_presize_max: set = (1840, 713)  # Max bounding size for cropping clearlogos
    logo_final_max: set = (1600, 620)  # Final post-crop scaling target for clearlogos
    fanart_target_size: set = (480, 270)  # Downsample resolution for fanart blur
    blur_radius: int = 50  # Guassian blur strength (in pixels) for fanart blur

    # --- Filtering thresholds ---
    skip_whites: bool = True  # ignore white-ish swatches unless overwhelmingly dominant
    skip_blacks: bool = True  # ignore black-ish swatches unless overwhelmingly dominant
    dominance_allow_threshold: float = 0.70  # allow skipped extremes if ≥70% of pixels
    alpha_thresholded_mask: bool = True  # binary alpha; uses alpha_opaque_min as cutoff
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
    text_overlay_colour: str = "ffd1cece"  # colour for readability checks (ARGB hex)
    text_overlay_rect: tuple[int, int, int, int] = (
        120,
        660,
        1680,
        360,
    )  # (x, y, w, h) region
    target_contrast_ratio: float = 4.5  # WCAG target (4.5 normal, 3.0 large)

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

    # PNG save knobs
    png_optimize: bool = False  # smaller files, slower saves
    png_compress_level: int = 3  # 0–9 (0 fastest, 9 smallest)


@dataclass
class ArtMeta:
    """
    Canonical artwork record passed from processors -> editor -> sqlite -> handler.
    Only add fields here once; all layers see the same shape.
    """

    category: str
    original_url: str | None = None
    processed_path: str | None = None
    cached_file_hash: str | None = None
    color: str | None = None
    accent: str | None = None
    contrast: str | None = None
    luminosity: int | None = None  # keep your int( L * 1000 )

    def to_dict(self) -> dict[str, Any]:
        """Dict view (for JSON/logging/UI)."""
        return asdict(self)

    def to_db_row(self) -> tuple[Any, ...]:
        """Tuple in DB column order (ART_DB_COLUMNS)."""
        d = self.to_dict()
        return tuple(d.get(k) for k in ART_DB_COLUMNS)

    @classmethod
    def from_values(
        cls,
        *,
        category: str,
        values: Mapping[str, Any] | None = None,
        **extras: Any,
    ) -> "ArtMeta":
        """
        Build an ArtMeta by filtering only known value fields from `values`
        and merging with editor-level extras (paths, url, hashes).
        """
        values = values or {}
        payload = {
            k: values.get(k)
            for k in ART_LISTITEM_EXPORT_KEYS
            if values.get(k) is not None
        }
        payload.update(extras)  # original_url, processed_path, cached_file_hash, etc.
        return cls(category=category, **payload)


@dataclass(frozen=True)
class ArtChoice:
    target_key: str  # normalized role to publish under (e.g. "fanart")
    path: str  # resolved VFS path ("" if none found)


def resolve_art_type(art: dict, art_type: str) -> ArtChoice:
    """
    Choose the best artwork path for a target art_type using ART_SOURCE_KEYS priority,
    with special episode-friendly fanart heuristic.

    :param art: Kodi-style dict of available art {key: path}
    :param art_type: role to resolve (e.g., "fanart", "clearlogo")
    :return: ArtChoice(target_key=art_type, path=...,)
             Empty path if nothing suitable found.
    """
    keys = ART_SOURCE_KEYS.get(art_type, (art_type,))

    # Episode-friendly heuristic: prefer thumb if fanart mirrors tvshow.fanart
    if art_type == "fanart":
        thumb = art.get("thumb")
        fanart = art.get("fanart")
        tv_fanart = art.get("tvshow.fanart")
        if thumb and (not fanart or (tv_fanart and fanart == tv_fanart)):
            return ArtChoice(target_key="fanart", path=thumb)

    # Return first valid path from priority list (or from art_type itself)
    return ArtChoice(
        target_key=art_type,
        path=next((art[k] for k in keys if art.get(k)), art.get(art_type, "")) or "",
    )


def flatten_art_attributes(
    records: Iterable[ArtMeta | dict[str, Any]],
) -> dict[str, Any]:
    """
    Flatten canonical records into ListItem.Art-style keys.

    processed_path -> "{category}"
    others        -> "{category}_{key}"
    """
    out: dict[str, Any] = {}
    for rec in records or ():
        d = rec.to_dict() if hasattr(rec, "to_dict") else dict(rec)
        cat = d.get("category")
        if not cat:
            continue
        for key in ART_LISTITEM_EXPORT_KEYS:
            val = d.get(key)
            if val is None:
                continue
            name = cat if key == "processed_path" else f"{cat}_{key}"
            out[name] = val
    return out
