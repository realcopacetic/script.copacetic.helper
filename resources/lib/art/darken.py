# author: realcopacetic

from dataclasses import dataclass
from typing import Iterable, Mapping

from PIL import Image

from resources.lib.shared.utilities import parse_bool, to_float

RGB = tuple[int, int, int]
Rect = tuple[int, int, int, int]


class DarkenSolution:
    """
    Pair of darken percentages for background and text/overlay.

    :param bg: Background darken percentage (0–100).
    :param text: Text/overlay darken percentage (0–100).
    """

    bg: int
    text: int


@dataclass(frozen=True)
class DarkenOverlayOpts:
    enabled: bool
    source: str | None
    rects: str | None
    target: float | None

    @classmethod
    def from_params(cls, params: Mapping[str, str], prefix: str) -> "DarkenOverlayOpts":
        """
        Build overlay options from a parameter mapping and a name prefix.

        :param params: Mapping of plugin parameters.
        :param prefix: Prefix such as "fanart" or "icon".
        :return: Parsed DarkenOverlayOpts instance.
        """
        return cls(
            enabled=parse_bool(params.get(f"{prefix}_overlay_enabled", "false")),
            source=params.get(f"{prefix}_overlay_source"),
            rects=params.get(f"{prefix}_overlay_rects"),
            target=to_float(params.get(f"{prefix}_overlay_target")),
        )


class ColorDarken:
    """
    WCAG-based solver for darkening background and overlay text regions.

    Computes a darken percentage for both the underlying image patch and
    the overlay/text colour to meet a target contrast ratio.
    """

    def __init__(self, color_analyzer: object) -> None:
        """
        Initialise with shared ColorAnalyzer utilities.

        :param color_analyzer: Analyzer instance providing colour helpers.
        """
        self.color = color_analyzer

    def compute_solution(
        self,
        image: Image.Image,
        overlay_rects: str,
        text_rgb: RGB | None = None,
        target_ratio: float | None = None,
    ) -> DarkenSolution:
        """
        Compute darken percentages for a background patch and overlay text.
        Uses contrast = (L_text+0.05)/(L_bg+0.05) with sRGB linearization (Rec.709).
        https://www.w3.org/TR/WCAG21/#contrast-minimum

        :param image: Source image for sampling.
        :param overlay_rects: Overlay rects in reference coordinates.
        :param text_rgb: Optional text RGB override.
        :param target_ratio: Optional WCAG contrast target override.
        :return: DarkenSolution(bg, text).
        """
        cfg = self.color.cfg

        rects = self.parse_overlay_rects(overlay_rects)
        if not rects:
            bx, by, bw, bh = cfg.text_overlay_rect
            rects = [(bx, by, bw, bh)]

        scaled = self._scale_rects(
            rects, image.width, image.height, ref_w=1920, ref_h=1080
        )

        bg_rgb = self._brightest_patch_rgb_multi(
            image, scaled, grid=cfg.avg_grid, pass2=cfg.avg_downsample
        )

        target = cfg.target_contrast_ratio if target_ratio is None else target_ratio
        text_rgb = text_rgb or self.color.from_hex(cfg.text_overlay_colour)

        bg_darken = self._solve_bg_darken(bg_rgb, text_rgb, target)
        text_darken = self._solve_text_darken(bg_rgb, text_rgb, target)

        return DarkenSolution(bg=bg_darken, text=text_darken)

    @staticmethod
    def parse_overlay_rects(param: str) -> list[Rect]:
        """
        Parse overlay rect definitions from a Kodi-style string.

        :param param: Raw rect string e.g. "(x,y,w,h),(x,y,w,h)".
        :return: Parsed rect tuples.
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
        Scale rects from a reference frame to image coordinates.

        :param rects: Rects in the reference frame.
        :param img_w: Image width in pixels.
        :param img_h: Image height in pixels.
        :param ref_w: Reference width for rect definitions.
        :param ref_h: Reference height for rect definitions.
        :return: Scaled and clamped rects.
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
        *,
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
         :return: Mean RGB of brightest patch.
        """
        if im.mode != "RGB":
            im = im.convert("RGB")

        W, H = im.size
        px = im.load()

        best_luma = -1.0
        best_box = None

        for rx, ry, rw, rh in rects:
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
                    y = 0.2126 * r + 0.7152 * g + 0.0722 * b  # Fast luma

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

    def _solve_bg_darken(
        self,
        bg_rgb: RGB,
        text_rgb: RGB,
        target: float,
    ) -> int:
        """
        Solve darken percentage applied to background luminance.

        :param bg_rgb: RGB underlay sample.
        :param text_rgb: Overlay/text RGB.
        :param target: Target contrast ratio.
        :return: Background darken percentage.
        """
        cfg = self.color.cfg

        # Red relax logic from original pipeline
        if cfg.red_relax_enable:
            h, _, _ = self.color.rgb_to_hls(text_rgb)
            d = min(abs(h - cfg.red_hue_center), 1.0 - abs(h - cfg.red_hue_center))
            if d <= cfg.red_hue_window and (
                self.color.get_luminosity(bg_rgb) <= cfg.red_bg_floor
            ):
                target = max(cfg.red_min_target, min(target, cfg.red_relax_cap))

        L_text = self.color.get_luminosity(text_rgb)
        L_bg = self.color.get_luminosity(bg_rgb)

        contrast = (max(L_text, L_bg) + 0.05) / (min(L_text, L_bg) + 0.05)
        if contrast >= target:
            return 0

        numerator = (L_text + 0.05) / target - 0.05
        if L_bg <= 0 or numerator <= 0:
            return cfg.max_darken_cap

        k = max(0.0, min(1.0, numerator / L_bg))
        pct = int(round((1.0 - k) * 100))
        return max(0, min(cfg.max_darken_cap, pct))

    def _solve_text_darken(
        self,
        bg_rgb: RGB,
        text_rgb: RGB,
        target: float,
    ) -> int:
        """
        Solve darken percentage for overlay/text colour alone.

        :param bg_rgb: RGB underlay sample.
        :param text_rgb: Overlay/text RGB.
        :param target: Target contrast ratio.
        :return: Text/overlay darken percentage.
        """
        L_bg = self.color.get_luminosity(bg_rgb)
        L_text = self.color.get_luminosity(text_rgb)

        def contrast_for(L_t: float) -> float:
            L1, L2 = (L_bg, L_t) if L_bg >= L_t else (L_t, L_bg)
            return (L1 + 0.05) / (L2 + 0.05)

        if contrast_for(L_text) >= target:
            return 0

        best = 100
        for pct in range(1, 101):
            k = 1.0 - (pct / 100.0)
            if contrast_for(L_text * k) >= target:
                best = pct
                break

        return best
