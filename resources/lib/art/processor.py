# author: realcopacetic

from typing import Any

from PIL import Image, ImageFilter

from resources.lib.art.analyzer import ColorAnalyzer
from resources.lib.art.policy import ColorConfig
from resources.lib.shared import logger as log


class ImageProcessor:
    """
    Performs artwork transforms (crop/blur) and extracts color metadata.
    Uses ColorAnalyzer for hex/contrast/luminosity.
    """

    def __init__(self, cfg: ColorConfig) -> ColorConfig:
        """Initialize the processor with a color analyzer."""
        self.cfg = cfg
        self.color_analyzer = ColorAnalyzer(self.cfg)

    @staticmethod
    def _ensure_mode(image: Image.Image, target: str) -> Image.Image:
        """
        Normalize image mode once.
        """
        return image if image.mode == target else image.convert(target)

    @log.duration
    def crop(self, image: Image.Image, **_: Any) -> dict[str, Any] | None:
        """
        Crop/resize clearlogos, normalize mode for PNG, extract color metadata.

        :param image: Input PIL Image.
        :return: Dict with {"image", "format", "metadata"} or None on failure.
        """
        pre_resize_max = self.cfg.logo_presize_max
        if image.width > pre_resize_max[0] or image.height > pre_resize_max[1]:
            image.thumbnail(pre_resize_max, Image.BOX)

        try:
            image = self._ensure_mode(image, "RGBA")
            alpha = image.getchannel("A")
            box = alpha.getbbox()
            if box:
                image = image.crop(box)
            else:
                image = image.crop(image.getbbox())
        except Exception as e:
            log.errro(f"{self.__class__.__name__}: Unable to crop image → {e}")
            return None

        final_max = self.cfg.logo_final_max
        if image.width > final_max[0] or image.height > final_max[1]:
            image.thumbnail(final_max, Image.LANCZOS)

        image = self._ensure_mode(image, "RGBA")
        analysis = self.color_analyzer.analyze(image)

        return {
            "image": image,
            "format": "PNG",
            "metadata": analysis,
        }

    @log.duration
    def blur(self, image: Image.Image, **kwargs: Any) -> dict[str, Any] | None:
        """
        Resize fanart, apply Gaussian blur, coerce JPEG-safe mode, extract colors.

        :param image: Input PIL Image.
        :param kwargs: Optional overlay parameters (e.g. overlay_source, overlay_rect).
        :return: Dict with {"image", "format", "metadata"}.
        """
        try:
            image.thumbnail(self.cfg.fanart_target_size, Image.BOX)
            sample_frame = image.copy()
            image = image.filter(ImageFilter.GaussianBlur(radius=self.cfg.blur_radius))
        except Exception as exc:
            log.error(f"{self.__class__.__name__}: Unable to blur image → {exc}")
            return None

        image = self._ensure_mode(image, "RGB")
        analysis = self.color_analyzer.analyze(image)

        return {
            "image": image,
            "format": "JPEG",
            "metadata": analysis,
            "sample_frame": sample_frame,
        }
