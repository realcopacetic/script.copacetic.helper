"""
Offline checks for clean names (shared/utilities.py clean_name): a film's title and
year, and an episode's show, 1x07 code and title in the scene, Sonarr, underscore and
title-less forms. Kodi's clean-up (CUtil::CleanString, Omega Util.cpp, with the default
cleanstrings) is stood in for by a port of it.
Run from the helper root: python tests/clean_name_offline.py
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
sys.path.insert(0, str(HELPER))

from resources.lib.shared import utilities  # noqa: E402

SEP = r"[ _\,\.\(\)\[\]\-]"
WORDS = (  # Kodi's default video cleanstrings (AdvancedSettings.cpp)
    "10bit|480p|480i|576p|576i|720p|720i|1080p|1080i|2160p|3d|aac|ac3|aka|atmos|avi|"
    "bd5|bdrip|bdremux|bluray|brrip|cam|cd[1-9]|custom|dc|ddp|divx|divx5|dolbydigital|"
    "dolbyvision|dsr|dsrip|dts|dts-hdma|dts-hra|dts-x|dv|dvd|dvd5|dvd9|dvdivx|dvdrip|"
    "dvdscr|dvdscreener|extended|fragment|fs|h264|h265|hdr|hdr10|hevc|hddvd|hdrip|hdtv|"
    "hdtvrip|hrhd|hrhdtv|internal|limited|multisubs|nfofix|ntsc|ogg|ogm|pal|pdtv|"
    "proper|r3|r5|read.nfo|remastered|remux|repack|rerip|retail|screener|se|svcd|tc|"
    "telecine|telesync|truehd|ts|uhd|unrated|ws|x264|x265|xvid|xvidvd|xxx|web-dl|"
    "webrip|www.www|\\[.*\\]"
)
TAGS = [
    re.compile(rf"{SEP}({WORDS})({SEP}|$)", re.I),
    re.compile(r"(\[.*\])", re.I),
]
YEAR = re.compile(
    r"(.*[^ _\,\.\(\)\[\]\-])[ _\.\(\)\[\]\-]+(19[0-9][0-9]|20[0-9][0-9])"
    rf"({SEP}|[^0-9]$)?"
)


def clean_string(path: str, use_folder: bool) -> tuple[str, str]:
    """CUtil::CleanString as getCleanMovieTitle runs it, default cleanstrings."""
    name, year = os.path.basename(path), ""
    if match := YEAR.search(name):
        name, year = match.group(1), match.group(2)
    root, ext = os.path.splitext(name)
    if ext.lower() in (".mkv", ".mp4", ".avi"):
        name = root
    for tag in TAGS:
        if (match := tag.search(name)) and match.start() > 0:
            name = name[: match.start()]
    spaced, initial, out = " " in name, True, []
    for char in name:
        initial = initial and char == "."
        dot = char == "." and not spaced and not initial
        out.append(" " if char == "_" or dot else char)
    return "".join(out).strip(" \t\r\n"), year


class CleanNameTest(unittest.TestCase):
    def setUp(self):
        utilities.xbmc.getCleanMovieTitle = clean_string

    def name(self, file):
        return utilities.clean_name(f"/media/{file}")

    def test_film(self):
        self.assertEqual(
            self.name("Batman.Begins.2005.1080p.BluRay.x264.mkv"),
            {"title": "Batman Begins", "year": "2005"},
        )

    def test_episodes(self):
        episode = {"tvshowtitle": "Show Name", "episode": "1x02"}
        titled = episode | {"title": "Episode Title"}
        for file, expected in (
            ("Show.Name.S01E02.Episode.Title.1080p.WEB-DL.x264-GRP.mkv", titled),
            ("Show Name - S01E02 - Episode Title.mkv", titled),
            ("Show_Name_S01E02_Episode_Title.avi", titled),
            ("Show.Name.1x02.Episode.Title.mkv", titled),
            ("Show.Name.S01E02E03.Episode.Title.mkv", titled),
            ("Show.Name.S01E02.1080p.WEB.mkv", episode),
            ("S01E02.Episode.Title.mkv", {"episode": "1x02", "title": "Episode Title"}),
        ):
            with self.subTest(file):
                self.assertEqual(self.name(file), expected)

    def test_numbers_inside_words_are_no_code(self):
        self.assertNotIn("episode", self.name("Area51x100.Documentary.mkv"))


if __name__ == "__main__":
    unittest.main()
