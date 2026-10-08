# author: realcopacetic

import re
import unicodedata
from typing import NamedTuple

_WORDS = (
    "one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty"
).split()
_NUMBERS = {word: n for n, word in enumerate(_WORDS, 1)}
_NUMBER = rf"\b(?:\d+|{'|'.join(sorted(_WORDS, key=len, reverse=True))})\b"
_SEASONS = re.compile(
    rf"\b(?:seasons?|series)\s+({_NUMBER}(?:\s*(?:&|and|,|-|–|to)\s*{_NUMBER})*)",
    re.I,
)
_SEASON_TOKEN = re.compile(rf"{_NUMBER}|[-–]|\bto\b", re.I)
_SPLIT = re.compile(r"\s*(?::|\s[-–—]\s|,|[()\[\]])\s*")
# Wording a soundtrack's title adds after the film or show's: "Original Motion
# Picture Soundtrack", "Music from the HBO Series", "Season 3", "Vol. 2" …
_QUALIFIER = re.compile(
    r"\b(?:soundtracks?|ost|score|music|songs|original|motion picture|album|"
    r"series|seasons?|vol|volume|edition|expanded|deluxe|complete|remastered|"
    r"anniversary|television|tv)\b",
    re.I,
)
_TV = re.compile(r"\b(?:television|tv|series|seasons?|hbo|netflix|channel)\b", re.I)
_FILM = re.compile(r"\b(?:motion picture|film|movie)\b", re.I)
SOUNDTRACK = "soundtrack"


class Claim(NamedTuple):
    """The films or shows a soundtrack album's title can name."""

    titles: tuple[str, ...]  # the whole title, then each shorter run it starts with
    keys: frozenset[str]  # title_key of each
    seasons: frozenset[int]  # seasons it names; empty for none
    medium: str  # "movie" or "tvshow" when its wording says, else ""

    def fits(self, keys: set[str], season: int) -> bool:
        """
        Whether it can be the soundtrack of a film or show titled keys: for a
        season (0 for none), naming that season or no season.

        :param keys: The film or show's title keys.
        :param season: Season number, 0 for the film or show itself.
        :return: True when it fits.
        """
        named = self.seasons
        return bool(self.keys & keys) and (not season or not named or season in named)


def title_key(title: str) -> str:
    """
    A film, show or album title reduced for matching: no case, accents or
    punctuation, "&" read as "and"; articles stay, so The Batman isn't Batman.

    :param title: Title.
    :return: Matching key.
    """
    title = unicodedata.normalize("NFKD", title.casefold().replace("&", "and"))
    return "".join(c for c in title if c.isalnum())


def seasons(title: str) -> frozenset[int]:
    """
    The seasons a title names: "Season 3", "Season One", "Seasons 3 & 4",
    "Seasons 1–3", "Series 2"; "Vol. 2" names none.

    :param title: Album title.
    :return: Season numbers.
    """
    found = set()
    for match in _SEASONS.finditer(title):
        start = last = None
        for token in _SEASON_TOKEN.findall(match[1]):
            if not token[0].isalnum() or token.lower() == "to":
                start = last
                continue
            last = int(token) if token.isdigit() else _NUMBERS[token.lower()]
            found.update(range(start, last + 1) if start else (last,))
            start = None
    return frozenset(found)


def claim(title: str) -> Claim:
    """
    Read an album title as a film or show's title plus soundtrack wording: the
    whole title, or a leading run of its ": ", " - ", ", " or bracket segments
    when every segment after it is wording ("Batman: Arkham Asylum" isn't Batman).

    :param title: Album title.
    :return: Its claim.
    """
    segments = [s for s in _SPLIT.split(title) if s]
    titles = (title,) + tuple(
        " ".join(segments[:end])
        for end in range(len(segments) - 1, 0, -1)
        if all(map(_QUALIFIER.search, segments[end:]))
    )
    named = seasons(title)
    medium = (
        "tvshow"
        if named or _TV.search(title)
        else "movie" if _FILM.search(title) else ""
    )
    return Claim(titles, frozenset(map(title_key, titles)), named, medium)


def release_year(album: dict) -> int:
    """
    An album's first release year: its original date (a reissue keeps the
    release group's), else its year; 0 when undated.

    :param album: AudioLibrary row with originaldate and year.
    :return: Year.
    """
    return int(album["originaldate"][:4] or 0) or album["year"]


def owner(
    claim: Claim, album_year: int, candidates: list[tuple[str, dict]]
) -> tuple[str, dict] | None:
    """
    The film or show an album belongs to among library rows sharing its title:
    its wording's medium if both kinds match, then the nearest year.

    :param claim: The album's claim.
    :param album_year: The album's first release year, 0 when undated.
    :param candidates: (movie or tvshow, row with title, originaltitle and year).
    :return: The (type, row) pair, or None when none matches.
    """
    fits = [
        (type, row)
        for type, row in candidates
        if claim.keys & {title_key(row["title"]), title_key(row["originaltitle"])}
    ]
    fits = [fit for fit in fits if fit[0] == claim.medium] or fits
    return min(
        fits,
        key=lambda fit: abs(fit[1]["year"] - album_year) if album_year else 0,
        default=None,
    )
