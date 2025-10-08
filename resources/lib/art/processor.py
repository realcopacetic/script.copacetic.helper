# author: realcopacetic

from typing import Any

from PIL import Image, ImageFilter

from resources.lib.art.analyzer import ColorAnalyzer
from resources.lib.art.policy import AnalyzerConfig
from resources.lib.shared.utilities import log, log_duration


class ImageProcessor:
    """
    Performs artwork transforms (crop/blur) and extracts color metadata.
    Uses ColorAnalyzer for hex/contrast/luminosity.
    """

    def __init__(self) -> None:
        """Initialize the processor with a color analyzer."""
        self.color_analyzer = ColorAnalyzer(AnalyzerConfig)

    @log_duration
    def crop(self, image: Image.Image) -> dict[str, Any] | None:
        """
        Crop/resize clearlogos, normalize mode for PNG, extract color metadata.

        :param image: Input PIL Image.
        :returns: Dict with {"image", "format", "metadata"} or None on failure.
        """
        pre_resize_max = (1840, 713)
        if image.width > pre_resize_max[0] or image.height > pre_resize_max[1]:
            image.thumbnail(pre_resize_max, Image.LANCZOS)

        try:
            image = image.crop(image.getbbox())
        except Exception as e:
            log(f"{self.__class__.__name__}: Error cropping image → {e}", force=True)
            return None

        final_max = (1600, 620)
        if image.width > final_max[0] or image.height > final_max[1]:
            image.thumbnail(final_max, Image.LANCZOS)

        if image.mode == "P":
            image = image.convert("RGBA")
        elif image.mode in ("LA",):
            image = image.convert("RGBA")
        elif image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")

        analysis = self.color_analyzer.analyze(image)

        return {
            "image": image,
            "format": "PNG",
            "metadata": analysis,
        }

    @log_duration
    def blur(self, image: Image.Image) -> dict[str, Any] | None:
        """
        Resize fanart, apply Gaussian blur, coerce JPEG-safe mode, extract colors.

        :param image: Input PIL Image.
        :returns: Dict with {"image", "format", "metadata"}.
        """
        target_size = (480, 270)
        try:
            image.thumbnail(target_size, Image.LANCZOS)
            image = image.filter(ImageFilter.GaussianBlur(radius=50))
        except Exception as exc:
            log(f"{self.__class__.__name__}: Error blurring image → {exc}", force=True)
            return None

        if image.mode in ("RGBA", "LA", "P"):
            image = image.convert("RGBA").convert("RGB")
        elif image.mode != "RGB":
            image = image.convert("RGB")

        analysis = self.color_analyzer.analyze(image)

        # Fanart readability — minimal darken% needed for overlay text
        try:
            darken = self.color_analyzer.compute_darken_percent(
                image,
                rect=self.text_overlay_rect,
                text_rgb=None,
            )
        except Exception as exc:
            log(f"{self.__class__.__name__}: darken calc failed → {exc}", force=True)
            darken = 0

        return {
            "image": image,
            "format": "JPEG",
            "metadata": {**analysis, "darken": darken},
        }
