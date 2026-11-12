# author: realcopacetic

import random
from collections import Counter, defaultdict
from collections.abc import Collection, Sequence
from datetime import date
from operator import itemgetter

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


def random_songs(query_filter: dict, limit: int | None = None) -> list[dict]:
    """
    Fetches songs in random order, with their files, artists and genres.

    :param query_filter: AudioLibrary.GetSongs filter.
    :param limit: Maximum number of songs; None for all.
    :return: Song dicts with songid, file, artist and genre.
    """
    return json_call(
        "AudioLibrary.GetSongs",
        properties=["file", "artist", "genre"],
        sort={"method": "random"},
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
) -> list[dict]:
    """
    Random songs for a mix: about share of them by artists (at least one), spread
    through songs by similar artists, SIMILAR_CAP each, then of genres by others.

    :param artists: Artist names the mix leans on.
    :param genres: Genre names for what similar artists don't fill.
    :param size: Most songs; what the others leave short is topped up by artists.
    :param exclude: Song ids to leave out: a seed, a queue's songs.
    :param share: Fraction of the songs by artists.
    :param similar: Library artist names like artists.
    :return: Song dicts with songid, file, artist and genre.
    """
    exclude = {*exclude}

    def pick(query_filter: dict, count: int, cap: int = 0) -> list[dict]:
        if count <= 0:  # a limit of 0 would fetch every song
            return []
        # Over-fetch by the exclusions, as many of them may come up; thrice for a cap
        songs = random_songs(query_filter, count * (3 if cap else 1) + len(exclude))
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
    own = pick(by_artist, want)
    rest = size - len(own)
    others = (
        pick({**by_artist, "value": [*similar]}, rest, SIMILAR_CAP) if similar else []
    )
    if genres:
        genre_rule = {"field": "genre", "operator": "is", "value": genres}
        not_theirs = {**by_artist, "operator": "isnot", "value": [*artists, *similar]}
        others += pick({"and": [genre_rule, not_theirs]}, rest - len(others))
    if len(own) == want:  # else the artists have no more
        own += pick(by_artist, rest - len(others))
    return spread(own, random.sample(others, len(others)))


def todays_mixes() -> list[dict]:
    """
    Today's mixes, worked out on the day's first read and kept for the day, so the
    cards hold while today's plays move lastplayed. Empty until there are plays.

    :return: Mix dicts: genreid, genre, artistids and artists, leads first.
    """
    cache, key = ApiCacheHandler(), f"library:daily_mixes:{date.today()}"
    if hit := cache.get(key):
        return hit[0]
    if mixes := _leading_genres():
        cache.put(key, mixes, DAILY_TTL)
    return mixes


def _leading_genres() -> list[dict]:
    """
    The genres of the songs played lately, by plays, each with its three most
    played artists; a genre whose lead already leads a mix is passed over.

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
            }
        )
        if len(mixes) == DAILY_MIXES:
            break
    return mixes
