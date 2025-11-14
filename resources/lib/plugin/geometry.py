# author: realcopacetic

from dataclasses import dataclass
from typing import Mapping, Optional

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import clamp, parse_bool, to_int

DEFAULT_COORDS: dict[str, tuple[int, int, int, int]] = {
    "TypewriterAnimation": (0, 0, 1920, 1080),
    "ProgressBarManager": (780, 1048, 360, 4),
    "JumpButton": (120, 1048, 1680, 4),
}


def parse_inset(s: str | None) -> tuple[int, int, int, int]:
    """
    Parse "inset" strings into a 4-tuple.

    :param s: "all" | "x,y" | "l,t,r,b" (CSV); empty/None → (0,0,0,0).
    :return: (left, top, right, bottom).
    """
    if not s:
        return 0, 0, 0, 0
    parts = [to_int(p.strip(), 0) for p in str(s).split(",")]
    if len(parts) == 1:
        l = t = r = b = parts[0]
    elif len(parts) == 2:
        l = r = parts[0]
        t = b = parts[1]
    elif len(parts) >= 4:
        l, t, r, b = parts[:4]
    else:
        l = t = r = b = 0
    return l, t, r, b


def apply_inset(
    rect: tuple[int, int, int, int], inset: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """
    Apply a 4-tuple inset to a rect.

    :param rect: (x, y, w, h) input rect.
    :param inset: (l, t, r, b) shrink values.
    :return: Inset (x, y, w, h).
    """
    posx, posy, width, height = rect
    l, t, r, b = inset
    posx += l
    posy += t
    width = max(0, width - l - r)
    height = max(0, height - t - b)
    return posx, posy, width, height


def resolve_rect(
    *,
    window,
    coords: str | None,
    anchor_id: int | None,
    caller_name: str | None = None,
) -> tuple[int, int, int, int]:
    """
    Resolve base rect: coords → anchor → default.

    :param window: Kodi window object for control lookup.
    :param coords: CSV "x,y,w,h" absolute override (highest priority).
    :param anchor_id: Control to derive (x,y,w,h) from if coords not provided.
    :param adjust_fn: Optional transform on the resolved rect.
    :param caller_name: Used for DEFAULT_COORDS lookup and logs.
    :return: (x, y, w, h) rect.
    """
    name = caller_name or "resolve_rect"

    if coords:
        try:
            return tuple(map(int, coords.split(",")))

        except Exception as exc:
            log.debug(f"{name}: Invalid coords '{coords}': {exc}")

    if anchor_id:
        try:
            a = window.getControl(int(anchor_id))
            return (a.getX(), a.getY(), a.getWidth(), a.getHeight())

        except Exception as exc:
            log.warning(f"{name}: Failed to read anchor {anchor_id}: {exc}")

    return DEFAULT_COORDS.get(name, (0, 0, 0, 0))


def axis_travel(start: int, span: int, item_size: int, fraction: float) -> int:
    """
    Slide an item of size 'item_size' across span, clamped to 0..1.

    :param start: Track start coordinate (x or y).
    :param span: Track length (w or h).
    :param item_size: Size of the sliding item (w or h).
    :param fraction: 0..1 position along the track.
    :return: Aligned coordinate on the main axis.
    """
    travel = max(0, span - item_size)
    return int(start + clamp(fraction, 0.0, 1.0) * travel)


def center_x(posx: int, width: int, w: int, offset: int = 0) -> int:
    """
    Center a width 'w' inside (posx,width).

    :param posx: Track x.
    :param width: Track width.
    :param w: Item width.
    :param offset: Optional nudge.
    :return: Centered x.
    """
    return int(posx + (width - w) / 2) + (offset or 0)


def center_y(posy: int, height: int, h: int, offset: int = 0) -> int:
    """
    Center a height 'h' inside (posy,height).

    :param posy: Track y.
    :param height: Track height.
    :param h: Item height.
    :param offset: Optional nudge.
    :return: Centered y.
    """
    return int(posy + (height - h) / 2) + (offset or 0)


def align_x(posx: int, width: int, w: int, align: str = "center", pad: int = 0) -> int:
    """
    Align width 'w' in a track on X.

    :param posx: Track x.
    :param width: Track width.
    :param w: Item width.
    :param align: left|center|right.
    :param pad: Padding offset.
    :return: Aligned x.
    """
    a = (align or "center").lower()
    if a == "left":
        return posx + (pad or 0)
    if a == "right":
        return posx + max(0, width - w - (pad or 0))
    return center_x(posx, width, w, pad or 0)


def align_y(posy: int, height: int, h: int, align: str = "center", pad: int = 0) -> int:
    """
    Align height 'h' in a track on Y.

    :param posy: Track y.
    :param height: Track height.
    :param h: Item height.
    :param align: top|center|bottom.
    :param pad: Padding offset.
    :return: Aligned y.
    """
    a = (align or "center").lower()
    if a == "top":
        return posy + (pad or 0)
    if a == "bottom":
        return posy + max(0, height - h - (pad or 0))
    return center_y(posy, height, h, pad or 0)


@dataclass(slots=True)
class PlacementOpts:
    """
    Generic geometry/placement options.

    :param coords: Absolute CSV "x,y,w,h" override.
    :param anchor_id: Control to derive rect from when coords empty.
    :param track_w: Optional content width within the resolved rect.
    :param track_h: Optional content height within the resolved rect.
    :param relative: Preserve thin-axis position when sliding along track.
    :param valign: Inside-rect vertical align: top|center|bottom.
    :param halign: Inside-rect horizontal align: left|center|right.
    :param vpad: Thin-axis nudge (Y for horizontal tracks).
    :param hpad: Thin-axis nudge (X for vertical tracks).
    :param inset: CSV inset "all" | "x,y" | "l,t,r,b".
    :param outside: Optional outside placement: below|above|left|right.
    """

    coords: str = ""
    anchor_id: Optional[int] = None
    track_w: Optional[int] = None
    track_h: Optional[int] = None
    relative: bool = False
    valign: str = "center"
    halign: str = "center"
    vpad: int = 0
    hpad: int = 0
    inset: str = ""
    outside: Optional[str] = None  # "below"|"above"|"left"|"right"

    @classmethod
    def from_params(cls, params: Mapping[str, str]) -> "PlacementOpts":
        """
        Build PlacementOpts from plugin params.

        :param params: Mapping of plugin path params.
        :return: PlacementOpts instance.
        """
        return cls(
            coords=params.get("coords", ""),
            anchor_id=to_int(params.get("anchor_id"), None),
            track_w=to_int(params.get("track_w"), None),
            track_h=to_int(params.get("track_h"), None),
            relative=parse_bool(params.get("relative"), False),
            valign=(params.get("valign") or "center"),
            halign=(params.get("halign") or "center"),
            vpad=to_int(params.get("vpad"), 0) or 0,
            hpad=to_int(params.get("hpad"), 0) or 0,
            inset=params.get("inset", ""),
            outside=(params.get("outside") or None),
        )


def compute_rect(
    *,
    window,
    caller_name: str,
    opts: PlacementOpts,
    content_w: int | None = None,
    content_h: int | None = None,
) -> tuple[int, int, int, int]:
    """
    Resolve and fit a rect using PlacementOpts.

    :param window: Kodi window object.
    :param caller_name: For DEFAULT_COORDS and logs.
    :param opts: Placement options container.
    :param content_w: Optional intrinsic content width.
    :param content_h: Optional intrinsic content height.
    :return: Final (x, y, w, h) rect.
    """
    # Resolve base rect
    posx, posy, width, height = resolve_rect(
        coords=opts.coords,
        window=window,
        anchor_id=opts.anchor_id,
        caller_name=caller_name,
    )

    # Keep raw anchor bounds for 'outside' placement
    anchor_x, anchor_y, anchor_w, anchor_h = posx, posy, width, height

    # Inset inside the base rect
    posx, posy, width, height = apply_inset(
        (posx, posy, width, height), parse_inset(opts.inset)
    )

    # Size/align inside
    target_w = opts.track_w or content_w or width
    target_h = opts.track_h or content_h or height

    # Outside placement if requested
    mode = (opts.outside or "").lower()
    if mode and opts.anchor_id:
        if mode == "below":
            out_x = align_x(
                anchor_x, anchor_w, target_w, align=opts.halign, pad=opts.hpad
            )
            out_y = anchor_y + anchor_h + (opts.vpad or 0)
            return out_x, out_y, target_w, target_h
        if mode == "above":
            out_x = align_x(
                anchor_x, anchor_w, target_w, align=opts.halign, pad=opts.hpad
            )
            out_y = anchor_y - (opts.vpad or 0) - target_h
            return out_x, out_y, target_w, target_h
        if mode == "right":
            out_x = anchor_x + anchor_w + (opts.hpad or 0)
            out_y = align_y(
                anchor_y, anchor_h, target_h, align=opts.valign, pad=opts.vpad
            )
            return out_x, out_y, target_w, target_h
        if mode == "left":
            out_x = anchor_x - (opts.hpad or 0) - target_w
            out_y = align_y(
                anchor_y, anchor_h, target_h, align=opts.valign, pad=opts.vpad
            )
            return out_x, out_y, target_w, target_h

    # Inside placement (default)
    if target_w < width:
        posx = align_x(posx, width, target_w, align=opts.halign, pad=opts.hpad)
        width = target_w
    if target_h < height:
        posy = align_y(posy, height, target_h, align=opts.valign, pad=opts.vpad)
        height = target_h

    return posx, posy, width, height
