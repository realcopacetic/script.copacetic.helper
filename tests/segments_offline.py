"""
Offline checks for skip segments (resources/lib/service/segments.py): chapter starts
from Player.Chapters, TheIntroDB's times snapped to chapter marks (another cut only
on marks), the tick pattern, named chapters taking over on entry, and what is
published as the playhead moves. Infolabels are a dict; nothing reaches the network.
Run from the helper root: python tests/segments_offline.py
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
sys.modules["xbmc"].Monitor = None  # imported by apis/cache; never called here
sys.path.insert(0, str(HELPER))

from resources.lib.service import segments  # noqa: E402

LENGTH = 3480.0  # a 58 minute episode


def chapters(*starts: float, first_at_zero: bool = True) -> dict[str, str]:
    """Player.Chapters and ChapterCount as Kodi builds them from chapter starts."""
    marks = [s * 100 / LENGTH for s in starts]
    pairs, last = [], 0.0
    for mark in marks:
        pairs += [f"{last:.5f}", f"{mark:.5f}"]
        last = mark
    count = len(starts) + first_at_zero if starts else 0
    return {"Player.Chapters": ",".join(pairs), "Player.ChapterCount": f"{count:02}"}


class SegmentsTest(unittest.TestCase):
    def setUp(self):
        self.labels, self.props = {"Player.Chapter": "01"}, {}
        for target, name, value in (
            (segments, "infolabel", lambda key: self.labels.get(key, "")),
            (segments, "window_property", self.prop),
        ):
            patcher = patch.object(segments, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def prop(self, key, value=""):
        if value:
            self.props[key] = value
        else:
            self.props.pop(key, None)

    def play(self, found=None, *starts, now=0.0, **labels):
        self.props.clear()  # the service clears them before each video
        self.labels |= chapters(*starts) | labels
        self.segments = segments.Segments(found or {}, LENGTH)
        self.segments.tick(now)
        return self.props

    def test_duplicate_and_zero_marks_keep_their_numbers(self):
        self.labels |= chapters(300, 300, 600) | {"Player.ChapterCount": "05"}
        self.assertEqual(segments.chapter_starts(LENGTH), [0.0, 0.0, 300, 300, 600])

    def test_chapter_starts(self):
        self.labels |= chapters(40, 70.5, 3300)
        starts = segments.chapter_starts(LENGTH)
        self.assertEqual(len(starts), 4)
        self.assertEqual(starts[0], 0.0)
        self.assertAlmostEqual(starts[2], 70.5, places=1)
        self.labels |= chapters(40, 3300, first_at_zero=False)
        self.assertEqual(len(segments.chapter_starts(LENGTH)), 2)
        self.labels |= {"Player.Chapters": "", "Player.ChapterCount": "00"}
        self.assertEqual(segments.chapter_starts(LENGTH), [])

    def test_theintrodb_snaps_to_marks(self):
        found = {
            "intro": [[61000, 92000]],
            "credits": [[3301500, None]],
            "duration": 3480000,
        }
        props = self.play(found, 60, 90, 3300)
        self.assertEqual(
            props,
            {
                "player_skip_kind": "intro",
                "player_skip_start": "61",  # Kodi rounds Player.Time(secs)
                "player_skip_end": "90",
                "player_skip_seek": props["player_skip_seek"],
                "player_credits": "3301",
            },
        )
        self.assertAlmostEqual(float(props["player_skip_seek"]), 90, places=1)

    def test_theintrodb_off_marks(self):
        props = self.play({"recap": [[0, 45000]], "intro": [[300000, 330000]]})
        self.assertEqual(props["player_skip_kind"], "recap")
        self.segments.tick(46)
        self.assertEqual(self.props["player_skip_kind"], "intro")
        self.assertEqual(self.props["player_skip_seek"], "330.000")
        self.segments.tick(331)
        self.assertNotIn("player_skip_kind", self.props)

    def test_credits_before_a_preview_run_to_the_end(self):
        found = {"credits": [[3300000, 3420000]], "preview": [[3420000, None]]}
        self.assertEqual(self.play(found), {"player_credits": "3301"})

    def test_another_cut_needs_marks(self):
        other = {"intro": [[61000, 92000]], "duration": 3000000}
        self.assertEqual(self.play(other), {})
        self.assertEqual(self.play(other, 60, 90)["player_skip_end"], "90")

    def test_pattern(self):
        props = self.play({}, 300, 360, 3300)
        self.assertEqual(props["player_skip_kind"], "intro")
        self.assertEqual(props["player_credits"], "3301")
        for starts in ((300, 360, 1500, 3300), (300, 900, 3300), (300, 3300, 3400)):
            self.assertEqual(self.play({}, *starts), {})  # even, wide or doubled
        self.assertEqual(self.play({}, 3300), {"player_credits": "3301"})

    def test_named_chapter_takes_over(self):
        found = {"intro": [[100000, 130000]]}
        self.play(found, 95, 125, 1700, 3300)
        self.assertEqual(self.props["player_skip_start"], "101")
        self.labels |= {"Player.Chapter": "02", "Player.ChapterName": "Opening"}
        self.segments.tick(96)
        self.assertEqual(self.props["player_skip_start"], "96")
        self.labels |= {"Player.Chapter": "05", "Player.ChapterName": "Ending"}
        self.segments.tick(3301)
        self.assertEqual(self.props, {"player_credits": "3301"})
        self.labels |= {"Player.Chapter": "03", "Player.ChapterName": "Prologue"}
        self.segments.tick(200)  # a cold open names nothing
        self.assertEqual(self.props, {"player_credits": "3301"})

    def test_named_credits_keep_an_earlier_credits_start(self):
        self.play({"credits": [[1300000, None]]}, 1380)
        self.labels |= {"Player.Chapter": "02", "Player.ChapterName": "Preview"}
        self.segments.tick(1380)  # Play next's card, opened at 1301, stays open
        self.assertEqual(self.props["player_credits"], "1301")

    def test_named_chapter_keeps_an_earlier_start(self):
        self.play({"intro": [[100000, 130000]]}, 120, 150, 3300)
        self.labels |= {"Player.Chapter": "02", "Player.ChapterName": "Intro"}
        self.segments.tick(121)  # a button dismissed at 100 stays dismissed
        self.assertEqual(self.props["player_skip_start"], "101")
        self.assertEqual(self.props["player_skip_end"], "150")

    def test_a_films_credits_around_its_scenes(self):  # mid- and post-credits
        found = {
            "credits": [[6000000, 6300000], [6420000, 6900000], [6960000, None]],
            "duration": 7200000,
        }
        self.segments = segments.Segments(found, 7200)
        self.segments.tick(0)
        self.assertEqual(self.props["player_skip_seek"], "6300.000")
        self.assertEqual(self.props["player_credits"], "6961")  # nothing for a film
        self.segments.tick(6301)
        self.assertEqual(self.props["player_skip_start"], "6421")
        self.assertEqual(self.props["player_skip_end"], "6900")

    def test_short_and_chapterless(self):
        self.assertEqual(self.play({}), {})
        self.assertEqual(self.segments.starts, [])


if __name__ == "__main__":
    unittest.main()
