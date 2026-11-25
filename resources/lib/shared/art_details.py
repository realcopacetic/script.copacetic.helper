# author: realcopacetic

"""
Art details: a picture file named "Artist - 'Title' (Year)" matched to its painting
on Wikidata, on demand, in folders the user marks (subfolders follow). Each file's
verdict, a match or a miss, is kept by path and mtime until it is refreshed.
"""

import json
import posixpath
import re
import unicodedata
from difflib import SequenceMatcher
from functools import cache
from pathlib import Path
from typing import Any, Callable, NamedTuple

import xbmcvfs
from xbmc import getSupportedMedia

from resources.lib.apis import wikidata
from resources.lib.apis.cache import DAY, Asides
from resources.lib.shared import logger as log
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import (
    ADDON,
    ADDONDATA,
    replace_file,
    window_property,
)

FOLDERS = Path(ADDONDATA, "art_details_folders.json")  # the marked folders' paths
# A verdict stands until refreshed or the file changes; a year, so a moved or deleted
# file's row is pruned in time
TTL_FILE = 365 * DAY
THRESHOLD = 0.8  # the least score a match needs; below it the file shows nothing
# A label whose words are some of the title's scores the share it covers: from
# CONTAIN up when it has CONTAIN_WORDS or more and covers half the title (Hokusai's
# Great Wave); otherwise at most SHARE_MAX, which no year bonus lifts to THRESHOLD
# ("Green Forest" in "Yellow and Green Forest")
CONTAIN, CONTAIN_WORDS, SHARE_MAX = 0.75, 3, 0.6
# Kodi browses these as folders, so a mark inside one never matches its own path again
ARCHIVES = ("zip://", "rar://", "archive://")
# Kodi's picture extensions it lists as folders or feeds, not pictures
NOT_PICTURES = frozenset((".cbz", ".cbr", ".zip", ".rar", ".rss"))
# Supports a painting is made on, as Wikidata names them: the surface when no
# applies-to-part qualifier says so
SURFACES = frozenset(
    "canvas, panel, wood, paper, board, cardboard, paperboard, copper, linen, "
    "oak panel, poplar panel, wood panel, hardboard, plywood, vellum, parchment, "
    "silk".split(", ")
)
YEAR_SAME, YEAR_NEAR, YEAR_FAR = 0.15, 0.05, -0.1  # in the file's years, one off, more
DEPICTS = 3  # values kept
# Words a title is matched without: articles and the small words around them
_MINOR = frozenset(
    "a an the of off at in on by to and with from over under "
    "la le les l los las el il der die das de het".split()
)
_NUMERALS = "i ii iii iv v vi vii viii ix x xi xii xiii xiv xv xvi xvii xviii xix xx"
_NUMBERS = (
    "one two three four five six seven eight nine ten eleven twelve thirteen "
    "fourteen fifteen sixteen seventeen eighteen nineteen twenty"
)
# One to twenty, written or in figures, as Roman numerals: "Composition Seven" is VII
_ROMAN = {
    **dict(zip(_NUMBERS.split(), _NUMERALS.split())),
    **{str(n): numeral for n, numeral in enumerate(_NUMERALS.split(), 1)},
}
_NAME = re.compile(r"(?P<artist>.+?)\s+[-–—]\s+(?P<title>.+)")
_YEARS = re.compile(r"\((\d{3,4})(?:\s*[-–]\s*(\d{2,4}))?\)")
_QUOTE = r"['‘’\"“”]"
_FROM = re.compile(rf"(.*?{_QUOTE})\s+from\s.*", re.I)  # 'Title' from Cycle '…'
_QUOTES = re.compile(rf"(?<!\w){_QUOTE}|{_QUOTE}(?!\w)")  # not an apostrophe
_USER = re.compile(r"^([a-z][a-z0-9+.-]*://)[^/@]*@", re.I)  # smb://user:pass@


class Name(NamedTuple):
    """What a file's name says: the artist, the title and its year or years."""

    artist: str
    title: str
    years: tuple[int, int] | None


def parse(path: str) -> Name | None:
    """
    A file's "Artist - Title (Year)": quotes optional, a year range allowed, words
    after a quoted title's "from" (a cycle or series) dropped.

    :param path: The picture's path or file name.
    :return: The name's parts; None for a name with no " - ".
    """
    base = re.split(r"[/\\]", path)[-1]
    if not (name := _NAME.fullmatch((base.rpartition(".")[0] or base).strip())):
        return None
    title, years = name["title"], None
    if found := [*_YEARS.finditer(title)]:
        first, last = found[-1].groups()
        last = last or first
        last = int(first[: -len(last)] + last)  # a short range's end: (1894-95)
        years, title = (int(first), last), title[: found[-1].start()]
    if cut := _FROM.fullmatch(title.strip()):
        title = cut[1]
    return Name(_unquote(name["artist"]), _unquote(title), years)


def _unquote(text: str) -> str:
    """Text without its quote marks; an apostrophe inside a word stays."""
    return _QUOTES.sub("", text).strip()


def words(text: str) -> list[str]:
    """
    A title as matched: accents folded, no case or punctuation, small words dropped,
    numbers to twenty as Roman numerals.

    :param text: A title, a label or an alias.
    :return: Its words.
    """
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return [_ROMAN.get(w, w) for w in re.findall(r"\w+", text) if w not in _MINOR]


def year_score(years: tuple[int, int] | None, inception: list[int]) -> float:
    """
    The year's part of a score: a bonus for a year in the file's range or one off,
    a cost for one further; nothing when either side has none.

    :param years: The file's first and last year.
    :param inception: The work's inception years.
    :return: Added to the title's score.
    """
    if not (years and inception):
        return 0
    gap = min(max(years[0] - year, year - years[1], 0) for year in inception)
    return YEAR_SAME if not gap else YEAR_NEAR if gap == 1 else YEAR_FAR


def title_score(title: list[str], labels: list[str], floor: float = 0) -> float:
    """
    The best of a work's labels against a title: their similarity; a label whose
    words are some of the title's, by the share it covers (from CONTAIN for
    CONTAIN_WORDS or more covering half; else at most SHARE_MAX).

    :param title: The file's title words.
    :param labels: The work's labels and aliases, as Wikidata has them.
    :param floor: Similarities at or under it aren't worked out: they can't match.
    :return: 0 to 1.
    """
    have, best = set(title), 0
    matcher = SequenceMatcher(b=" ".join(title))  # b's index is built once
    for label in labels:
        if not (own := words(label)):
            continue
        if (part := set(own)) < have:  # "Green Forest" in "Yellow and Green Forest"
            share = len(part) / len(have)
            if len(part) >= max(CONTAIN_WORDS, len(have) / 2):
                share = CONTAIN + (1 - CONTAIN) * share
            else:
                share = min(share, SHARE_MAX)
            best = max(best, share)
            continue
        matcher.set_seq1(" ".join(own))
        bar = max(best, floor)  # the quick ratios are upper bounds: cheap rejects
        if matcher.real_quick_ratio() > bar and matcher.quick_ratio() > bar:
            best = max(best, matcher.ratio())
    return best


def match(name: Name, works: list[list]) -> tuple[str, float] | None:
    """
    The file's work among an artist's: the best title and year score, ties to the
    work with the most sitelinks (the famous version), at THRESHOLD or above.

    :param name: The file's name.
    :param works: The artist's works, as wikidata.works gives them.
    :return: The work's Q-id and its score; None below the threshold.
    """
    if not (title := words(name.title)):
        return None
    floor = THRESHOLD - YEAR_SAME  # no title under this reaches the threshold

    def score(labels: list[str], inception: list[int]) -> float:
        """A work's score, to two places: closer than that is a tie."""
        total = title_score(title, labels, floor) + year_score(name.years, inception)
        return round(total, 2)

    best, _, qid = max(
        (score(labels, years), links, qid) for qid, links, years, labels in works
    )
    return (qid, best) if best >= THRESHOLD else None


def _cm(metres: float) -> str:
    """A size in metres as centimetres to one place, with no needless ".0"."""
    return f"{metres * 100:.1f}".removesuffix(".0")


def _medium(materials: list[list]) -> str:
    """
    Materials as a caption: paint on its surface ("Oil on canvas" from oil paint
    and canvas, the painting surface, or a support SURFACES names), else in turn.

    :param materials: [label, is the painting surface] pairs.
    :return: The medium, or "".
    """
    paints, surfaces = {}, {}  # dicts: each label once, in Wikidata's order
    for label, surface in materials:
        on = surface or label.casefold() in SURFACES
        (surfaces if on else paints)[label.removesuffix(" paint")] = None
    text = " on ".join(filter(None, (" and ".join(paints), " and ".join(surfaces))))
    return text[:1].upper() + text[1:]


def fields(name: Name, artist: dict[str, Any], qid: str, work: dict, text: str) -> dict:
    """
    A match's standard fields, as served: one value each, depicts up to DEPICTS;
    a collection Wikidata knows only as unknown is None (a private one).

    :param name: The file's name, for what Wikidata lacks.
    :param artist: wikidata.works's answer.
    :param qid: The work's Q-id.
    :param work: wikidata.painting's answer.
    :param text: The English Wikipedia summary, or "".
    :return: Fields by name.
    """

    def first(kind: str) -> Any:
        """The kind's first value Wikidata names; "" for none."""
        return next(filter(None, work.get(kind, [])), "")

    height, width = first("height"), first("width")
    year = min(work.get("inception", [0])) or (name.years and name.years[0])
    return {
        "qid": qid,
        "title": first("title") or name.title,
        "artist": artist["label"] or name.artist,
        "artist_qid": artist["qid"],
        "year": str(year or ""),
        "medium": _medium(work.get("material", [])),
        "genre": first("genre"),
        "collection": first("collection") or (None if "collection" in work else ""),
        "dimensions": f"{_cm(height)} × {_cm(width)} cm" if height and width else "",
        "depicts": [*dict.fromkeys(filter(None, work.get("depicts", [])))][:DEPICTS],
        "summary": text,
        "enwiki": first("enwiki"),
    }


def _mtime(path: str) -> int:
    """The file's modification time; 0 for one Kodi can't stat."""
    return int(xbmcvfs.Stat(path).st_mtime())


def _key(path: str) -> str:
    """The api_cache key of a file's verdict."""
    return f"wikidata:file:{path}"


def verdict(path: str) -> dict[str, Any] | None:
    """
    A file's kept verdict, while the file is unchanged.

    :param path: The picture's path.
    :return: Its fields; {} for a miss; None when not looked up (or changed since).
    """
    row = ApiCacheHandler().get(_key(path))
    if row and row[0] and row[0]["mtime"] == _mtime(path):
        return row[0]["fields"]
    return None


def look_up(path: str) -> dict[str, Any] | None:
    """
    Match a file to its painting and keep the verdict; a request not answered
    (busy, refused, failed) keeps none, so the next visit asks again.

    :param path: The picture's path.
    :return: Its fields; {} for a miss; None when a request wasn't answered.
    """
    found = _found(path)
    if found is not None:
        kept = {"mtime": _mtime(path), "fields": found}
        ApiCacheHandler().put(_key(path), kept, TTL_FILE)
    return found


def _found(path: str) -> dict[str, Any] | None:
    """
    look_up's answer, asked of Wikidata and Wikipedia in turn.

    :param path: The picture's path.
    :return: Its fields; {} for a miss; None when a request wasn't answered.
    """
    if not (name := parse(path)):
        return {}
    if not (artist := wikidata.works(name.artist)):
        return artist  # None: not answered; {}: no such painter
    if not (best := match(name, artist["works"])):
        return {}
    qid, score = best
    if (work := wikidata.painting(qid)) is None:
        return None
    article = next(iter(work.get("enwiki", [])), "")
    if (text := wikidata.summary(article) if article else "") is None:
        return None
    log.debug(f"art_details → {qid} at {score} for {path}")
    return fields(name, artist, qid, work, text)


def forget(path: str) -> None:
    """
    Drop a file's verdict, and mark the answers it came from stale (its artist's
    works, the painting, the summary), so a look-up asks again.

    :param path: The picture's path.
    """
    cache, name = ApiCacheHandler(), parse(path)
    row = cache.get(_key(path))
    found = row and row[0] and row[0]["fields"] or {}
    artist = name.artist if name else ""
    wikidata.forget(artist, found.get("qid", ""), found.get("enwiki", ""))
    cache.drop(_key(path))  # exactly: a path's % or _ would match other files


"""Marked folders"""


def folder(path: str) -> str:
    """A folder's path ending in its separator, so a prefix is a whole folder."""
    if path.endswith(("/", "\\")):
        return path
    return path + ("\\" if "\\" in path and "/" not in path else "/")


def marked() -> list[str]:
    """The folders marked for look-ups, as their paths."""
    return json.loads(FOLDERS.read_text("utf-8")) if FOLDERS.exists() else []


def covers(folders: list[str], path: str) -> bool:
    """
    Whether a path is in a marked folder or is one: subfolders follow.

    :param folders: The marked folders.
    :param path: A file's or folder's path.
    """
    return path.startswith(tuple(folders))


def without_user(path: str) -> str:
    """A path as Kodi shows it (ListItem.FolderPath): no user name or password."""
    return _USER.sub(r"\1", path)


def wanted(path: str) -> bool:
    """
    Whether a picture may be looked up now: the setting on and its folder marked,
    tested again before any request, so none goes out once either is undone.

    :param path: The picture's path.
    """
    return ADDON.getSettingBool("wikidata") and covers(marked(), path)


def is_picture(path: str) -> bool:
    """Whether Kodi shows a file as a picture: its extension, not an archive's."""
    extension = posixpath.splitext(path)[1].lower()
    return extension in _picture_extensions() and extension not in NOT_PICTURES


@cache
def _picture_extensions() -> frozenset[str]:
    """Kodi's picture extensions, image decoder add-ons' included."""
    return frozenset(getSupportedMedia("picture").lower().split("|"))


def publish(folders: list[str], path: str) -> None:
    """
    A folder's state, for the context menu's items to compare with its path:
    art_details_marked (itself marked), _unmarked (neither it nor a folder above).

    :param folders: The marked folders.
    :param path: The folder's path, as ListItem.FolderPath shows it.
    """
    window_property("art_details_marked", value=folder(path) in folders and path)
    window_property("art_details_unmarked", value=not covers(folders, path) and path)


def mark(path: str, on: bool) -> list[str]:
    """
    Mark a folder for look-ups, or unmark it (its subfolders' own marks stay).

    :param path: The folder's path.
    :param on: True to mark it.
    :return: The marked folders after.
    """
    path, folders = folder(path), marked()
    folders = [f for f in folders if f != path] + [path] * on
    replace_file(FOLDERS, json.dumps(folders, indent=1).encode())
    return folders


# Files looked up for served calls, one at a time as the query service asks, each
# still wanted when its turn comes; a verdict, a match or a miss, is news
ASIDES = Asides(lambda path: look_up(path) if wanted(path) else None)


def fit_chips(
    labels: list[str], width: Callable[[str], float], row: float, gap: float
) -> list[str]:
    """
    The chips a row holds, from the first: as a grouplist lays them out, a row too
    wide drops chips from the end.

    :param labels: The chips' labels, empty ones left out.
    :param width: A chip's drawn width for its label.
    :param row: The row's width.
    :param gap: The grouplist's itemgap.
    :return: The labels that fit.
    """
    used, kept = -gap, []
    for label in labels:
        if (used := used + gap + width(label)) > row:
            break
        kept.append(label)
    return kept
