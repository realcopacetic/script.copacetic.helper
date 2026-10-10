# author: realcopacetic

"""
Compose maths: the second pass over prepared art, run once per serve from each
art's measurement and never cached. No PIL, so a cached serve never imports it.
"""

import math
from typing import Any

from resources.lib.art import policy
from resources.lib.art.color import (
    RGB,
    contrast,
    from_hex,
    hls_to_rgb,
    luminance,
    rgb_to_hls,
    to_hex,
)

GAMMA = 2.2  # fadediffuse multiplies encoded colour: keeping k of it keeps ~k^2.2 light


def solve_darken(lt: float, hi: float, ratio: float) -> int:
    """
    Least % black over a zone whose brightest end is hi for an element of
    luminance lt to read at ratio; 0 when no floor can carry it or none is needed.

    :param lt: Element luminance, 0-1.
    :param hi: Luminance of the zone's brightest 10 %, 0-1.
    :param ratio: Contrast target.
    :return: % black, 0-100, rounded up so the ratio holds.
    """
    floor = (lt + 0.05) / ratio - 0.05
    if floor < 0 or hi <= floor:
        return 0
    return math.ceil(100 * (1 - (floor / hi) ** (1 / GAMMA)))


def darken(zones: list[dict], sources: list[str], surface: str, ratio: float) -> int:
    """
    The largest of each rect's least darken: one value carries every zone.

    :param zones: The measurement's zones, in rect order.
    :param sources: Element colour (hex) per rect; the last repeats.
    :param surface: "art" or "blur"; an art with no blur measures the art.
    :param ratio: Contrast target.
    :return: % black, 0-100.
    """
    return max(
        solve_darken(
            luminance(from_hex(sources[min(i, len(sources) - 1)])),
            zone.get(surface, zone["art"])[1],
            ratio,
        )
        for i, zone in enumerate(zones)
    )


def element(
    zones: list[dict], colors: tuple[str, ...], ratio: float
) -> tuple[int, str]:
    """
    Step for an element on art, and its colour (the candidate whose worst ratio
    over both ends of every zone is best): 1 nothing, 2 the blur band, 3 a pull.

    :param zones: The measurement's zones, in rect order.
    :param colors: Candidate element colours, hex.
    :param ratio: Contrast target.
    :return: (step, colour); step 3's colour is decided from the histogram later.
    """
    lums = {c: luminance(from_hex(c)) for c in colors}

    def best(surface: str) -> tuple[str, float]:
        worst = {
            c: min(contrast(lt, end) for zone in zones for end in zone[surface])
            for c, lt in lums.items()
        }
        color = max(worst, key=worst.get)
        return color, worst[color]

    color, worst = best("art")
    busy = any(contrast(*zone["art"]) >= ratio for zone in zones)
    if (worst >= ratio and not busy) or "blur" not in zones[0]:
        return 1, color
    color, worst = best("blur")
    return (2 if worst >= ratio else 3), color


def tint(color: str, band: list[str]) -> str:
    """
    The band palette's end a candidate pulls toward: whichever contrasts more
    with it (the darkest under light text, the lightest under dark).

    :param color: Candidate element colour, hex.
    :param band: The band palette's [darkest, lightest], hex.
    :return: Tint, hex.
    """
    lt = luminance(from_hex(color))
    return max(band, key=lambda c: contrast(lt, luminance(from_hex(c))))


def chroma(rgb: RGB) -> float:
    """
    HLS chroma: saturation scaled by distance from black and white.

    :param rgb: (r, g, b) in 0-255.
    :return: Chroma, 0-1.
    """
    _, l, s = rgb_to_hls(rgb)
    return s * (1 - abs(2 * l - 1))


def at_luminance(rgb: RGB, target: float, saturation: float = 1.0) -> str:
    """
    The colour's hue at a relative luminance, by bisection on HLS lightness
    (luminance rises with it).

    :param rgb: (r, g, b) in 0-255.
    :param target: Relative luminance, 0-1.
    :param saturation: Share of the colour's saturation kept.
    :return: Hex colour.
    """
    h, _, s = rgb_to_hls(rgb)
    lo, hi = 0.0, 1.0
    for _ in range(16):
        mid = (lo + hi) / 2
        lo, hi = (
            (mid, hi)
            if luminance(hls_to_rgb((h, mid, s * saturation))) < target
            else (lo, mid)
        )
    return to_hex(hls_to_rgb((h, (lo + hi) / 2, s * saturation)))


def palette(
    measure: dict[str, Any],
    logo: str | None,
    surface: str,
    ratio: float,
    general: int,
    cfg: policy.ColorConfig,
) -> dict[str, Any]:
    """
    Colours at a fixed luminance in the art's hue (accent when it has colour,
    else dominant) and the logo's, each with the % black its floor needs.

    :param measure: The art's measurement: colours and zones.
    :param logo: The clearlogo's dominant colour, hex, or None.
    :param surface: The surface the skin darkens, "art" or "blur".
    :param ratio: Contrast target.
    :param general: The art's general darken, for a neutral base.
    :param cfg: Colour configuration (palette luminance and chroma).
    :return: palette_* fields; a neutral base gives the element colour, no secondary.
    """
    zones = measure["zones"]
    accent, dominant = from_hex(measure["accent"]), from_hex(measure["dominant"])
    base = accent if chroma(accent) >= cfg.palette_chroma else dominant
    if chroma(base) < cfg.palette_chroma:
        out = {
            policy.ART_FIELD_PALETTE_PRIMARY: cfg.element_overlay_color,
            policy.ART_FIELD_PALETTE_DARKEN: general,
        }
    else:
        primary = at_luminance(base, cfg.palette_luminance)
        out = {
            policy.ART_FIELD_PALETTE_PRIMARY: primary,
            policy.ART_FIELD_PALETTE_SECONDARY: at_luminance(
                base,
                cfg.palette_secondary_luminance,
                cfg.palette_secondary_saturation,
            ),
            policy.ART_FIELD_PALETTE_DARKEN: darken(zones, [primary], surface, ratio),
        }
    if logo and chroma(from_hex(logo)) >= cfg.palette_chroma:
        color = at_luminance(from_hex(logo), cfg.palette_luminance)
        out[policy.ART_FIELD_PALETTE_LOGO] = color
        out[policy.ART_FIELD_PALETTE_LOGO_DARKEN] = darken(
            zones, [color], surface, ratio
        )
    return out
