# author: realcopacetic

import re
from operator import itemgetter

LINES = "lyrics_lines"  # Home property: the service's synced lines as JSON, for plugins
# A line's neighbours by offset, for the skin's distance fade: the service publishes
# the playing line's as lyrics_<key>, the info=lyrics items carry their own
NEIGHBOURS = {"m2": -2, "m1": -1} | {f"p{n}": n for n in range(1, 6)}

# A line's leading time stamps: [mm:ss], [mm:ss.xx] or [mm:ss.xxx], some writers' colon
STAMPS = re.compile(r"(?:\[\d+:\d{1,2}(?:[.:]\d{1,3})?\])+")
STAMP = re.compile(r"\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]")
OFFSET = re.compile(r"\[offset:\s*([+-]?\d+)\s*\]", re.IGNORECASE)
WORD = re.compile(r"<\d+:\d{1,2}(?:[.:]\d{1,3})?>")  # enhanced LRC's word stamps
# LRC's tags ([ar:...], [offset:...]: lowercase keys) and stamps, timed or not; a
# lyric's own [Chorus] or [Verse 1: Name] has neither form
TAG = re.compile(r"\[(?:[a-z#]+:[^\]]*|\d+[:.,][\d:.,]*)\]")


def parse(text: str) -> list[list[int | str]]:
    """
    LRC text as timed lines, by time: a line under several stamps once for each,
    [offset:] applied (positive is sooner), metadata tags dropped, empty lines kept.

    :param text: LRC text, or lyrics without stamps.
    :return: [[ms, text], ...]; empty when the text has no stamps.
    """
    offset, lines = 0, []
    for line in text.splitlines():
        line = line.strip()
        if found := OFFSET.fullmatch(line):
            offset = int(found[1])
        elif stamps := STAMPS.match(line):
            words = WORD.sub("", line[stamps.end() :]).strip()
            for minutes, seconds, fraction in STAMP.findall(stamps[0]):
                ms = (int(minutes) * 60 + int(seconds)) * 1000
                lines.append([ms + int(fraction.ljust(3, "0")), words])
    return sorted(
        ([max(ms - offset, 0), words] for ms, words in lines), key=itemgetter(0)
    )


def plain(text: str) -> str:
    """
    Lyrics parse() can't time, as plain text: LRC tags and stamps taken out, a line
    of nothing else dropped, blank lines between verses kept.

    :param text: Lyrics, from a .lrc or tags.
    :return: The text; "" when nothing else is left.
    """
    return "\n".join(
        bare
        for line in text.splitlines()
        if (bare := TAG.sub("", line).strip()) or not TAG.search(line)
    ).strip()
