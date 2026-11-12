"""
Offline checks for clean names (shared/utilities.py clean_name and file_clean_name):
a film's title and year, and an episode's show, 1x07 code and title in the scene,
Sonarr, underscore and title-less forms; which titles count as the file's own name.
Kodi's clean-up (CUtil::CleanString, Omega Util.cpp, with the default cleanstrings,
and GetMovieName's decoding) is stood in for by a port of it.
Run from the helper root: python tests/clean_name_offline.py
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote_plus

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
    name, year = unquote_plus(os.path.basename(path)), ""  # GetMovieName decodes
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

    def test_titled_by_its_file(self):  # file_clean_name: VideoPlayer.Title's forms
        film = {"title": "Batman Begins", "year": "2005"}
        local = "/media/Batman.Begins.2005.mkv"
        for path, title, expected in (
            (local, "Batman.Begins.2005.mkv", film),  # extensions shown
            (local, "Batman.Begins.2005", film),  # hidden
            (local, local, film),  # a label that is the path (a stack part)
            (local, "Batman Begins", {}),  # a title of its own
            (  # titled decoded (extensions shown), cleaned as Kodi's clean-up does
                "/m/Romeo+Juliet.1996.mkv",
                "Romeo Juliet.1996.mkv",
                {"title": "Romeo Juliet", "year": "1996"},
            ),
            (
                "https://h/v/My%20Movie.2001.mp4?token=abc",
                "My Movie.2001.mp4",
                {"title": "My Movie", "year": "2001"},
            ),
            (
                "https://h/v/My%20Movie.mp4|User-Agent=Mozilla/5.0",
                "My%20Movie",
                {"title": "My Movie"},
            ),
            (
                "davs://h/AC%2FDC%20Live%20(2010).mkv",
                "AC/DC Live (2010).mkv",
                {"title": "AC/DC Live", "year": "2010"},
            ),
            (
                "http://h/Romeo%2BJuliet.mkv",
                "Romeo+Juliet.mkv",
                {"title": "Romeo+Juliet"},
            ),
            (
                "http://h/C%2B%2B%20Talk%20S01E02%20Pilot.mkv",
                "C++ Talk S01E02 Pilot.mkv",
                {"tvshowtitle": "C++ Talk", "episode": "1x02", "title": "Pilot"},
            ),
        ):
            with self.subTest(path=path, title=title):
                self.assertEqual(utilities.file_clean_name(path, title), expected)

    def test_numbers_inside_words_are_no_code(self):
        self.assertNotIn("episode", self.name("Area51x100.Documentary.mkv"))


if __name__ == "__main__":
    unittest.main()
