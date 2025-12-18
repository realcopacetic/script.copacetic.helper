# author: realcopacetic

from typing import Any

from PIL import Image, ImageFilter

from resources.lib.art.analyzer import ColorAnalyzer
from resources.lib.art.policy import ColorConfig
from resources.lib.shared import logger as log
from resources.lib.art.darken import ColorDarken


class ImageProcessor:
    """
    Performs artwork transforms (crop/blur/analyze) and extracts color metadata.
    Uses ColorAnalyzer for hex/contrast/luminosity.

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

    @log.duration
    def crop(self, image: Image.Image, **_: Any) -> dict[str, Any] | None:
        """
        Crop/resize clearlogos, normalize mode for PNG, extract color metadata.

        :param image: Input PIL Image.
        :return: Dict with {"image", "format", "metadata"} or None on failure.
        """
        thumb_size = self.cfg.logo_presize_max
        if image.width > thumb_size[0] or image.height > thumb_size[1]:
            image.thumbnail(self.cfg.logo_presize_max, Image.BOX)

        try:
            image = self._ensure_mode(image, "RGBA")
            alpha = image.getchannel("A")
            box = alpha.getbbox()
            if box:
                image = image.crop(box)
            else:
                image = image.crop(image.getbbox())
        except Exception as e:
            log.error(f"{self.__class__.__name__}: Unable to crop image → {e}")
            return None

        final_max = self.cfg.logo_final_max
        if image.width > final_max[0] or image.height > final_max[1]:
            image.thumbnail(final_max, Image.LANCZOS)

        return {
            "image": self._ensure_mode(image, "RGBA"),
            "format": "PNG",
        }

    @log.duration
    def blur(self, image: Image.Image, **kwargs: Any) -> dict[str, Any] | None:
        """
        Resize fanart, apply Gaussian blur, coerce JPEG-safe mode, extract colors.

        :param image: Input PIL Image.
        :param kwargs: Optional overlay parameters (e.g. overlay_source, overlay_rect).
        :return: Dict with {"image", "format", "metadata", "work_image"} or None on failure.
        """
        thumb_size = self.cfg.fanart_target_size
        if image.width > thumb_size[0] or image.height > thumb_size[1]:
            image.thumbnail(self.cfg.fanart_target_size, Image.BOX)

        opts = kwargs["opts"]
        radius = opts.blur_radius if opts.blur_radius else self.cfg.blur_radius
        try:
            image = image.filter(ImageFilter.GaussianBlur(radius=radius))
            return {
                "image": self._ensure_mode(image, "RGB"),
                "format": "JPEG",
            }
        except Exception as exc:
            log.error(f"{self.__class__.__name__}: Unable to blur image → {exc}")
            return None

    @log.duration
    def analyze(self, image: Image.Image, *_: Any) -> dict[str, Any] | None:
        """
        Extract color metadata from arbitrary artwork without saving output.

        :param image: Input PIL image.
        :param art_type: Artwork type key.
        :param kwargs: Process inputs (e.g. work_image).
        :return: Dict with {"image", "metadata"} or None on failure.
        """
        thumb_size = self.cfg.fanart_target_size
        if image.width > thumb_size[0] or image.height > thumb_size[1]:
            image.thumbnail(self.cfg.fanart_target_size, Image.BOX)

        try:
            return {
                "metadata": self.color_analyzer.analyze(
                    self._ensure_mode(image, "RGBA")  # keep alpha where present
                )
            }
        except Exception as exc:
            log.error(f"{self.__class__.__name__}: Unable to analyze image → {exc}")
            return None

    @log.duration
    def darken(
        self, image: Image.Image, art_type: str, **kwargs: Any
    ) -> dict[str, Any] | None:
        """
        Compute darken metadata without altering pixels.
        Uses contrast rules against the configured source.

        :param image: Input PIL image.
        :param art_type: Artwork type key.
        :param kwargs: Process inputs (expects ``darken`` options).
        :return: Dict with {"image", "metadata"} or None on failure.
        """
        darken_opts = kwargs["opts"].darken
        if not darken_opts or not darken_opts.enabled:
            return {"image": image, "metadata": {}}

        shared = kwargs["shared"]
        try:
            return {
                "metadata": self.darken_engine.compute_darken(
                    image, opts=darken_opts, shared=shared
                )
                or {}
            }
        except Exception as exc:
            log.error(f"{self.__class__.__name__}: Unable to darken image → {exc}")
            return None
