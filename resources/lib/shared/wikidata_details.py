# author: realcopacetic

"""
Wikidata details for library films, TV shows, artists and albums, found by their
TMDb, IMDb and MusicBrainz ids alone (no id, no look-up): a film's composers, the
written work it is based on and where it is set; an artist's labels and place; an
album's producers; the soundtrack albums and films they link. Kept per item.
"""

from functools import partial
from typing import Any, Callable

from resources.lib.apis import wikidata
from resources.lib.apis.cache import Asides
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
# Written works a story is based on, as instance of (P31) or form of creative work
# (P7937) names them, and their word on screen. Novels are mostly a literary work
# with the form novel (Dune, Slow Horses); games, toys, characters and films are out
WRITTEN = {
    "Q8261": "novel",
    "Q149537": "novella",
    "Q49084": "short story",
    "Q5185279": "poem",
    "Q25379": "play",
    "Q7725634": "book",  # literary work
    "Q47461344": "book",  # written work
    "Q571": "book",
    "Q1004": "comic",
    "Q14406742": "comic",  # comic book series
    "Q725377": "graphic novel",
    "Q21198342": "manga",  # manga series
    "Q8274": "manga",
}
NAMES = 2  # an artist's labels named, the rest counted (+N)


class _Unanswered(Exception):
    """A request not answered (busy, refused, failed) or a look-up no longer live."""


def based_on(title: str, source: dict[str, Any]) -> str:
    """
    A story line's source, after "Based on ": "the novel by Mick Herron" for a work
    sharing the item's title, else "Dune, novel by Frank Herbert"; authors by " and ".

    :param title: The item's title.
    :param source: The details' source: title, type and authors.
    :return: The text.
    """
    kind, authors = source["type"], " and ".join(source["authors"])
    same = fold(source["title"]) == fold(title)
    text = f"the {kind}" if same else f"{source['title']}, {kind}"
    return f"{text} by {authors}" if authors else text


def properties(kind: str, found: dict[str, Any], title: str) -> dict[str, str]:
    """
    The details as an item's wikidata_* properties, an empty one left out.

    :param kind: movie, tvshow, artist or album.
    :param found: The kept details; {} for none.
    :param title: The item's title, for the based-on wording.
    :return: The properties.
    """
    if not found:
        return {}
    if kind == "artist":
        values = {
            "labels": named(found["labels"], found["more"]),
            "place": found["place"],
        }
    elif kind == "album":
        values = {"producer": " / ".join(found["producer"])}
    else:
        source = found["source"]
        values = {
            "music_by": " / ".join(found["music_by"]),
            "based_on": source and based_on(title, source),
            "set_in": found["set_in"],
        }
    return {f"wikidata_{key}": value for key, value in values.items() if value}


def _kind(claims: dict[str, list]) -> str:
    """A written work's word: its form (P7937) if WRITTEN names it, else its type."""
    forms = (*claims.get("P7937", []), *claims.get("P31", []))
    return next((WRITTEN[q] for q in forms if q in WRITTEN), "")


def _item(ask: Callable, prop: str, value: str) -> tuple[str, dict] | None:
    """The first item with a statement of a value, and its statements; None for none."""
    if not (found := ask(wikidata.having, prop, value)):
        return None
    qid = found[0]
    return qid, ask(wikidata.items, [qid])[qid]["claims"]


def _once(*qids: list[str]) -> list[str]:
    """Items from both ends of a link, each once: an album often links both ways."""
    return [*dict.fromkeys(qid for group in qids for qid in group)]


def _video(kind: str, ask: Callable, tmdb: str, imdb: str) -> dict[str, Any]:
    """
    A film's or show's details: composers (names and MusicBrainz ids), its first
    written source, where it's set, and its soundtracks' release groups (its P406
    albums', and albums whose P9899 names it).
    """
    found = (tmdb and _item(ask, TMDB[kind], tmdb)) or (
        imdb and _item(ask, "P345", imdb)
    )
    if not found:
        return {}
    qid, claims = found
    composers, sources, places = (claims.get(p, []) for p in ("P86", "P144", "P840"))
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
    names = ask(wikidata.labels, [*authors, *places[:1]])
    return {
        "music_by": [*filter(None, (linked[q]["label"] for q in composers))],
        "composers": [
            mbid for q in composers for mbid in linked[q]["claims"].get("P434", [])
        ],
        "source": source
        and {
            "title": source["label"],
            "type": _kind(source["claims"]),
            "authors": [*filter(None, map(names.get, authors))],
        },
        "set_in": names[places[0]] if places else "",
        "soundtracks": [
            group for q in albums for group in linked[q]["claims"].get("P436", [])
        ],
    }


def _artist(ask: Callable, mbid: str) -> dict[str, Any]:
    """An artist's details: its labels (NAMES named), and where it formed or was born."""
    if not (found := _item(ask, "P434", mbid)):
        return {}
    claims = found[1]
    signed = claims.get("P264", [])
    # A group's formation, else a person's birth
    place = (claims.get("P740") or claims.get("P19") or [""])[0]
    names = ask(wikidata.labels, [*signed[:NAMES], *filter(None, [place])])
    shown = [*filter(None, map(names.get, signed[:NAMES]))]
    return {"labels": shown, "more": len(signed[NAMES:]), "place": names.get(place, "")}


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
    """A request's answer, while the look-up is live; raises _Unanswered otherwise."""
    if not live() or (answer := call(*args)) is None:
        raise _Unanswered
    return answer


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


def linked(key: tuple[str, ...] | None, field: str) -> list:
    """
    One of an item's details as kept, while the setting is on: never asked, as a
    plugin call holds one of Kodi's three directory workers (the served call asks).

    :param key: As kept takes it; None for an item with no id.
    :param field: soundtracks, composers or films.
    :return: Its values; none when off, not kept, or for no item.
    """
    if not (key and wanted()):
        return []
    return (kept(key)[0] or {}).get(field, [])


# Details looked up for served calls, one request at a time as the queue asks; before
# each request the setting is still on and an asker still current
ASIDES = Asides(lambda key, live: details(key, lambda: live() and wanted()))
