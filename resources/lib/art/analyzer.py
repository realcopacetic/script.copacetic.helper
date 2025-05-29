# author: realcopacetic

import colorsys
from PIL import Image


class ColorAnalyzer:
    """
    Analyzes image colors and provides utilities for color conversion and contrast.
    """

    def extract_dominant_color(self, image):
        """
        Extracts the most common opaque color from the image.

        :param image: PIL Image object.
        :returns: RGB tuple of the dominant color.
        """
        try:
            pixeldata = image.getcolors(image.width * image.height)
        except Exception:
            return (0, 0, 0)

        opaque_pixels = [
            color
            for count, color in sorted(pixeldata or [], reverse=True)
            if (len(color) == 3 or (len(color) == 4 and color[3] > 64))  # RGBA check
        ]

        if not opaque_pixels:
            return (0, 0, 0)

        try:
            paletted = Image.new("RGBA", (len(opaque_pixels), 1))
            paletted.putdata(opaque_pixels)
            paletted = paletted.convert("P", palette=Image.ADAPTIVE, colors=16)
            palette = paletted.getpalette()
            dominant_index = max(paletted.getcolors(), key=lambda x: x[0])[1]
            paletted.close()
            return tuple(palette[dominant_index * 3 : dominant_index * 3 + 3])
        except Exception:
            return (0, 0, 0)

    def get_luminosity(self, rgb):
        """
        Calculates perceived brightness of an RGB color.

        :param rgb: Tuple of (r, g, b).
        :returns: Float between 0 and 1.
        """

        def linearize(channel):
            c = channel / 255.0
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = map(linearize, rgb)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def to_hex(self, rgb):
        """
        Converts RGB to ARGB hex with full opacity.

        :param rgb: Tuple of (r, g, b).
        :returns: Hex string like "ff336699".
        """
        r, g, b = rgb
        return f"ff{r:02x}{g:02x}{b:02x}"

    def from_hex(self, hex_str):
        """
        Converts ARGB hex string to RGB tuple.

        :param hex_str: Hex string like "#ff336699" or "336699".
        :returns: Tuple of (r, g, b).
        """
        hex_str = hex_str.lstrip("#")
        if len(hex_str) == 8:
            hex_str = hex_str[2:]
        return tuple(int(hex_str[i : i + 2], 16) for i in (0, 2, 4))

    def rgb_to_hls(self, rgb):
        """
        Converts RGB to HLS using colorsys.
        :param rgb: Tuple of (r, g, b).
        :returns: Tuple of (h, l, s) with values 0–1.
        """
        r, g, b = [c / 255.0 for c in rgb]
        return colorsys.rgb_to_hls(r, g, b)

    def hls_to_rgb(self, hls):
        """
        Converts HLS back to RGB.
        :param hls: Tuple of (h, l, s) with values 0–1.
        :returns: Tuple of (r, g, b).
        """
        r, g, b = colorsys.hls_to_rgb(*hls)
        return tuple(int(c * 255) for c in (r, g, b))

    def get_contrasting_color(self, rgb, shift=0.4):
        """
        Shifts lightness to generate a contrast color.
        
        :param rgb: Original RGB tuple.
        :param shift: Amount to adjust L in HLS.
        :returns: Adjusted RGB color with contrast.
        """
        h, l, s = self.rgb_to_hls(rgb)
        if l < 0.5:
            l = min(1.0, l + shift)
        else:
            l = max(0.0, l - shift)
        return self.hls_to_rgb((h, l, s))

    def analyze(self, image, shift=0.4):
        """
        Extracts dominant color, computes luminosity, and generates a contrast color.

        :param image: PIL Image (resized/cropped externally).
        :param shift: Lightness delta for contrast color.
        :returns: Dict with hex, luminosity, and contrast_hex.
        """
        rgb = self.extract_dominant_color(image)
        contrast_rgb = self.get_contrasting_color(rgb, shift=shift)
        return {
            "dominant_hex": self.to_hex(rgb),
            "luminosity": self.get_luminosity(rgb),
            "contrast_hex": self.to_hex(contrast_rgb),
        }
