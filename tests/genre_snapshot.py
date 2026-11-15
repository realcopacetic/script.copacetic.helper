"""
Rewrites SUBGENRES in resources/lib/shared/genres.py, and the fixture genre_offline.py
checks, from MusicBrainz: its genre list (the web service), and for each genre no term
finds, its "subgenre of" genres (each genre's page: the web service gives no genre
relationships). Run by hand from the helper root when MusicBrainz adds genres, or
after a change to EXCEPTIONS or KEYWORDS (an hour or more: MusicBrainz allows a
request a second): python tests/genre_snapshot.py
"""

import importlib
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
_last = 0.0


def fetch(path: str) -> str:
    """
    One MusicBrainz page, a second after the last, retried while it is busy.

    :param path: Path and query under SITE.
    :return: Response text.
    """
    global _last
    request = urllib.request.Request(SITE + path, headers={"User-Agent": USER_AGENT})
    for wait in (1, 2, 5, 10, 30, 60, 120, 300, 600):
        time.sleep(max(0.0, _last + wait - time.monotonic()))
        _last = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read().decode()
        except (urllib.error.URLError, ConnectionError) as error:
            print(f"retry {path}: {error}", file=sys.stderr)
    raise SystemExit(f"MusicBrainz kept refusing {path}")


def genre_list() -> dict[str, str]:
    """
    MusicBrainz's genres.

    :return: Name by MBID.
    """
    names, offset, count = {}, 0, 1
    while offset < count:
        page = json.loads(fetch(f"/ws/2/genre/all?limit=100&offset={offset}&fmt=json"))
        names |= {genre["id"]: genre["name"] for genre in page["genres"]}
        offset, count = offset + 100, page["genre-count"]
    return names


def ruled(name: str) -> tuple[bool, str | None]:
    """
    Whether an EXCEPTIONS or KEYWORDS term is found in a genre's name, and its bucket.

    :param name: Genre name.
    :return: (found, bucket).
    """
    rows = (*genres.EXCEPTIONS, *genres.KEYWORDS.items())
    return next(
        ((True, b) for b, terms in rows if any(t in name for t in terms)), (False, None)
    )


def inherited(names: dict[str, str]) -> dict[str, str | None]:
    """
    Each genre no term finds, by its parents' buckets (the first in KEYWORDS order),
    a parent no term finds by its own, each page read once.

    :param names: Name by MBID.
    :return: Bucket (None for none) by name.
    """
    order, parents, buckets = [*genres.KEYWORDS], {}, {}

    def bucket(mbid: str, seen: frozenset = frozenset()) -> str | None:
        found, ruled_bucket = ruled(names[mbid])
        if found:
            return ruled_bucket
        if mbid not in parents:
            cell = PARENTS.search(fetch(f"/genre/{mbid}"))
            parents[mbid] = GENRE_ID.findall(cell[1]) if cell else []
            print(f"{len(parents)} {names[mbid]}: {len(parents[mbid])} parents")
        found = {bucket(p, seen | {mbid}) for p in parents[mbid] if p not in seen}
        return next((b for b in order if b in found), None)

    for mbid, name in names.items():
        if not ruled(name)[0]:
            buckets[name] = bucket(mbid)
    if not any(parents.values()):
        raise SystemExit("No genre page named a parent: has its layout changed?")
    return buckets


def subgenres(found: dict[str, str | None]) -> dict[str, str | None]:
    """
    The genres SUBGENRES lists: those with a bucket, and those in none that hold one
    of their names (None: its row, the longer, is tried first).

    :param found: Bucket (None for none) by genre name, from inherited.
    :return: Bucket (None for none) by genre name.
    """
    kept = {name: bucket for name, bucket in found.items() if bucket}
    held = (name for name, bucket in found.items() if not bucket)
    return kept | {name: None for name in held if any(k in name for k in kept)}


def write(table: dict[str, str | None]) -> None:
    """
    Replaces the generated block in MODULE.

    :param table: Bucket (None for none) by genre name.
    """
    text = MODULE.read_text()
    head, rest = text.split(BEGIN)
    tail = rest.split(END)[1]
    lines = "".join(
        f'    "{name}": {json.dumps(bucket) if bucket else None},\n'
        for name, bucket in sorted(table.items())
    )
    body = (
        f"# MusicBrainz, {date.today()}\n"
        f"SUBGENRES: dict[str, str | None] = {{\n{lines}}}\n"
    )
    MODULE.write_text(head + BEGIN + body + END + tail)


def main() -> None:
    names = genre_list()
    print(f"{len(names)} genres")
    found = inherited(names)
    write(subgenres(found))
    importlib.reload(genres)  # what it now gives every genre, as the icon rows would
    table = {name: genres.genre_bucket(name) for name in sorted(names.values())}
    FIXTURE.write_text(json.dumps(table, indent=1, ensure_ascii=False) + "\n")
    wanted = {name: found.get(name, ruled(name)[1]) for name in table}
    if wrong := {name for name in table if table[name] != wanted[name]}:
        raise SystemExit(f"Rows that give another genre's bucket: {sorted(wrong)}")
    print(f"{len(found)} genres no term finds, {sum(map(bool, found.values()))} filed")


if __name__ == "__main__":
    main()
