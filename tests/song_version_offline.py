"""
Offline checks for a song title's version (shared/utilities.py song_version): a last
(…), […] or " - …" naming a version splits off; a leading bracket, a bracket naming
none and a plain title stay whole.
Run from the helper root: python tests/song_version_offline.py
"""

import sys
import tempfile
import unittest
from pathlib import Path

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
sys.path.insert(0, str(HELPER))

from resources.lib.shared.utilities import song_version  # noqa: E402

SPLIT = {
    "Panopticom (Bright-Side Mix)": ("Panopticom", "Bright-Side Mix"),
    "Panopticom (Dark-Side Mix)": ("Panopticom", "Dark-Side Mix"),
    "Hey Jude - Remastered 2015": ("Hey Jude", "Remastered 2015"),
    "Pyramid Song (Live)": ("Pyramid Song", "Live"),
    "Love Will Tear Us Apart (Pennine Version)": (
        "Love Will Tear Us Apart",
        "Pennine Version",
    ),
    "Song (feat. X)": ("Song", "feat. X"),
    "Bohemian Rhapsody - Live Aid": ("Bohemian Rhapsody", "Live Aid"),
    "Track [Instrumental]": ("Track", "Instrumental"),
    "Song (Live) (Remastered)": ("Song (Live)", "Remastered"),  # the last one only
}
WHOLE = (
    "(I Can't Get No) Satisfaction",
    "Losing My Religion",
    "Daft (Craft)",  # "ft" inside a word
    "Song (Ft Lauderdale)",  # ft. needs its dot
    "(Live)",  # nothing left to name it
    "Take Five",
)


class SongVersion(unittest.TestCase):
    def test_split(self):
        for title, parts in SPLIT.items():
            with self.subTest(title):
                self.assertEqual(song_version(title), parts)

    def test_whole(self):
        for title in WHOLE:
            with self.subTest(title):
                self.assertEqual(song_version(title), (title, ""))


if __name__ == "__main__":
    unittest.main()
