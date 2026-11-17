"""
Rewrites SUBGENRES in resources/lib/shared/genres.py, and the fixture genre_offline.py
checks, from MusicBrainz: its genre list (the web service), and for each genre no term
finds, its "subgenre of" genres (each genre's page: the web service gives no genre
relationships). Run by hand from the helper root when MusicBrainz adds genres, or
after a change to EXCEPTIONS or KEYWORDS (an hour or more: MusicBrainz allows a
request a second): python tests/genre_snapshot.py [--cache DIR]. With --cache, each
page is kept in DIR and read from there next time: a rules change needs no fetch.
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from resources.lib.shared import genres  # noqa: E402

SITE = "https://musicbrainz.org"
USER_AGENT = "kodi-genre-buckets/1.0 ( tests/genre_snapshot.py )"
MODULE = ROOT / "resources/lib/shared/genres.py"
FIXTURE = ROOT / "tests/fixtures/genre_buckets.json"
BEGIN, END = (
    "# --- generated: tests/genre_snapshot.py ---\n",
    "# --- end generated ---\n",
)
PARENTS = re.compile(r"<th>subgenre of:</th><td[^>]*>(.*?)</td>")
GENRE_ID = re.compile(r'href="/genre/([0-9a-f-]{36})"')
# What a name can't hold: Kodi's operators (InfoExpression::GetOperator) and its
# param syntax (CUtil::SplitParams), the builder's {tokens}, the tag separator
UNSAFE = re.compile(r'[\[\]!+|,()"\\${}]|^\s|\s$|' + re.escape(genres.TAG_SEPARATOR))
_last = 0.0


def fetch(path: str, cache: Path | None) -> str:
    """
    One MusicBrainz page, a second after the last, retried while it is busy; kept
    in and read from cache when given.

    :param path: Path and query under SITE.
    :param cache: Folder of fetched pages; None to fetch every one.
    :return: Response text.
    """
    global _last
    if cache and (page := cache / hashlib.sha1(path.encode()).hexdigest()).exists():
        return page.read_text()
    request = urllib.request.Request(SITE + path, headers={"User-Agent": USER_AGENT})
    for wait in (1, 2, 5, 10, 30, 60, 120, 300, 600):
        time.sleep(max(0.0, _last + wait - time.monotonic()))
        _last = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                text = response.read().decode()
        except (urllib.error.URLError, ConnectionError) as error:
            print(f"retry {path}: {error}", file=sys.stderr)
            continue
        if cache:
            page.write_text(text)
        return text
    raise SystemExit(f"MusicBrainz kept refusing {path}")


def genre_list(cache: Path | None) -> dict[str, str]:
    """
    MusicBrainz's genres.

    :param cache: Folder of fetched pages (fetch).
    :return: Name by MBID.
    """
    names, offset, count = {}, 0, 1
    while offset < count:
        path = f"/ws/2/genre/all?limit=100&offset={offset}&fmt=json"
        page = json.loads(fetch(path, cache))
        names |= {genre["id"]: genre["name"] for genre in page["genres"]}
        offset, count = offset + 100, page["genre-count"]
    return names


def ruled(name: str) -> tuple[bool, str | None]:
    """
    Whether an EXCEPTIONS or KEYWORDS term is found in a genre's name, and its bucket.

    :param name: Genre name.
    :return: (found, bucket).
    """
    rows = genres.rows()
    return next(
        ((True, b) for b, terms in rows if any(t in name for t in terms)), (False, None)
    )


def inherited(names: dict[str, str], cache: Path | None) -> dict[str, str | None]:
    """
    Each genre no term finds, by its parents' buckets (the first in KEYWORDS order),
    a parent no term finds by its own, each page read once.

    :param names: Name by MBID.
    :param cache: Folder of fetched pages (fetch).
    :return: Bucket (None for none) by name.
    """
    order, parents, buckets = [*genres.KEYWORDS], {}, {}

    def bucket(mbid: str, seen: frozenset = frozenset()) -> str | None:
        found, ruled_bucket = ruled(names[mbid])
        if found:
            return ruled_bucket
        if mbid not in parents:
            cell = PARENTS.search(fetch(f"/genre/{mbid}", cache))
            parents[mbid] = GENRE_ID.findall(cell[1]) if cell else []
        found = {bucket(p, seen | {mbid}) for p in parents[mbid] if p not in seen}
        return next((b for b in order if b in found), None)

    for mbid, name in names.items():
        if not ruled(name)[0]:
            buckets[name] = bucket(mbid)
    if not any(parents.values()):
        raise SystemExit("No genre page named a parent: has its layout changed?")
    return buckets


def write(subgenres: dict[str, str]) -> None:
    """
    Replaces the generated block in MODULE.

    :param subgenres: Bucket by genre name.
    """
    text = MODULE.read_text()
    head, rest = text.split(BEGIN)
    tail = rest.split(END)[1]
    lines = "".join(
        f"    {json.dumps(name, ensure_ascii=False)}: {json.dumps(bucket)},\n"
        for name, bucket in sorted(subgenres.items())
    )
    body = f"# MusicBrainz, {date.today()}\nSUBGENRES: dict[str, str] = {{\n{lines}}}\n"
    MODULE.write_text(head + BEGIN + body + END + tail)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cache", type=Path, help="folder to keep fetched pages in")
    cache = parser.parse_args().cache
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    names = genre_list(cache)
    if unsafe := sorted(n for n in names.values() if UNSAFE.search(n)):
        print(f"left out, as no row can test them: {unsafe}")
    # every genre walks the tree, so a child still inherits through an unsafe parent
    found = {n: b for n, b in inherited(names, cache).items() if n not in unsafe}
    subgenres = {name: bucket for name, bucket in found.items() if bucket}
    # what the module will give every genre, checked before anything is written
    genres.SUBGENRES = subgenres
    genres.genre_bucket.cache_clear()
    table = {name: genres.genre_bucket(name) for name in sorted(names.values())}
    wanted = {name: found.get(name, ruled(name)[1]) for name in table}
    if wrong := sorted(name for name in table if table[name] != wanted[name]):
        raise SystemExit(f"Rows that give a genre another bucket: {wrong}")
    write(subgenres)
    FIXTURE.write_text(json.dumps(table, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(names)} genres; {len(found)} no term finds, {len(subgenres)} filed")


if __name__ == "__main__":
    main()
