# author: realcopacetic

import colorsys
from PIL import Image

from resources.lib.art.policy import AnalyzerConfig

RGB = tuple[int, int, int]
HLS = tuple[float, float, float]

class ColorAnalyzer:
    """
    Extracts a dominant color and computes derived values like luminosity/contrast.
    Provides helpers for hex conversion and HLS/RGB transforms.
    """

    def __init__(self, cfg: AnalyzerConfig):
        self.cfg = cfg

    # ---------- public summary ----------
    def analyze(self, image: Image.Image) -> dict[str, float | str]:
        """Extract dominant + accent; compute luminosity and a contrast colour (hex)."""
        dominant = self.extract_dominant_color(image)
        accent = self.extract_accent_color(image, dominant_rgb=dominant)
        contrast_rgb = self.get_contrasting_color(
            dominant, shift=self.cfg.contrast_shift
        )
        return {
            "color": self.to_hex(dominant),
            "accent": self.to_hex(accent),
            "contrast": self.to_hex(contrast_rgb),
            "luminosity": int(self.get_luminosity(dominant) * 1000),
        }

    # ---------- public methods ----------
    def extract_dominant_color(self, image: Image.Image) -> RGB:
        """
        Dominant colour via downsample + adaptive palette; ignores transparent pixels.
        Uses Pillow's ADAPTIVE palette on a small sample for speed/stability.

        :param image: Input PIL image (any mode).
        :returns: Dominant colour as (r, g, b).
        """
        try:
            im_small = self._sample_image(image)
            rgb_small = self._opaque_rgb(im_small)
            if rgb_small is None:
                return (0, 0, 0)
            swatches, counts = self._quantize_palette(rgb_small)
            total = sum(c for c, _ in counts) or 1
            filtered: list[tuple[int, int]] = []
            for c, idx in counts:
                r, g, b = swatches[idx]
                near_white = (
                    r > self.cfg.near_white
                    and g > self.cfg.near_white
                    and b > self.cfg.near_white
                )
                near_black = (
                    r < self.cfg.near_black
                    and g < self.cfg.near_black
                    and b < self.cfg.near_black
                )
                if (self.cfg.skip_whites and near_white) or (
                    self.cfg.skip_blacks and near_black
                ):
                    if (
                        c / total >= self.cfg.dominance_allow_threshold
                    ):  # allow if truly dominant
                        filtered.append((c, idx))
                    continue
                filtered.append((c, idx))
            _, idx = max(filtered or counts, key=lambda t: t[0])
            return swatches[idx]
        except Exception:
            return (0, 0, 0)

    def extract_accent_color(self, image: Image.Image, dominant_rgb: RGB) -> RGB:
        """
        Accent colour distinct from dominant using freq^γ, saturation, and distance.
        Scores palette swatches by w_freq*freq^γ + w_sat*s + w_dist*Δ, skipping near-duplicates.

        :param image: Input PIL image (any mode).
        :param dominant_rgb: Dominant colour used as the reference.
        :returns: Accent colour as (r, g, b).
        """
        try:
            im_small = self._sample_image(image)
            rgb_small = self._opaque_rgb(im_small)
            if rgb_small is None:
                return dominant_rgb
            swatches, counts = self._quantize_palette(rgb_small)
            count_map = {swatches[idx]: c for c, idx in counts if idx < len(swatches)}

            def score(rgb: RGB) -> float:
                f = count_map.get(rgb, 0) ** self.cfg.accent_freq_exponent
                s = self._saturation(rgb)
                d = self._rgb_dist(rgb, dominant_rgb) / self.cfg.freq_distance_norm
                w = self.cfg.accent_weight
                return w["freq"] * f + w["sat"] * s + w["dist"] * d

            candidates = [
                c
                for c in count_map
                if self._rgb_dist(c, dominant_rgb) > self.cfg.accent_min_dist
            ]
            return max(candidates or [dominant_rgb], key=score)
        except Exception:
            return dominant_rgb

    def get_luminosity(self, rgb: RGB) -> float:
        """
        Relative luminance per sRGB/Rec.709 with WCAG transfer curve.
        https://www.w3.org/TR/WCAG21/#dfn-relative-luminance
        :param rgb: (r, g, b) in 0-255.
        :returns: L in 0-1.
        """
        r, g, b = rgb
        r, g, b = self._linearize(r), self._linearize(g), self._linearize(b)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def get_contrasting_color(self, rgb: RGB, shift: float) -> RGB:
        """
        Opposite contrast colour by shifting HLS lightness around a pivot.
        Lighten if L<pivot else darken; clamps to min/max lightness.

        :param rgb: Base colour (r, g, b).
        :param shift: Lightness delta (0-1) to apply.
        :returns: Contrasting (r, g, b).
        """
        h, l, s = self.rgb_to_hls(rgb)
        l = (
            min(self.cfg.max_lightness, l + shift)
            if l < self.cfg.contrast_midpoint
            else max(self.cfg.min_lightness, l - shift)
        )
        return self.hls_to_rgb((h, l, s))

    def compute_darken_percent(
        self,
        image: Image.Image,
        rect: tuple[int, int, int, int],
        text_rgb: RGB | None = None,
    ) -> int:
        """
        Minimal darken% so text meets target contrast over a rect (WCAG 2.1).
        Uses contrast=(L_text+0.05)/(L_bg+0.05) with sRGB linearization (Rec.709).
        https://www.w3.org/TR/WCAG21/#contrast-minimum

        :param image: Source image (as displayed).
        :param rect: (x, y, w, h) overlay region to analyze.
        :param text_rgb: Text colour (defaults to configured overlay colour).
        :returns: Darken percent 0-100 for fadediffuse mapping.
        """
        text_rgb = (
            self.from_hex(self.cfg.text_overlay_colour)
            if text_rgb is None
            else text_rgb
        )
        x, y, w, h = rect
        crop = image.crop((x, y, x + w, y + h))
        bg_rgb = self._avg_rgb(crop)
        L_text = self.get_luminosity(text_rgb)
        L_bg = self.get_luminosity(bg_rgb)

        # If already sufficient contrast, return 0
        if (L_text + 0.05) / (L_bg + 0.05) >= self.cfg.target_contrast_ratio:
            return 0

        # Solve for minimal k such that (L_text+0.05)/(k*L_bg+0.05) >= target_contrast_ratio
        numerator = (L_text + 0.05) / self.cfg.target_contrast_ratio - 0.05
        if L_bg <= 1e-9 or numerator <= 0:
            return 100  # clamp: fully black
        k = max(0.0, min(1.0, numerator / L_bg))
        darken = int(round((1.0 - k) * 100))
        return max(0, min(100, darken))

    # ---------- public helper methods ----------
    @staticmethod
    def to_hex(rgb: RGB) -> str:
        """Convert RGB to ARGB hex with full opacity."""
        r, g, b = rgb
        return f"ff{r:02x}{g:02x}{b:02x}"

    @staticmethod
    def from_hex(hex_str: str) -> RGB:
        """Convert ARGB/RGB hex to an RGB tuple."""
        s = hex_str.lstrip("#")
        if len(s) == 8:  # strip alpha
            s = s[2:]
        return tuple(int(s[i : i + 2], 16) for i in (0, 2, 4))

    @staticmethod
    def rgb_to_hls(rgb: RGB) -> HLS:
        r, g, b = [c / 255.0 for c in rgb]
        return colorsys.rgb_to_hls(r, g, b)

    @staticmethod
    def hls_to_rgb(hls: HLS) -> RGB:
        r, g, b = colorsys.hls_to_rgb(*hls)
        return tuple(int(round(c * 255)) for c in (r, g, b))

    # ---------- private helper methods ----------
    def _sample_image(self, im: Image.Image) -> Image.Image:
        """Downsample early to cap cost while keeping structure."""
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "A" in im.getbands() else "RGB")
        return im.resize((self.cfg.sample_size, self.cfg.sample_size), Image.BOX)

    def _opaque_rgb(self, im_small: Image.Image) -> Image.Image | None:
        """Return an RGB image with transparent pixels discarded; None if fully transparent."""
        if im_small.mode == "RGBA":
            rgb, alpha = im_small.convert("RGB"), im_small.getchannel("A")
            if self.cfg.alpha_thresholded_mask:
                a = alpha.point(lambda v: 255 if v >= self.cfg.alpha_opaque_min else 0)
            else:
                a = alpha
            if not a.getbbox():
                return None
            return Image.composite(rgb, Image.new("RGB", rgb.size, (0, 0, 0)), a)
        return im_small.convert("RGB")

    def _quantize_palette(
        self, rgb_small: Image.Image
    ) -> tuple[list[RGB], list[tuple[int, int]]]:
        """Adaptive palette quantization on a small image; returns (swatches, counts)."""
        pal = rgb_small.convert(
            "P", palette=Image.ADAPTIVE, colors=self.cfg.palette_size
        )
        palette = pal.getpalette()[: self.cfg.palette_size * 3]
        swatches = [tuple(palette[i : i + 3]) for i in range(0, len(palette), 3)]
        counts = pal.getcolors() or []
        return swatches, counts

    def _saturation(self, rgb: RGB) -> float:
        return self.rgb_to_hls(rgb)[2]

    @staticmethod
    def _rgb_dist(a: RGB, b: RGB) -> float:
        return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5

    @staticmethod
    def _linearize(channel_0_255: int) -> float:
        """
        sRGB EOTF (piecewise gamma) per WCAG/IEC 61966-2-1.
        https://www.w3.org/TR/WCAG21/relative-luminance.html

        :param channel_0_255: 8-bit sRGB channel.
        :returns: Linearized channel in 0-1.
        """
        c = channel_0_255 / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def _avg_rgb(self, im: Image.Image) -> RGB:
        """
        Mean RGB on a small BOX-resampled image for robust luminance.

        :param im: Input PIL image.
        :returns: Average (r, g, b).
        """
        if im.mode != "RGB":
            im = im.convert("RGB")
        small = im.resize((self.cfg.avg_downsample, self.cfg.avg_downsample), Image.BOX)
        r = g = b = 0
        n = small.size[0] * small.size[1]
        for pr, pg, pb in small.getdata():
            r += pr
            g += pg
            b += pb
        return (r // n, g // n, b // n)
