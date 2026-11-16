"""
Offline checks for lyrics: the LRC parser (shared/lrc.py).
Run from the helper root: python tests/lyrics_offline.py
"""

import sys
import tempfile
import unittest
from pathlib import Path

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
sys.path.insert(0, str(HELPER))

from resources.lib.shared import lrc  # noqa: E402


class ParseTest(unittest.TestCase):
    def test_stamp_forms(self):
        text = (
            "[00:01]one\n[00:02.5]two\n[00:03.25]three\n[01:04.125]four\n[0:05:50]five"
        )
        self.assertEqual(
            lrc.parse(text),
            [
                [1000, "one"],
                [2500, "two"],
                [3250, "three"],
                [5500, "five"],  # a colon before the hundredths
                [64125, "four"],
            ],
        )

    def test_several_stamps_share_a_line_and_sort(self):
        text = "[00:30.00][00:10.00]chorus\n[00:20.00]verse"
        self.assertEqual(
            lrc.parse(text), [[10000, "chorus"], [20000, "verse"], [30000, "chorus"]]
        )

    def test_offset_tags_gaps_and_word_stamps(self):
        text = (
            "[ar:Gorillaz]\n[ti:Feel Good Inc]\n[length: 03:43]\n"
            "[00:01.00]<00:01.00>Feel <00:01.40>good\n\n[00:05.00]\n"
            "[00:06.00]  City's breaking down  \n[offset:+500]\n[re:LRC Maker]"
        )
        self.assertEqual(
            lrc.parse(text),
            [[500, "Feel good"], [4500, ""], [5500, "City's breaking down"]],
        )
        self.assertEqual(lrc.parse("[offset:-250]\n[00:00.10]a")[0], [350, "a"])
        self.assertEqual(lrc.parse("[offset:+500]\n[00:00.10]a")[0], [0, "a"])

    def test_plain_text_has_no_lines(self):
        self.assertEqual(lrc.parse("Feel good\n\nCity's breaking down"), [])
        self.assertEqual(lrc.parse(""), [])


if __name__ == "__main__":
    unittest.main()
