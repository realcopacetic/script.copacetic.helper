# author: realcopacetic

from typing import Any

from PIL import Image, ImageFilter

from resources.lib.plugin.opts import ArtOpts
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
        :return: Dict with {"image", "format"} or None on failure.
        """
        image = self._ensure_mode(image, "RGBA")
        thumb_size = self.cfg.crop_target_size
        if image.width > thumb_size[0] or image.height > thumb_size[1]:
            image.thumbnail(thumb_size, Image.BILINEAR)

        box = image.getchannel("A").getbbox()
        if not box:
            return None  # invalid clearlogo

        try:
            return {"image": image.crop(box), "format": "PNG"}
        except Exception as exc:
            log.error(f"{self.__class__.__name__}: Unable to crop image → {exc}")
            return None

    @log.duration
    def blur(self, image: Image.Image, opts: ArtOpts, **_: Any) -> dict[str, Any] | None:
        """
        Resize fanart, apply Gaussian blur, coerce JPEG-safe mode, extract colors.

        :param image: Input PIL Image.
        :param opts: Parsed ArtOpts for this art_type.
        :return: Dict with {"image", "format"} or None on failure.
        """
        thumb_size = self.cfg.blur_target_size
        if image.width > thumb_size[0] or image.height > thumb_size[1]:
            image.thumbnail(thumb_size, Image.BOX)

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
    def analyze(self, image: Image.Image, **_: Any) -> dict[str, Any] | None:
        """
        Extract color metadata from arbitrary artwork without saving output.

        :param image: Input PIL image.
        :return: Dict with "metadata" or None on failure.
        """
        thumb_size = self.cfg.blur_target_size
        if image.width > thumb_size[0] or image.height > thumb_size[1]:
            image.thumbnail(thumb_size, Image.BOX)

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
        self, image: Image.Image, opts: ArtOpts, shared: dict[str, Any]
    ) -> dict[str, Any] | None:
        """
        Compute darken metadata without altering pixels.
        Uses contrast rules against the configured source.

        :param image: Input PIL image.
        :param opts: Parsed ArtOpts for this art_type.
        :param shared: Shared context across jobs in this call.
        :return: Dict with "metadata" or None on failure.
        """
        if not (darken_opts := opts.darken) or not darken_opts.enabled:
            return {"metadata": {}}

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
