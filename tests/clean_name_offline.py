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
    # GetMovieName: URIUtils::GetFileName (at / or \), then CURL::Decode
    name, year = unquote_plus(re.split(r"[/\\]", path)[-1]), ""
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
            (local, local, film),  # a label that is the path (PlayList.add(url))
            (local, "Batman Begins", {}),  # a title of its own
            ("https://h/?id=1", "", {}),  # no title, no name
            (
                "/m/Show%20S01E02.mkv",
                "Show%20S01E02.mkv",
                {"tvshowtitle": "Show", "episode": "1x02"},
            ),
            (
                "HTTP://h/Film%20Two.2003.mkv",
                "Film Two.2003.mkv",
                {"title": "Film Two", "year": "2003"},
            ),
            (  # no code made of an escape's digits
                "http://h/Top%25x05%20Film.mkv",
                "Top%x05 Film.mkv",
                {"title": "Top%x05 Film"},
            ),
            (
                "http://h/Show%2BS01E02%20Pilot.mkv",
                "Show+S01E02 Pilot.mkv",
                {"tvshowtitle": "Show+", "episode": "1x02", "title": "Pilot"},
            ),
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
                "http://h/100%2525%20Wolf%20(2020).mkv",
                "100%25 Wolf (2020).mkv",
                {"title": "100%25 Wolf", "year": "2020"},
            ),
            (
                "http://h/AC%5CDC.Live.2010.mkv",
                "AC\\DC.Live.2010.mkv",
                {"title": "AC\\DC Live", "year": "2010"},
            ),
            (  # an episode code straight after an escape
                "http://h/Show%2BS01E02.Pilot.mkv",
                "Show+S01E02.Pilot.mkv",
                {"tvshowtitle": "Show+", "episode": "1x02", "title": "Pilot"},
            ),
            (  # Kodi's own FTP option
                "ftp://h/Movie.2001.mkv|utf8=0",
                "Movie.2001.mkv",
                {"title": "Movie", "year": "2001"},
            ),
            (
                "http://h/C%2B%2B%20Talk%20S01E02%20Pilot.mkv",
                "C++ Talk S01E02 Pilot.mkv",
                {"tvshowtitle": "C++ Talk", "episode": "1x02", "title": "Pilot"},
            ),
        ):
            with self.subTest(path=path, title=title):
                self.assertEqual(utilities.file_clean_name(path, title), expected)

    def test_stack_named_by_kodi(self):  # GetMovieName names a stack from its parts
        films = "stack:///m/Film.2001.cd1.mkv , /m/Film.2001.cd2.mkv"
        shows = (
            "stack:///m/Show S01E02 Pilot part1.mkv , /m/Show S01E02 Pilot part2.mkv"
        )
        dated = "stack:///m/Doctor.Who.2005.S01E02.Rose.part1.mkv , /m/Doctor.Who.2005.S01E02.Rose.part2.mkv"  # noqa: E501
        named = {
            films: ("Film", "2001"),
            shows: ("Show S01E02 Pilot", ""),
            dated: ("Doctor Who", "2005"),  # CleanString cuts at the year
        }

        def clean(path, folder):  # Kodi's GetStackedTitlePath, stood in for
            return named[path] if path in named else clean_string(path, folder)

        utilities.xbmc.getCleanMovieTitle = clean
        film = {"title": "Film", "year": "2001"}
        show = {"tvshowtitle": "Show", "episode": "1x02", "title": "Pilot"}
        self.assertEqual(utilities.file_clean_name(films), film)
        self.assertEqual(utilities.file_clean_name(shows), show)  # not "part2"
        # Played, it is titled by its label, the stack's name: clean alike, or not
        self.assertEqual(utilities.file_clean_name(films, "Film.2001.mkv"), film)
        self.assertEqual(
            utilities.file_clean_name(shows, "Show S01E02 Pilot.mkv"), show
        )
        who = {"tvshowtitle": "Doctor Who", "episode": "1x02"}
        self.assertEqual(utilities.file_clean_name(dated), who)
        label = "Doctor.Who.2005.S01E02.Rose.mkv"
        self.assertEqual(utilities.file_clean_name(dated, label), who)
        self.assertEqual(utilities.file_clean_name(films, "Its Own Title"), {})
        self.assertEqual(utilities.file_clean_name(films, ""), {})

    def test_plugin_options_cut(self):
        self.assertEqual(
            utilities.file_clean_name("plugin://plugin.video.x/Film.2001.mkv?id=5"),
            {"title": "Film", "year": "2001"},
        )

    def test_without_a_title_any_file(self):  # the clean_name plugin path
        self.assertEqual(
            utilities.file_clean_name("http://h/Show%20Name%20S01E02.mkv"),
            {"tvshowtitle": "Show Name", "episode": "1x02"},
        )
        self.assertEqual(  # undecoded, as Kodi passes it: its own '?' is no option
            utilities.file_clean_name("https://h/Who%20Am%20I%3F%202014.mkv"),
            {"title": "Who Am I?", "year": "2014"},
        )

    def test_numbers_inside_words_are_no_code(self):
        self.assertNotIn("episode", self.name("Area51x100.Documentary.mkv"))


if __name__ == "__main__":
    unittest.main()
