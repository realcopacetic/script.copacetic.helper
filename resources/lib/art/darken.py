# author: realcopacetic

from typing import Any, Iterable

from PIL import Image, ImageStat

from resources.lib.art import policy
from resources.lib.art.color import linear, luminance
from resources.lib.plugin.opts import DarkenOpts
from resources.lib.shared import logger as log

RGB = tuple[int, int, int]
Rect = tuple[int, int, int, int]
Box = tuple[int, int, int, int]
DarkenUpdates = dict[str, int]

W = (0.2126, 0.7152, 0.0722)
LIN = [round(255 * linear(v / 255)) for v in range(256)]


def luminance_image(image: Image.Image) -> Image.Image:
    """
    8-bit linear luminance of an RGB image: a point table, then a weighted convert.

    :param image: RGB image.
    :return: "L" image of linear luminance, 0-255.
    """
    return image.point(LIN * 3).convert("L", (*W, 0))


class ColorDarken:
    """
    Measure artwork for compose: each rect's extremes on the art and on its blur.
    Mode "all" also returns the element darken series.
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
        The element darken series, for mode "all" only.

        :param image: PIL image to sample (original, not blurred).
        :param opts: Darken options for sampling.
        :return: darken_element* updates, or None.
        """
        if opts.mode != "all":
            return None

        rects, _ = self._clamp_rects_to_labels(opts)
        framed, (rects,) = self._prepare_image_and_rects(
            image=image, rects=(rects,), frame=opts.frame
        )
        return self._compute_darken_element_series(framed=framed, rects=rects)

    def measure(
        self, raw: Image.Image, blur: Image.Image | None, opts: DarkenOpts
    ) -> tuple[dict[str, Any], list[int | None]]:
        """
        Darkest and brightest 10 % of each rect on the raw art and on the blur, and
        the band palette: the blur from the rects' top down.

        :param raw: Art flattened on the matte, cover-scaled to the blur's width.
        :param blur: The blur as drawn, or None when the art isn't blurred.
        :param opts: Darken options carrying rects, frame and labels.
        :return: ({"zones": [{"art": [lo, hi], "blur": [lo, hi]}], "band"}, widths).
        """
        rects, widths = self._clamp_rects_to_labels(opts)
        zones = [
            {"art": self._extremes(raw, box)}
            for box in self.boxes(raw.size, rects, opts.frame)
        ]
        measure = {"zones": zones}
        if blur:
            boxes = self.boxes(blur.size, rects, opts.frame)
            for zone, box in zip(zones, boxes):
                zone["blur"] = self._extremes(blur, box)
            top = min(box[1] for box in boxes)
            measure["band"] = self.color.extremes(
                blur.crop((0, top, blur.width, blur.height))
            )
        return measure, widths

    def boxes(
        self, size: tuple[int, int], rects: str | None, frame: str | None
    ) -> list[Box]:
        """
        Map frame rects onto an image drawn to cover the frame, centred (Kodi's
        scale aspect ratio). No rects is the whole frame.

        :param size: Image size (w, h).
        :param rects: Rect string in frame coordinates.
        :param frame: Frame size "w,h"; None is the default frame.
        :return: (x0, y0, x1, y1) boxes in image pixels, each at least 1 px.
        """
        fw, fh = tuple(map(int, frame.split(","))) if frame else self.color.cfg.bg_frame
        iw, ih = size
        k = max(fw / iw, fh / ih)
        ox, oy = (iw * k - fw) / 2, (ih * k - fh) / 2
        boxes = []
        for x, y, w, h in self.parse_overlay_rects(rects) or [(0, 0, fw, fh)]:
            x0 = min(iw - 1, max(0, round((x + ox) / k)))
            y0 = min(ih - 1, max(0, round((y + oy) / k)))
            x1 = max(x0 + 1, min(iw, round((x + w + ox) / k)))
            y1 = max(y0 + 1, min(ih, round((y + h + oy) / k)))
            boxes.append((x0, y0, x1, y1))
        return boxes

    def _extremes(self, image: Image.Image, box: Box) -> list[float]:
        """
        Mean linear luminance of the darkest and brightest 10 % of a box, sampled
        at 32x32.

        :param image: RGB image.
        :param box: Box in image pixels.
        :return: [lo, hi], each 0-1.
        """
        cfg = self.color.cfg
        n = cfg.avg_downsample
        px = sorted(
            luminance_image(image.crop(box).resize((n, n), Image.BOX)).getdata()
        )
        k = max(1, round(len(px) * cfg.bg_sampling_topk))
        return [round(sum(px[:k]) / k / 255, 4), round(sum(px[-k:]) / k / 255, 4)]

    def _compute_darken_element_series(
        self,
        *,
        framed: Image.Image,
        rects: list[Rect],
    ) -> DarkenUpdates:
        """
        Darken elements on top of artwork (e.g. white text/logo on bright art).
        Each rect evaluated independently; complex patches return -1. Also emits a
        mean-luminance companion per rect (darken_element_mean*).

        :param framed: Framed image.
        :param rects: Scaled rects.
        :return: Dict of darken_element*/darken_element_mean* values.
        """
        keys = policy.ART_FIELDS_DARKEN_ELEMENT
        mean_keys = policy.ART_FIELDS_DARKEN_ELEMENT_MEAN
        updates = {}
        best = None
        for idx, rect in enumerate(rects[: len(keys)]):
            x, y, w, h = rect
            patch = framed.crop((x, y, x + w, y + h))
            key = keys[idx]
            updates[mean_keys[idx]] = self._sample_mean_pct(patch)

            if not self._is_simple_patch(patch):
                pct = -1
            else:
                bg_rgb, L_bg = self._sample_bg(patch)
                pct = self._solve_darken_element(
                    L_bg=L_bg, floor=self.color.cfg.darken_element_floor
                )
                if pct > 0 and (best is None or pct > best[0]):
                    best = (pct, idx, key, rect, bg_rgb, L_bg)

            updates[key] = pct

        if best:
            pct, idx, key, rect, bg_rgb, L_bg = best
            log.debug(
                f"{self.__class__.__name__} → element winner rect[{idx}] → "
                f"key={key}, rect={rect}, bg_rgb={bg_rgb}, "
                f"L_bg={L_bg:.4f}, darken={pct}",
            )

        return updates

    def _clamp_rects_to_labels(self, opts: DarkenOpts) -> tuple[str, list[int | None]]:
        """
        Clamp each rect by its parallel label and collect per-rect widths.
        Rects without a paired label pass through unclamped.

        :param opts: Darken options carrying rects and the label series.
        :return: (clamped rect string, per-rect width list).
        """
        widths = []
        if not any(opts.labels):
            return opts.rects, widths

        cfg = self.color.cfg
        px = opts.label_px if opts.label_px else cfg.darken_label_px_per_char
        raw = opts.rects.replace(" ", "")
        parts = raw.split("),(") if "(" in raw else [raw]
        clamped = []
        for idx, part in enumerate(parts):
            label = opts.labels[idx] if idx < len(opts.labels) else None
            if label:
                cr, w = self.clamp_rect_to_label(part.strip("()"), label, px)
                clamped.append(cr)
                widths.append(w)
            else:
                clamped.append(part.strip("()"))
                widths.append(None)
        rect_str = f"({'),('.join(clamped)})" if len(clamped) > 1 else clamped[0]
        return rect_str, widths

    def _prepare_image_and_rects(
        self,
        *,
        image: Image.Image,
        rects: Iterable[str],
        frame: str | None,
    ) -> tuple[Image.Image, list[list[Rect]]]:
        """
        Normalize image to a frame and scale each rect string into image coordinates.
        A rect string with no valid rect covers the whole frame.

        :param image: PIL image to sample.
        :param rects: Rect strings in frame coordinates.
        :param frame: Optional frame size "w,h".
        :return: Tuple (framed_image, scaled rects per rect string).
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

        framed, (ref_w, ref_h) = self.frame_image(image, frame_w, frame_h)
        scaled = [
            self._scale_rects(
                rects=self.parse_overlay_rects(r) or [(0, 0, frame_w, frame_h)],
                img_w=framed.width,
                img_h=framed.height,
                ref_w=ref_w,
                ref_h=ref_h,
            )
            for r in rects
        ]
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
        out = []
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
    def clamp_rect_to_label(
        rect: str, label: str, px_per_char: float
    ) -> tuple[str, int | None]:
        """
        Clamp a single rect's width to an estimated label width (left-anchored).

        :param rect: Single rect "x,y,w,h" in frame coordinates.
        :param label: Overlay label text for this rect.
        :param px_per_char: Glyph advance in frame px.
        :return: (clamped rect string, estimated width or None on bad input).
        """
        n = len(label.strip())
        if n <= 0:
            return rect, None
        est = int(round(n * px_per_char))
        if est <= 0:
            return rect, None
        nums = rect.replace(" ", "").strip("()").split(",")
        if len(nums) != 4:
            return rect, None
        try:
            x, y, w, h = (int(v) for v in nums)
        except ValueError:
            return rect, None
        w = min(w, est)
        return f"{x},{y},{w},{h}", w

    @staticmethod
    def frame_image(
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
        return rgb, luminance(rgb)

    def _sample_mean_pct(self, patch: Image.Image) -> int:
        """
        Mean luminance of a patch as a 0-100 percentage.
        Predicts the value the region collapses toward under a strong blur.
        Non-mutating: samples a copy so callers can still read ``patch``.

        :param patch: Cropped patch in image coordinates.
        :return: Mean luminance 0..100.
        """
        n = self.color.cfg.avg_downsample
        small = patch.copy() if patch.mode == "RGB" else patch.convert("RGB")
        if small.width > n or small.height > n:
            small.thumbnail((n, n), Image.BOX)
        r, g, b = ImageStat.Stat(small).mean
        L = luminance((round(r), round(g), round(b)))
        return int(round(L * 100))

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

    def _solve_darken_element(self, *, L_bg: float, floor: float) -> int:
        """
        Map background luminance to a darken percentage for elements on top of artwork.
        Bright art → heavy darkening, dark art → little or none; 0 below floor, where a
        light element already contrasts enough. The skin XML maps 0-100 to tint steps.

        :param L_bg: Background luminance (0..1).
        :param floor: Luminance floor (0..1) below which no darkening is applied.
        :return: Darken percentage (0..100).
        """
        if L_bg <= 0:
            return 0

        if L_bg < floor:
            return 0

        return min(100, int(round(L_bg * 100)))
