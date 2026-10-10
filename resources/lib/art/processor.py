# author: realcopacetic

import json
from typing import Any

from PIL import Image, ImageFilter

from resources.lib.art import policy
from resources.lib.art.analyzer import ColorAnalyzer
from resources.lib.art.darken import ColorDarken
from resources.lib.art.policy import ColorConfig
from resources.lib.plugin.opts import ArtOpts
from resources.lib.shared import logger as log


class ImageProcessor:
    """
    Performs artwork transforms (crop/blur) and measures art for compose.
    """

    def __init__(self, cfg: ColorConfig) -> None:
        """Initialize the processor with a color analyzer."""
        self.cfg = cfg
        self.color_analyzer = ColorAnalyzer(self.cfg)
        self.darken_engine = ColorDarken(self.color_analyzer)

    @staticmethod
    def _ensure_mode(image: Image.Image, target: str) -> Image.Image:
        """
        Normalize image mode once.
        """
        return image if image.mode == target else image.convert(target)

    def _flatten(self, image: Image.Image) -> Image.Image:
        """
        Composite transparent art on the matte the skin shows behind it; other
        art only changes mode.

        :param image: Input PIL Image.
        :return: RGB image.
        """
        if "A" not in image.getbands() and "transparency" not in image.info:
            return self._ensure_mode(image, "RGB")
        rgba = image.convert("RGBA")
        matte = Image.new("RGBA", rgba.size, "#" + self.cfg.matte[2:])
        return Image.alpha_composite(matte, rgba).convert("RGB")

    @staticmethod
    def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
        """
        Downsample to cover a box, aspect kept, never upscaling.

        :param image: Input PIL Image.
        :param size: Box (w, h) the result must cover.
        :return: Resized image, or the input when it already fits.
        """
        scale = max(size[0] / image.width, size[1] / image.height)
        if scale >= 1:
            return image
        return image.resize(
            (round(image.width * scale), round(image.height * scale)), Image.BOX
        )

    @log.duration
    def crop(self, image: Image.Image, **_: Any) -> dict[str, Any] | None:
        """
        Crop/resize clearlogos to alpha bounds, export PNG with its dimensions.

        :param image: Input PIL Image.
        :return: Dict with {"image", "format", "metadata"} or None on failure.
        """

        image = self._ensure_mode(image, "RGBA")
        thumb_size = self.cfg.crop_target_size
        if image.width > thumb_size[0] or image.height > thumb_size[1]:
            image = image.copy()  # thumbnail() is in place; measure shares the source
            image.thumbnail(thumb_size, Image.BILINEAR)

        box = image.getchannel("A").getbbox()
        if not box:
            return None  # invalid clearlogo

        try:
            cropped = image.crop(box)
            return {
                "image": cropped,
                "format": "PNG",
                "metadata": {
                    policy.ART_FIELD_WIDTH: cropped.width,
                    policy.ART_FIELD_HEIGHT: cropped.height,
                },
            }
        except Exception as exc:
            log.error(f"{self.__class__.__name__} → Unable to crop image → {exc}")
            return None

    @log.duration
    def blur(
        self, image: Image.Image, opts: ArtOpts, **_: Any
    ) -> dict[str, Any] | None:
        """
        Resize (to the darken frame when given, so the blur matches the art as
        drawn), flatten transparent art on the matte, apply Gaussian blur.

        :param image: Input PIL Image.
        :param opts: Parsed ArtOpts for this art_type.
        :return: Dict with {"image", "format"} or None on failure.
        """
        if opts.edge_trim:
            dx = round(image.width * opts.edge_trim / 100)
            dy = round(image.height * opts.edge_trim / 100)
            image = image.crop((dx, dy, image.width - dx, image.height - dy))
        if opts.darken and opts.darken.frame:
            frame_w, frame_h = map(int, opts.darken.frame.split(","))
            image, _ = ColorDarken.frame_image(image, frame_w, frame_h)
        else:
            image = self._cover(image, self.cfg.blur_target_size)

        radius = opts.blur_radius if opts.blur_radius else self.cfg.blur_radius
        try:
            return {
                "image": self._flatten(image).filter(
                    ImageFilter.GaussianBlur(radius=radius)
                ),
                "format": "JPEG",
                "metadata": {"blur_radius": radius},
            }
        except Exception as exc:
            log.error(f"{self.__class__.__name__} → Unable to blur image → {exc}")
            return None

    @log.duration
    def darken(
        self, image: Image.Image, opts: ArtOpts, attrs: dict[str, Any], **_: Any
    ) -> dict[str, Any] | None:
        """
        Measure the art for compose: colours always; with darken opts, each rect's
        extremes on the art and on its blur, and the band palette.

        :param image: Input PIL image.
        :param opts: Parsed ArtOpts for this art_type.
        :param attrs: This art's attributes so far (the blur's processed_path).
        :return: Dict with "metadata" or None on failure.
        """
        try:
            cover = self._cover(image, self.cfg.blur_target_size)
            measure = self.color_analyzer.colors(cover)
            widths = []
            if opts.darken:
                blur = attrs.get(policy.ART_FIELD_PROCESSED) if opts.blur else None
                measured, widths = self.darken_engine.measure(
                    self._flatten(cover),
                    Image.open(blur).convert("RGB") if blur else None,
                    opts.darken,
                )
                measure |= measured
            return {
                "metadata": {
                    **dict(zip(policy.ART_FIELDS_DARKEN_LABEL_WIDTH, widths)),
                    policy.ART_FIELD_MEASURE: json.dumps(
                        measure, separators=(",", ":")
                    ),
                }
            }
        except Exception as exc:
            log.error(f"{self.__class__.__name__} → Unable to darken image → {exc}")
            return None
