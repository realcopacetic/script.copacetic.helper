# author: realcopacetic

import random
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Sequence
from datetime import date
from math import ceil
from operator import itemgetter

from resources.lib.shared import logger as log
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import json_call

MIX_SIZE = 50
# A mix's share by its seed's artists, as radios lean 12–36 % on theirs (coding-notes
# audits/2026-11-12-music-popularity.md); Ash, 12 Nov
SEED_SHARE = {"song": 0.25, "album": 0.35, "artist": 0.35}
SIMILAR_CAP = 6  # most songs of a mix by any one similar artist
DAILY_ARTIST_SHARE = 0.3  # a daily mix leans harder on the artists it is named for
DAILY_MIXES = 6
DAILY_SEEDS = 3  # lead artists a genre needs to make a daily mix
DAILY_WINDOW = "30"  # days of plays the daily mixes read
DAILY_TTL = 2 * 86400  # past the day its key is dated, so a late read still hits
MIXES_WANTED = "daily_mixes_wanted"  # set by a Daily mixes read: the service's go
RANDOM = {"method": "random"}
MOST_PLAYED = {"method": "playcount", "order": "descending"}
UNPLAYED = {"field": "playcount", "operator": "is", "value": "0"}


def random_songs(
    query_filter: dict, limit: int | None = None, sort: dict = RANDOM
) -> list[dict]:
    """
    Fetches songs in random order unless sort says otherwise, with their files,
    artists and genres.

    :param query_filter: AudioLibrary.GetSongs filter.
    :param limit: Maximum number of songs; None for all.
    :param sort: JSON-RPC sort.
    :return: Song dicts with songid, file, artist and genre.
    """
    return json_call(
        "AudioLibrary.GetSongs",
        properties=["file", "artist", "genre"],
        sort=sort,
        limit=limit,
        query_filter=query_filter,
        parent="music",
    )["result"].get("songs", [])


def artist_genres(artists: list[str]) -> list[str]:
    """
    The genres of these artists' library songs, for a seed song with none.

    :param artists: Artist names.
    :return: Genre names, first seen first.
    """
    songs = json_call(
        "AudioLibrary.GetSongs",
        properties=["genre"],
        query_filter={"field": "artist", "operator": "is", "value": artists},
        parent="mix",
    )["result"].get("songs", [])
    return [*dict.fromkeys(g for song in songs for g in song["genre"])]


def spread(own: list, others: list) -> list:
    """
    Spreads own evenly through others, keeping the order of each.

    :param own: Items to spread.
    :param others: Items to spread them through.
    :return: Merged list.
    """
    step = (len(others) + 1) / (len(own) + 1)
    keyed = [*enumerate(others), *((n * step - 0.5, s) for n, s in enumerate(own, 1))]
    return [s for _, s in sorted(keyed, key=itemgetter(0))]


def mix_songs(
    artists: list[str],
    genres: list[str],
    size: int,
    exclude: Collection[int] = (),
    share: float = SEED_SHARE["song"],
    similar: Sequence[str] = (),
    played: str = "",
) -> list[dict]:
    """
    Random songs for a mix: about share by artists (at least one), spread through songs
    by similar artists, SIMILAR_CAP each, then of genres by others. With played (daily),
    half the artists' are most played lately, the rest unplayed; similar artists' keep to genres.

    :param artists: Artist names the mix leans on.
    :param genres: Genre names for what similar artists don't fill.
    :param size: Most songs; what the others leave short is topped up by artists.
    :param exclude: Song ids to leave out: a seed, a queue's songs.
    :param share: Fraction of the songs by artists.
    :param similar: Library artist names like artists.
    :param played: Days of plays the artists' songs lean on; empty for random.
    :return: Song dicts with songid, file, artist and genre.
    """
    exclude = {*exclude}

    def pick(
        query_filter: dict, count: int, cap: int = 0, sort: dict = RANDOM
    ) -> list[dict]:
        if count <= 0:  # a limit of 0 would fetch every song
            return []
        # Over-fetch by the exclusions, as many of them may come up; thrice for a cap
        limit = count * (3 if cap else 1) + len(exclude)
        songs = random_songs(query_filter, limit, sort)
        per_artist = Counter()
        picked = []
        for song in songs:
            if (
                song["songid"] in exclude
                or cap
                and per_artist[song["artist"][0]] >= cap
            ):
                continue
            per_artist[song["artist"][0]] += 1
            picked.append(song)
            if len(picked) == count:
                break
        exclude.update(song["songid"] for song in picked)
        return picked

    by_artist = {"field": "artist", "operator": "is", "value": artists}
    want = max(1, round(size * share))
    own = []
    if played:  # familiar then new, as Spotify's daily mixes; each artist a fair share
        lately = {"field": "lastplayed", "operator": "inthelast", "value": played}
        familiar = want // 2
        cap = ceil(familiar / len(artists))
        own = pick({"and": [by_artist, lately]}, familiar, cap, MOST_PLAYED)
        new = want - len(own)
        own += pick({"and": [by_artist, UNPLAYED]}, new, ceil(new / len(artists)))
    own += pick(by_artist, want - len(own))
    rest = size - len(own)
    genre_rule = {"field": "genre", "operator": "is", "value": genres}
    theirs = {**by_artist, "value": [*similar]}
    if played:  # a daily mix: its similar artists' songs in its genre too
        theirs = {"and": [theirs, genre_rule]}
    others = pick(theirs, rest, SIMILAR_CAP) if similar else []
    if genres:
        not_theirs = {**by_artist, "operator": "isnot", "value": [*artists, *similar]}
        others += pick({"and": [genre_rule, not_theirs]}, rest - len(others))
    if len(own) == want:  # else the artists have no more
        own += pick(by_artist, rest - len(others))
    return spread(own, random.sample(others, len(others)))


def _day_key() -> str:
    """
    Today's api_cache key; v2, as a day kept before mixes carried similar lacks it.

    :return: Key.
    """
    return f"library:daily_mixes:v2:{date.today()}"


def todays_mixes() -> list[dict]:
    """
    Today's mixes as the service kept them (keep_todays_mixes); until then its leads
    alone, worked out now with no network and not kept. Empty until there are plays.

    :return: Mix dicts: genreid, genre, artistids and artists (leads) and similar.
    """
    if hit := ApiCacheHandler().get(_day_key()):
        return hit[0]
    return _leading_genres()


def keep_todays_mixes(alive: Callable[[], bool]) -> bool | None:
    """
    Keeps today's mixes (those kept already, else today's leads) with their similar
    artists in their genre as answered now, a lookup per distinct lead, so a second
    pass fills only what the first missed. Stops unsaved once alive turns False.

    :param alive: Whether to go on; the service's abort.
    :return: Whether the kept mixes changed; None when none are (no plays, an abort).
    """
    from resources.lib.plugin.music import artist_names, fused, similar_artists

    store, key = ApiCacheHandler(), _day_key()
    kept = (store.get(key) or (None,))[0]
    if not (mixes := kept or _leading_genres()):
        return None
    owned, like, unread = artist_names("daily_mixes"), {}, set()
    for artistid in dict.fromkeys(a for mix in mixes for a in mix["artistids"]):
        if not alive():
            return None
        try:
            like[artistid] = similar_artists(artistid, "daily_mixes", owned)
        except KeyError:  # no details: gone from the library, or it failed to open
            log.debug(f"keep_todays_mixes → no details for artist {artistid}")
            like[artistid] = []
            unread.add(artistid)
    if not alive():
        return None
    fresh = []
    for mix in mixes:
        if kept and not unread.isdisjoint(mix["artistids"]):
            fresh.append(mix)  # mixes are kept's: a library hiccup keeps what it had
            continue
        scores = fused((1, like[artistid]) for artistid in mix["artistids"])
        similar = [a for a, _ in scores.most_common() if a not in mix["artists"]]
        fresh.append(mix | {"similar": similar and _in_genre(similar, mix["genre"])})
    if fresh == kept:
        return False
    store.put(key, fresh, DAILY_TTL)
    return True


def _in_genre(artists: list[str], genre: str) -> list[str]:
    """
    The library artists of these with songs in genre (theirs or on their albums), in
    order: a daily mix's similar artists, so its card and songs keep to its genre.

    :param artists: Library artist names.
    :param genre: Genre name.
    :return: Those of artists in genre.
    """
    rules = [
        {"field": "genre", "operator": "is", "value": genre},
        {"field": "artist", "operator": "is", "value": artists},
    ]
    rows = json_call(
        "AudioLibrary.GetArtists",
        query_filter={"and": rules},
        params={"albumartistsonly": False},
        parent="daily_mixes",
    )["result"].get("artists", [])
    found = {row["artist"] for row in rows}
    return [artist for artist in artists if artist in found]


def _leading_genres() -> list[dict]:
    """
    The genres of the songs played lately, by plays, each with its three most
    played artists and no similar ones yet; a genre whose lead already leads a mix
    is passed over.

    :return: Up to DAILY_MIXES mix dicts.
    """
    songs = json_call(
        "AudioLibrary.GetSongs",
        properties=["artist", "artistid", "genre", "genreid", "playcount"],
        query_filter={
            "field": "lastplayed",
            "operator": "inthelast",
            "value": DAILY_WINDOW,
        },
        parent="daily_mixes",
    )["result"].get("songs", [])
    plays, totals, artists, genres = defaultdict(Counter), Counter(), {}, {}
    for song in songs:
        credits = dict(zip(song["artistid"], song["artist"]))
        artists |= credits
        for genreid, genre in zip(song["genreid"], song["genre"]):
            genres[genreid] = genre
            totals[genreid] += song["playcount"]  # once a song: a duet counts once
            plays[genreid].update(dict.fromkeys(credits, song["playcount"]))
    mixes, leads = [], set()
    for genreid, _ in totals.most_common():
        seeds = [artistid for artistid, _ in plays[genreid].most_common(DAILY_SEEDS)]
        if len(seeds) < DAILY_SEEDS or seeds[0] in leads:
            continue
        leads.add(seeds[0])
        mixes.append(
            {
                "genreid": genreid,
                "genre": genres[genreid],
                "artistids": seeds,
                "artists": [artists[artistid] for artistid in seeds],
                "similar": [],
            }
        )
        if len(mixes) == DAILY_MIXES:
            break
    return mixes
