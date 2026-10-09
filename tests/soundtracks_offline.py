"""
Offline checks for the soundtracks listing's title matching
(resources/lib/plugin/soundtracks.py): how album titles read as a film or show plus
soundtrack wording, the seasons they name, and which library item owns each one.
Album titles are from a MusicBrainz-tagged library (Oct 2026); the Watchmen
volumes are MusicBrainz's release titles. Run from the helper root:
python tests/soundtracks_offline.py
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resources.lib.plugin.soundtracks import (  # noqa: E402
    claim,
    lead,
    owner,
    release_year,
    seasons,
    title_key,
)


def row(title, year, originaltitle=""):
    """A library film or show row with the fields matching reads."""
    return {"title": title, "originaltitle": originaltitle, "year": year}


class Claims(unittest.TestCase):
    def assertNames(self, album, title):
        self.assertIn(title_key(title), claim(album).keys, album)

    def assertNotNames(self, album, title):
        self.assertNotIn(title_key(title), claim(album).keys, album)

    def test_whole_title(self):
        for album in (
            "Batman Returns",
            "Black Swan",
            "Berberian Sound Studio",
            "Birdman or (The Unexpected Virtue of Ignorance)",
        ):
            self.assertNames(album, album)

    def test_title_and_wording(self):
        for album, title in (
            ("Batman Begins: Original Motion Picture Soundtrack", "Batman Begins"),
            ("28 Days Later: The Soundtrack Album", "28 Days Later"),
            (
                "The Assassination of Jesse James by the Coward Robert Ford: "
                "Music from the Motion Picture",
                "The Assassination of Jesse James by the Coward Robert Ford",
            ),
            (
                "The Bourne Ultimatum: Expanded Motion Picture Soundtrack",
                "The Bourne Ultimatum",
            ),
            (
                "Halt and Catch Fire (Original Television Series Soundtrack)",
                "Halt and Catch Fire",
            ),
            (
                "Halt and Catch Fire, Vol. 2 (Original Television Series Soundtrack)",
                "Halt and Catch Fire",
            ),
            ("The Leftovers: Music from the HBO Series, Season One", "The Leftovers"),
            ("Watchmen: Volume 1: Music From the HBO Series", "Watchmen"),
            (
                "Crazy, Stupid, Love: Original Motion Picture Soundtrack",
                "Crazy, Stupid, Love",
            ),
        ):
            self.assertNames(album, title)

    def test_articles_and_subtitles_matter(self):
        self.assertNames("The Batman: Original Motion Picture Soundtrack", "The Batman")
        self.assertNotNames("The Batman: Original Motion Picture Soundtrack", "Batman")
        # a subtitle that isn't soundtrack wording keeps the whole name
        self.assertNotNames(
            "Batman: Arkham Asylum: Original Video Game Score", "Batman"
        )
        self.assertNames(
            "Batman: Arkham Asylum: Original Video Game Score", "Batman: Arkham Asylum"
        )

    def test_keys(self):
        self.assertEqual(title_key("Fast & Furious"), title_key("Fast and Furious"))
        self.assertEqual(title_key("Amélie"), title_key("Amelie"))
        self.assertNotEqual(title_key("The Batman"), title_key("Batman"))

    def test_seasons(self):
        for album, named in (
            (
                "Battlestar Galactica: Season 3: Original Soundtrack from the Sci-Fi Channel",
                {3},
            ),
            ("The Leftovers: Music from the HBO Series, Season One", {1}),
            (
                "Person of Interest: Seasons 3 & 4: Original Television Soundtrack",
                {3, 4},
            ),
            ("Show: Seasons 1–3", {1, 2, 3}),
            ("Show: Seasons 1 to 2 and 4", {1, 2, 4}),
            ("Show: Series 2 (Original Soundtrack)", {2}),
            ("Show: Season Seventeen", {17}),
            (
                "Halt and Catch Fire, Vol. 2 (Original Television Series Soundtrack)",
                set(),
            ),
            ("Broadchurch", set()),
            ("Season of the Witch", set()),
        ):
            self.assertEqual(seasons(album), named, album)

    def test_medium(self):
        self.assertEqual(
            claim("Watchmen: Volume 1: Music From the HBO Series").medium, "tvshow"
        )
        self.assertEqual(
            claim("Batman Begins: Original Motion Picture Soundtrack").medium, "movie"
        )
        self.assertEqual(claim("Black Swan").medium, "")

    def test_fits_season(self):
        keys = {title_key("Person of Interest")}
        both = claim(
            "Person of Interest: Seasons 3 & 4: Original Television Soundtrack"
        )
        self.assertTrue(both.fits(keys, 0))  # the show
        self.assertTrue(both.fits(keys, 4))
        self.assertFalse(both.fits(keys, 2))
        volume = claim(
            "Halt and Catch Fire, Vol. 2 (Original Television Series Soundtrack)"
        )
        self.assertTrue(volume.fits({title_key("Halt and Catch Fire")}, 1))


class Owners(unittest.TestCase):
    def test_single_candidate_ignores_dates(self):
        reissue = {"originaldate": "", "year": 2022}  # no original date in the tags
        found = owner(
            claim("28 Days Later: The Soundtrack Album"),
            release_year(reissue),
            [("movie", row("28 Days Later", 2002))],
        )
        self.assertEqual(found[1]["title"], "28 Days Later")

    def test_original_date_wins(self):
        self.assertEqual(
            release_year({"originaldate": "2002-11-04", "year": 2022}), 2002
        )
        self.assertEqual(release_year({"originaldate": "", "year": 2011}), 2011)
        self.assertEqual(release_year({"originaldate": "", "year": 0}), 0)

    def test_remakes_take_the_nearest_year(self):
        kings = [
            ("movie", row("The Lion King", 1994)),
            ("movie", row("The Lion King", 2019)),
        ]
        album = claim("The Lion King (Original Motion Picture Soundtrack)")
        self.assertEqual(owner(album, 1994, kings)[1]["year"], 1994)
        self.assertEqual(owner(album, 2019, kings)[1]["year"], 2019)

    def test_wording_picks_film_or_show(self):
        both = [("movie", row("Watchmen", 2009)), ("tvshow", row("Watchmen", 2019))]
        self.assertEqual(
            owner(claim("Watchmen: Volume 1: Music From the HBO Series"), 2019, both)[
                0
            ],
            "tvshow",
        )
        self.assertEqual(
            owner(claim("Watchmen (Original Motion Picture Score)"), 2009, both)[0],
            "movie",
        )
        # wording for a kind the library lacks still matches the other
        film = [("movie", row("Watchmen", 2009))]
        self.assertEqual(
            owner(claim("Watchmen: Volume 1: Music From the HBO Series"), 2019, film)[
                0
            ],
            "movie",
        )

    def test_original_title(self):
        film = [("movie", row("Spirited Away", 2001, "Sen to Chihiro no Kamikakushi"))]
        self.assertIsNotNone(
            owner(claim("Sen to Chihiro no Kamikakushi: Soundtrack"), 2001, film)
        )

    def test_no_match(self):
        self.assertIsNone(
            owner(
                claim("Batman: Arkham Asylum: Original Video Game Score"),
                2013,
                [("movie", row("Batman", 1989))],
            )
        )

    def test_lead_finds_a_title_with_a_colon_or_dash(self):
        album = "Mission: Impossible – Fallout (Music from the Motion Picture)"
        self.assertEqual(lead(album), "Mission")
        self.assertEqual(lead("(500) Days of Summer (Soundtrack)"), "(500")
        film = [("movie", row("Mission: Impossible - Fallout", 2018))]
        self.assertIsNotNone(owner(claim(album), 2018, film))


if __name__ == "__main__":
    unittest.main(verbosity=2)
