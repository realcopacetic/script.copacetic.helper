# author: realcopacetic

from typing import Any, Iterable

from PIL import Image, ImageStat

from resources.lib.plugin.opts import DarkenOpts
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import to_float

RGB = tuple[int, int, int]
Rect = tuple[int, int, int, int]
DarkenUpdates = dict[str, int]


class ColorDarken:
    """
    Compute darken percentages for artwork and overlay elements.

    Public methods return dicts ready to be merged into artwork metadata.
    """

    def __init__(self, color_analyzer: object) -> None:
        """
        Initialise with shared ColorAnalyzer utilities.

        :param color_analyzer: Analyzer instance providing colour helpers.
        """
        self.color = color_analyzer
        self._BG_SAMPLERS = {
            "grid": self._sample_bg_grid,
            "percentile": self._sample_bg_percentile,
            "topk": self._sample_bg_topk,
        }

    def compute_darken(
        self,
        image: Image.Image,
        *,
        opts: DarkenOpts,
        shared: dict[str, Any] | None = None,
    ) -> DarkenUpdates | None:
        """
        Compute darken updates based on ``opts.mode``.

        :param image: PIL image to sample (original, not blurred).
        :param opts: Darken options for sampling and targets.
        :param shared: Shared per-run context containing prior process results (e.g. clearlogo color).
        :return: Dict of updates or None.
        """
        if not opts.enabled:
            return None

        ctx = self._prepare_darken_context(image=image, opts=opts, shared=shared)
        if not ctx:
            return None

        framed, rects, target, text_rgb, L_text = ctx
        mode = opts.mode or ""
        updates: DarkenUpdates = {}
        updates["darken"] = self._compute_artwork_darken(
            framed=framed,
            rects=rects,
            target=target,
            text_rgb=text_rgb,
            L_text=L_text,
        )

        if mode == "all":
            updates.update(
                self._compute_element_darken_series(
                    framed=framed,
                    rects=rects,
                    target=target,
                    text_rgb=text_rgb,
                    L_text=L_text,
                )
            )

        return updates

    def _compute_artwork_darken(
        self,
        *,
        framed: Image.Image,
        rects: list[Rect],
        target: float,
        text_rgb: RGB,
        L_text: float,
    ) -> int:
        """
        Compute one artwork darken value using worst-case (brightest) rect.

        :param framed: Framed image.
        :param rects: Scaled rects.
        :param target: Target contrast ratio.
        :param text_rgb: Text/overlay RGB.
        :param L_text: Text luminance.
        :return: Darken percentage 0..cap.
        """

        def _sample(rect: Rect) -> tuple[Rect, RGB, float]:
            x, y, w, h = rect
            patch = framed.crop((x, y, x + w, y + h))
            bg_rgb, L_bg = self._sample_bg(patch)
            return rect, bg_rgb, L_bg

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
                f"{self.__class__.__name__} → artwork winner rect[{idx}] → "
                f"rect={rect}, bg_rgb={bg_rgb}, text_rgb={text_rgb}, "
                f"L_bg={L_bg:.4f}, L_text={L_text:.4f}, "
                f"contrast={contrast:.3f}, target={target:.2f}, "
                f"diff={diff:+.3f}, darken={pct}",
            )

        return pct

    def _compute_element_darken_series(
        self,
        *,
        framed: Image.Image,
        rects: list[Rect],
        target: float,
        text_rgb: RGB,
        L_text: float,
    ) -> DarkenUpdates:
        """
        Compute per-rect element darken values for overlays.

        :param framed: Framed image.
        :param rects: Scaled rects.
        :param target: Target contrast ratio.
        :param text_rgb: Text/overlay RGB.
        :param L_text: Text luminance.
        :return: Dict like {"element_darken": x, "element_darken1": y, ...}.
        """
        keys = ("element_darken", "element_darken1", "element_darken2")
        updates: DarkenUpdates = {}
        best = None
        for idx, rect in enumerate(rects[:3]):
            x, y, w, h = rect
            patch = framed.crop((x, y, x + w, y + h))
            key = keys[idx]

            if not self._is_simple_patch(patch):
                pct = -1
            else:
                bg_rgb, L_bg = self._sample_bg(patch)
                pct = self._solve_element_darken(
                    L_bg=L_bg, L_text=L_text, target=target
                )
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

    def _prepare_darken_context(
        self,
        *,
        image: Image.Image,
        opts: DarkenOpts,
        shared: dict[str, Any] | None = None,
    ) -> tuple[Image.Image, list[Rect], float, RGB, float] | None:
        """
        Prepare shared darken inputs from options.

        :param image: PIL image to sample.
        :param opts: Parsed options.
        :param shared: Shared per-run context containing prior process results (e.g. clearlogo color).
        :return: Tuple (framed, rects, target, text_rgb, L_text) or None.
        """
        if not opts.rects:
            return None

        framed, rects = self._prepare_image_and_rects(
            image=image,
            rects=opts.rects,
            frame=opts.frame,
        )
        if not rects:
            return None

        cfg = self.color.cfg
        target = to_float(opts.target)
        if target <= 0:
            target = cfg.target_contrast_ratio

        src = (opts.source or "").strip()
        if src.lower() == "clearlogo":
            clearlogo = shared["results"]["clearlogo"]
            src = clearlogo.get("color") or ""

        text_rgb = (
            self.color.from_hex(src)
            if src
            else self.color.from_hex(cfg.element_overlay_color)
        )
        L_text = self.color.get_luminosity(text_rgb)
        return framed, rects, target, text_rgb, L_text

    def _prepare_image_and_rects(
        self,
        *,
        image: Image.Image,
        rects: str,
        frame: str | None,
    ) -> tuple[Image.Image, list[Rect]]:
        """
        Normalize image to a frame and scale rects into image coordinates.

        :param image: PIL image to sample.
        :param rects: Rect string in frame coordinates.
        :param frame: Optional frame size "w,h".
        :return: Tuple (framed_image, scaled_rects).
        """
        cfg = self.color.cfg
        frame_w, frame_h = cfg.bg_frame
        if frame:
            parts = [p.strip() for p in str(frame).split(",")]
            if len(parts) == 2:
                try:
                    w = int(parts[0])
                    h = int(parts[1])
                    if w > 0 and h > 0:
                        frame_w, frame_h = w, h
                except ValueError:
                    frame_w, frame_h = cfg.bg_frame

        framed, frame_size = self._frame_image(image, frame_w, frame_h)
        parsed = self.parse_overlay_rects(rects or "")
        if not parsed:
            bx, by, bw, bh = cfg.element_overlay_rect
            parsed = [(bx, by, bw, bh)]

        ref_w, ref_h = frame_size
        scaled = self._scale_rects(
            rects=parsed,
            img_w=framed.width,
            img_h=framed.height,
            ref_w=ref_w,
            ref_h=ref_h,
        )
        return framed, scaled

    @staticmethod
    def parse_overlay_rects(param: str) -> list[Rect]:
        """
        Parse overlay rect definitions from a Kodi-style string.

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
    def _frame_image(
        image: Image.Image, frame_w: int, frame_h: int
    ) -> tuple[Image.Image, tuple[int, int]]:
        """
        Normalize image into a frame size using cover-scaling and centering.

        :param image: Source image.
        :param frame_w: Frame width in pixels.
        :param frame_h: Frame height in pixels.
        :return: Tuple (framed_image, (frame_w, frame_h)).
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

    def _sample_bg(self, patch: Image.Image) -> tuple[RGB, float]:
        """
        Sample background RGB and luminance using configured sampler.

        :param patch: Cropped patch image for a single rect.
        :return: Tuple of (rgb, relative_luminance).
        """
        cfg = self.color.cfg
        sampler = self._BG_SAMPLERS.get(cfg.bg_sampling_mode, self._sample_bg_grid)
        return sampler(patch)

    def _sample_bg_grid(self, patch: Image.Image) -> tuple[RGB, float]:
        """
        Sample background using brightest-cell mean (robust baseline).

        :param patch: Patch image cropped to one overlay rect.
        :return: Tuple of (bg_rgb, bg_luminance).
        """
        rgb = self.color.brightest_mean_rgb(patch)
        return rgb, self.color.get_luminosity(rgb)

    def _sample_bg_percentile(self, patch: Image.Image) -> tuple[RGB, float]:
        """
        Downsample patch, compute luminance percentile, mean pixels in bright tail.

        :param patch: Patch image cropped to one overlay rect.
        :return: Tuple of (bg_rgb, bg_luminance).
        """
        cfg = self.color.cfg
        n = max(8, int(cfg.avg_downsample))
        q = max(0.0, min(1.0, float(cfg.bg_sampling_percentile)))

        tiny = patch.convert("RGB").resize((n, n), Image.BOX)
        px = list(tiny.getdata())
        if not px:
            rgb = self.color.plain_mean_rgb(tiny)
            return rgb, self.color.get_luminosity(rgb)

        lumas = [self.color.luma709(p) for p in px]
        l_sorted = sorted(lumas)
        idx = int(round((len(l_sorted) - 1) * q))
        thresh = l_sorted[idx]

        rs = gs = bs = count = 0
        for (r, g, b), y in zip(px, lumas):
            if y >= thresh:
                rs += r
                gs += g
                bs += b
                count += 1

        rgb = (
            self.color.plain_mean_rgb(tiny)
            if count <= 0
            else (rs // count, gs // count, bs // count)
        )
        return rgb, self.color.get_luminosity(rgb)

    def _sample_bg_topk(self, patch: Image.Image) -> tuple[RGB, float]:
        """
        Downsample patch, take top-k brightest pixels by luminance, mean their RGB.

        :param patch: Patch image cropped to one overlay rect.
        :return: Tuple of (bg_rgb, bg_luminance).
        """
        cfg = self.color.cfg
        n = max(8, int(cfg.avg_downsample))
        k_frac = max(0.0, min(1.0, float(cfg.bg_sampling_topk)))

        tiny = patch.convert("RGB").resize((n, n), Image.BOX)
        px = list(tiny.getdata())
        if not px:
            rgb = self.color.plain_mean_rgb(tiny)
            return rgb, self.color.get_luminosity(rgb)

        scored = [(self.color.luma709(p), p) for p in px]
        scored.sort(key=lambda t: t[0], reverse=True)

        k = max(1, int(round(len(scored) * k_frac)))
        rs = sum(p[0] for _, p in scored[:k])
        gs = sum(p[1] for _, p in scored[:k])
        bs = sum(p[2] for _, p in scored[:k])

        rgb = (rs // k, gs // k, bs // k)
        return rgb, self.color.get_luminosity(rgb)

    def _is_simple_patch(self, patch: Image.Image) -> bool:
        """
        Return True if a patch is simple enough for element darken.

        :param patch: Patch image already cropped to one overlay rect.
        :return: True if simple enough, else False.
        """
        cfg = self.color.cfg
        try:
            stat = ImageStat.Stat(patch.convert("L"))
            std = float(stat.stddev[0]) if stat.stddev else 0.0
            return std < cfg.element_complexity_stddev

        except Exception:
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
        Compute how much to darken background to meet target contrast vs text.

        :param text_rgb: Text colour RGB.
        :param L_bg: Background luminance (0..1).
        :param L_text: Text luminance (0..1).
        :param target: Target contrast ratio.
        :return: Darken percentage (0..100).
        """
        if L_bg <= 0:
            return 0

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
        k = numerator / L_bg
        k = 0.0 if k < 0.0 else (1.0 if k > 1.0 else k)
        pct = int(round((1.0 - k) * 100.0))
        return 0 if pct < 0 else (100 if pct > 100 else pct)

    def _solve_element_darken(
        self, *, L_bg: float, L_text: float, target: float
    ) -> int:
        """
        Compute how much to darken element to meet target contrast vs background.
        Uses a simple scan from 1..100 for stability.

        :param L_bg: Background luminance (0..1).
        :param L_text: Text luminance (0..1).
        :param target: Target contrast ratio.
        :return: Darken percentage (1..100) or 0 if already compliant.
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
