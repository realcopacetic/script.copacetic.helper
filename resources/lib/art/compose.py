# author: realcopacetic

"""
Compose: the second pass over prepared art, once per serve and never cached, so
compose params retune for free. Reads each art's measurement; no PIL.
"""

import json
import math
from typing import Any, Mapping

from resources.lib.art import policy
from resources.lib.art.color import from_hex, luminance
from resources.lib.plugin.opts import ArtOpts

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


def compose(records: Mapping[str, dict[str, Any]], art_opts: Mapping[str, ArtOpts]):
    """
    Add each art's compose outputs to its record, in place, from its measurement
    and the clearlogo's colour.

    :param records: Prepared attributes per art_type.
    :param art_opts: Parsed ArtOpts per art_type.
    """
    measures = {
        art_type: json.loads(attrs[policy.ART_FIELD_MEASURE])
        for art_type, attrs in records.items()
        if policy.ART_FIELD_MEASURE in attrs
    }
    logo = measures.get("clearlogo", {}).get("dominant")
    for art_type, attrs in records.items():
        opts = art_opts[art_type].darken
        if not (opts and opts.enabled):
            continue
        sources = [
            logo or policy.ColorConfig.element_overlay_color if s == "clearlogo" else s
            for s in opts.sources
        ]
        pct = darken(
            measures[art_type]["zones"], sources, opts.surface, art_opts[art_type].ratio
        )
        attrs[policy.ART_FIELD_DARKEN] = pct if opts.max is None else min(pct, opts.max)
