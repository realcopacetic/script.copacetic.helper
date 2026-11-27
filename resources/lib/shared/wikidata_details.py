# author: realcopacetic

"""
Wikidata details for library films, TV shows, artists and albums, found by their
TMDb, IMDb and MusicBrainz ids alone (no id, no look-up): a film's composers, the
written work it is based on, where and when it is set, what it is about and its
universe; a show's creators; an artist's labels, place, instruments, members,
memberships, awards and influences; an album's producers; the soundtrack albums and
films they link. Kept per item. Also the story band's and the Biography bands' fitting.
"""

import re
from functools import partial
from typing import Any, Callable

from xbmc import Monitor

from resources.lib.apis import wikidata
from resources.lib.apis.cache import Asides, busy, hold, while_live
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import ADDON, fold, named

# A film's or show's TMDb id property; IMDb's (P345) is the fallback for both
TMDB = {"movie": "P4947", "tvshow": "P4983"}
# The ids a linked film or show is found by in the library, named as Kodi's uniqueid
VIDEO_IDS = {
    "P4947": ("movie", "tmdb"),
    "P4983": ("tvshow", "tmdb"),
    "P345": ("", "imdb"),
}
# Written works a story is based on, as instance of (P31), form of creative work
# (P7937) or genre (P136) names them, and their word on screen. Novels are mostly a
# literary work with the form novel (Dune, Slow Horses); games, toys, characters and
# films are out
WRITTEN = {
    "Q36279": "biography",  # a genre: American Prometheus is a written work
    "Q8261": "novel",
    "Q1667921": "novel series",
    "Q149537": "novella",
    "Q49084": "short story",
    "Q5185279": "poem",
    "Q25379": "play",
    "Q7725634": "book",  # literary work
    "Q47461344": "book",  # written work
    "Q571": "book",
    "Q277759": "book series",
    "Q1004": "comic",
    "Q14406742": "comic",  # comic book series
    "Q725377": "graphic novel",
    "Q21198342": "manga",  # manga series
    "Q8274": "manga",
}
NAMES = 2  # an artist's labels and instruments named, the rest counted (+N)
LOOKED = 6  # periods and subjects labelled, Wikidata's first: some don't show
PLACES, SUBJECTS = 2, 3  # chips at most
# Times by their label, finer first, each with the years it spans: a year (1940), a
# decade (1940s), a century (20th century, 20. century, XX century)
TIMES = (
    (re.compile(r"(\d{4})"), 0),
    (re.compile(r"(\d{3}0)s"), 9),
    (re.compile(r"(?:\d+(?:st|nd|rd|th|\.)|[IVXLC]+) century", re.IGNORECASE), None),
)
NEAR = 5  # a year or decade this close to the release year is its own time: not shown
# Words a universe's name is matched without (Despicable Me universe, … Collection)
GENERIC = frozenset({"universe", "collection", "franchise", "series"})
COLUMNS = ("set_in", "about", "universe", "part_of")  # the story band's, as drawn
# The story band's cuts, in turn, while it overflows: a column to so many chips
DROPS = (
    ("universe", 0),
    ("about", 2),
    ("about", 1),
    ("about", 0),
    ("places", 1),
    ("period", 0),
)
BIO = 2  # a Biography band column's chips at most
LISTED = 6  # an artist's members or memberships labelled for its Biography line
# A Biography line's and band's statements on an artist's item, and the labels asked
ARTIST_BIO = {
    "members": ("P527", LISTED),
    "member_of": ("P463", LISTED),
    "awards": ("P166", BIO),
    "influences": ("P737", BIO),
}
# The Biography tabs' bands by kind: their columns as drawn, then their cuts in turn
# while one overflows, as the story band's (the last column first, then the chips)
BIOS = {
    "artist": (("awards", "influences"), (("influences", 0), ("awards", 1))),
    "painter": (
        ("known_for", "genre", "worked_in"),
        (("worked_in", 0), ("genre", 1), ("genre", 0), ("known_for", 1)),
    ),
}


class Unanswered(Exception):
    """A request not answered (busy, refused, failed) or a look-up no longer live."""


def based_on(source: dict[str, Any]) -> str:
    """
    The written work an item is based on: "Slow Horses, novel by Mick Herron";
    authors by " and ".

    :param source: The details' source: title, type and authors.
    :return: The text.
    """
    text, authors = f"{source['title']}, {source['type']}", source["authors"]
    return f"{text} by {' and '.join(authors)}" if authors else text


def properties(
    kind: str, found: dict[str, Any] | None, counts: bool = True
) -> dict[str, str]:
    """
    The details as an item's wikidata_* properties, an empty one left out.

    :param kind: movie, tvshow, artist or album.
    :param found: The kept details; None or {} for none.
    :param counts: Whether an artist's labels and instruments count the rest (+N).
    :return: The properties.
    """
    if not found:
        return {}
    if kind == "artist":
        values = {
            "labels": named(found["labels"], counts and found["more"]),
            "place": found["place"],
            # details kept before instruments were looked up have none
            "instruments": named(
                found.get("instruments", []),
                counts and found.get("instruments_more", 0),
            ),
        }
    elif kind == "album":
        values = {"producer": " / ".join(found["producer"])}
    else:
        source = found["source"]
        values = {
            "music_by": kind == "movie" and " / ".join(found["music_by"]),
            # details kept before creators were looked up have none
            "created_by": kind == "tvshow" and " / ".join(found.get("created_by", [])),
            "based_on": source and based_on(source),
        }
    return {f"wikidata_{key}": value for key, value in values.items() if value}


def story_chips(
    found: dict[str, Any], title: str, year: int, collection: str
) -> dict[str, list[str]]:
    """
    A film's or show's story band by column, before fitting: places, period (a named
    one, else the finest time), about, universe, and part_of (its collection) for a
    band of one chip at most. Nothing repeats the title (or a universe, collection).

    :param found: The kept details; {} for none (kept before the band: none of it).
    :param title: The item's title.
    :param year: Its year; 0 for none.
    :param collection: A film's set; "" for none.
    :return: Each column's chips.
    """
    periods = [p for p in found.get("periods", []) if not _near(p, year)]
    period = min(periods, key=lambda p: _time(p)[0], default="")
    universe = found.get("universe", "")
    others = _words(title, GENERIC), _words(collection, GENERIC)
    titled = (_words(title),)
    about = [
        s
        for s in found.get("about", [])
        if _time(s)[0] < 0 and not _overlaps(_words(s), titled)
    ]
    repeats = _overlaps(_words(universe, GENERIC), others)
    columns = {
        "places": found.get("places", []),
        "period": [period] if period else [],
        "about": about[:SUBJECTS],
        "universe": [universe] if universe and not repeats else [],
    }
    one = sum(map(len, columns.values())) < 2
    return columns | {"part_of": [collection] if collection and one else []}


def _rows(columns: dict[str, list[str]]) -> dict[str, list[str]]:
    """The story band's columns as drawn: Set in holds the places, then the period."""
    return {
        "set_in": columns["places"] + columns["period"],
        "about": columns["about"],
        "universe": columns["universe"],
        "part_of": columns["part_of"],
    }


def fit_band(
    columns: dict[str, list[str]],
    chip: Callable[[str], float],
    width: float,
    gaps: tuple[float, float],
    captions: dict[str, float],
    drops: tuple[tuple[str, int], ...] = DROPS,
    rows: Callable[[dict], dict[str, list[str]]] = _rows,
) -> dict[str, str]:
    """
    A band fitted to its width, cut in drops' turn while it overflows, as
    wikidata_{column}_{n} of the columns rows draws (the story band's by default). A
    column takes its chips' width, or its caption's if wider ({column}_caption_wide).

    :param columns: Each column's chips, as the drops cut them (story_chips').
    :param chip: A chip's width.
    :param width: The band's width.
    :param gaps: The gap between two columns, and between two chips of a column.
    :param captions: Each drawn column's caption width, by its key; none for none.
    :param drops: The cuts in turn, each a column to so many chips.
    :param rows: The columns as drawn, by their keys.
    :return: The properties.
    """
    gap, chip_gap = gaps

    def chips(row: list[str]) -> float:
        return sum(map(chip, row)) + chip_gap * (len(row) - 1)

    for key, keep in drops:
        drawn = [
            max(captions.get(name, 0), chips(row))
            for name, row in rows(columns).items()
            if row
        ]
        if sum(drawn) + gap * (len(drawn) - 1) <= width:
            break
        columns = columns | {key: columns[key][:keep]}
    fitted = rows(columns)
    wide = {
        f"wikidata_{key}_caption_wide": "true"
        for key, row in fitted.items()
        if row and captions.get(key, 0) > chips(row)
    }
    return wide | {
        f"wikidata_{key}_{n}": name
        for key, row in fitted.items()
        for n, name in enumerate(row, 1)
    }


def bio_band(
    kind: str,
    found: dict[str, Any],
    chip: Callable[[str], float],
    width: float,
    gaps: tuple[float, float],
    captions: dict[str, float],
) -> dict[str, str]:
    """
    A Biography tab's band (BIOS' kind), fitted as the story band is: BIO chips a
    column at most, the columns drawn as they are.

    :param kind: artist or painter.
    :param found: The details: each column's labels by its key; none for none.
    :param chip: A chip's width.
    :param width: The band's width.
    :param gaps: The gap between two columns, and between two chips of a column.
    :param captions: Each drawn column's caption width, by its key; none for none.
    :return: The band's wikidata_{column}_{n} and _caption_wide properties.
    """
    keys, drops = BIOS[kind]
    columns = {key: found.get(key, [])[:BIO] for key in keys}
    return fit_band(columns, chip, width, gaps, captions, drops, dict)


def joined(names: list[str]) -> str:
    """
    Names as one line of text: "Royal Academy of Arts", "A and B", "A, B and C".

    :param names: The names, in order.
    :return: The text; "" for none.
    """
    return " and ".join(filter(None, (", ".join(names[:-1]), *names[-1:])))


def _words(text: str, generic: frozenset[str] = frozenset()) -> str:
    """Text as matched, word by word: each folded, generic ones left out, spaced."""
    words = (fold(word) for word in text.split() if word.casefold() not in generic)
    return f" {' '.join(filter(None, words))} "


def _overlaps(words: str, others: tuple[str, ...]) -> bool:
    """Whether matched words (_words) hold, or are held by, any of the others."""
    return words.strip() != "" and any(
        other.strip() and (words in other or other in words) for other in others
    )


def _kind(claims: dict[str, list]) -> str:
    """A written work's word: its form (P7937), genre or type, as WRITTEN names it."""
    forms = (*claims.get("P7937", []), *claims.get("P136", []), *claims.get("P31", []))
    return next((WRITTEN[q] for q in forms if q in WRITTEN), "")


def _near(label: str, year: int) -> bool:
    """Whether a year or decade is within NEAR years of the item's year; 0 for none."""
    years = _time(label)[1]
    return bool(year and years) and years[0] - NEAR <= year <= years[-1] + NEAR


def _time(label: str) -> tuple[int, range]:
    """
    A period's rank by its label (TIMES: 0 a year, 1 a decade, 2 a century; -1 a
    named period, World War II) and the years it spans (none: named, a century).
    """
    for rank, (pattern, span) in enumerate(TIMES):
        if match := pattern.fullmatch(label):
            if span is None:  # a century: never its release's own time
                return rank, range(0)
            return rank, range(int(match[1]), int(match[1]) + span + 1)
    return -1, range(0)


def _item(ask: Callable, prop: str, value: str) -> tuple[str, dict] | None:
    """The first item with a statement of a value, and its statements; None for none."""
    if not (found := ask(wikidata.having, prop, value)):
        return None
    qid = found[0]
    return qid, ask(wikidata.items, [qid])[qid]["claims"]


def _labelled(names: dict[str, str], qids: list[str]) -> list[str]:
    """The items' labels in order, an unlabelled item left out."""
    return [*filter(None, map(names.get, qids))]


def _once(*groups: list[str]) -> list[str]:
    """Items from both ends of a link, each once: an album often links both ways."""
    return [*dict.fromkeys(qid for group in groups for qid in group)]


def _video(kind: str, ask: Callable, tmdb: str, imdb: str) -> dict[str, Any]:
    """
    A film's or show's details: composers (names and MusicBrainz ids), creators, its
    first written source, where and when it's set, what about, its universe (else
    franchise), and its soundtracks' release groups (P406's, and those naming it).
    """
    found = (tmdb and _item(ask, TMDB[kind], tmdb)) or (
        imdb and _item(ask, "P345", imdb)
    )
    if not found:
        return {}
    qid, claims = found
    composers, sources = claims.get("P86", []), claims.get("P144", [])
    places = claims.get("P840", [])[:PLACES]
    periods, subjects = (claims.get(p, [])[:LOOKED] for p in ("P2408", "P921"))
    universes = (claims.get("P1434") or claims.get("P8345", []))[:1]
    creators = claims.get("P170", []) if kind == "tvshow" else []  # only shows serve
    albums = _once(claims.get("P406", []), ask(wikidata.having, "P9899", qid))
    linked = ask(wikidata.items, [*composers, *sources, *albums])
    source = next(
        (
            linked[q]
            for q in sources
            if WRITTEN.keys() & set(linked[q]["claims"].get("P31", []))
        ),
        None,
    )
    authors = source["claims"].get("P50", []) if source else []
    story = [*universes, *places, *periods, *subjects]  # by label alone
    names = ask(wikidata.labels, [*authors, *creators, *story])
    return {
        "music_by": [*filter(None, (linked[q]["label"] for q in composers))],
        "created_by": _labelled(names, creators),
        "composers": [
            mbid for q in composers for mbid in linked[q]["claims"].get("P434", [])
        ],
        "source": source
        and {
            "title": source["label"],
            "type": _kind(source["claims"]),
            "authors": _labelled(names, authors),
        },
        "places": _labelled(names, places),
        "periods": _labelled(names, periods),
        "about": _labelled(names, subjects),
        "universe": next(iter(_labelled(names, universes)), ""),
        "soundtracks": [
            group for q in albums for group in linked[q]["claims"].get("P436", [])
        ],
    }


def _artist(ask: Callable, mbid: str) -> dict[str, Any]:
    """
    An artist's details: its labels and instruments (NAMES named, an instrument
    capitalised), where it formed or was born, and its Biography line's and band's
    labels (ARTIST_BIO: members, memberships, awards, influences).
    """
    if not (found := _item(ask, "P434", mbid)):
        return {}
    claims = found[1]
    signed, played = claims.get("P264", []), claims.get("P1303", [])
    # A group's formation, else a person's birth
    place = (claims.get("P740") or claims.get("P19") or [""])[0]
    bio = {
        key: claims.get(prop, [])[:asked] for key, (prop, asked) in ARTIST_BIO.items()
    }
    names = ask(
        wikidata.labels,
        [
            *signed[:NAMES],
            *filter(None, [place]),
            *played[:NAMES],
            *(qid for qids in bio.values() for qid in qids),
        ],
    )
    shown = [*filter(None, map(names.get, signed[:NAMES]))]  # an unlabelled one counts
    instruments = [n[:1].upper() + n[1:] for q in played[:NAMES] if (n := names[q])]
    return {
        "labels": shown,
        "more": len(signed) - len(shown),
        "place": names.get(place, ""),
        "instruments": instruments,
        "instruments_more": len(played) - len(instruments),
        **{key: _labelled(names, qids) for key, qids in bio.items()},
    }


def _album(ask: Callable, group: str) -> dict[str, Any]:
    """
    An album's details by its release group: its producers, and the films and shows
    it was made for (its P9899, and items whose P406 names it) as [type, id kind, id].
    """
    if not (found := _item(ask, "P436", group)):
        return {}
    qid, claims = found
    producers = claims.get("P162", [])
    films = _once(claims.get("P9899", []), ask(wikidata.having, "P406", qid))
    linked = ask(wikidata.items, [*producers, *films])
    return {
        "producer": [*filter(None, (linked[q]["label"] for q in producers))],
        "films": [
            [*VIDEO_IDS[prop], value]
            for q in films
            for prop, values in linked[q]["claims"].items()
            if prop in VIDEO_IDS
            for value in values
        ],
    }


# Each kind's look-up, given the request asker and the key's ids
LOOK_UPS = {
    "movie": partial(_video, "movie"),
    "tvshow": partial(_video, "tvshow"),
    "artist": _artist,
    "album": _album,
}


def _key(key: tuple[str, ...]) -> str:
    """The api_cache key of an item's details: its kind and ids."""
    return f"wikidata:details:{':'.join(key)}"


def kept(key: tuple[str, ...]) -> tuple[dict[str, Any] | None, bool]:
    """
    An item's details as kept, whatever their age, and whether they're fresh.

    :param key: (movie or tvshow, TMDb id, IMDb id), (artist, MBID) or (album, MBID).
    :return: (details, fresh); (None, False) for none kept.
    """
    return ApiCacheHandler().get(_key(key)) or (None, False)


def answer(live: Callable[[], bool], call: Callable, *args: Any) -> Any:
    """
    A request's answer, while the look-up is live, waiting out a busy queue (which
    cached skips: the look-up runs aside), and asked once more after a 429's short
    hold (which cached waits out); raises Unanswered otherwise.

    :param live: Tested before each try; False stops the wait.
    :param call: The request, a cached fetch: None when not answered.
    :param args: Its arguments.
    :return: Its answer.
    """
    tries = 2
    while tries and live():
        last = hold(wikidata.NEXT_CALL)
        if (found := call(*args)) is not None:
            return found
        if busy(wikidata.NEXT_CALL):
            if Monitor().waitForAbort(1):
                break
        elif hold(wikidata.NEXT_CALL) != last:  # a 429 held the queue meanwhile
            tries -= 1
        else:  # refused, failed or timed out: not asked again
            break
    raise Unanswered


def details(key: tuple[str, ...], live: Callable[[], bool]) -> dict[str, Any] | None:
    """
    An item's details: kept ones while fresh, else asked of Wikidata and kept; a
    request not answered, or a look-up no longer live, keeps none.

    :param key: As kept takes it.
    :param live: Tested before each request; False stops the look-up.
    :return: The details; {} for an item Wikidata lacks; None when unanswered.
    """
    found, fresh = kept(key)
    if fresh:
        return found
    try:
        with while_live(live):  # tested again after each queue wait
            found = LOOK_UPS[key[0]](partial(answer, live), *key[1:])
    except Unanswered:
        return None
    if not live():  # stopped: a stale answer keeps no details
        return None
    ttl = wikidata.TTL_HIT if found else wikidata.TTL_EMPTY
    ApiCacheHandler().put(_key(key), found, ttl)
    return found


def wanted() -> bool:
    """Whether Wikidata may be asked: the helper's wikidata setting is on."""
    return ADDON.getSettingBool("wikidata")


def video_key(type: str, uniqueid: dict[str, str]) -> tuple[str, ...] | None:
    """
    A library film's or show's details key, by its TMDb and IMDb ids.

    :param type: movie or tvshow.
    :param uniqueid: The library row's uniqueid.
    :return: The key, as kept takes it; None with neither id.
    """
    ids = uniqueid.get("tmdb", ""), uniqueid.get("imdb", "")
    return (type, *ids) if any(ids) else None


def linked(key: tuple[str, ...] | None) -> dict[str, Any]:
    """
    An item's details as kept, while the setting is on, for their links (soundtracks,
    composers, films): never asked, as a plugin call holds one of Kodi's three
    directory workers (the served call asks).

    :param key: As kept takes it; None for an item with no id.
    :return: The details; {} when off, not kept, or for no item.
    """
    if not (key and wanted()):
        return {}
    return kept(key)[0] or {}


# Details looked up for served calls, one request at a time as the queue asks; before
# each request the setting is still on and an asker still current
ASIDES = Asides(lambda key, live: details(key, lambda: live() and wanted()))
