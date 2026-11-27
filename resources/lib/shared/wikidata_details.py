# author: realcopacetic

"""
Wikidata details for library films, TV shows, artists and albums, found by their
TMDb, IMDb and MusicBrainz ids alone (no id, no look-up): a film's composers, the
written work it is based on, where and when it is set, what it is about and its
universe; a show's creators; an artist's labels, place and instruments; an album's
producers; the soundtrack albums and films they link. Kept per item.
"""

from functools import partial
from typing import Any, Callable

from xbmc import Monitor

from resources.lib.apis import wikidata
from resources.lib.apis.cache import Asides, busy, hold
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
LOOKED = 6  # places and subjects looked up, Wikidata's first: a city's item is large
PLACES, SUBJECTS = 2, 3  # chips at most
# Places too broad beside a more specific one: Earth (Q2) itself, and instances (P31)
# of continent, part of the world, planet (inner, outer, gas giant) and moon
BROAD = frozenset(
    "Q2 Q5107 Q2418896 Q634 Q3504248 Q30014 Q121750 Q2537 Q109645860".split()
)
# Times as a period's or subject's class (P31), finer first: the years one with no
# end (P582) spans. Year, calendar year; decade; century, millennium
TIMES = {"Q577": 0, "Q3186692": 0, "Q39911": 9, "Q578": 99, "Q36507": 999}
TAXA = frozenset({"Q16521", "Q55983715"})  # taxon; organisms known by a common name
NEAR = 5  # a period this close to the release year is its own time: not shown
# Words a universe's name is matched without (Despicable Me universe, … Collection)
GENERIC = frozenset({"universe", "collection", "franchise", "series"})
# The story band's cuts, in turn, while it overflows: a column to so many chips
DROPS = (
    ("universe", 0),
    ("about", 2),
    ("about", 1),
    ("about", 0),
    ("places", 1),
    ("period", 0),
)


class _Unanswered(Exception):
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


def properties(kind: str, found: dict[str, Any] | None) -> dict[str, str]:
    """
    The details as an item's wikidata_* properties, an empty one left out.

    :param kind: movie, tvshow, artist or album.
    :param found: The kept details; None or {} for none.
    :return: The properties.
    """
    if not found:
        return {}
    if kind == "artist":
        values = {
            "labels": named(found["labels"], found["more"]),
            "place": found["place"],
            # details kept before instruments were looked up have none
            "instruments": named(
                found.get("instruments", []), found.get("instruments_more", 0)
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
    A film's or show's story band by column, before fitting: places, period, about,
    universe, and part_of (its collection) for a band of one chip at most. A subject
    the title names, a universe the title or collection names, aren't repeated.

    :param found: The kept details; {} for none (kept before the band: none of it).
    :param title: The item's title.
    :param year: Its year; 0 for none.
    :param collection: A film's set; "" for none.
    :return: Each column's chips.
    """
    label, start, end = found.get("period") or ("", None, None)
    near = year and start is not None and start - NEAR <= year <= end + NEAR
    universe = found.get("universe", "")
    names = _words(title, GENERIC), _words(collection, GENERIC)
    about = [s for s in found.get("about", []) if _words(s) not in _words(title)]
    columns = {
        "places": found.get("places", []),
        "period": [label] if label and not near else [],
        "about": about[:SUBJECTS],
        "universe": [universe] if universe and not _repeats(universe, names) else [],
    }
    one = sum(map(len, columns.values())) < 2
    return columns | {"part_of": [collection] if collection and one else []}


def fit_band(
    columns: dict[str, list[str]],
    chip: Callable[[str], float],
    width: float,
    gap: float,
    chip_gap: float,
) -> dict[str, str]:
    """
    The story band fitted to its width, cut in DROPS' turn while it overflows, as
    numbered wikidata_{column}_{n}: set_in (the places, then the period), about,
    universe, part_of.

    :param columns: story_chips' columns.
    :param chip: A chip's width.
    :param width: The band's width.
    :param gap: The gap between two columns.
    :param chip_gap: The gap between two chips of a column.
    :return: The properties.
    """
    for key, keep in DROPS:
        rows = [row for row in _rows(columns).values() if row]
        chips = [name for row in rows for name in row]
        drawn = sum(map(chip, chips)) + chip_gap * (len(chips) - len(rows))
        if drawn + gap * (len(rows) - 1) <= width:
            break
        columns = columns | {key: columns[key][:keep]}
    return {
        f"wikidata_{key}_{n}": name
        for key, row in _rows(columns).items()
        for n, name in enumerate(row, 1)
    }


def _rows(columns: dict[str, list[str]]) -> dict[str, list[str]]:
    """The band's columns as drawn: Set in holds the places, then the period."""
    return {
        "set_in": columns["places"] + columns["period"],
        "about": columns["about"],
        "universe": columns["universe"],
        "part_of": columns["part_of"],
    }


def _words(text: str, generic: frozenset[str] = frozenset()) -> str:
    """Text as matched, word by word: each folded, generic ones left out, spaced."""
    words = (fold(word) for word in text.split() if word.casefold() not in generic)
    return f" {' '.join(filter(None, words))} "


def _repeats(universe: str, named: tuple[str, ...]) -> bool:
    """Whether a universe's name, generic words aside, holds or is held by another."""
    words = _words(universe, GENERIC)
    return words.strip() != "" and any(
        other.strip() and (words in other or other in words) for other in named
    )


def _kind(claims: dict[str, list]) -> str:
    """A written work's word: its form (P7937), genre or type, as WRITTEN names it."""
    forms = (*claims.get("P7937", []), *claims.get("P136", []), *claims.get("P31", []))
    return next((WRITTEN[q] for q in forms if q in WRITTEN), "")


def _classes(item: dict[str, Any]) -> list[str]:
    """An item's classes: its instance of (P31) values."""
    return item["claims"].get("P31", [])


def _span(item: dict[str, Any]) -> int:
    """The years a time spans past its first (TIMES); -1 for a named period."""
    return min((TIMES[c] for c in _classes(item) if c in TIMES), default=-1)


def _year(times: list[str]) -> int | None:
    """The first time's year: "+1940-00-00T00:00:00Z" is 1940; None for none."""
    return int(times[0][: times[0].index("-", 1)]) if times else None


def _places(qids: list[str], linked: dict[str, dict]) -> list[str]:
    """
    Where a story is set, in Wikidata's order: not a country (P17) of another place,
    nor a continent, planet or Earth beside somewhere more specific; PLACES at most.
    """
    countries = {c for q in qids for c in linked[q]["claims"].get("P17", []) if c != q}
    places = [q for q in qids if q not in countries and linked[q]["label"]]
    specific = [
        q for q in places if q not in BROAD and BROAD.isdisjoint(_classes(linked[q]))
    ]
    return [linked[q]["label"] for q in specific or places][:PLACES]


def _period(qids: list[str], linked: dict[str, dict]) -> list:
    """
    When a story is set: a named period first (World War II), else the finest time,
    a year, then a decade, then a century; [label, first year, last year] or [].
    """
    if not (named := [linked[q] for q in qids if linked[q]["label"]]):
        return []
    period = min(named, key=_span)
    claims = period["claims"]
    start = _year(claims.get("P580") or claims.get("P585", []))
    end = _year(claims.get("P582", [])) or start and start + max(_span(period), 0)
    return [period["label"], start, end]


def _subjects(qids: list[str], linked: dict[str, dict]) -> list[str]:
    """What a story is about, in Wikidata's order: no time (1970s) and no taxon."""
    unwanted = TAXA | TIMES.keys()
    return [
        linked[q]["label"]
        for q in qids
        if linked[q]["label"] and unwanted.isdisjoint(_classes(linked[q]))
    ]


def _item(ask: Callable, prop: str, value: str) -> tuple[str, dict] | None:
    """The first item with a statement of a value, and its statements; None for none."""
    if not (found := ask(wikidata.having, prop, value)):
        return None
    qid = found[0]
    return qid, ask(wikidata.items, [qid])[qid]["claims"]


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
    composers, sources, periods = (claims.get(p, []) for p in ("P86", "P144", "P2408"))
    places, subjects = (claims.get(p, [])[:LOOKED] for p in ("P840", "P921"))
    universes = (claims.get("P1434") or claims.get("P8345", []))[:1]
    creators = claims.get("P170", []) if kind == "tvshow" else []  # only shows serve
    albums = _once(claims.get("P406", []), ask(wikidata.having, "P9899", qid))
    story = [*places, *periods, *subjects]  # their classes, countries and times
    linked = ask(wikidata.items, [*composers, *sources, *albums, *story])
    source = next(
        (
            linked[q]
            for q in sources
            if WRITTEN.keys() & set(linked[q]["claims"].get("P31", []))
        ),
        None,
    )
    authors = source["claims"].get("P50", []) if source else []
    names = ask(wikidata.labels, [*authors, *creators, *universes])
    return {
        "music_by": [*filter(None, (linked[q]["label"] for q in composers))],
        "created_by": [*filter(None, map(names.get, creators))],
        "composers": [
            mbid for q in composers for mbid in linked[q]["claims"].get("P434", [])
        ],
        "source": source
        and {
            "title": source["label"],
            "type": _kind(source["claims"]),
            "authors": [*filter(None, map(names.get, authors))],
        },
        "places": _places(places, linked),
        "period": _period(periods, linked),
        "about": _subjects(subjects, linked),
        "universe": next(filter(None, map(names.get, universes)), ""),
        "soundtracks": [
            group for q in albums for group in linked[q]["claims"].get("P436", [])
        ],
    }


def _artist(ask: Callable, mbid: str) -> dict[str, Any]:
    """
    An artist's details: its labels and instruments (NAMES named, an instrument
    capitalised), where it formed or was born.
    """
    if not (found := _item(ask, "P434", mbid)):
        return {}
    claims = found[1]
    signed, played = claims.get("P264", []), claims.get("P1303", [])
    # A group's formation, else a person's birth
    place = (claims.get("P740") or claims.get("P19") or [""])[0]
    names = ask(
        wikidata.labels, [*signed[:NAMES], *filter(None, [place]), *played[:NAMES]]
    )
    shown = [*filter(None, map(names.get, signed[:NAMES]))]  # an unlabelled one counts
    instruments = [n[:1].upper() + n[1:] for q in played[:NAMES] if (n := names[q])]
    return {
        "labels": shown,
        "more": len(signed) - len(shown),
        "place": names.get(place, ""),
        "instruments": instruments,
        "instruments_more": len(played) - len(instruments),
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


def _answer(live: Callable[[], bool], call: Callable, *args: Any) -> Any:
    """
    A request's answer, while the look-up is live, waiting out a busy queue (which
    cached skips: the look-up runs aside), and asked once more after a 429's short
    hold (which cached waits out); raises _Unanswered otherwise.
    """
    tries = 2
    while tries and live():
        last = hold(wikidata.NEXT_CALL)
        if (answer := call(*args)) is not None:
            return answer
        if busy(wikidata.NEXT_CALL):
            if Monitor().waitForAbort(1):
                break
        elif hold(wikidata.NEXT_CALL) != last:  # a 429 held the queue meanwhile
            tries -= 1
        else:  # refused, failed or timed out: not asked again
            break
    raise _Unanswered


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
        found = LOOK_UPS[key[0]](partial(_answer, live), *key[1:])
    except _Unanswered:
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
