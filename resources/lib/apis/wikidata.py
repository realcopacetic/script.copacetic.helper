# author: realcopacetic

"""
Wikidata, keyless: a painter by name, its works and a painting's fields by SPARQL,
and the painting's English Wikipedia summary. Every request waits its turn in one
queue, a second apart; a 429's Retry-After holds the queue.
"""

import re
from typing import Any
from urllib.parse import quote

from resources.lib.apis import http
from resources.lib.apis.cache import DAY, cached
from resources.lib.apis.http import HttpError
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import fold

SPARQL = "https://query.wikidata.org/sparql"
SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary/"
NEXT_CALL = "copacetic.wikidata_next"  # home property: epoch of the next free slot
TTL_HIT, TTL_EMPTY = 30 * DAY, 7 * DAY
TIMEOUT = 15  # seconds: a longer request would hold Kodi's exit, which waits for it
ENTITY = "http://www.wikidata.org/entity/"
PAINTER = "Q1028181"  # occupation (P106) the artist search asks for
SURFACE = f"{ENTITY}Q861259"  # painting surface, a material's applies-to-part (P518)
# Labels and aliases scored against a file's title: the languages paintings are
# named in, Norwegian under both its codes
LANGUAGES = ", ".join(
    f'"{code}"' for code in ("en", "de", "fr", "es", "it", "ru", "ja", "nl", "no", "nb")
)
SEPARATOR = "\t"  # between a work's labels in one answer row: never in a label
_ITEMS = ("material", "genre", "collection", "depicts")  # kinds whose values are items

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


def works(artist: str) -> dict[str, Any] | None:
    """
    A painter's works, by the name a file gives: the search's best painter, else
    one found fuzzily, word by word ("Kandinksy~"); each a request of its own. Each
    work is [qid, sitelinks, inception years, labels and aliases].

    :param artist: Artist name.
    :return: The painter's qid and label, and works; {} for none; None if not asked.
    """
    painter = _painter(f"wikidata:artist:{fold(artist)}", artist)
    if painter == {}:
        fuzzy = " ".join(f"{word}~" for word in artist.split())
        painter = _painter(f"wikidata:fuzzy:{fold(artist)}", fuzzy)
    if not painter:  # {}: none; None: not asked
        return painter
    if (found := _works(painter["qid"])) is None:
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


def forget(artist: str = "", qid: str = "", article: str = "") -> None:
    """
    Mark a look-up's answers stale, so the next one asks again: an artist's
    searches and its painter's works, a painting, an article's summary.

    :param artist: The artist's name, as a file gives it.
    :param qid: The painting's Q-id.
    :param article: Its English Wikipedia article's title.
    """
    cache, name = ApiCacheHandler(), fold(artist)
    searches = [f"wikidata:artist:{name}", f"wikidata:fuzzy:{name}"] if name else []
    painters = [row[0]["qid"] for key in searches if (row := cache.get(key)) and row[0]]
    # Patterns, but folded names, Q-ids and folded titles hold no % or _
    cache.expire(
        *searches,
        *(f"wikidata:works:{painter}" for painter in painters),
        *([f"wikidata:painting:{qid}"] if qid else []),
        *([f"wikidata:summary:{fold(article)}"] if article else []),
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
