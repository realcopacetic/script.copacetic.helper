# author: realcopacetic

"""
Art details: a picture file named "Artist - 'Title' (Year)" matched to its painting
on Wikidata, on demand, in folders the user marks (subfolders follow). Each file's
verdict, a match or a miss, is kept by path and mtime until it is refreshed. Then
its artist's page: the artist's details and biography, and three rails.
"""

import json
import posixpath
import re
import unicodedata
from difflib import SequenceMatcher
from functools import cache, partial
from operator import itemgetter
from pathlib import Path
from typing import Any, Callable, NamedTuple

import xbmcvfs
from xbmc import getLocalizedString, getSupportedMedia

from resources.lib.apis import wikidata
from resources.lib.apis.cache import DAY, Asides, while_live
from resources.lib.shared import logger as log
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import (
    ADDON,
    ADDONDATA,
    file_label,
    fold,
    replace_file,
    window_property,
)
from resources.lib.shared.wikidata_details import Unanswered, answer

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
NAMES = 2  # teachers and influences named on the artist page, the rest counted
# A demonym's adjective endings: Wikidata lists a country's noun too, in no set order
# (Briton before British, Spaniard after Spanish); the shortest of them wins
ADJECTIVES = ("sh", "ch", "an", "ese", "ic", "i")
_ORDINALS = {1: "st", 2: "nd", 3: "rd"}  # by last digit, else th (and 11th to 13th)
# Widths Commons scales a picture to, two of its standard thumbnail steps: the 600
# squares (portrait, rails) at a 4K GUI's 1200 near enough, and full screen
TILE, FULL = 1280, 1920
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


def look_up(path: str, live: Callable[[], bool]) -> dict[str, Any] | None:
    """
    Match a file to its painting and keep the verdict; a request not answered
    (busy, refused, failed), or a look-up no longer live, keeps none.

    :param path: The picture's path.
    :param live: Tested before each request; False stops the look-up.
    :return: Its fields; {} for a miss; None when unanswered or stopped.
    """
    with while_live(live):  # tested again after each queue wait
        found = _found(path, live)
    if found is None or not live():  # stopped: a stale answer keeps no verdict
        return None
    kept = {"mtime": _mtime(path), "fields": found}
    ApiCacheHandler().put(_key(path), kept, TTL_FILE)
    return found


def _found(path: str, live: Callable[[], bool]) -> dict[str, Any] | None:
    """
    look_up's answer, asked of Wikidata and Wikipedia in turn, each request waiting
    out a busy queue as the info screens' look-ups do (wikidata_details.answer).

    :param path: The picture's path.
    :param live: Tested before each request; False stops the look-up.
    :return: Its fields; {} for a miss; None when unanswered or stopped.
    """
    if not (name := parse(path)):
        return {}
    ask = partial(answer, live)
    try:
        if not (artist := ask(wikidata.works, name.artist, live)):
            return {}  # no such painter
        if not (best := match(name, artist["works"])):
            return {}
        qid, score = best
        work = ask(wikidata.painting, qid)
        article = next(iter(work.get("enwiki", [])), "")
        text = ask(wikidata.summary, article) if article else ""
    except Unanswered:
        return None
    log.debug(f"art_details → {qid} at {score} for {path}")
    return fields(name, artist, qid, work, text)


def search(query: str, limit: int) -> list[tuple[str, dict]]:
    """
    Kept verdicts of pictures in marked folders whose details, or file name, hold
    every word of a query, best first; with no query, every match. Asks nothing.

    :param query: The words to find.
    :param limit: The most hits: the best so many, those gone from disk left out.
    :return: (path, fields) pairs; fields {} for a picture no painting matched.
    """
    typed = query.split()
    if not (words := [*filter(None, map(fold, typed))]) and typed:
        return []  # text with no word, such as emoji alone: nothing holds it
    folders, movements = marked(), {}

    def movement(qid: str) -> str:
        """The artist's movements, from its kept page; "" with none kept."""
        if qid not in movements:
            page = wikidata.kept("painter", qid)[0] or {}
            movements[qid] = " ".join(label for _, label in page.get("movement", []))
        return movements[qid]

    def rank(path: str, fields: dict) -> int | None:
        """0 the title holds the words, 1 the artist, 2 the details, 3 the name."""
        details = [fields.get(key) or "" for key in ("title", "artist", "collection")]
        details += [*fields.get("depicts", []), movement(fields.get("artist_qid", ""))]
        tiers = (details[:1], details[1:2], details, [file_label(path)])
        for tier, texts in enumerate(tiers):
            texts = [*map(fold, texts)]
            if all(any(word in text for text in texts) for word in words):
                return tier
        return None

    found = []
    prefix = _key("")
    for key, kept in ApiCacheHandler().starting(prefix):
        path, fields = key.removeprefix(prefix), kept["fields"]
        if not (is_picture(path) and covers(folders, path)):
            continue
        if (tier := rank(path, fields)) is None:
            continue
        if fields or words:  # no words: the matches alone
            found.append((tier, path, fields))
    found.sort(
        key=lambda hit: (
            hit[0],
            not hit[2],  # matches before misses
            fold(hit[2].get("artist", "")),
            int(hit[2].get("year") or 0),
            fold(hit[2].get("title") or file_label(hit[1])),
        )
    )
    # A picture moved or deleted keeps its verdict: dropped, as it won't open. The
    # page alone is checked, with no refill: a sleeping NAS stalls each check
    return [(path, fields) for _, path, fields in found[:limit] if xbmcvfs.exists(path)]


def forget(path: str) -> None:
    """
    Drop a file's verdict, and mark the answers it came from stale (its artist's
    works, the painting, the summary) and its artist's page, so both ask again.

    :param path: The picture's path.
    """
    cache, name = ApiCacheHandler(), parse(path)
    row = cache.get(_key(path))
    found = row and row[0] and row[0]["fields"] or {}
    artist = name.artist if name else ""
    wikidata.forget(
        artist,
        found.get("qid", ""),
        found.get("enwiki", ""),
        found.get("artist_qid", ""),
    )
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
    Whether a picture may be looked up now: the setting on and its folder marked.
    A look-up tests it before each of its requests: none goes out once either is undone.

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


# Files looked up for served calls, one at a time as the query service asks; before
# each request the file is still wanted and an asker still current. A verdict, a
# match or a miss, is news
ASIDES = Asides(lambda path, live: look_up(path, lambda: live() and wanted(path)))


"""Artist page"""


def commons(url: str, width: int) -> str:
    """A Commons file's URL, as Wikidata gives it, scaled to a width over https."""
    return f"{url.replace('http://', 'https://', 1)}?width={width}"


def page(kind: str, qid: str) -> tuple[Any, bool]:
    """
    Part of an artist's page as kept, whatever its age: its fields, the biography
    in them, or a rail; and whether all of it is fresh.

    :param kind: painter, or a rail's kind.
    :param qid: The artist's Q-id.
    :return: (answer, fresh), as wikidata.kept gives them.
    """
    found, fresh = wikidata.kept(kind, qid)
    if kind != "painter" or not found:
        return found, fresh
    if not (article := next(iter(found.get("enwiki", [])), "")):
        return found | {"biography": ""}, fresh
    text, known = wikidata.kept("summary", article)
    return found | {"biography": text or ""}, fresh and known


def _ask(key: tuple[str, str], live: Callable[[], bool]) -> Any:
    """
    Fetch part of an artist's page, each request while the setting is on and an
    asker current; then the part as page reads it, so an unchanged one is no news.

    :param key: (kind, Q-id), as page takes them.
    :param live: Whether an asker is still current.
    :return: The part, as page gives it.
    """
    kind, qid = key

    def wanted() -> bool:
        return live() and ADDON.getSettingBool("wikidata")

    if not wanted():
        return None
    with while_live(wanted):  # tested again after each queue wait
        if kind != "painter":
            wikidata.rail(kind, qid)
        elif (found := wikidata.artist(qid)) and found.get("enwiki") and wanted():
            wikidata.summary(found["enwiki"][0])
    return page(kind, qid)[0]


# Artist pages' parts for served calls, one request at a time as for files
PAGES = Asides(_ask)


def _julian(year: int, month: int, day: int) -> tuple[int, int, int]:
    """A proleptic Gregorian date as the Julian calendar's, by its Julian Day Number."""
    a = (14 - month) // 12
    y, m = year + 4800 - a, month + 12 * a - 3
    jdn = day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045
    c = jdn + 32082
    y = (4 * c + 3) // 1461
    e = c - 1461 * y // 4
    m = (5 * e + 2) // 153
    return y - 4800 + m // 10, m + 3 - 12 * (m // 10), e - (153 * m + 2) // 5 + 1


def _date(time: str, precision: int, calendar: str = "", limit: int = 14) -> str:
    """
    A Wikidata time to its precision, limit at the finest: day, month and year in
    Kodi's month names; a decade (1600s) or century (17th century, as Wikidata's); BC.
    """
    year, month, day = map(int, re.match(r"(-?\d+)-(\d\d)-(\d\d)", time).groups())
    # The query service gives a Julian date as Gregorian from a day's precision on
    if calendar == wikidata.JULIAN and precision >= 11:
        year, month, day = _julian(year, month, day)
    # From a year's precision on, years are astronomical (0 is 1 BC); coarser, not
    bc = 1 - year if precision >= 9 else -year
    era, year = (" BC", bc) if bc > 0 else ("", year)
    precision = min(precision, limit)
    if precision == 7:
        century = -(-year // 100)  # 1601 to 1700: the 17th
        teens = century % 100 in (11, 12, 13)
        text = (
            f"{century}{'th' if teens else _ORDINALS.get(century % 10, 'th')} century"
        )
    elif precision == 8:
        text = f"{year // 10 * 10}s"
    elif precision < 10:
        text = str(year)
    else:
        name = getLocalizedString(20 + month)  # 21-32: January to December
        text = f"{day} {name} {year}" if precision > 10 else f"{name} {year}"
    return text + era


def artist_fields(found: dict[str, Any]) -> dict[str, str]:
    """
    An artist's page as served, one string each: the first NAMES teachers and
    influences named and the rest counted (_more), the first movement likewise, the
    first country's demonym.

    :param found: page's answer for the painter.
    :return: Fields by name; the portrait a TILE-wide URL, or "".
    """

    def first(kind: str) -> Any:
        """The kind's first value; "" for none."""
        return next(iter(found.get(kind, [])), "")

    def event(time: str, place: str) -> str:
        """A birth or death: its date to its precision, then its place's label."""
        date = first(time) and _date(*first(time))
        return ", ".join(filter(None, (date, first(place) and first(place)[1])))

    def named(kind: str, names: int) -> dict[str, str]:
        """Its first labels joined, and how many more, each once in Wikidata's order."""
        labels = [*dict.fromkeys(label for _, label in found.get(kind, []))]
        more = str(len(labels[names:]) or "")
        return {kind: ", ".join(labels[:names]), f"{kind}_more": more}

    occupations = dict(found.get("occupation", []))  # qid → label, in order
    occupation = occupations.get(wikidata.PAINTER) or next(
        iter(occupations.values()), ""
    )
    # Years, or a coarser precision's decade or century
    born, died = (
        first(kind) and _date(*first(kind), limit=9) for kind in ("born", "died")
    )
    # Each country's demonyms, the earliest citizenship first (one with no start first)
    countries = {}
    for country, _, name in sorted(found.get("nationality", []), key=itemgetter(1)):
        countries.setdefault(country, []).append(name)
    portrait = first("portrait")
    return {
        "name": first("name"),
        "occupation": occupation[:1].upper() + occupation[1:],
        "life": f"{born}–{died}" if died else born,  # –1851: the death year alone
        "born": event("born", "birthplace"),
        "died": event("died", "deathplace"),
        **named("teacher", NAMES),
        **named("movement", 1),
        **named("influence", NAMES),
        "nationality": min(
            next(iter(countries.values()), [""]),
            key=lambda name: (not name.endswith(ADJECTIVES), len(name)),
        ),
        "paintings": str(first("paintings") or ""),
        "portrait": portrait and commons(portrait, TILE),
        "biography": found["biography"],
    }


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
