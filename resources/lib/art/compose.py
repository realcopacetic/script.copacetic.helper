# author: realcopacetic

"""
Compose maths: the second pass over prepared art, run once per serve from each
art's measurement and never cached. No PIL, so a cached serve never imports it.
"""

import math

from resources.lib.art.color import contrast, from_hex, luminance

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
