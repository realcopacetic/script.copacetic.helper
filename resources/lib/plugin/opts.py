# author: realcopacetic

from dataclasses import dataclass
from typing import Mapping
from resources.lib.shared.utilities import parse_bool, to_int


@dataclass(frozen=True, slots=True)
class DarkenOpts:
    """
    Darken configuration for a given artwork type.

    :param mode: Darken mode or "None" to disable.
    :param source: Colour source override (hex or "clearlogo").
    :param rects: Rect string for sampling in frame coordinates.
    :param frame: Frame size "w,h" as a raw string.
    :param target: Contrast target override as a raw string.
    """
    mode: str | None
    source: str | None
    rects: str | None
    frame: str | None
    target: str | None

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
            source=params.get(f"{prefix}_darken_source"),
            rects=params.get(f"{prefix}_darken_rects"),
            frame=params.get(f"{prefix}_darken_frame"),
            target=params.get(f"{prefix}_darken_target"),
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

    @property
    def darken_mode(self) -> str | None:
        """Return *_darken_mode param as a property"""
        return self.darken.mode if self.darken else None

    @property
    def darken_source(self) -> str | None:
        """Return *_darken_source param as a property"""
        return self.darken.source if self.darken else None

    @property
    def darken_rects(self) -> str | None:
        """Return *_darken_rects param as a property"""
        return self.darken.rects if self.darken else None

    @property
    def darken_frame(self) -> str | None:
        """Return *_darken_frame param as a property"""
        return self.darken.frame if self.darken else None

    @property
    def darken_target(self) -> str | None:
        """Return *_darken_target param as a property"""
        return self.darken.target if self.darken else None

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
