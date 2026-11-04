# author: realcopacetic

from __future__ import annotations

import io
import math
import re
import struct
import time
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

import xbmcvfs

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import SKINXML, skin_path

if TYPE_CHECKING:
    from PIL import ImageFont

# Kodi wraps at U+0020 only; tabs and newlines fold into a break as before
_WORDS = re.compile(r"[^ \t\n\r\f\v]+")

# Kodi's label formatting (CGUITextLayout::ParseText): a [CR] is a newline, tabs a space
_KODI_TABS = re.compile(r"\[TABS\][^\[]*\[/TABS\]")
_KODI_STYLES = re.compile(
    r"\[/?(?:B|I|LIGHT|UPPERCASE|LOWERCASE|CAPITALIZE)\]|\[COLOR[^\]]*\]|\[/COLOR\]"
)

# Markdown's headings ("## v7.4.4", closing #s dropped) and "-" list lines
_MD_HEADING = re.compile(r"^#{1,6}[ \t]+(.+?)[ \t#]*$", re.MULTILINE)
_MD_BULLET = re.compile(r"^([ \t]*)-[ \t]+", re.MULTILINE)

# Rendered pixels Kodi's last-glyph ink extent can add past its advance.
_INK_OVERHANG = 2

DEFAULT_ELLIPSIS = "..."
DEFAULT_ABBREV = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "sr",
    "jr",
    "lt",
    "sgt",
    "cpl",
    "pvt",
    "capt",
    "cmdr",
    "col",
    "maj",
    "gen",
    "adm",
    "det",
    "insp",
    "supt",
    "gov",
    "sen",
    "rev",
    "fr",
    "hon",
    "st",
    "mt",
    "ft",
    "rd",
    "ave",
    "blvd",
    "vs",
    "etc",
    "ie",
    "eg",
    "inc",
    "ltd",
    "bros",
    "co",
    "corp",
    "dept",
    "feat",
    "u",
    "us",
    "uk",
    "eu",
    "u.s",
    "u.k",
    "e.g",
    "i.e",
}


def skin_font(name: str) -> tuple[str, int] | None:
    """
    File and size of a font in the skin's Font.xml (its first fontset), as Kodi
    loads it for a control that names it. None, with a warning, for an unknown name.

    :param name: Kodi font name, e.g. "description_l".
    :return: (special://skin/fonts/ path, size in skin px), or None.
    """
    xml = Path(skin_path(f"{SKINXML}/Font.xml")).read_text("utf-8")
    font = next((b for b in xml.split("</font>") if f"<name>{name}</name>" in b), "")
    if not font:
        log.warning(f"skin_font → not in Font.xml: {name}")
        return None
    filename, size = (
        re.search(rf"<{tag}>\s*(.+?)\s*</{tag}>", font)[1]
        for tag in ("filename", "size")
    )
    return f"special://skin/fonts/{filename}", int(size)


def units_per_em(data: bytes) -> int:
    """unitsPerEm from an sfnt's head table: the denominator of FreeType's scale.

    :param data: TrueType/OpenType font bytes.
    :return: Font units per em.
    """
    (count,) = struct.unpack_from(">H", data, 4)
    offset = next(
        off
        for tag, _, off, _ in struct.iter_unpack(">4sIII", data[12 : 12 + 16 * count])
        if tag == b"head"
    )
    return struct.unpack_from(">H", data, offset + 18)[0]


@lru_cache(maxsize=8)
def load_font(font_path: str) -> ImageFont.FreeTypeFont | None:
    """Load a font at its units-per-em, so a glyph's length is its advance in font
    units. A VFS read covers every path scheme. BASIC layout: no GPOS kerning.

    :param font_path: special://, resource://, or absolute font path.
    :return: Loaded font, or None if unreadable.
    """

    t0 = time.perf_counter()
    from PIL import ImageFont

    log.debug(f"load_font → PIL import {(time.perf_counter() - t0) * 1000:.0f}ms")
    handle = xbmcvfs.File(font_path)
    try:
        data = handle.readBytes()
    finally:
        handle.close()
    if not data:
        log.warning(f"load_font → unreadable: {font_path}")
        return None
    try:
        return ImageFont.truetype(
            io.BytesIO(data), units_per_em(data), layout_engine=ImageFont.LAYOUT_BASIC
        )
    except (OSError, StopIteration, struct.error):
        log.warning(f"load_font → not a valid font: {font_path}")
        return None


class KodiMetric:
    """
    Line width as CGUIFontTTF computes it: advances in FreeType's 16.16 scale and
    26.6 fixed point at the rendered size and xdpi aspect, summed without kerning.
    """

    def __init__(
        self,
        font: ImageFont.FreeTypeFont,
        font_size: int,
        scale_x: float,
        scale_y: float,
    ) -> None:
        """
        Model RescaleFontSizeAndAspect and FT_Set_Char_Size for the current GUI scale.
        Float scaling misses the 1/64 px quantisation that tips advances past .5.

        :param font: Font loaded by load_font, at its units-per-em.
        :param font_size: Font size in skin-coordinate pixels.
        :param scale_x: ScreenWidth / skin width.
        :param scale_y: ScreenHeight / skin height.
        """
        xdpi = math.floor(72 * scale_x / scale_y + 0.5)
        width = (int(font_size * scale_y * 64 + 0.5) * xdpi + 36) // 72
        self.font = font
        self.x_scale = ((width << 16) + font.size // 2) // font.size
        self.scale_x = scale_x
        self.advances = {}

    def getlength(self, text: str) -> float:
        """
        Width of text in skin-coordinate pixels, last-glyph ink headroom included.

        :param text: Single line to measure.
        :return: Sum of rounded rendered advances divided by scale_x.
        """
        total = _INK_OVERHANG
        for ch in text:
            if (advance := self.advances.get(ch)) is None:
                units = round(self.font.getlength(ch))
                advance = self.advances[ch] = (
                    ((units * self.x_scale + 0x8000) >> 16) + 32
                ) >> 6
            total += advance
        return total / self.scale_x


def plain_text(text: str) -> str:
    """Label text without Kodi's formatting tags: a [CR] becomes a newline, as Kodi
    draws it, and [TABS] a space.

    :param text: Text as an infolabel returns it.
    :return: The text the tags format.
    """
    text = _KODI_TABS.sub(" ", text).replace("[CR]", "\n")
    return _KODI_STYLES.sub("", text)


def markdown_label(text: str) -> str:
    """Markdown as a Kodi label: headings bold, "-" list lines "•", lines joined by
    [CR]. Inline markdown stays as written.

    :param text: Text as an infolabel returns it, e.g. ListItem.AddonNews.
    :return: The label, with no blank line at either end.
    """
    text = "\n".join(text.replace("[CR]", "\n").splitlines())
    text = _MD_BULLET.sub(r"\1• ", _MD_HEADING.sub(r"[B]\1[/B]", text))
    return text.strip().replace("\n", "[CR]")


def sentence_cap(text: str, abbrev: set[str] | None = None) -> str | None:
    """
    Return text truncated to its last complete sentence, or None if none found.
    Skips abbreviations and initials, and requires the next token to be capitalised.

    :param text: Input string (no trailing ellipsis).
    :param abbrev: Lowercased abbreviations that don't end a sentence.
    :return: Sentence-capped prefix, or None if no safe boundary exists.
    """
    abbrev = abbrev or DEFAULT_ABBREV
    boundaries = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch in ".!?":
            j = i + 1
            while j < len(text) and text[j] in " \t\n\r\"'»”’)]}":
                j += 1
            token = text[:i].rstrip()
            prev = token.rsplit(" ", 1)[-1].strip(" \"')]}»”’").lower().rstrip(".")
            if len(prev) == 1 and prev.isalpha():
                i += 1
                continue
            next_ok = (j >= len(text)) or text[j].isupper()
            if prev not in abbrev and next_ok:
                boundaries.append(i)
        i += 1
    if not boundaries:
        return None
    return text[: boundaries[-1] + 1].rstrip()


def text_width(font, text: str, tracking: float = 0.0) -> float:
    """Rendered width of text including uniform letter tracking.

    :param font: FreeType font object exposing ``getlength``.
    :param text: String to measure.
    :param tracking: Extra pixels inserted between adjacent glyphs.
    :return: Advance width in pixels.
    """
    return font.getlength(text) + tracking * max(0, len(text) - 1)


def wrap_text(font, text: str, max_width: int, tracking: float = 0.0) -> list[str]:
    """Greedy word-wrap by advance width, as CGUITextLayout::WrapText: breaks at
    ASCII spaces only, so a no-break space holds, and a word wider than the line
    is cut after the last character that fits.

    :param font: FreeType font object exposing ``getlength``.
    :param text: String to wrap.
    :param max_width: Line width ceiling in pixels.
    :param tracking: Extra pixels inserted between adjacent glyphs.
    :return: List of wrapped lines.
    """
    lines = []
    cur = ""
    for word in _WORDS.findall(text):
        trial = f"{cur} {word}" if cur else word
        if text_width(font, trial, tracking) <= max_width:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        while len(word) > 1 and text_width(font, word, tracking) > max_width:
            cut = next(
                i
                for i in range(1, len(word))
                if text_width(font, word[: i + 1], tracking) > max_width
            )
            lines.append(word[:cut])
            word = word[cut:]
        cur = word
    if cur:
        lines.append(cur)
    return lines


def fit_lines(
    font,
    text: str,
    max_width: int,
    max_lines: int,
    tracking: float = 0.0,
    ellipsis: str = DEFAULT_ELLIPSIS,
    abbrev: set[str] | None = None,
    sentences: bool = True,
) -> list[str]:
    """Wrap to lines; on overflow cap at the last sentence, else ellipsise.

    :param font: FreeType font object exposing ``getlength``.
    :param text: String to wrap and clamp.
    :param max_width: Line width ceiling in pixels.
    :param max_lines: Maximum lines to keep.
    :param tracking: Extra pixels inserted between adjacent glyphs.
    :param ellipsis: Suffix appended when a hard cut is required.
    :param abbrev: Lowercased abbreviations that don't end a sentence.
    :param sentences: Cap at a sentence end; False always ellipsises (a title).
    :return: At most ``max_lines`` wrapped lines.
    """
    lines = wrap_text(font, text, max_width, tracking)
    if len(lines) <= max_lines:
        return lines

    # Slice the visible text from the source: a word cut at a character has no space.
    words = " ".join(_WORDS.findall(text))
    end = 0
    for line in lines[:max_lines]:
        end = words.index(line, end) + len(line)
    visible = words[:end]
    if sentences and (capped := sentence_cap(visible, abbrev)):
        return wrap_text(font, capped, max_width, tracking)[:max_lines]

    lines = lines[:max_lines]
    last = lines[-1]
    while last and text_width(font, f"{last}{ellipsis}", tracking) > max_width:
        last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
    last = last.rstrip(".,;:!?…-–—").rstrip("\"')]}»”’")
    lines[-1] = f"{last}{ellipsis}"
    return lines


def fit_paragraphs(
    font, text: str, max_width: int, max_lines: int, tracking: float = 0.0
) -> list[str]:
    """Wrap each line of text alone, as CGUITextLayout::LineBreakText breaks at a
    newline (an empty line stays blank). The paragraph that overflows ends at its last
    sentence; with none, the text ends before it, or ellipsises if it is the first.

    :param font: FreeType font object exposing ``getlength``.
    :param text: Text whose newlines are line breaks.
    :param max_width: Line width ceiling in pixels.
    :param max_lines: Maximum lines to keep.
    :param tracking: Extra pixels inserted between adjacent glyphs.
    :return: At most ``max_lines`` lines, with no blank line at either end.
    """
    lines = []
    for paragraph in text.strip().split("\n"):
        room = max_lines - len(lines)
        wrapped = wrap_text(font, paragraph, max_width, tracking) or [""]
        if len(wrapped) <= room:
            lines += wrapped
            continue
        if room:
            part = fit_lines(font, paragraph, max_width, room, tracking)
            if not lines or not part[-1].endswith(DEFAULT_ELLIPSIS):
                lines += part
        break
    while lines and not lines[-1]:
        lines.pop()
    return lines
