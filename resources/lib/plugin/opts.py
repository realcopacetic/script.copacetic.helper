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
    :param rects: Rect string for sampling in frame coordinates.
    :param frame: Frame size "w,h" as a raw string.
    """
    mode: str | None
    strength: float
    source: str | None
    rects: str | None
    frame: str | None

    def match_fields(self) -> dict[str, object]:
        """
        Return fields that vary the cache key for this darken configuration.
        Used by ImageEditor._expected_from_spec; values of None are excluded.
        """
        return {
            k: v for k, v in {
                policy.ART_FIELD_DARKEN_MODE: self.mode,
                policy.ART_FIELD_DARKEN_SOURCE: self.source,
                policy.ART_FIELD_DARKEN_RECTS: self.rects,
                policy.ART_FIELD_DARKEN_FRAME: self.frame,
                policy.ART_FIELD_DARKEN_STRENGTH: self.strength,
            }.items() if v is not None
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
            rects=params.get(f"{prefix}_darken_rects"),
            frame=params.get(f"{prefix}_darken_frame"),
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
    """
    url: str | None
    crop: bool
    blur: bool
    analyze: bool
    blur_radius: int | None
    darken: DarkenOpts | None

    def enabled(self, process: str) -> bool:
        """
        Return True if the given process is enabled for this artwork.

        :param process: Process name (crop, blur, analyze, darken).
        :return: True if enabled.
        """
        return (
            bool(self.darken and self.darken.enabled)
            if process == "darken"
            else bool(getattr(self, process, False))
        )

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
        )
