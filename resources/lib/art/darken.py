# author: realcopacetic

from typing import Iterable

from PIL import Image

from resources.lib.shared import logger as log

RGB = tuple[int, int, int]
Rect = tuple[int, int, int, int]


class ColorDarken:
    """
    Multi-rect darken computation using ColorAnalyzer helpers.
    Finds the brightest sampled cell across provided rects, then solves WCAG darken%.
    """

    def __init__(self, color_analyzer: object) -> None:
        """
        Inject shared colour utilities and configuration.
        Stores a reference to ColorAnalyzer to reuse its helpers and cfg.

        :param color_analyzer: ColorAnalyzer instance providing helpers and ColorConfig.
        """
        self.color = color_analyzer

    @log.duration
    def compute_darken_percent(
        self,
        image: Image.Image,
        overlay_rects: str,  # "(x,y,w,h),(x,y,w,h)"
        text_rgb: RGB | None = None,
        target_ratio: float | None = None,
    ) -> int:
        """
        Compute minimal darken% so overlay text meets a WCAG 2.1 contrast target.
        Uses contrast = (L_text+0.05)/(L_bg+0.05) with sRGB linearization (Rec.709).
        https://www.w3.org/TR/WCAG21/#contrast-minimum

        :param image: Source image (as displayed).
        :param overlay_rects: Rects separated by parenthises "(x,y,w,h),(x,y,w,h)" in a 1920x1080 reference frame.
        :param text_rgb: Optional text RGB override (defaults to cfg.text_overlay_colour).
        :param target_ratio: Optional WCAG contrast target override (e.g. 4.5 body, 3.0 large/logo).
        :return: Darken percent 0-cfg.max_darken_cap for fade/diffuse mapping.
        """
        cfg = self.color.cfg

        rects = self.parse_overlay_rects(overlay_rects)
        if not rects:
            # Fall back to default full-frame rect in config
            bx, by, bw, bh = cfg.text_overlay_rect
            rects = [(bx, by, bw, bh)]

        scaled = self._scale_rects(
            rects, image.width, image.height, ref_w=1920, ref_h=1080
        )

        # Brightest cell across all rects, then precise mean RGB
        bg_rgb = self._brightest_patch_rgb_multi(
            image, scaled, grid=cfg.avg_grid, pass2=cfg.avg_downsample
        )

        target = cfg.target_contrast_ratio if target_ratio is None else target_ratio
        text_rgb = text_rgb or self.color.from_hex(cfg.text_overlay_colour)

        return self._solve_darken(bg_rgb, text_rgb, target)

    @staticmethod
    def parse_overlay_rects(param: str) -> list[Rect]:
        """
        Parse overlay rects into a list of (x, y, w, h) tuples. Accepts single
        rect "x,y,w,h" or multiple wrapped in parenthises "(x,y,w,h),(x,y,w,h),..."

        :param param: Rects string from Kodi .
        :return: Rect list as [(x, y, w, h), ...].
        """
        if not (value := (param or "").strip()):
            return []

        value = value.replace(" ", "")
        rect_strings = (
            [part.strip("()") for part in value.split("),(")]
            if "(" in value and ")" in value
            else [value]
        )
        return [
            (x, y, w, h)
            for rect_str in rect_strings
            for parts in [rect_str.split(",")]
            if len(parts) == 4
            for x, y, w, h in [tuple(map(int, parts))]
            if w > 0 and h > 0
        ]

    @staticmethod
    def _scale_rects(
        rects: Iterable[Rect],
        img_w: int,
        img_h: int,
        ref_w: int,
        ref_h: int,
    ) -> list[Rect]:
        """
        Scale rects from a reference frame to image coordinates and clamp.
        Drops degenerate rects after scaling/clamping to image bounds.

        :param rects: Rects in the reference frame.
        :param img_w: Image width in pixels.
        :param img_h: Image height in pixels.
        :param ref_w: Reference width the rects are defined against.
        :param ref_h: Reference height the rects are defined against.
        :return: Scaled, clamped rects in image coordinates.
        """
        sx = img_w / float(ref_w or 1)
        sy = img_h / float(ref_h or 1)

        out = []
        for bx, by, bw, bh in rects:
            x = int(round(bx * sx))
            y = int(round(by * sy))
            w = int(round(bw * sx))
            h = int(round(bh * sy))

            x0, y0 = max(0, x), max(0, y)
            x1, y1 = min(img_w, x + w), min(img_h, y + h)
            if x1 <= x0 or y1 <= y0:
                continue
            out.append((x0, y0, x1 - x0, y1 - y0))
        return out

    def _brightest_patch_rgb_multi(
        self,
        im: Image.Image,
        rects: Iterable[Rect],
        grid: int,
        pass2: int,
    ) -> RGB:
        """
        Return mean RGB of the brightest grid cell across all rects.
        Center-samples each cell for speed, then averages the winning cell precisely.

        :param im: Source image; converted to RGB if needed.
        :param rects: Image-space rects to sample.
        :param grid: Grid resolution per rect for cell search.
        :param pass2: Downsample size for precise mean on winning cell.
        :return: Mean (r, g, b) of the brightest cell.
        """
        if im.mode != "RGB":
            im = im.convert("RGB")

        W, H = im.size
        px = im.load()

        best_luma = -1.0
        best_box = None

        for rx, ry, rw, rh in rects:
            # Clamp grid for tiny rects
            gx = max(1, min(grid, rw))
            gy = max(1, min(grid, rh))

            cell_w = rw / gx
            cell_h = rh / gy

            for iy in range(gy):
                for ix in range(gx):
                    left = int(round(rx + ix * cell_w))
                    top = int(round(ry + iy * cell_h))
                    right = int(round(rx + (ix + 1) * cell_w))
                    bottom = int(round(ry + (iy + 1) * cell_h))

                    cx = min(max(0, (left + right) // 2), W - 1)
                    cy = min(max(0, (top + bottom) // 2), H - 1)

                    r, g, b = px[cx, cy]
                    # Fast luma; you already have _luma709 if you prefer to call it
                    y = 0.2126 * r + 0.7152 * g + 0.0722 * b

                    if y > best_luma:
                        best_luma = y
                        best_box = (left, top, right, bottom)

        if best_box is None:
            # Fallback: whole-image bright patch mean (unlikely)
            tiny = im.resize((pass2, pass2), Image.BOX)
            return self.color.mean_rgb(tiny)

        left, top, right, bottom = best_box
        patch = im.crop((left, top, right, bottom))
        tiny = patch.resize((pass2, pass2), Image.BOX)
        return self.color.mean_rgb(tiny)

    def _solve_darken(self, bg_rgb: RGB, text_rgb: RGB, target: float) -> int:
        """
        Solve multiplicative darken on background luminance to reach target.
        Applies optional red leniency, then computes darken% capped by configuration.

        :param bg_rgb: Mean background RGB of the brightest sampled cell.
        :param text_rgb: Overlay text RGB for contrast calculation.
        :param target: Desired WCAG contrast ratio.
        :return: Darken percentage clamped to [0, cfg.max_darken_cap].
        """
        cfg = self.color.cfg

        # Optional red relax (same semantics as your analyzer)
        if cfg.red_relax_enable:
            h, _, _ = self.color.rgb_to_hls(text_rgb)
            d = min(abs(h - cfg.red_hue_center), 1.0 - abs(h - cfg.red_hue_center))
            # Use linearized background luminance via analyzer
            if d <= cfg.red_hue_window and (
                self.color.get_luminosity(bg_rgb) <= cfg.red_bg_floor
            ):
                target = max(cfg.red_min_target, min(target, cfg.red_relax_cap))

        L_text = self.color.get_luminosity(text_rgb)
        L_bg = self.color.get_luminosity(bg_rgb)

        contrast = (max(L_text, L_bg) + 0.05) / (min(L_text, L_bg) + 0.05)
        log.debug(
            f"{self.__class__.__name__}: darken → "
            f"bg_rgb={bg_rgb}, text_rgb={text_rgb}, "
            f"L_bg={L_bg:.4f}, L_text={L_text:.4f}, "
            f"contrast={contrast:.3f}, target={target:.2f}, "
            f"diff={(contrast - target):+.3f}",
        )
        if contrast >= (target - 1e-9):
            return 0

        numerator = (L_text + 0.05) / target - 0.05
        if L_bg <= 1e-9 or numerator <= 0:
            return cfg.max_darken_cap

        k = max(0.0, min(1.0, numerator / L_bg))  # L_bg' = k * L_bg
        darken = int(round((1.0 - k) * 100))
        return max(0, min(cfg.max_darken_cap, darken))
