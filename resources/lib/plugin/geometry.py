# author: realcopacetic
from dataclasses import dataclass
from typing import Callable, Mapping, Optional, Tuple

from resources.lib.shared.utilities import clamp, log, parse_bool, to_int

DEFAULT_COORDS = {
    "TypewriterAnimation": (0, 0, 1920, 1080),
    "ProgressBarManager": (780, 1048, 360, 4),
    "JumpButton": (120, 1048, 1680, 4),
}

def parse_inset(s: str | None) -> Tuple[int, int, int, int]:
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
    rect: Tuple[int, int, int, int], inset: Tuple[int, int, int, int]
) -> Tuple[int, int, int, int]:
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
    adjust_fn: Optional[
        Callable[[Tuple[int, int, int, int]], Tuple[int, int, int, int]]
    ] = None,
    caller_name: str | None = None,
) -> Tuple[int, int, int, int]:
    """Absolute rect: coords → anchor bounds → default, then optional adjust."""
    name = caller_name or "resolve_rect"
    if coords:
        try:
            rect = tuple(map(int, coords.split(",")))
            return adjust_fn(rect) if adjust_fn else rect
        except Exception as exc:
            log(f"{name}: Invalid coords '{coords}': {exc}")
    if anchor_id:
        try:
            a = window.getControl(int(anchor_id))
            rect = (a.getX(), a.getY(), a.getWidth(), a.getHeight())
            return adjust_fn(rect) if adjust_fn else rect
        except Exception as exc:
            log(f"{name}: Failed to read anchor {anchor_id}: {exc}")
    rect = DEFAULT_COORDS.get(name, (0, 0, 0, 0))
    return adjust_fn(rect) if adjust_fn else rect


def axis_travel(start: int, span: int, item_size: int, fraction: float) -> int:
    travel = max(0, span - item_size)
    return int(start + clamp(fraction, 0.0, 1.0) * travel)


def center_x(posx: int, width: int, w: int, offset: int = 0) -> int:
    return int(posx + (width - w) / 2) + (offset or 0)


def center_y(posy: int, height: int, h: int, offset: int = 0) -> int:
    return int(posy + (height - h) / 2) + (offset or 0)


def align_x(posx: int, width: int, w: int, align: str = "center", pad: int = 0) -> int:
    a = (align or "center").lower()
    if a == "left":
        return posx + (pad or 0)
    if a == "right":
        return posx + max(0, width - w - (pad or 0))
    return center_x(posx, width, w, pad or 0)


def align_y(posy: int, height: int, h: int, align: str = "center", pad: int = 0) -> int:
    a = (align or "center").lower()
    if a == "top":
        return posy + (pad or 0)
    if a == "bottom":
        return posy + max(0, height - h - (pad or 0))
    return center_y(posy, height, h, pad or 0)


@dataclass(slots=True)
class PlacementOpts:
    """Generic geometry/placement options shared by helpers."""

    coords: str = ""  # "x,y,w,h" absolute override
    anchor_id: Optional[int] = None  # derive rect from control bounds
    track_w: Optional[int] = None  # optional track sizing inside resolved rect
    track_h: Optional[int] = None  # optional track sizing inside resolved rect
    relative: bool = False  # preserve thin-axis position
    valign: str = "center"  # for horizontal tracks: top|center|bottom
    halign: str = "center"  # for vertical tracks: left|center|right
    vpad: int = 0  # thin-axis nudge (Y on horizontal)
    hpad: int = 0  # thin-axis nudge (X on vertical)
    inset: str = ""  # "l,t,r,b" | "x,y" | "all"

    @classmethod
    def from_params(cls, params: Mapping[str, str]) -> "PlacementOpts":
        return cls(
            coords=params.get("coords", ""),
            anchor_id=to_int(params.get("anchor_id"), None),
            relative=parse_bool(params.get("relative"), False),
            valign=(params.get("valign") or "center"),
            halign=(params.get("halign") or "center"),
            vpad=to_int(params.get("vpad"), 0) or 0,
            hpad=to_int(params.get("hpad"), 0) or 0,
            inset=params.get("inset", ""),
        )
