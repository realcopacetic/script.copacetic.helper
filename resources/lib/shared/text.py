# author: realcopacetic

import re

# Kodi wraps at U+0020 only; tabs and newlines fold into a break as before
_WORDS = re.compile(r"[^ \t\n\r\f\v]+")

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
) -> list[str]:
    """Wrap to lines; on overflow cap at the last sentence, else ellipsise.

    :param font: FreeType font object exposing ``getlength``.
    :param text: String to wrap and clamp.
    :param max_width: Line width ceiling in pixels.
    :param max_lines: Maximum lines to keep.
    :param tracking: Extra pixels inserted between adjacent glyphs.
    :param ellipsis: Suffix appended when a hard cut is required.
    :param abbrev: Lowercased abbreviations that don't end a sentence.
    :return: At most ``max_lines`` wrapped lines.
    """
    lines = wrap_text(font, text, max_width, tracking)
    if len(lines) <= max_lines:
        return lines

    visible = " ".join(lines[:max_lines])
    if capped := sentence_cap(visible, abbrev):
        return wrap_text(font, capped, max_width, tracking)[:max_lines]

    lines = lines[:max_lines]
    last = lines[-1]
    while " " in last and text_width(font, f"{last}{ellipsis}", tracking) > max_width:
        last = last.rsplit(" ", 1)[0]
    last = last.rstrip(".,;:!?…-–—").rstrip("\"')]}»”’")
    lines[-1] = f"{last}{ellipsis}"
    return lines
