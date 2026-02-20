# author: realcopacetic

from typing import Iterable

from PIL import Image, ImageStat

from resources.lib.art.policy import ART_FIELDS_DARKEN_ELEMENT
from resources.lib.plugin.opts import DarkenOpts
from resources.lib.shared import logger as log

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

    def compute_darken(
        self,
        image: Image.Image,
        *,
        opts: DarkenOpts,
    ) -> DarkenUpdates | None:
        """
        Compute darken updates based on ``opts.mode``.

        :param image: PIL image to sample (original, not blurred).
        :param opts: Darken options for sampling and targets.
        :return: Dict of updates or None.  Keys: "darken" always; plus element keys if mode="all".
        """
        if not opts.enabled:
            return None

        ctx = self._prepare_darken_context(image=image, opts=opts)
        if not ctx:
            return None

        framed, rects, L_text, strength = ctx
        mode = opts.mode or ""
        updates: DarkenUpdates = {}
        updates["darken"] = self._compute_artwork_darken(
            framed=framed,
            rects=rects,
            strength=strength,
            L_text=L_text,
        )

        if mode == "all":
            updates.update(
                self._compute_darken_element_series(
                    framed=framed,
                    rects=rects,
                    strength=strength,
                )
            )

        return updates

    def _compute_artwork_darken(
        self,
        *,
        framed: Image.Image,
        rects: list[Rect],
        L_text: float,
        strength: float,
    ) -> int:
        """
        Darken the artwork behind elements.
        Finds the brightest rect, maps its luminance to 0-100 scaled by opts.strength.
        Aborts if the overlay element is dark (no darken needed).

        :param framed: Framed image.
        :param rects: Scaled rects.
        :param L_text: Overlay element luminance — used to abort if element is dark.
        :param strength: Multiplier (0.0-2.0) controlling effect strength.
        :return: Darken percentage 0..100.
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
        pct = self._solve_bg_darken(L_bg=L_bg, L_text=L_text, strength=strength)
        if pct > 0:
            log.debug(
                f"{self.__class__.__name__} → artwork winner rect[{idx}] → "
                f"rect={rect}, bg_rgb={bg_rgb}, "
                f"L_bg={L_bg:.4f}, L_text={L_text:.4f}, strength={strength:.2f}, darken={pct}",
            )

        return pct

    def _compute_darken_element_series(
        self,
        *,
        framed: Image.Image,
        rects: list[Rect],
        strength: float,
    ) -> DarkenUpdates:
        """
        Darken elements on top of artwork (e.g. white text/logo on bright art).
        Each rect evaluated independently; complex patches skipped (-1).

        :param framed: Framed image.
        :param rects: Scaled rects.
        :param strength: Multiplier (0.0-2.0) controlling effect strength.
        :return: Dict like {"darken_element": x, "darken_element1": y, ...}.
        """
        keys = ART_FIELDS_DARKEN_ELEMENT
        updates: DarkenUpdates = {}
        best = None
        for idx, rect in enumerate(rects[: len(keys)]):
            x, y, w, h = rect
            patch = framed.crop((x, y, x + w, y + h))
            key = keys[idx]

            if not self._is_simple_patch(patch):
                pct = -1
            else:
                bg_rgb, L_bg = self._sample_bg(patch)
                pct = self._solve_darken_element(
                    L_bg=L_bg,
                    strength=strength,
                    floor=self.color.cfg.darken_element_floor,
                )
                if pct > 0 and (best is None or pct > best[0]):
                    best = (pct, idx, key, rect, bg_rgb, L_bg)

            updates[key] = pct

        if best:
            pct, idx, key, rect, bg_rgb, L_bg = best
            log.debug(
                f"{self.__class__.__name__} → element winner rect[{idx}] → "
                f"key={key}, rect={rect}, bg_rgb={bg_rgb}, "
                f"L_bg={L_bg:.4f}, strength={strength:.2f}, darken={pct}",
            )

        return updates

    def _prepare_darken_context(
        self,
        *,
        image: Image.Image,
        opts: DarkenOpts,
    ) -> tuple[Image.Image, list[Rect], float, float] | None:
        """
        Resolve image, rects, overlay luminance and strength for darken sampling.
        opts.source is expected to be a resolved hex string at this point —
        clearlogo resolution is handled upstream in ImageProcessor.darken.

        :param image: PIL image to sample.
        :param opts: Parsed options.
        :return: Tuple (framed, rects, L_text, strength) or None.
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

        src = (opts.source or "").strip()
        text_rgb = (
            self.color.from_hex(src)
            if src
            else self.color.from_hex(cfg.element_overlay_color)
        )
        L_text = self.color.get_luminosity(text_rgb)
        return framed, rects, L_text, opts.strength

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
            parsed = [(0, 0, frame_w, frame_h)]

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
        Downsample patch, take top-k brightest pixels using a histogram mask.
        """
        cfg = self.color.cfg
        n = max(8, int(cfg.avg_downsample))
        k_frac = max(0.0, min(1.0, float(cfg.bg_sampling_topk)))

        tiny = patch.convert("RGB").resize((n, n), Image.BOX)
        tiny_l = tiny.convert("L")

        hist = tiny_l.histogram()
        target_pixels = max(1, int(round((n * n) * k_frac)))

        count = 0
        thresh = 255
        for i in range(255, -1, -1):
            count += hist[i]
            if count >= target_pixels:
                thresh = i
                break

        mask = tiny_l.point(lambda p: 255 if p >= thresh else 0, mode="1")
        stat = ImageStat.Stat(tiny, mask=mask)

        if stat.count[0] == 0:
            rgb = self.color.plain_mean_rgb(tiny)
        else:
            r, g, b = stat.mean
            rgb = (int(r), int(g), int(b))
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
        L_bg: float,
        L_text: float,
        strength: float,
    ) -> int:
        """
        Map background luminance to a darken percentage for artwork behind elements.
        Aborts if the overlay element is already dark (L_text < 0.2) since no
        darkening is needed when a dark element sits on a bright background.
        Bright art → high value; dark art → low or zero.
        The skin XML maps the 0-100 output to opacity/tint steps.

        :param L_bg: Background luminance (0..1).
        :param L_text: Overlay element luminance (0..1) — abort gate only.
        :param strength: Multiplier (0.0-2.0) controlling effect strength.
        :return: Darken percentage (0..100).
        """
        if L_bg <= 0:
            return 0

        if L_text < 0.2:
            log.debug(
                f"{self.__class__.__name__}: bg darken aborted → "
                f"element is dark (L_text={L_text:.3f})"
            )
            return 0

        return min(100, int(round(L_bg * 100 * strength)))

    def _solve_darken_element(self, *, L_bg: float, strength: float, floor: float) -> int:
        """
        Map background luminance to a darken percentage for elements on top of artwork.
        Bright art → element needs heavy darkening toward black; dark art → little or none.
        Returns 0 if L_bg is below floor — background is dark enough that a light
        element already has sufficient contrast without any darkening.
        The skin XML maps the 0-100 output to opacity/tint steps.

        :param L_bg: Background luminance (0..1).
        :param strength: Multiplier (0.0-2.0) controlling effect strength.
        :param floor: Luminance floor (0..1) below which no darkening is applied.
        :return: Darken percentage (0..100).
        """
        if L_bg <= 0:
            return 0

        if L_bg < floor:
            return 0

        return min(100, int(round(L_bg * 100 * strength)))
