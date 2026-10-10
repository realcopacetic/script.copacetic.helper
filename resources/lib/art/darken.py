# author: realcopacetic

from functools import reduce
from math import ceil
from operator import mul
from typing import Any

from PIL import Image, ImageChops, ImageFilter

from resources.lib.art.color import W, encode, from_hex, linear, luminance
from resources.lib.plugin.opts import ArtOpts, DarkenOpts

Rect = tuple[int, int, int, int]
Box = tuple[int, int, int, int]

LIN = [round(255 * linear(v / 255)) for v in range(256)]


def luminance_image(image: Image.Image) -> Image.Image:
    """
    8-bit linear luminance of an RGB image: a point table, then a weighted convert.

    :param image: RGB image.
    :return: "L" image of linear luminance, 0-255.
    """
    return image.point(LIN * 3).convert("L", (*W, 0))


def ramp(size: tuple[int, int], box: Box, margin: int) -> Image.Image:
    """
    Smoothstep mask: full inside the box, falling to 0 over `margin` px outside it,
    with no step at the box's edge.

    :param size: Mask size (w, h).
    :param box: Box (x0, y0, x1, y1) at full strength.
    :param margin: Fade length outside the box, px.
    :return: Mode "L" mask.
    """

    def axis(n: int, a: int, b: int) -> bytes:
        ts = (max(0.0, 1 - max(a - x, x - (b - 1), 0) / margin) for x in range(n))
        return bytes(round(255 * t * t * (3 - 2 * t)) for t in ts)

    w, h = size
    rx = Image.frombytes("L", (w, 1), axis(w, box[0], box[2]))
    ry = Image.frombytes("L", (1, h), axis(h, box[1], box[3]))
    return ImageChops.multiply(*(s.resize(size, Image.NEAREST) for s in (rx, ry)))


def pull_table(text: str, tint: str, ratio: float, margin: float) -> list[int]:
    """
    Per linear luminance 0-255, the pull toward tint (0-255) that makes a grey of
    that luminance read under text at ratio; 255 when even the tint can't carry it.

    :param text: Element colour, hex.
    :param tint: Colour pulled toward, hex.
    :param ratio: Contrast target.
    :param margin: Tolerance on the limits for 8-bit rounding and the grey model.
    :return: 256 pull values.
    """
    lt = luminance(from_hex(text))
    lo = ((lt + 0.05) / ratio - 0.05) * (1 - margin)
    hi = (ratio * (lt + 0.05) - 0.05) * (1 + margin)
    te = [c / 255 for c in from_hex(tint)]

    def reads(lum: float) -> bool:
        return lum <= lo or lum >= hi

    def mix(ge: float, a: float) -> float:
        return sum(w * linear(ge * (1 - a) + t * a) for w, t in zip(W, te))

    table = []
    for v in range(256):
        ge, a0, a1 = encode(v / 255), 0.0, 1.0
        if reads(v / 255):
            a1 = 0.0
        elif reads(mix(ge, 1.0)):  # bisection: luminance is monotonic in the pull
            for _ in range(8):
                mid = (a0 + a1) / 2
                a0, a1 = (a0, mid) if reads(mix(ge, mid)) else (mid, a1)
        table.append(round(a1 * 255))
    return table


def lift_table(text: str, ratio: float, margin: float) -> list[int]:
    """
    Per linear luminance 0-255, the amount to add to R, G and B that makes a grey of
    that luminance read under dark text at ratio. Adding keeps each pixel's hue and
    chroma, so a lifted colour stays itself, only lighter.

    :param text: Element colour, hex.
    :param ratio: Contrast target.
    :param margin: Tolerance on the limit for 8-bit rounding and the grey model.
    :return: 256 amounts, 0-255.
    """
    hi = (ratio * (luminance(from_hex(text)) + 0.05) - 0.05) * (1 + margin)
    floor = encode(min(hi, 1.0))
    return [max(0, ceil(255 * (floor - encode(v / 255)))) for v in range(256)]


def band_tables(
    text: str, tint: str, ratio: float, margin: float
) -> tuple[bool, list[int], list[float]]:
    """
    How a band carries text: lift under text darker than its tint, else pull toward
    the tint; with each table's change to a grey, in levels, to compare candidates.

    :param text: Element colour, hex.
    :param tint: The band palette end the candidate faces, hex.
    :param ratio: Contrast target.
    :param margin: Tolerance on the limits.
    :return: (lifts, table to apply, change per luminance).
    """
    lt = luminance(from_hex(tint))
    if lt > luminance(from_hex(text)):
        table = lift_table(text, ratio, margin)
        return True, table, table
    table = pull_table(text, tint, ratio, margin)
    t = 255 * encode(lt)
    change = [
        a * max(0.0, 255 * encode(v / 255) - t) / 255 for v, a in enumerate(table)
    ]
    return False, table, change


class ColorDarken:
    """
    Measure artwork for compose (each rect's extremes on the art and on its blur)
    and build the per-pixel band, step 3 of an element on art.
    """

    def __init__(self, color_analyzer: object) -> None:
        """
        Initialise with shared ColorAnalyzer utilities.

        :param color_analyzer: Analyzer instance providing colour helpers.
        """
        self.color = color_analyzer

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

    def band(
        self, blur: Image.Image, opts: ArtOpts, tints: dict[str, str]
    ) -> tuple[str, Image.Image]:
        """
        The candidate whose band changes the rects least, from their luminance
        histogram, and its copy of the blur: clashing pixels lifted (dark text) or
        pulled toward its tint (light text).

        :param blur: The band's blur, RGB.
        :param opts: ArtOpts carrying rects, frame, labels and ratio.
        :param tints: Tint (hex) per candidate element colour (hex).
        :return: (chosen element colour, tinted copy of the blur).
        """
        cfg = self.color.cfg
        rects, _ = self._clamp_rects_to_labels(opts.darken)
        boxes = self.boxes(blur.size, rects, opts.darken.frame)
        k, _, _ = self._cover(blur.size, opts.darken.frame)
        m = round(cfg.band_feather / k)
        x0, y0 = (max(0, min(b[i] for b in boxes) - m) for i in (0, 1))
        x1 = min(blur.width, max(b[2] for b in boxes) + m)
        y1 = min(blur.height, max(b[3] for b in boxes) + m)
        area = blur.crop((x0, y0, x1, y1))  # rects plus fade: all the band touches
        boxes = [
            (bx0 - x0, by0 - y0, bx1 - x0, by1 - y0) for bx0, by0, bx1, by1 in boxes
        ]

        hist = [
            sum(n)
            for n in zip(*(luminance_image(area.crop(b)).histogram() for b in boxes))
        ]
        tables = {
            c: band_tables(c, t, opts.ratio, cfg.band_tolerance)
            for c, t in tints.items()
        }
        text = min(tables, key=lambda c: sum(map(mul, hist, tables[c][2])))
        lifts, table, _ = tables[text]
        fade = reduce(ImageChops.lighter, (ramp(area.size, box, m) for box in boxes))

        def need(image: Image.Image) -> Image.Image:
            return (
                luminance_image(image)
                .reduce(2)
                .point(table)
                .filter(ImageFilter.MaxFilter(3))
                .resize(area.size, Image.BILINEAR)
                .filter(ImageFilter.GaussianBlur(2))
            )

        if lifts:  # repeated: a channel that clips at white lifts less than a grey
            lifted = area
            for _ in range(4):
                if not (amount := need(lifted)).getbbox():
                    break
                lifted = ImageChops.add(lifted, Image.merge("RGB", [amount] * 3))
            area = Image.composite(lifted, area, fade)
        else:
            tint = Image.new("RGB", area.size, "#" + tints[text][2:])
            area = Image.composite(tint, area, ImageChops.multiply(need(area), fade))
        out = blur.copy()
        out.paste(area, (x0, y0))
        return text, out

    def _frame(self, frame: str | None) -> tuple[int, int]:
        """
        The berth the rects are written against.

        :param frame: Frame size "w,h"; None is the default frame.
        :return: (w, h) in frame px.
        """
        return tuple(map(int, frame.split(","))) if frame else self.color.cfg.bg_frame

    def _cover(
        self, size: tuple[int, int], frame: str | None
    ) -> tuple[float, float, float]:
        """
        How Kodi's scale aspect ratio draws an image over the frame: frame px per
        image px, and the image's overhang each side, in frame px.

        :param size: Image size (w, h).
        :param frame: Frame size "w,h"; None is the default frame.
        :return: (k, ox, oy).
        """
        fw, fh = self._frame(frame)
        iw, ih = size
        k = max(fw / iw, fh / ih)
        return k, (iw * k - fw) / 2, (ih * k - fh) / 2

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
        k, ox, oy = self._cover(size, frame)
        iw, ih = size
        boxes = []
        for x, y, w, h in self.parse_overlay_rects(rects) or [
            (0, 0, *self._frame(frame))
        ]:
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
