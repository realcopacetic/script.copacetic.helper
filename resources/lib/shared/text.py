# author: realcopacetic

DEFAULT_ABBREV = {
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "sr",
    "jr",
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
    "dept",
    "u",
    "us",
    "uk",
    "eu",
    "u.s",
    "u.k",
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
