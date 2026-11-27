# author: realcopacetic

"""
Wikidata, keyless: a painter by name, its works and a painting's fields by SPARQL,
an artist's page and rails, and English Wikipedia summaries; items by an external id
and their entity data from the wiki's own API, which answered while the query service
was throttled (25 Nov 2026). Every request waits its turn in one queue, a second
apart; a 429's Retry-After holds the queue.
"""

import re
from typing import Any, Callable
from urllib.parse import quote

from resources.lib.apis import http
from resources.lib.apis.cache import DAY, cached
from resources.lib.apis.http import HttpError
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import fold

SPARQL = "https://query.wikidata.org/sparql"
API = "https://www.wikidata.org/w/api.php"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
NEXT_CALL = "copacetic.wikidata_next"  # home property: epoch of the next free slot
TTL_HIT, TTL_EMPTY = 30 * DAY, 7 * DAY
TIMEOUT = 15  # seconds: a longer request would hold Kodi's exit, which waits for it
API_TIMEOUT = 6  # the wiki's API answers in well under a second: Kodi's exit waits less
ENTITY = "http://www.wikidata.org/entity/"
PAINTER = "Q1028181"  # occupation (P106) the artist search asks for
PAINTING = "Q3305213"  # instance of (P31) an artist's paintings count
SURFACE = f"{ENTITY}Q861259"  # painting surface, a material's applies-to-part (P518)
# Labels and aliases scored against a file's title: the languages paintings are
# named in, Norwegian under both its codes
LANGUAGES = ", ".join(
    f'"{code}"' for code in ("en", "de", "fr", "es", "it", "ru", "ja", "nl", "no", "nb")
)
SEPARATOR = "\t"  # between a work's labels in one answer row: never in a label
_ITEMS = ("material", "genre", "collection", "depicts")  # kinds whose values are items
# An artist's kinds whose values are items, kept as [qid, English label]: the page's,
# then its Biography line's and band's (memberships, notable works, genres, work places)
_PEOPLE = (
    "birthplace",
    "deathplace",
    "occupation",
    "teacher",
    "movement",
    "influence",
    "member",
    "notable",
    "genre",
    "workplace",
)
# Kept as [ISO time, precision, calendar]: 9 a year, 10 a month, 11 a day; the
# calendar's Q-id (an answer kept before calendars has none: Gregorian)
_DATES = ("born", "died")
JULIAN = "Q1985786"  # the calendar model of a date entered as Julian

# The first painter a search finds (srlimit doesn't limit the answer: the ordinal does)
_SEARCH = """SELECT ?artist ?artistLabel WHERE {
  SERVICE wikibase:mwapi {
    bd:serviceParam wikibase:api "Search"; wikibase:endpoint "www.wikidata.org";
      mwapi:srsearch "%s haswbstatement:P106=%s"; mwapi:srlimit "1" .
    ?artist wikibase:apiOutputItem mwapi:title .
    ?ordinal wikibase:apiOrdinal true .
  }
  OPTIONAL { ?artist rdfs:label ?artistLabel FILTER(LANG(?artistLabel) = "en") }
} ORDER BY ?ordinal LIMIT 1"""

# A painter's works, one row each: sitelinks, every label and alias, each inception
# year. The painter is bound: joined to the search in one query, the query service
# read every work of every artist first (504 after 65 s for Van Gogh; bound, 0.9 s)
_WORKS = """SELECT ?work ?links
  (GROUP_CONCAT(DISTINCT ?label; separator="\\t") AS ?labels)
  (GROUP_CONCAT(DISTINCT ?year; separator=" ") AS ?years) WHERE {
  VALUES ?artist { wd:%s }
  ?work wdt:P170 ?artist; wikibase:sitelinks ?links .
  { ?work rdfs:label ?label } UNION { ?work skos:altLabel ?label }
  FILTER(LANG(?label) IN (%s))
  OPTIONAL { ?work wdt:P571 ?date BIND(YEAR(?date) AS ?year) }
} GROUP BY ?work ?links"""

# One painting's fields, a row per value: its kind, the value, its English label and,
# for a material, the part it makes. Best-rank statements; a collection left is ended
_PAINTING = """SELECT ?kind ?value ?valueLabel ?part WHERE {
  VALUES ?work { wd:%s }
  { ?work rdfs:label ?value FILTER(LANG(?value) = "en") BIND("title" AS ?kind) }
  UNION { ?work wdt:P571 ?value BIND("inception" AS ?kind) }
  UNION { ?work p:P186 ?s . ?s a wikibase:BestRank; ps:P186 ?value .
    OPTIONAL { ?s pq:P518 ?part } BIND("material" AS ?kind) }
  UNION { ?work wdt:P136 ?value BIND("genre" AS ?kind) }
  UNION { ?work p:P195 ?s . ?s a wikibase:BestRank; ps:P195 ?value .
    FILTER NOT EXISTS { ?s pq:P582 ?end } BIND("collection" AS ?kind) }
  UNION { ?work p:P2048 ?s . ?s a wikibase:BestRank;
    psn:P2048/wikibase:quantityAmount ?value BIND("height" AS ?kind) }
  UNION { ?work p:P2049 ?s . ?s a wikibase:BestRank;
    psn:P2049/wikibase:quantityAmount ?value BIND("width" AS ?kind) }
  UNION { ?work wdt:P180 ?value BIND("depicts" AS ?kind) }
  UNION { ?article schema:about ?work; schema:isPartOf <https://en.wikipedia.org/>;
    schema:name ?value BIND("enwiki" AS ?kind) }
  OPTIONAL { ?value rdfs:label ?valueLabel FILTER(LANG(?valueLabel) = "en") }
}"""

# An artist's page, a row per value as a painting's: dates with their precision and
# calendar, the nationality as its countries' English demonyms, each with its country
# and the citizenship's start year (0 for none), and its paintings counted
_ARTIST = """SELECT ?kind ?value ?valueLabel ?precision ?calendar ?country ?since
WHERE {
  VALUES ?artist { wd:%(qid)s }
  { ?artist rdfs:label ?value FILTER(LANG(?value) = "en") BIND("name" AS ?kind) }
  UNION { ?artist p:P569 ?s . ?s a wikibase:BestRank; psv:P569 ?v .
    ?v wikibase:timeValue ?value; wikibase:timePrecision ?precision;
      wikibase:timeCalendarModel ?calendar BIND("born" AS ?kind) }
  UNION { ?artist p:P570 ?s . ?s a wikibase:BestRank; psv:P570 ?v .
    ?v wikibase:timeValue ?value; wikibase:timePrecision ?precision;
      wikibase:timeCalendarModel ?calendar BIND("died" AS ?kind) }
  UNION { ?artist wdt:P19 ?value BIND("birthplace" AS ?kind) }
  UNION { ?artist wdt:P20 ?value BIND("deathplace" AS ?kind) }
  UNION { ?artist wdt:P106 ?value BIND("occupation" AS ?kind) }
  UNION { ?artist wdt:P1066 ?value BIND("teacher" AS ?kind) }
  UNION { ?artist wdt:P135 ?value BIND("movement" AS ?kind) }
  UNION { ?artist p:P27 ?s . ?s a wikibase:BestRank; ps:P27 ?country .
    OPTIONAL { ?s pq:P580 ?start }
    ?country wdt:P1549 ?value FILTER(LANG(?value) = "en")
    BIND(COALESCE(YEAR(?start), 0) AS ?since) BIND("nationality" AS ?kind) }
  UNION { ?artist wdt:P737 ?value BIND("influence" AS ?kind) }
  UNION { ?artist wdt:P463 ?value BIND("member" AS ?kind) }
  UNION { ?artist wdt:P800 ?value BIND("notable" AS ?kind) }
  UNION { ?artist wdt:P136 ?value BIND("genre" AS ?kind) }
  UNION { ?artist wdt:P937 ?value BIND("workplace" AS ?kind) }
  UNION { ?artist wdt:P18 ?value BIND("portrait" AS ?kind) }
  UNION { SELECT ("paintings" AS ?kind) (COUNT(DISTINCT ?work) AS ?value) WHERE {
    ?work wdt:P170 wd:%(qid)s; wdt:P31 wd:%(painting)s } }
  UNION { ?article schema:about ?artist; schema:isPartOf <https://en.wikipedia.org/>;
    schema:name ?value BIND("enwiki" AS ?kind) }
  OPTIONAL { ?value rdfs:label ?valueLabel FILTER(LANG(?valueLabel) = "en") }
}"""

# An artist's rails, each row an item with a picture (P18): its English label, the
# picture's Commons URL and, for a work, its first inception year. An artist must have
# an English label, as selecting one opens its page; a work may be art only
RAILS = {
    # Its works: the notable ones (the artist's P800) first, then by sitelinks
    "gallery": """SELECT ?item ?links ?notable (SAMPLE(?name) AS ?label)
  (SAMPLE(?picture) AS ?image) (MIN(?made) AS ?year) WHERE {
  VALUES ?artist { wd:%(qid)s }
  ?item wdt:P170 ?artist; wdt:P18 ?picture; wikibase:sitelinks ?links .
  BIND(EXISTS { ?artist wdt:P800 ?item } AS ?notable)
  OPTIONAL { ?item rdfs:label ?name FILTER(LANG(?name) = "en") }
  OPTIONAL { ?item wdt:P571 ?date BIND(YEAR(?date) AS ?made) }
} GROUP BY ?item ?links ?notable ORDER BY DESC(?notable) DESC(?links) LIMIT 30""",
    # Painters of its movements born within YEARS of it, the CANDIDATES best known,
    # with PAINTINGS or more on Wikidata: an occupation and a painting let in a writer
    # who also painted (E. T. A. Hoffmann, fifth on Turner's rail). In the order
    # written: counted for every member of Romanticism, the query ran out (504, 65 s)
    "similar": """SELECT ?item ?links (SAMPLE(?name) AS ?label)
  (SAMPLE(?picture) AS ?image) WHERE {
  hint:Query hint:optimizer "None" .
  { SELECT DISTINCT ?item ?links WHERE {
    VALUES ?artist { wd:%(qid)s }
    ?artist wdt:P135 ?movement; wdt:P569 ?birth .
    ?item wdt:P135 ?movement; wdt:P106 wd:%(painter)s; wdt:P569 ?born;
      wikibase:sitelinks ?links .
    FILTER(?item != ?artist && ABS(YEAR(?born) - YEAR(?birth)) <= %(years)s)
  } ORDER BY DESC(?links) LIMIT %(candidates)s }
  ?item wdt:P18 ?picture; rdfs:label ?name FILTER(LANG(?name) = "en")
  ?work wdt:P170 ?item; wdt:P31 wd:%(painting)s .
} GROUP BY ?item ?links HAVING(COUNT(DISTINCT ?work) >= %(paintings)s)
ORDER BY DESC(?links) LIMIT 30""",
    # Those it influenced: their own influenced by (P737) names it
    "influenced": """SELECT ?item ?links (SAMPLE(?name) AS ?label)
  (SAMPLE(?picture) AS ?image) WHERE {
  VALUES ?artist { wd:%(qid)s }
  ?item wdt:P737 ?artist; wdt:P18 ?picture; wikibase:sitelinks ?links .
  ?item rdfs:label ?name FILTER(LANG(?name) = "en")
} GROUP BY ?item ?links ORDER BY DESC(?links) LIMIT 30""",
}
HITS = 10  # items a statement search keeps, best first
BATCH = 50  # the most ids wbgetentities answers in one request
# The statements an item is kept with: the details' (wikidata_details.py) and the
# external ids that lead back to the library
CLAIMS = frozenset(
    "P19 P31 P50 P86 P136 P144 P162 P166 P170 P264 P345 P406 P434 P436 P463 P527 "
    "P737 P740 P840 P921 P1303 P1434 P2408 P4947 P4983 P7937 P8345 P9899".split()
)
YEARS = 35  # the most a similar painter's birth year is from the artist's
PAINTINGS = 5  # the fewest paintings a similar painter has on Wikidata
CANDIDATES = 60  # similar painters' paintings counted, the most sitelinks first


def sparql(query: str) -> list[dict[str, dict[str, str]]]:
    """
    Run a query on the Wikidata query service.

    :param query: SPARQL text.
    :return: The answer's bindings, one dict per row.
    :raises HttpError: On an HTTP error status, no connection or bad JSON.
    """
    answer = http.get_json(
        SPARQL,
        {"query": query, "format": "json"},
        headers={"Accept": "application/sparql-results+json"},
        timeout=TIMEOUT,
    )
    return answer["results"]["bindings"]


def _literal(text: str) -> str:
    """Text safe inside a SPARQL string literal: no quote or backslash ends it."""
    return re.sub(r'["\\]', " ", text)


def _qid(uri: str) -> str:
    """An entity URI's Q-id; "" for anything else (an unknown value's blank node)."""
    return uri.removeprefix(ENTITY) if uri.startswith(f"{ENTITY}Q") else ""


def works(artist: str, live: Callable[[], bool]) -> dict[str, Any] | None:
    """
    A painter's works, by the name a file gives: the search's best painter, else
    one found fuzzily, word by word ("Kandinksy~"); each a request of its own. Each
    work is [qid, sitelinks, inception years, labels and aliases].

    :param artist: Artist name.
    :param live: Tested before each request; False stops, with no answer.
    :return: The painter's qid and label, and works; {} for none; None if not asked.
    """
    if not live():
        return None
    painter = _painter(f"wikidata:artist:{fold(artist)}", artist)
    if painter == {}:
        if not live():
            return None
        fuzzy = " ".join(f"{word}~" for word in artist.split())
        painter = _painter(f"wikidata:fuzzy:{fold(artist)}", fuzzy)
    if not painter:  # {}: none; None: not asked
        return painter
    if not live() or (found := _works(painter["qid"])) is None:
        return None
    return painter | {"works": found} if found else {}


def _painter(key: str, search: str) -> dict[str, str] | None:
    """
    The first painter a search finds; cached and queued.

    :param key: api_cache key.
    :param search: CirrusSearch text.
    :return: Its qid and English label; {} for none; None if not asked.
    """

    def fetch() -> dict[str, str]:
        if not (rows := sparql(_SEARCH % (_literal(search), PAINTER))):
            return {}
        return {
            "qid": _qid(rows[0]["artist"]["value"]),
            "label": rows[0].get("artistLabel", {}).get("value", ""),
        }

    return cached(key, fetch, (TTL_HIT, TTL_EMPTY), NEXT_CALL)


def _works(qid: str) -> list[list] | None:
    """
    A painter's works; cached and queued.

    :param qid: The painter's Q-id.
    :return: As works gives them, possibly empty; None if not asked.
    """

    def fetch() -> list[list]:
        return [
            [
                _qid(row["work"]["value"]),
                int(row["links"]["value"]),
                # A work with no inception has no years binding
                [int(y) for y in row.get("years", {}).get("value", "").split()],
                row["labels"]["value"].split(SEPARATOR),
            ]
            for row in sparql(_WORKS % (qid, LANGUAGES))
        ]

    return cached(f"wikidata:works:{qid}", fetch, (TTL_HIT, TTL_EMPTY), NEXT_CALL)


def forget(
    artist: str = "", qid: str = "", article: str = "", painter: str = ""
) -> None:
    """
    Mark a look-up's answers stale, so the next one asks again: an artist's
    searches and its painter's works, a painting, an article's summary, and the
    matched painter's page, its biography and its rails.

    :param artist: The artist's name, as a file gives it.
    :param qid: The painting's Q-id.
    :param article: Its English Wikipedia article's title.
    :param painter: The matched painter's Q-id.
    """
    cache, name = ApiCacheHandler(), fold(artist)
    searches = [f"wikidata:artist:{name}", f"wikidata:fuzzy:{name}"] if name else []
    found = [row[0]["qid"] for key in searches if (row := cache.get(key)) and row[0]]
    page = (kept("painter", painter)[0] or {}) if painter else {}
    articles = [article] * bool(article) + page.get("enwiki", [])
    # Patterns, but folded names, Q-ids and folded titles hold no % or _
    cache.expire(
        *searches,
        *(f"wikidata:works:{searched}" for searched in found),
        *([f"wikidata:painting:{qid}"] if qid else []),
        *(f"wikidata:summary:{fold(title)}" for title in articles),
        *(f"wikidata:{kind}:{painter}" for kind in ("painter", *RAILS) if painter),
    )


def painting(qid: str) -> dict[str, Any] | None:
    """
    One painting's standard fields: title, inception years, materials, genres,
    current collections (None for an unknown one), height and width, depicts, article.
    An item with no English label, and an unknown value elsewhere, is left out.

    :param qid: The painting's Q-id.
    :return: Lists of values by kind (sizes in metres); None if not asked.
    """

    def fetch() -> dict[str, Any]:
        fields = {}
        for row in sparql(_PAINTING % qid):
            kind, value = row["kind"]["value"], row["value"]
            label = row.get("valueLabel", {}).get("value", "")
            if kind in _ITEMS:
                if _qid(value["value"]):
                    value = label
                elif kind == "collection":  # unknown: privately owned
                    value = None
                else:
                    continue
                if value == "":  # a known item with no English label
                    continue
                if kind == "material":
                    value = [value, row.get("part", {}).get("value") == SURFACE]
            elif value["type"] != "literal":  # an unknown date or size: a node
                continue
            elif kind == "inception":
                value = int(re.match(r"-?\d+", value["value"])[0])
            elif kind in ("height", "width"):
                value = float(value["value"])
            else:
                value = value["value"]
            fields.setdefault(kind, []).append(value)
        return fields

    return cached(f"wikidata:painting:{qid}", fetch, (TTL_HIT, TTL_EMPTY), NEXT_CALL)


def artist(qid: str) -> dict[str, list] | None:
    """
    An artist's page: name, birth and death, occupations, teachers, movements,
    nationality, influences, memberships, notable works, genres, work places,
    portrait, paintings, article. An unlabelled item or unknown value is left out.

    :param qid: The artist's Q-id.
    :return: Lists of values by kind; None if not asked.
    """

    def fetch() -> dict[str, list]:
        fields = {}
        query = _ARTIST % {"qid": qid, "painting": PAINTING}
        for row in sparql(query):
            kind, value = row["kind"]["value"], row["value"]["value"]
            if kind in _PEOPLE:
                if not (label := row.get("valueLabel", {}).get("value")):
                    continue
                value = [_qid(value), label]
            elif kind in _DATES:
                calendar = _qid(row["calendar"]["value"])
                value = [value, int(row["precision"]["value"]), calendar]
            elif kind == "nationality":
                country = _qid(row["country"]["value"])
                value = [country, int(row["since"]["value"]), value]
            elif kind == "paintings":
                value = int(value)
            fields.setdefault(kind, []).append(value)
        return fields

    return cached(f"wikidata:painter:{qid}", fetch, (TTL_HIT, TTL_EMPTY), NEXT_CALL)


def rail(kind: str, qid: str) -> list[list] | None:
    """
    An artist's rail, ranked: its works (gallery), painters like it (similar), or
    those it influenced (influenced); each [qid, English label, picture, year].

    :param kind: gallery, similar or influenced.
    :param qid: The artist's Q-id.
    :return: Its items, possibly none; None if not asked.
    """

    def fetch() -> list[list]:
        query = RAILS[kind] % {
            "candidates": CANDIDATES,
            "qid": qid,
            "painter": PAINTER,
            "painting": PAINTING,
            "paintings": PAINTINGS,
            "years": YEARS,
        }
        return [
            [
                _qid(row["item"]["value"]),
                row.get("label", {}).get("value", ""),
                row["image"]["value"],
                row.get("year", {}).get("value", ""),
            ]
            for row in sparql(query)
        ]

    return cached(f"wikidata:{kind}:{qid}", fetch, (TTL_HIT, TTL_EMPTY), NEXT_CALL)


def kept(kind: str, key: str) -> tuple[Any, bool]:
    """
    An answer as kept, whatever its age, and whether it is fresh: for a served call,
    which never waits on a request.

    :param kind: painter, summary, or a rail's kind.
    :param key: The Q-id, or a summary's article title.
    :return: (answer, fresh); (None, False) for none; a failed request's is fresh.
    """
    key = fold(key) if kind == "summary" else key
    return ApiCacheHandler().get(f"wikidata:{kind}:{key}") or (None, False)


def summary(title: str) -> str | None:
    """
    An English Wikipedia article's summary: its first paragraph, as plain text.

    :param title: The article's title, as Wikidata's sitelink names it.
    :return: The summary; "" for no article; None if not asked.
    """

    def fetch() -> str:
        try:
            page = http.get_json(f"{SUMMARY}{quote(title.replace(' ', '_'), '')}")
        except HttpError as exc:
            if exc.status == 404:  # renamed or deleted since Wikidata linked it
                return ""
            raise
        # One space between words: the extract keeps a dropped aside's ("Kanagawa  is")
        return " ".join(page.get("extract", "").split())

    return cached(
        f"wikidata:summary:{fold(title)}", fetch, (TTL_HIT, TTL_EMPTY), NEXT_CALL
    )


def having(prop: str, value: str) -> list[str] | None:
    """
    The items with a statement of a value, by the wiki's search (haswbstatement):
    a film by its TMDb id, an artist by its MusicBrainz id. Cached and queued.

    :param prop: The property, e.g. P4947.
    :param value: Its value: an external id or a Q-id, with no space.
    :return: Their Q-ids, best first, possibly none; None if not asked.
    """

    def fetch() -> list[str]:
        answer = http.get_json(
            API,
            {
                "action": "query",
                "list": "search",
                "srsearch": f"haswbstatement:{prop}={value}",
                "srlimit": HITS,
                "srprop": "",
                "format": "json",
            },
            timeout=API_TIMEOUT,
        )
        return [hit["title"] for hit in answer["query"]["search"]]

    key = f"wikidata:having:{prop}={value}"
    return cached(key, fetch, (TTL_HIT, TTL_EMPTY), NEXT_CALL)


def items(qids: list[str]) -> dict[str, dict] | None:
    """
    Items' English or multilingual labels and the CLAIMS statements' best-rank values
    (a Q-id or a string), by wbgetentities. Kept per item, cached and queued.

    :param qids: Q-ids; none asks nothing.
    :return: Each one's {"label", "claims"}, empty for a missing item; None if not asked.
    """
    return _entities("items", qids, {"props": "labels|claims", "languages": "en|mul"})


def labels(qids: list[str]) -> dict[str, str] | None:
    """
    Items' labels alone (a city's statements run to megabytes), as items reads them,
    else in any language: Paris may have only its French one.

    :param qids: Q-ids; none asks nothing.
    :return: Each one's label, "" for none; None if not asked.
    """
    found = _entities("labels", qids, {"props": "labels"})
    return found and {qid: item["label"] for qid, item in found.items()}


def _entities(
    kind: str, qids: list[str], params: dict[str, str]
) -> dict[str, dict] | None:
    """
    wbgetentities' answers, shaped as items gives them: each item kept on its own (a
    composer once across films), the stale ones asked BATCH a request.

    :param kind: items or labels, the cache keys' kind.
    :param qids: Q-ids, each asked once.
    :param params: Its props parameter, and languages to limit the labels to.
    :return: Each one's {"label", "claims"}; None if one is not asked.
    """
    cache = ApiCacheHandler()
    keys = {qid: f"wikidata:{kind}:{qid}" for qid in qids}
    rows = {qid: cache.get(key) or (None, False) for qid, key in keys.items()}
    found = {qid: payload for qid, (payload, _) in rows.items()}
    stale = [qid for qid, (_, fresh) in rows.items() if not fresh]
    for start in range(0, len(stale), BATCH):
        found |= _batch(stale[start : start + BATCH], keys, params)
    return None if None in found.values() else found


def _batch(
    qids: list[str], keys: dict[str, str], params: dict[str, str]
) -> dict[str, Any]:
    """
    One request for up to BATCH items, each kept: the first through cached, which
    holds the queue and keeps a failure, the others as the answer comes.

    :param qids: Q-ids, BATCH at most.
    :param keys: Each one's cache key.
    :param params: As _entities takes them.
    :return: Each one's payload as now kept (a stale one on a failure); None for none.
    """
    cache, (first, *others) = ApiCacheHandler(), qids

    def fetch() -> dict[str, Any]:
        answer = http.get_json(
            API,
            {
                "action": "wbgetentities",
                "ids": "|".join(qids),
                **params,
                "format": "json",
            },
            timeout=API_TIMEOUT,
        )
        shaped = {qid: _shape(answer["entities"].get(qid, {})) for qid in qids}
        for qid in others:
            cache.put(keys[qid], shaped[qid], TTL_HIT)
        return shaped[first]

    found = {first: cached(keys[first], fetch, (TTL_HIT, TTL_EMPTY), NEXT_CALL)}
    return found | {qid: (cache.get(keys[qid]) or (None,))[0] for qid in others}


def _shape(item: dict) -> dict[str, Any]:
    """
    An entity as kept: its label (English, else multilingual, else any: Pharrell
    Williams' item had no English one) and its CLAIMS' best-rank values.
    """
    names = item.get("labels", {})
    label = names.get("en") or names.get("mul") or next(iter(names.values()), {})
    claims = {}
    for prop, statements in item.get("claims", {}).items():
        if prop not in CLAIMS:
            continue
        ranked = [s for s in statements if s["rank"] == "preferred"] or [
            s for s in statements if s["rank"] == "normal"
        ]
        values = [
            (
                value["id"]
                if isinstance(value := snak["datavalue"]["value"], dict)
                else value
            )
            for snak in (s["mainsnak"] for s in ranked)
            if "datavalue" in snak  # an unknown or no value has none
        ]
        if values:
            claims[prop] = values
    return {"label": label.get("value", ""), "claims": claims}
