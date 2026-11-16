# author: realcopacetic

import re
from operator import itemgetter

LINES = "lyrics_lines"  # Home property: the service's synced lines as JSON, for plugins

# A line's leading time stamps: [mm:ss], [mm:ss.xx] or [mm:ss.xxx], some writers' colon
STAMPS = re.compile(r"(?:\[\d+:\d{1,2}(?:[.:]\d{1,3})?\])+")
STAMP = re.compile(r"\[(\d+):(\d{1,2})(?:[.:](\d{1,3}))?\]")
OFFSET = re.compile(r"\[offset:\s*([+-]?\d+)\s*\]", re.IGNORECASE)
WORD = re.compile(r"<\d+:\d{1,2}(?:[.:]\d{1,3})?>")  # enhanced LRC's word stamps


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
