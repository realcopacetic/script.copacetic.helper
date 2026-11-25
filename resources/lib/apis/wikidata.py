# author: realcopacetic

"""
Wikidata, keyless: a painter's works and one painting's standard fields from the
query service (SPARQL), and the painting's English Wikipedia summary. Every request
waits its turn in one queue, a second apart; a 429's Retry-After holds the queue.
"""

import re
from typing import Any
from urllib.parse import quote

from resources.lib.apis import http
from resources.lib.apis.cache import DAY, cached
from resources.lib.apis.http import HttpError
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

# The first painter a search finds and its works, one row each: sitelinks, every
# label and alias, and each inception year
_WORKS = """SELECT ?artist ?artistLabel ?work ?links
  (GROUP_CONCAT(DISTINCT ?label; separator="\\t") AS ?labels)
  (GROUP_CONCAT(DISTINCT ?year; separator=" ") AS ?years) WHERE {
  { SELECT ?artist WHERE {
    SERVICE wikibase:mwapi {
      bd:serviceParam wikibase:api "Search"; wikibase:endpoint "www.wikidata.org";
        mwapi:srsearch "%s haswbstatement:P106=%s"; mwapi:srlimit "1" .
      ?artist wikibase:apiOutputItem mwapi:title .
    } } }
  ?work wdt:P170 ?artist; wikibase:sitelinks ?links .
  { ?work rdfs:label ?label } UNION { ?work skos:altLabel ?label }
  FILTER(LANG(?label) IN (%s))
  OPTIONAL { ?work wdt:P571 ?date BIND(YEAR(?date) AS ?year) }
  OPTIONAL { ?artist rdfs:label ?artistLabel FILTER(LANG(?artistLabel) = "en") }
} GROUP BY ?artist ?artistLabel ?work ?links"""

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
    one found fuzzily, word by word ("Kandinksy~"), in a request of its own. Each
    work is [qid, sitelinks, inception years, labels and aliases].

    :param artist: Artist name.
    :return: The painter's qid and label, and works; {} for none; None if not asked.
    """
    found = _works(f"wikidata:works:{fold(artist)}", artist)
    if found != {}:  # found, or not asked
        return found
    fuzzy = " ".join(f"{word}~" for word in artist.split())
    return _works(f"wikidata:fuzzy:{fold(artist)}", fuzzy)


def _works(key: str, search: str) -> dict[str, Any] | None:
    """
    The first painter one search finds, and its works; cached and queued.

    :param key: api_cache key.
    :param search: CirrusSearch text.
    :return: As works; {} for no painter; None if not asked.
    """

    def fetch() -> dict[str, Any]:
        if not (rows := sparql(_WORKS % (_literal(search), PAINTER, LANGUAGES))):
            return {}
        return {
            "qid": _qid(rows[0]["artist"]["value"]),
            "label": rows[0].get("artistLabel", {}).get("value", ""),
            "works": [
                [
                    _qid(row["work"]["value"]),
                    int(row["links"]["value"]),
                    # A work with no inception has no years binding
                    [int(y) for y in row.get("years", {}).get("value", "").split()],
                    row["labels"]["value"].split(SEPARATOR),
                ]
                for row in rows
            ],
        }

    return cached(key, fetch, (TTL_HIT, TTL_EMPTY), NEXT_CALL)


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
        return page.get("extract", "")

    return cached(
        f"wikidata:summary:{fold(title)}", fetch, (TTL_HIT, TTL_EMPTY), NEXT_CALL
    )
