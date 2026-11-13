# author: realcopacetic

from math import ceil

from resources.lib.apis import theintrodb
from resources.lib.shared.utilities import (
    condition,
    infolabel,
    json_call,
    to_float,
    to_int,
    window_property,
)

ENABLED = "Skin.HasSetting(skip_segments)"
SNAP = 3  # seconds a TheIntroDB time may sit from a chapter mark and take it
SAME_CUT = 0.02  # a release within 2 % of the file's length is the same cut
TAIL = 0.05  # a film's file up to 5 % longer is too: a tail after the credits
EARLY, LATE, SHORTEST = 600, 0.9, 900  # the tick pattern's windows; shorter: no pattern
INTRO_GAP = 20, 120  # seconds between the pattern's two early marks
NAMES = {  # chapter names (case folded) that name a segment; "prologue" is a cold open
    **dict.fromkeys(("intro", "opening", "opening credits", "op"), "intro"),
    **dict.fromkeys(("recap", "previously", "previously on"), "recap"),
    **dict.fromkeys(("credits", "end credits", "ending", "ed", "outro"), "credits"),
    **dict.fromkeys(("preview", "next episode", "next time"), "preview"),
}
PROPS = (
    "player_skip_kind",
    "player_skip_start",
    "player_skip_end",
    "player_skip_seek",
    "player_credits",
)


def clear() -> None:
    """Clear the published segment properties and a skin's player_skip_dismissed."""
    for key in (*PROPS, "player_skip_dismissed"):
        window_property(key)


def chapter_starts(duration: float) -> list[float]:
    """
    Each chapter's start in seconds, by chapter number: Player.Chapters holds percent
    pairs ending at each start after 0, so chapters at 0 are added back.

    :param duration: The file's length in seconds.
    :return: Starts, starts[n - 1] being chapter n's; empty without chapters.
    """
    count = to_int(infolabel("Player.ChapterCount"))
    pairs = infolabel("Player.Chapters").split(",")
    marks = sorted(round(to_float(p) * duration / 100, 3) for p in pairs[1::2] if p)
    return [0.0] * (count - len(marks)) + marks


LIBRARY = {  # how a video's TheIntroDB ids are read: an episode's are its show's
    "movie": ("VideoLibrary.GetMovieDetails", "movieid", "moviedetails"),
    "tvshow": ("VideoLibrary.GetTVShowDetails", "tvshowid", "tvshowdetails"),
}


def lookup(
    total: float,
    media: str,
    dbid: int,
    season: int | None = None,
    episode: int | None = None,
) -> "Segments | None":
    """
    A new video's segments, with the skin's skip setting on: TheIntroDB's answer for
    a library film or episode while it is on, the rest built on the first tick.

    :param total: The file's length in seconds.
    :param media: movie, or tvshow for an episode.
    :param dbid: Library id of the film or the episode's show; 0 for any other video.
    :param season: An episode's season number.
    :param episode: An episode's number.
    :return: Segments; None with the setting off.
    """
    if not condition(ENABLED):
        return None
    found = {}
    if dbid and theintrodb.enabled():
        method, key, result = LIBRARY[media]
        ids = json_call(
            method,
            params={"properties": ["uniqueid"], key: dbid},
            parent="skip_segments",
        )["result"][result]["uniqueid"]
        found = theintrodb.segments(ids, round(total * 1000), season, episode)
    return Segments(found, total, TAIL if media == "movie" else 0.0)


class Segments:
    """
    A playing video's skip segments: TheIntroDB's, else the tick pattern, and named
    chapters as the playhead enters them. Publishes the one in play or next.
    """

    def __init__(self, found: dict, duration: float, tail: float = 0.0) -> None:
        """
        Hold TheIntroDB's answer until the first tick, when the chapters are in.

        :param found: theintrodb.segments' payload.
        :param duration: The file's length in seconds.
        :param tail: The fraction longer a film's file may be and stay the same cut.
        """
        self.found, self.duration, self.tail = found, duration, tail
        self.starts = []  # chapter starts by number, read once Kodi has them
        self.spans = []  # (start, end, kind)
        self.credits = None  # where credits run to the end: Play next opens there
        self.chapter = -1
        self.published = {}

    def tick(self, now: float) -> None:
        """
        Poller step: build the spans once, take a named chapter on entering it,
        publish the segment the playhead is in or comes to next.

        :param now: The playhead in seconds.
        """
        if self.found is not None:  # a second in: Kodi has the chapters by now
            self.starts = chapter_starts(self.duration)
            self._build(self.found)
            self.found = None
        if not (self.starts or self.spans or self.credits):
            return
        if (chapter := to_int(infolabel("Player.Chapter"))) != self.chapter:
            self.chapter = chapter
            self._named(chapter)
        self._publish(now)

    def _snap(self, time: float | None) -> float | None:
        """
        The chapter mark (or 0) within SNAP seconds of time.

        :param time: Seconds; None for the end of the file.
        :return: The mark; None when none is near.
        """
        if time is None:
            return None
        near = [m for m in (0.0, *self.starts) if abs(m - time) <= SNAP]
        return min(near, key=lambda m: abs(m - time), default=None)

    def _add(self, start: float, end: float | None, kind: str) -> None:
        """
        Take a segment: one running to the end opens Play next (credits, preview);
        else a span for the skip button.

        :param start: Seconds.
        :param end: Seconds; None, or at the end, for one running to the end.
        :param kind: intro, recap, credits or preview.
        """
        if end is None or end >= self.duration - SNAP:
            if kind in theintrodb.OPEN_ENDED:  # credits ending where it starts join it
                joined = {
                    s for s in self.spans if s[2] == "credits" and s[1] + SNAP > start
                }
                self.spans = [s for s in self.spans if s not in joined]
                self.credits = min(
                    start, *(s[0] for s in joined), self.credits or start
                )
            return
        self.spans = sorted([*self.spans, (start, end, kind)])

    def _build(self, found: dict) -> None:
        """
        Spans from TheIntroDB's answer, snapped to the chapter marks; an answer from
        another cut needs its times on marks. Without one, the tick pattern.

        :param found: theintrodb.segments' payload.
        """
        group = found.get("duration")
        extra = (self.duration - group / 1000) / self.duration if group else 0.0
        same = -SAME_CUT <= extra <= max(SAME_CUT, self.tail)
        for kind in theintrodb.KINDS:
            for span in found.get(kind, ()):
                start, end = span[0] / 1000, span[1] and span[1] / 1000
                on_start, on_end = self._snap(start), self._snap(end)
                if same or on_start is not None and (end is None or on_end is not None):
                    start = start if on_start is None else on_start
                    self._add(start, end if on_end is None else on_end, kind)
        if not (self.spans or self.credits):
            self._pattern()

    def _pattern(self) -> None:
        """
        Unnamed marks shaped like a streaming release's: two in the first 10 minutes
        a short gap apart (the intro), one in the last 10 % (credits), none between.
        """
        if self.duration < SHORTEST:
            return
        marks = [m for m in self.starts if m]
        early = [m for m in marks if m <= EARLY]
        late = [m for m in marks if m >= LATE * self.duration]
        if len(early) + len(late) < len(marks) or len(early) not in (0, 2):
            return
        if (
            len(late) > 1
            or early
            and not INTRO_GAP[0] <= early[1] - early[0] <= INTRO_GAP[1]
        ):
            return
        if early:
            self._add(*early, "intro")
        if late:
            self._add(late[0], None, "credits")

    def _named(self, chapter: int) -> None:
        """
        A chapter named as a segment, entered: it replaces what it overlaps.

        :param chapter: The chapter now playing; 0 before the first.
        """
        name = infolabel("Player.ChapterName").strip().casefold()
        if not (0 < chapter <= len(self.starts) and (kind := NAMES.get(name))):
            return
        start = self.starts[chapter - 1]
        end = self.starts[chapter] if chapter < len(self.starts) else None
        if end is None and kind not in theintrodb.OPEN_ENDED:
            return
        over = [s for s in self.spans if s[1] > start and not (end and s[0] >= end)]
        self.spans = [s for s in self.spans if s not in over]
        # Keep an earlier start of the same kind: a dismissal names that start
        self._add(min([start, *(s[0] for s in over if s[2] == kind)]), end, kind)

    def _publish(self, now: float) -> None:
        """
        Publish the span the playhead is in or comes to next, and where credits
        open Play next: whole seconds for the skin's Player.Time(secs) tests, which
        Kodi rounds, so a start reads only once it is reached.

        :param now: The playhead in seconds.
        """
        props = {
            "player_credits": f"{ceil(self.credits + 0.5)}" if self.credits else ""
        }
        if span := next((s for s in self.spans if s[1] > now), None):
            start, end, kind = span
            props |= {
                "player_skip_kind": kind,
                "player_skip_start": f"{ceil(start + 0.5)}",
                "player_skip_end": f"{round(end)}",
                "player_skip_seek": f"{end:.3f}",
            }
        for key in PROPS:
            if (value := props.get(key, "")) != self.published.get(key, ""):
                window_property(key, value=value)
        self.published = props
