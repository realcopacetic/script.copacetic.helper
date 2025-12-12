# author: realcopacetic

from dataclasses import dataclass
from typing import Iterable, Mapping

from PIL import Image, ImageStat

from resources.lib.shared.utilities import parse_bool, to_float
from resources.lib.shared import logger as log

RGB = tuple[int, int, int]
Rect = tuple[int, int, int, int]
DarkenUpdates = dict[str, int]


@dataclass(frozen=True, slots=True)
class DarkenOverlayOpts:
    """
    Overlay configuration for a given artwork type.

    :param enabled: Whether darken is active.
    :param source: Colour source override (hex or "clearlogo").
    :param rects: Rect string for sampling in frame coordinates.
    :param frame: Frame size "w,h" as a raw string.
    :param target: Contrast target override as a raw string.
    """
    enabled: bool
    source: str | None
    rects: str | None
    frame: str | None
    target: str | None

    @classmethod
    def from_params(cls, params: Mapping[str, str], prefix: str) -> "DarkenOverlayOpts":
        """
        Build overlay options from a parameter mapping and a name prefix.

        :param params: Mapping of plugin parameters.
        :param prefix: Prefix such as "background" or "icon".
        :return: Parsed DarkenOverlayOpts instance.
        """
        return cls(
            enabled=parse_bool(params.get(f"{prefix}_overlay_enabled", "false")),
            source=params.get(f"{prefix}_overlay_source"),
            rects=params.get(f"{prefix}_overlay_rects"),
            frame=params.get(f"{prefix}_overlay_frame"),
            target=params.get(f"{prefix}_overlay_target"),
        )


class ColorDarken:
    """
    Compute WCAG-based darken percentages for backgrounds and overlay elements.
    Public methods return dicts ready to be merged into artwork attributes.
    """

    def __init__(self, color_analyzer: object) -> None:
        """
        Initialise with shared ColorAnalyzer utilities.

        :param color_analyzer: Analyzer instance providing colour helpers.
        """
        self.color = color_analyzer

    # --- Public API ---
    def compute_background_darken(
        self,
        image: Image.Image,
        *,
        opts: DarkenOverlayOpts,
    ) -> DarkenUpdates | None:
        """
        Compute a single background darken value across all rects.
        Uses the brightest rect sample as the worst-case background.

        :param image: PIL image to sample.
        :param opts: Parsed DarkenOverlayOpts instance.
        :return: Dict like {"background_darken": pct} or None.
        """
        ctx = self._prepare_darken_context(image=image, opts=opts)
        if not ctx:
            return None

        framed, rects, target, text_rgb, L_text = ctx

        def _sample(rect: Rect) -> tuple[Rect, RGB, float]:
            x, y, w, h = rect
            patch = framed.crop((x, y, x + w, y + h))
            bg_rgb = self._brightest_patch_rgb(patch)
            return rect, bg_rgb, self.color.get_luminosity(bg_rgb)

        idx, (rect, bg_rgb, L_bg) = max(
            ((i, _sample(r)) for i, r in enumerate(rects)),
            key=lambda t: t[1][2],
        )
        pct = self._solve_bg_darken(
            text_rgb=text_rgb,
            L_bg=L_bg,
            L_text=L_text,
            target=target,
        )
        if pct > 0:
            contrast = (max(L_text, L_bg) + 0.05) / (min(L_text, L_bg) + 0.05)
            diff = target - contrast
            log.debug(
                f"{self.__class__.__name__} → background winner rect[{idx}] → "
                f"rect={rect}, bg_rgb={bg_rgb}, text_rgb={text_rgb}, "
                f"L_bg={L_bg:.4f}, L_text={L_text:.4f}, "
                f"contrast={contrast:.3f}, target={target:.2f}, "
                f"diff={diff:+.3f}, darken={pct}",
            )

        return {"darken": pct}

    def compute_element_darken_series(
        self,
        image: Image.Image,
        *,
        opts: DarkenOverlayOpts,
    ) -> DarkenUpdates | None:
        """
        Compute per-rect element darken values for overlays.
        Logs only the strongest non-zero element darken (to avoid spam).

        :param image: PIL image to sample.
        :param opts: Parsed DarkenOverlayOpts instance.
        :return: Dict like {"element_darken": x, "element_darken1": y, ...} or None.
        """
        ctx = self._prepare_darken_context(image=image, opts=opts)
        if not ctx:
            return None

        framed, rects, target, text_rgb, L_text = ctx
        updates: DarkenUpdates = {}
        best = None
        for idx, rect in enumerate(rects):
            x, y, w, h = rect
            patch = framed.crop((x, y, x + w, y + h))
            key = "element_darken" if idx == 0 else f"element_darken{idx}"
            if not self._is_simple_patch(patch):
                pct = -1

            else:
                bg_rgb = self._brightest_patch_rgb(patch)
                L_bg = self.color.get_luminosity(bg_rgb)
                pct = self._solve_text_darken(L_bg=L_bg, L_text=L_text, target=target)
                if pct > 0 and (best is None or pct > best[0]):
                    best = (pct, idx, key, rect, bg_rgb, L_bg)

            updates[key] = pct

        if best:
            pct, idx, key, rect, bg_rgb, L_bg = best
            contrast = (max(L_text, L_bg) + 0.05) / (min(L_text, L_bg) + 0.05)
            diff = target - contrast
            log.debug(
                f"{self.__class__.__name__} → element winner rect[{idx}] → "
                f"key={key}, rect={rect}, bg_rgb={bg_rgb}, text_rgb={text_rgb}, "
                f"L_bg={L_bg:.4f}, L_text={L_text:.4f}, "
                f"contrast={contrast:.3f}, target={target:.2f}, "
                f"diff={diff:+.3f}, darken={pct}",
            )

        return updates

    # --- Internal helpers ---
    def _prepare_darken_context(
        self,
        *,
        image: Image.Image,
        opts: DarkenOverlayOpts,
    ) -> tuple[Image.Image, list[Rect], float, RGB, float] | None:
        """
        Prepare shared darken inputs from overlay options.

        :param image: PIL image to sample.
        :param opts: Parsed DarkenOverlayOpts instance.
        :return: Tuple (framed, rects, target, text_rgb, L_text) or None.
        """
        if not opts.rects:
            return None

        framed, rects = self._prepare_image_and_rects(
            image=image,
            overlay_rects=opts.rects,
            overlay_frame=opts.frame,
        )
        if not rects:
            return None

        cfg = self.color.cfg
        target = to_float(opts.target)
        if target <= 0:
            target = cfg.target_contrast_ratio

        src = (opts.source or "").strip()
        text_rgb = (
            self.color.from_hex(src)
            if src
            else self.color.from_hex(cfg.text_overlay_colour)
        )
        L_text = self.color.get_luminosity(text_rgb)

        return framed, rects, target, text_rgb, L_text

    def _prepare_image_and_rects(
        self,
        *,
        image: Image.Image,
        overlay_rects: str | None,
        overlay_frame: str | None,
    ) -> tuple[Image.Image, list[Rect]]:
        """
        Normalize image to a frame and scale rects into image coordinates.
        Falls back to cfg.text_overlay_rect when no rects are provided.

        :param image: PIL image to sample.
        :param overlay_rects: Rect string in frame coordinates.
        :param overlay_frame: Frame size override "w,h".
        :return: Tuple (framed_image, scaled_rects).
        """
        cfg = self.color.cfg
        frame_w, frame_h = cfg.overlay_default_frame

        if overlay_frame:
            parts = [p.strip() for p in str(overlay_frame).split(",")]
            if len(parts) == 2:
                try:
                    w = int(parts[0])
                    h = int(parts[1])
                    if w > 0 and h > 0:
                        frame_w, frame_h = w, h
                except ValueError:
                    frame_w, frame_h = cfg.overlay_default_frame

        framed, frame_size = self._frame_image(image, frame_w, frame_h)

        rects = self.parse_overlay_rects(overlay_rects or "")
        if not rects:
            bx, by, bw, bh = cfg.text_overlay_rect
            rects = [(bx, by, bw, bh)]

        ref_w, ref_h = frame_size
        scaled = self._scale_rects(
            rects=rects,
            img_w=framed.width,
            img_h=framed.height,
            ref_w=ref_w,
            ref_h=ref_h,
        )

        return framed, scaled

    @staticmethod
    def _frame_image(
        image: Image.Image, frame_w: int, frame_h: int
    ) -> tuple[Image.Image, tuple[int, int]]:
        """
        Normalize image into a frame size using cover-scaling and centering.
        Returns the original image if framing is invalid.

        :param image: Source image.
        :param frame_w: Frame width in pixels.
        :param frame_h: Frame height in pixels.
        :return: Tuple of (framed image, (frame_w, frame_h)).
        """
        if frame_w <= 0 or frame_h <= 0:
            return image, image.size

        if image.size == (frame_w, frame_h):
            return image, (frame_w, frame_h)

        src_w, src_h = image.size
        if src_w <= 0 or src_h <= 0:
            return image, image.size

        scale = max(frame_w / float(src_w), frame_h / float(src_h))
        new_w = max(1, int(round(src_w * scale)))
        new_h = max(1, int(round(src_h * scale)))

        resized = image.resize((new_w, new_h), Image.BOX)

        left = max(0, (new_w - frame_w) // 2)
        top = max(0, (new_h - frame_h) // 2)
        right = min(new_w, left + frame_w)
        bottom = min(new_h, top + frame_h)

        return resized.crop((left, top, right, bottom)), (frame_w, frame_h)

    @staticmethod
    def parse_overlay_rects(param: str) -> list[Rect]:
        """
        Parse overlay rect definitions from a Kodi-style string.
        Accepts "(x,y,w,h),(x,y,w,h)" or "x,y,w,h".

        :param param: Raw rect string.
        :return: Parsed rect tuples.
        """
        value = (param or "").strip()
        if not value:
            return []

        value = value.replace(" ", "")
        parts = [p.strip("()") for p in value.split("),(")] if "(" in value else [value]

        out: list[Rect] = []
        for rect_str in parts:
            nums = rect_str.strip("()").split(",")
            if len(nums) != 4:
                continue
            try:
                x, y, w, h = map(int, nums)
            except ValueError:
                continue
            if w > 0 and h > 0:
                out.append((x, y, w, h))

        return out

    @staticmethod
    def _scale_rects(
        *,
        rects: Iterable[Rect],
        img_w: int,
        img_h: int,
        ref_w: int,
        ref_h: int,
    ) -> list[Rect]:
        """
        Scale rects from a reference frame into image coordinates.
        Clamps to image bounds and discards invalid rects.

        :param rects: Rects in the reference frame.
        :param img_w: Image width in pixels.
        :param img_h: Image height in pixels.
        :param ref_w: Reference width for rect definitions.
        :param ref_h: Reference height for rect definitions.
        :return: Scaled and clamped rects.
        """
        sx = img_w / float(ref_w or 1)
        sy = img_h / float(ref_h or 1)

        out: list[Rect] = []
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

    def _brightest_patch_rgb(self, patch: Image.Image) -> RGB:
        """
        Return mean RGB of the brightest grid cell in a patch.
        Uses cfg.avg_grid and cfg.avg_downsample for speed and stability.

        :param patch: Patch image already cropped to a single overlay rect.
        :return: Mean RGB of the brightest sub-area.
        """
        cfg = self.color.cfg
        if patch.mode != "RGB":
            patch = patch.convert("RGB")

        w, h = patch.size
        gx = max(1, min(cfg.avg_grid, w))
        gy = max(1, min(cfg.avg_grid, h))
        cell_w = w / gx
        cell_h = h / gy

        px = patch.load()
        best_luma = -1.0
        best_box: tuple[int, int, int, int] | None = None

        for iy in range(gy):
            for ix in range(gx):
                left = int(round(ix * cell_w))
                top = int(round(iy * cell_h))
                right = int(round((ix + 1) * cell_w))
                bottom = int(round((iy + 1) * cell_h))

                cx = min(max(0, (left + right) // 2), w - 1)
                cy = min(max(0, (top + bottom) // 2), h - 1)

                r, g, b = px[cx, cy]
                y = 0.2126 * r + 0.7152 * g + 0.0722 * b
                if y > best_luma:
                    best_luma = y
                    best_box = (left, top, right, bottom)

        if best_box is None:
            tiny = patch.resize((cfg.avg_downsample, cfg.avg_downsample), Image.BOX)
            return self.color.mean_rgb(tiny)

        left, top, right, bottom = best_box
        region = patch.crop((left, top, right, bottom))
        tiny = region.resize((cfg.avg_downsample, cfg.avg_downsample), Image.BOX)
        return self.color.mean_rgb(tiny)

    # def _is_simple_patch(self, patch: Image.Image) -> bool:
    #     """
    #     Return True if a patch is simple enough for text darken evaluation.
    #     Uses a grayscale stddev threshold from config.

    #     :param patch: Patch image already cropped to a single overlay rect.
    #     :return: True if patch is not visually complex, else False.
    #     """
    #     cfg = self.color.cfg
    #     try:
    #         stat = ImageStat.Stat(patch.convert("L"))
    #         std = float(stat.stddev[0]) if stat.stddev else 0.0
    #         return std < cfg.text_complexity_stddev
    #     except Exception:
    #         return True

    def _is_simple_patch(self, patch: Image.Image) -> bool:
        """
        Return True if a patch is simple enough for text darken evaluation.

        Heuristic:
        1) Low grayscale stddev => simple.
        2) Otherwise:
        - If truly bimodal (meaningful dark + bright presence) => busy.
        - Else if histogram entropy is high => busy (captures mid-tone texture).
        - Else => simple.
        """
        cfg = self.color.cfg
        try:
            s = cfg.text_complexity_probe_size
            g = patch.convert("L").resize((s, s), Image.BOX)

            stat = ImageStat.Stat(g)
            std = stat.stddev[0] if stat.stddev else 0.0
            if std < cfg.text_complexity_stddev:
                return True

            hist = g.histogram()
            total = s * s

            dark = sum(hist[: cfg.text_complexity_dark_luma + 1])
            bright = sum(hist[cfg.text_complexity_bright_luma :])

            dark_frac = dark / total
            bright_frac = bright / total

            # Busy if *both* extremes are meaningfully present
            if min(dark_frac, bright_frac) >= cfg.text_complexity_bimodal_min:
                return False

            # Otherwise, detect mid-tone texture via entropy
            # entropy in [0..~8] for 256-bin grayscale
            import math

            ent = 0.0
            for c in hist:
                if c:
                    p = c / total
                    ent -= p * math.log2(p)

            return ent < cfg.text_complexity_entropy

        except Exception:
            # Fail open — never block rendering due to analysis failure
            return True


    def _solve_bg_darken(
        self,
        *,
        text_rgb: RGB,
        L_bg: float,
        L_text: float,
        target: float,
    ) -> int:
        """
        Solve the darken percentage applied to background luminance.
        Uses a direct formula so the result is deterministic and fast.

        :param text_rgb: Overlay/text RGB.
        :param L_bg: Background luminance (precomputed).
        :param L_text: Text luminance (precomputed).
        :param target: Target contrast ratio.
        :return: Background darken percentage.
        """
        cfg = self.color.cfg

        if cfg.red_relax_enable:
            h, _, _ = self.color.rgb_to_hls(text_rgb)
            center = cfg.red_hue_center
            d = min(abs(h - center), 1.0 - abs(h - center))
            if d <= cfg.red_hue_window and L_bg <= cfg.red_bg_floor:
                target = max(cfg.red_min_target, min(target, cfg.red_relax_cap))

        contrast = (max(L_text, L_bg) + 0.05) / (min(L_text, L_bg) + 0.05)
        if contrast >= target:
            return 0

        numerator = (L_text + 0.05) / target - 0.05
        if L_bg <= 0 or numerator <= 0:
            return int(cfg.max_darken_cap)

        k = max(0.0, min(1.0, numerator / L_bg))
        pct = int(round((1.0 - k) * 100))
        return max(0, min(int(cfg.max_darken_cap), pct))

    def _solve_text_darken(self, *, L_bg: float, L_text: float, target: float) -> int:
        """
        Solve the darken percentage for overlay/text luminance.
        Performs a small bounded search from 1..100.

        :param L_bg: Background luminance (precomputed).
        :param L_text: Text luminance (precomputed).
        :param target: Target contrast ratio.
        :return: Text/overlay darken percentage.
        """

        def contrast_for(L_t: float) -> float:
            L1, L2 = (L_bg, L_t) if L_bg >= L_t else (L_t, L_bg)
            return (L1 + 0.05) / (L2 + 0.05)

        if contrast_for(L_text) >= target:
            return 0

        for pct in range(1, 101):
            k = 1.0 - (pct / 100.0)
            if contrast_for(L_text * k) >= target:
                return pct

        return 100
