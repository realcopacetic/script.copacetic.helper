# author: realcopacetic

"""Colour maths for the analyser and compose; no PIL, so a cached serve never imports it."""

import colorsys

RGB = tuple[int, int, int]
HLS = tuple[float, float, float]


def from_hex(hex_str: str) -> RGB:
    """
    Convert ARGB/RGB hex to an RGB tuple.

    :param hex_str: Hex string with optional leading "#" and optional alpha.
    :return: (r, g, b) tuple in 0..255.
    """
    s = hex_str.lstrip("#")
    if len(s) == 8:  # strip alpha
        s = s[2:]
    return tuple(int(s[i : i + 2], 16) for i in (0, 2, 4))


def to_hex(rgb: RGB) -> str:
    """
    Convert RGB to ARGB hex with full opacity.

    :param rgb: (r, g, b) tuple in 0..255.
    :return: ARGB hex string (e.g. "ff112233").
    """
    r, g, b = rgb
    return f"ff{r:02x}{g:02x}{b:02x}"


def linear(c: float) -> float:
    """
    sRGB EOTF (piecewise gamma) per WCAG/IEC 61966-2-1.

    :param c: Encoded channel, 0-1.
    :return: Linear channel, 0-1.
    """
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: RGB) -> float:
    """
    Relative luminance per sRGB/Rec.709 with the WCAG transfer curve.
    https://www.w3.org/TR/WCAG21/#dfn-relative-luminance

    :param rgb: (r, g, b) in 0-255.
    :return: L in 0-1.
    """
    r, g, b = (linear(c / 255) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: float, b: float) -> float:
    """
    WCAG contrast ratio of two luminances, either order.

    :param a: Luminance 0-1.
    :param b: Luminance 0-1.
    :return: Ratio, 1-21.
    """
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def rgb_to_hls(rgb: RGB) -> HLS:
    """
    Convert RGB to HLS in 0..1 space.

    :param rgb: RGB tuple in 0..255.
    :return: HLS tuple in 0..1.
    """
    return colorsys.rgb_to_hls(*(c / 255.0 for c in rgb))


def hls_to_rgb(hls: HLS) -> RGB:
    """
    Convert HLS (0..1 floats) to RGB (0..255 ints).

    :param hls: (h, l, s) in 0..1 space.
    :return: (r, g, b) tuple in 0..255.
    """
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(*hls))
