# author: realcopacetic

from dataclasses import dataclass
from typing import Mapping

from resources.lib.art import policy
from resources.lib.shared.utilities import parse_bool, to_float, to_int


@dataclass(frozen=True, slots=True)
class DarkenOpts:
    """
    Darken configuration for a given artwork type.

    :param mode: Darken mode or "None" to disable.
    :param strength: Effect strength multiplier (0.0-2.0); 1.0 = full luminance mapping.
    :param source: Colour source override (hex or "clearlogo").
    :param contrast_source: Colour scored for contrast per rect (hex or "clearlogo").
    :param contrast_rects: Rect string the contrast is scored on; default the rects.
    :param rects: Rect string for sampling in frame coordinates.
    :param frame: Frame size "w,h" as a raw string.
    """

    mode: str | None
    strength: float
    source: str | None
    contrast_source: str | None
    contrast_rects: str | None
    rects: str | None
    frame: str | None
    labels: tuple[str | None, ...]
    label_px: float | None

    def match_fields(self) -> dict[str, object]:
        """
        Return fields that vary the cache key for this darken configuration.
        Used by ImageEditor._expected_from_spec; values of None are excluded.
        """
        return {
            k: v
            for k, v in {
                policy.ART_FIELD_DARKEN_MODE: self.mode,
                policy.ART_FIELD_DARKEN_SOURCE: self.source,
                policy.ART_FIELD_DARKEN_CONTRAST_SOURCE: self.contrast_source,
                policy.ART_FIELD_DARKEN_CONTRAST_RECTS: self.contrast_rects,
                policy.ART_FIELD_DARKEN_RECTS: self.rects,
                policy.ART_FIELD_DARKEN_FRAME: self.frame,
                policy.ART_FIELD_DARKEN_STRENGTH: self.strength,
                policy.ART_FIELD_DARKEN_LABEL_PX: self.label_px,
                **{
                    f: lbl
                    for f, lbl in zip(policy.ART_FIELDS_DARKEN_LABEL, self.labels)
                    if lbl
                },
            }.items()
            if v is not None
        }

    @property
    def enabled(self) -> bool:
        """Return True if darken mode is valid."""
        return self.mode in ("artwork", "all")

    @classmethod
    def from_params(cls, params: Mapping[str, str], prefix: str) -> "DarkenOpts":
        """
        Build darken options from a parameter mapping and a name prefix.

        :param params: Mapping of plugin parameters.
        :param prefix: Prefix such as "background" or "icon".
        :return: Parsed DarkenOpts instance.
        """
        return cls(
            mode=params.get(f"{prefix}_darken", None),
            strength=max(
                0.0,
                min(2.0, to_float(params.get(f"{prefix}_darken_strength"), 1.0)),
            ),
            source=params.get(f"{prefix}_darken_source"),
            contrast_source=params.get(f"{prefix}_darken_contrast_source"),
            contrast_rects=params.get(f"{prefix}_darken_contrast_rects"),
            rects=params.get(f"{prefix}_darken_rects"),
            frame=params.get(f"{prefix}_darken_frame"),
            labels=tuple(
                params.get(f"{prefix}_{f}") for f in policy.ART_FIELDS_DARKEN_LABEL
            ),
            label_px=to_float(params.get(f"{prefix}_darken_label_px"), None),
        )


@dataclass(frozen=True, slots=True)
class ArtOpts:
    """
    Artwork process options for a single art_type.

    :param url: Source URL for the artwork.
    :param crop: Enable crop.
    :param blur: Enable blur.
    :param blur_radius: Blur radius override.
    :param analyze: Enable analysis.
    :param darken: Darken options for this art_type.
    :param edge_trim: Border to discard before blurring, percent per side.
    """

    url: str | None
    crop: bool
    blur: bool
    analyze: bool
    blur_radius: int | None
    darken: DarkenOpts | None
    edge_trim: float

    def enabled(self, process: str) -> bool:
        """
        Return True if the given process is enabled for this artwork. The darken
        process measures; a clearlogo (no darken opts) is always measured.

        :param process: Process name (crop, blur, analyze, darken).
        :return: True if enabled.
        """
        return (
            self.darken is None or self.darken.enabled
            if process == "darken"
            else bool(getattr(self, process, False))
        )

    def match_fields(self) -> dict[str, object]:
        """
        Cache-key fields for every process; each spec picks its own. The blur's
        radius and trim are 0 without a blur, so the measurement row tells them apart.
        """
        return {
            policy.ART_FIELD_BLUR_RADIUS: self.blur_radius if self.blur else 0,
            policy.ART_FIELD_EDGE_TRIM: self.edge_trim if self.blur else 0.0,
            **(self.darken.match_fields() if self.darken else {}),
        }

    @classmethod
    def from_params(cls, params: Mapping[str, str], art_type: str) -> "ArtOpts":
        """
        Build art options from plugin params.

        :param params: Mapping of plugin parameters.
        :param art_type: Artwork type prefix (e.g. "background", "icon", "clearlogo").
        :return: Parsed ArtOpts instance.
        """
        return cls(
            url=params.get(f"{art_type}_url") or None,
            crop=parse_bool(params.get(f"{art_type}_crop", "false")),
            blur=parse_bool(params.get(f"{art_type}_blur", "false")),
            blur_radius=to_int(params.get(f"{art_type}_blur_radius"), None),
            analyze=parse_bool(params.get(f"{art_type}_analyze", "false")),
            darken=(
                DarkenOpts.from_params(params, art_type)
                if art_type in ("background", "icon")
                else None
            ),
            edge_trim=to_float(params.get(f"{art_type}_edge_trim"), 0.0),
        )
