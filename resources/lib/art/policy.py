# author: realcopacetic

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Mapping

# Fields produced by analysis/processing that we want to persist/export
ART_VALUE_FIELDS: tuple[str, ...] = (
    "color",
    "accent",
    "contrast",
    "luminosity",
    "darken",
)

ART_SOURCE_KEYS: dict[str, tuple[str, ...]] = {
    "fanart": ("fanart", "tvshow.fanart", "artist.fanart", "thumb"),
    "clearlogo": ("clearlogo", "clearlogo-alt", "clearlogo-billboard"),
}

# Keys exported to ListItem.Art: processed_path maps to "{category}"; others map to "{category}_{key}"
ART_LISTITEM_EXPORT_KEYS: tuple[str, ...] = ("processed_path",) + ART_VALUE_FIELDS

# DB column order for inserts/updates (tuple order matters)
ART_DB_COLUMNS: tuple[str, ...] = (
    "category",
    "original_url",
    "cached_file_hash",
) + ART_LISTITEM_EXPORT_KEYS


@dataclass
class AnalyzerConfig:
    """Tunable parameters for colour analysis, contrast, and readability."""

    # --- Sampling & Palette ---
    # Number of colours in adaptive palette (lower = faster, smoother clusters)
    palette_size: int = 8

    # Downsample size for palette sampling (square SxS)
    sample_size: int = 64

    # Downsample size used when averaging RGB for luminance
    avg_downsample: int = 32

    # --- Filtering thresholds ---
    # Ignore near-white swatches unless overwhelmingly dominant
    skip_whites: bool = True

    # Ignore near-black swatches unless overwhelmingly dominant
    skip_blacks: bool = True

    # Allow skipped extremes (white/black) if they cover ≥70 % of sampled pixels
    dominance_allow_threshold: float = 0.70

    # Treat alpha channel as binary if True; use alpha_opaque_min as cutoff
    alpha_thresholded_mask: bool = True

    # Alpha cutoff (0–255) for treating pixels as opaque when thresholding
    alpha_opaque_min: int = 65

    # Per-channel threshold for considering a swatch “near white”
    near_white: int = 245

    # Per-channel threshold for considering a swatch “near black”
    near_black: int = 10

    # --- Accent extraction ---
    # Normalization factor for RGB distance in accent scoring (Δ/255)
    freq_distance_norm: float = 255.0

    # Weights for accent scoring: frequency, saturation, distance
    accent_weight: dict[str, float] = field(
        default_factory=lambda: {"freq": 0.5, "sat": 0.3, "dist": 0.2}
    )

    # Gamma (γ) exponent applied to frequency to flatten dominance (0.5 = sqrt)
    accent_freq_exponent: float = 0.5

    # Ignore swatches contributing <6% of counts)
    accent_freq_floor: float = 0.06

    # Minimum RGB Euclidean distance from dominant to consider as accent
    accent_min_dist: int = 28

    # --- Contrast & Lightness ---
    # Default lightness delta for opposite contrast colour (0.3–0.5 typical)
    contrast_shift: float = 0.3

    # HLS lightness pivot; lighten if L < pivot else darken
    contrast_midpoint: float = 0.5

    # Lower clamp for HLS lightness when adjusting contrast
    min_lightness: float = 0.0

    # Upper clamp for HLS lightness when adjusting contrast
    max_lightness: float = 1.0

    # --- Readability (text overlay) ---
    # Overlay text colour used for readability checks (ARGB hex)
    text_overlay_colour: str = "ffd1cece"

    # (x, y, w, h) Overlay region to analyze
    text_overlay_rect: tuple[int, int, int, int] = (120,660,1680,360)

    # Required WCAG contrast ratio for text (4.5 normal, 3.0 large)
    target_contrast_ratio: float = 4.5


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
    darken: int | None = None  # 0..100

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
