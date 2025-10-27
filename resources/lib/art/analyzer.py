# author: realcopacetic

import colorsys
from PIL import Image, ImageStat

from resources.lib.art.policy import ColorConfig
from resources.lib.art.darken import ColorDarken
from resources.lib.shared.utilities import log, log_duration

RGB = tuple[int, int, int]
HLS = tuple[float, float, float]


class ColorAnalyzer:
    """
    Extracts a dominant color and computes derived values like luminosity/contrast.
    Provides helpers for hex conversion and HLS/RGB transforms.
    """

    def __init__(self, cfg: ColorConfig):
        self.cfg = cfg
        self.darken = ColorDarken(self)

    @log_duration
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

    def compute_darken_percent(
        self,
        image: Image.Image,
        overlay_rects: str,
        text_rgb: RGB | None = None,
        target_ratio: float | None = None,
    ) -> int:
        """Forward to ColorDarken for convenience."""
        return self.darken.compute_darken_percent(
            image=image,
            overlay_rects=overlay_rects,
            text_rgb=text_rgb,
            target_ratio=target_ratio,
        )

    @log_duration
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

    @log_duration
    def extract_accent_color(self, image: Image.Image, dominant_rgb: RGB) -> RGB:
        """
        Pick a secondary hue distinct from the dominant color.

        :param image: Input image to analyze.
        :param dominant_rgb: The primary (dominant) RGB color.
        :returns: Accent RGB tuple, or dominant_rgb on failure.
        """
        # --- Step 0: Early uniformity check ---
        try:
            im_small = self._sample_image(image)
            stat = ImageStat.Stat(im_small.convert("RGB"))
            if max((v ** 0.5 for v in stat.var)) < self.cfg.accent_stdev_floor:
                return dominant_rgb
        except Exception:
            pass

        # --- Step 1: Safe preprocessing ---
        try:
            im_small = self._sample_image(image)
            rgb_small = self._opaque_rgb(im_small)
            if rgb_small is None:
                return dominant_rgb
        except Exception as exc:
            log(f"ColorAnalyzer: accent preproc failed → {exc}", force=True)
            return dominant_rgb

        # --- Step 2: Quantize palette ---
        try:
            swatches, counts = self._quantize_palette(rgb_small)
            count_map: dict[RGB, int] = {
                swatches[idx]: c for c, idx in counts if idx < len(swatches)
            }
            if not count_map:
                return dominant_rgb
        except Exception as exc:
            log(f"ColorAnalyzer: accent quantize failed → {exc}", force=True)
            return dominant_rgb

        # --- Step 2.5: Dominant-share early exit ---
        try:
            total = float(sum(count_map.values()) or 1)
            # Find the cluster closest to dominant so we measure its actual share
            nearest = min(count_map, key=lambda c: self._rgb_dist(c, dominant_rgb))
            dominant_share = count_map.get(nearest, 0) / total
            if dominant_share >= self.cfg.accent_dom_share_cutoff:
                return dominant_rgb
        except Exception:
            # Non-fatal; continue to normal scoring
            pass

        # --- Step 3: Score swatches ---
        total = sum(count_map.values()) or 1
        w = self.cfg.accent_weight
        min_dist = self.cfg.accent_min_dist
        dist_norm = float(self.cfg.freq_distance_norm or 255.0)
        freq_floor = float(self.cfg.accent_freq_floor)

        def score(rgb: RGB) -> float:
            f = count_map.get(rgb, 0) / total
            if f < freq_floor:
                return -1.0
            f = f**self.cfg.accent_freq_exponent
            s = self._saturation(rgb)
            d = self._rgb_dist(rgb, dominant_rgb) / dist_norm
            return w["freq"] * f + w["sat"] * s + w["dist"] * d

        try:
            candidates = [
                c for c in count_map if self._rgb_dist(c, dominant_rgb) > min_dist
            ]
            return max(candidates or [dominant_rgb], key=score)
        except Exception as exc:
            log(f"ColorAnalyzer: accent scoring failed → {exc}", force=True)
            return dominant_rgb

    @log_duration
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

    @log_duration
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

    # ---------- public helper methods ----------
    def mean_rgb(self, im: Image.Image) -> RGB:
        """
        Brightest-patch mean: locate the brightest grid cell by luminance,
        then return the mean RGB of that cell.

        :param im: Input PIL image.
        :returns: Average (r, g, b) of the brightest patch.
        """
        return self._brightest_patch_rgb(
            im, grid=self.cfg.avg_grid, pass2=self.cfg.avg_downsample
        )

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
        """
        Build an RGB image containing **only** pixels with alpha >= alpha_opaque_min.
        This avoids black-matting transparent regions (common for clearlogos).
        Returns a tiny 1*N strip; None if no opaque pixels.
        """
        if im_small.mode == "RGBA":
            rgb = im_small.convert("RGB")
            a = im_small.getchannel("A")
            thresh = self.cfg.alpha_opaque_min
            pixels = rgb.getdata()
            alphas = a.getdata()
            opaque = [p for p, av in zip(pixels, alphas) if av >= thresh]
            if not opaque:
                return None
            out = Image.new("RGB", (len(opaque), 1))
            out.putdata(opaque)
            return out
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

    @staticmethod
    def _luma709(r: int, g: int, b: int) -> float:
        """Per-pixel relative luminance using Rec.709 coefficients (sRGB primaries)."""
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def _brightest_patch_rgb(self, im: Image.Image, *, grid: int, pass2: int) -> RGB:
        """
        Find the brightest grid cell (by luminance) and return its average RGB.

        Pass 1: resize to (grid x grid) with BOX to cheaply locate the brightest cell.
        Pass 2: crop that cell in the original image and compute its mean RGB by
                resizing to (pass2 x pass2) with BOX, then averaging pixels.

        :param im: Input PIL image (any mode).
        :param grid: Grid resolution (GxG) to locate brightest cell.
        :param pass2: Downsample size used for mean on the winning patch.
        :returns: Average (r, g, b) of the brightest cell.
        """
        if im.mode != "RGB":
            im = im.convert("RGB")

        # --- Pass 1: locate brightest cell cheaply (each pixel ≈ cell average) ---
        small = im.resize((grid, grid), Image.BOX)

        max_idx = 0
        max_y = -1.0
        for idx, (r, g, b) in enumerate(small.getdata()):
            y = self._luma709(r, g, b)
            if y > max_y:
                max_y = y
                max_idx = idx

        cx, cy = (max_idx % grid), (max_idx // grid)

        # --- Map the winning cell back to original coordinates and crop ----------
        W, H = im.size
        cell_w = W / grid
        cell_h = H / grid
        left = int(round(cx * cell_w))
        top = int(round(cy * cell_h))
        right = int(round((cx + 1) * cell_w))
        bottom = int(round((cy + 1) * cell_h))
        patch = im.crop((left, top, right, bottom))

        # --- Pass 2: precise average on the chosen patch -------------------------
        tiny = patch.resize((pass2, pass2), Image.BOX)
        r = g = b = 0
        n = pass2 * pass2
        for pr, pg, pb in tiny.getdata():
            r += pr
            g += pg
            b += pb
        return (r // n, g // n, b // n)
