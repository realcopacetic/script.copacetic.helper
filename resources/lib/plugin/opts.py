# author: realcopacetic

from dataclasses import dataclass
from typing import Mapping

from resources.lib.art import policy
from resources.lib.shared.utilities import parse_bool, to_float, to_int


@dataclass(frozen=True, slots=True)
class DarkenOpts:
    """
    Darken configuration for a given artwork type: where elements sit (prepare)
    and what the darken must carry (compose).

    :param mode: Darken mode or "None" to disable.
    :param rects: Rect string for sampling in frame coordinates.
    :param frame: Frame size "w,h" as a raw string.
    :param labels: Label text per rect, narrowing each to its estimated width.
    :param label_px: Glyph advance for the labels, in frame px.
    :param sources: Element colour per rect (hex or "clearlogo"); the last repeats.
    :param surface: The image the skin darkens: "art" or "blur".
    :param max: Cap on the darken, % black; None is no cap.
    """

    mode: str | None
    rects: str | None
    frame: str | None
    labels: tuple[str | None, ...]
    label_px: float | None
    sources: tuple[str, ...]
    surface: str
    max: int | None

    def match_fields(self) -> dict[str, object]:
        """
        Return the prepare fields that vary the cache key; compose fields stay out.
        Used by ArtOpts.match_fields; values of None are excluded.
        """
        return {
            k: v
            for k, v in {
                policy.ART_FIELD_DARKEN_RECTS: self.rects,
                policy.ART_FIELD_DARKEN_FRAME: self.frame,
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
            rects=params.get(f"{prefix}_darken_rects"),
            frame=params.get(f"{prefix}_darken_frame"),
            labels=tuple(
                params.get(f"{prefix}_{f}") for f in policy.ART_FIELDS_DARKEN_LABEL
            ),
            label_px=to_float(params.get(f"{prefix}_darken_label_px"), None),
            sources=tuple(
                (
                    params.get(f"{prefix}_darken_source")
                    or policy.ColorConfig.element_overlay_color
                ).split(",")
            ),
            surface=params.get(f"{prefix}_darken_surface", "art"),
            max=to_int(params.get(f"{prefix}_darken_max"), None),
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
    :param ratio: Contrast target for compose.
    :param element_colors: Candidate colours (hex) of an element drawn on the art.
    :param palette: Return the palette for this art.
    """

    url: str | None
    crop: bool
    blur: bool
    analyze: bool
    blur_radius: int | None
    darken: DarkenOpts | None
    edge_trim: float
    ratio: float
    element_colors: tuple[str, ...]
    palette: bool

    def enabled(self, process: str) -> bool:
        """
        Return True if the given process is enabled for this artwork. The darken
        process measures for compose; a clearlogo (no darken opts) always is.

        :param process: Process name (crop, blur, analyze, darken).
        :return: True if enabled.
        """
        return (
            self.darken is None
            or self.darken.enabled
            or bool(self.element_colors)
            or self.palette
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
            policy.ART_FIELD_RATIO: self.ratio,
            policy.ART_FIELD_ELEMENT_COLORS: ",".join(self.element_colors) or None,
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
            ratio=to_float(params.get(f"{art_type}_ratio"), policy.ColorConfig.ratio),
            element_colors=tuple(
                filter(None, params.get(f"{art_type}_element_colors", "").split(","))
            ),
            palette=parse_bool(params.get(f"{art_type}_palette", "false")),
        )
