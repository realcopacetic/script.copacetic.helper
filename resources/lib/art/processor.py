# author: realcopacetic

from PIL import Image, ImageFilter

from resources.lib.art.analyzer import ColorAnalyzer
from resources.lib.shared.utilities import log, log_duration


class ImageProcessor:
    """
    Performs artwork transformations like crop and blur,
    and extracts color metadata using ColorAnalyzer.
    """

    def __init__(self):
        self.color_analyzer = ColorAnalyzer()

    @log_duration
    def crop(self, image):
        """
        Crops and resizes clearlogos, and extracts color metadata.
        :param image: PIL Image object.
        :returns: Dict with processed image, format, and metadata.
        """
        if image.mode != "RGBA":
            image = image.convert("RGBA")

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

        analysis = self.color_analyzer.analyze(image)

        return {
            "image": image,
            "format": "PNG",
            "metadata": {
                "color": analysis["hex"],
                "contrast": analysis["contrast_hex"],
                "luminosity": int(analysis["luminosity"] * 1000),
            },
        }

    @log_duration
    def blur(self, image):
        """
        Applies Gaussian blur and resizes fanart. Also extracts color metadata.
        :param image: PIL Image object.
        :returns: Dict with processed image, format, and metadata.
        """
        target_size = (480, 270)
        image.thumbnail(target_size, Image.LANCZOS)
        image = image.filter(ImageFilter.GaussianBlur(radius=50))

        analysis = self.color_analyzer.analyze(image)

        return {
            "image": image,
            "format": "JPEG",
            "metadata": {
                "color": analysis["hex"],
                "contrast": analysis["contrast_hex"],
                "luminosity": int(analysis["luminosity"] * 1000),
            },
        }
