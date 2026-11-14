# author: realcopacetic

import random
from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Iterator, Sequence
from datetime import date, datetime, time, timedelta
from math import ceil
from operator import itemgetter

from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import json_call

MIX_SIZE = 50
# A mix's share by its seed's artists, as radios lean 12–36 % on theirs (coding-notes
# audits/2026-11-12-music-popularity.md); Ash, 12 Nov
SEED_SHARE = {"song": 0.25, "album": 0.35, "artist": 0.35}
SIMILAR_CAP = 6  # most songs of a mix by any one similar artist
DAILY_ARTIST_SHARE = 0.3  # a genre's mix leans harder on the artists you played in it
DAILY_MIXES = 6
DAILY_SEEDS = 3  # artists a genre's played songs need to make a daily mix; its leads
DAILY_WINDOW = "30"  # days of plays the daily mixes read
HALF_LIFE = 7  # days for a play's weight to halve (N88; Ash, 14 Nov)
HEARD = 3  # days a song just heard is drawn only once the rest run short (Ash, 14 Nov)
RANDOM = {"method": "random"}
SONG_PROPERTIES = ["file", "artist", "albumartist", "genre"]


def random_songs(query_filter: dict, limit: int | None = None) -> list[dict]:
    """
    Fetches a random draw of songs in random order, with what a mix reads of each.

    :param query_filter: AudioLibrary.GetSongs filter.
    :param limit: Maximum number of songs; None for all.
    :return: Song dicts with songid, file, artist, albumartist and genre.
    """
    songs = json_call(
        "AudioLibrary.GetSongs",
        properties=SONG_PROPERTIES,
        sort=RANDOM,
        limit=limit,
        query_filter=query_filter,
        parent="mix",
    )["result"].get("songs", [])
    # Kodi draws at random but lists the draw by song id once artists are asked for
    return random.sample(songs, len(songs))


def played_songs(genres: Collection[str] = ()) -> list[dict]:
    """
    The songs played in DAILY_WINDOW days: a genre mix's seeds.

    :param genres: Genre names to keep to; empty for every genre.
    :return: Song dicts with songid, file, artist, albumartist, genre and lastplayed.
    """
    rules = [{"field": "lastplayed", "operator": "inthelast", "value": DAILY_WINDOW}]
    if genres:
        rules.append(genre_rule(genres))
    return json_call(
        "AudioLibrary.GetSongs",
        properties=[*SONG_PROPERTIES, "lastplayed"],
        query_filter={"and": rules},
        parent="mix",
    )["result"].get("songs", [])


def genre_rule(genres: Collection[str]) -> dict:
    """
    The songs rule for a mix's genres: Kodi's genres by name, exactly ("is" is SQL
    LIKE: case doesn't matter, spelling does). The one place a genre is matched.

    :param genres: Genre names.
    :return: AudioLibrary.GetSongs rule.
    """
    return {"field": "genre", "operator": "is", "value": [*genres]}


def genre_ids() -> dict[str, int]:
    """
    The library's music genres.

    :return: Genre id by name.
    """
    rows = json_call("AudioLibrary.GetGenres", parent="mix")["result"].get("genres", [])
    return {row["label"]: row["genreid"] for row in rows}


def credits(song: dict) -> list[str]:
    """
    The artists a song counts for: those of its artists who lead its album, else
    (a compilation, a soundtrack) all of them; never a guest on another's album.

    :param song: Song dict with artist and albumartist.
    :return: Artist names.
    """
    return [a for a in song["albumartist"] if a in song["artist"]] or song["artist"]


def lead_id(song: dict) -> int:
    """
    The library id of the first artist a song counts for (credits).

    :param song: Song dict with artist, artistid and albumartist.
    :return: Artist id.
    """
    return dict(zip(song["artist"], song["artistid"]))[credits(song)[0]]


def artist_genres(artists: list[str]) -> list[str]:
    """
    The genres of these artists' albums' songs, for seeds with none.

    :param artists: Artist names.
    :return: Genre names, first seen first.
    """
    songs = json_call(
        "AudioLibrary.GetSongs",
        properties=["genre"],
        query_filter={"field": "albumartist", "operator": "is", "value": artists},
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
    seeds: Sequence[dict],
    size: int,
    exclude: Collection[int] = (),
    share: float = SEED_SHARE["song"],
    similar: Sequence[str] = (),
    keep: dict | None = None,
    familiar: int = 0,
) -> list[dict]:
    """
    A mix grown from seed songs: about share by the artists they count for (the first
    familiar of it the seeds themselves), then similar artists', then their genres'
    (else their artists'), or keep's; songs heard in HEARD days fill only what's short.

    :param seeds: Song dicts with artist, albumartist and genre; none for keep alone.
    :param size: Most songs.
    :param exclude: Song ids to leave out: a seed played first, a queue's songs.
    :param share: Fraction of the songs by the seeds' artists.
    :param similar: Library artist names like the seeds' artists.
    :param keep: A songs rule every song must meet (a genre's, a year's); None to roam.
    :param familiar: Most seeds to play as they are, in their order.
    :return: Song dicts in play order.
    """
    exclude = {*exclude}

    def take(
        songs: Iterable[dict], count: int, cap: int = 0, tally: Counter | None = None
    ) -> list[dict]:
        taken, tally = [], Counter() if tally is None else tally
        if count <= 0:  # before songs is read: pick's draw is lazy
            return taken
        for song in songs:
            artist = song["artist"][0]
            if song["songid"] in exclude or cap and tally[artist] >= cap:
                continue
            tally[artist] += 1
            exclude.add(song["songid"])
            taken.append(song)
            if len(taken) == count:
                break
        return taken

    def drawn(rule: dict, limit: int) -> Iterator[dict]:
        # Songs not just heard (or never played) first; the rest only when short
        for heard in ("notinthelast", "inthelast"):
            when = {"field": "lastplayed", "operator": heard, "value": str(HEARD)}
            yield from random_songs({"and": [rule, when]}, limit)

    def pick(
        rule: dict, count: int, cap: int = 0, tally: Counter | None = None
    ) -> list[dict]:
        # Over-fetch by the exclusions, as many of them may come up; thrice for a cap
        limit = count * (3 if cap else 1) + len(exclude)
        return take(drawn(rule, limit), count, cap, tally)

    def by(names: Sequence[str]) -> dict:  # their own albums' songs, within keep
        rule = {"field": "albumartist", "operator": "is", "value": [*names]}
        return {"and": [rule, keep]} if keep else rule

    leads = Counter(artist for song in seeds for artist in credits(song))
    artists = [artist for artist, _ in leads.most_common()]
    fill = keep
    if seeds and not keep:  # the seeds' genres, else their artists'
        genres = [*dict.fromkeys(g for song in seeds for g in song["genre"])]
        if genres := genres or artist_genres(artists):
            fill = genre_rule(genres)
    own = []
    if artists:
        want = max(1, round(size * share))
        cap, theirs = ceil(want / len(artists)), Counter()  # a fair share each
        own = take(seeds, min(familiar, want), cap, theirs)
        own += pick(by(artists), want - len(own), cap, theirs)
    others = pick(by(similar), size - len(own), SIMILAR_CAP) if similar else []
    if fill:
        names = [*artists, *similar]
        strangers = {"field": "albumartist", "operator": "isnot", "value": names}
        rule = {"and": [fill, strangers]} if names else fill
        others += pick(rule, size - len(own) - len(others))
    if artists:  # what the others left short
        own += pick(by(artists), size - len(own) - len(others))
    return spread(own, random.sample(others, len(others)))


def recency(song: dict) -> float:
    """
    A played song's weight: 1 played now, halving every HALF_LIFE days since (Kodi
    keeps one date a song, so a song counts once).

    :param song: Song dict with lastplayed.
    :return: Weight.
    """
    age = datetime.now() - datetime.fromisoformat(song["lastplayed"])
    return 0.5 ** (age / timedelta(days=HALF_LIFE))


def by_weight(songs: Sequence[dict]) -> list[dict]:
    """
    Songs in a weighted random order, each as likely to come first as its recency
    (Efraimidis and Spirakis's key), those heard in HEARD days after the rest: what
    a mix played yesterday seeds today's without coming back in it.

    :param songs: Song dicts with lastplayed.
    :return: The songs reordered.
    """
    # Kodi's inthelast: after the date HEARD days back, as text ("lastplayed > '…'")
    heard = f"{date.today() - timedelta(days=HEARD)}"

    def key(song: dict) -> tuple[bool, float]:
        return song["lastplayed"] <= heard, random.random() ** (1 / recency(song))

    return sorted(songs, key=key, reverse=True)


def leading_genres(played: Sequence[dict]) -> list[tuple[str, list[dict]]]:
    """
    The DAILY_MIXES genres with most weight (recency) in the songs played lately,
    the last played first, each with its songs (its mix's seeds); a genre needs
    DAILY_SEEDS artists and yields when most of its weight already seeds another.

    :param played: Songs played in DAILY_WINDOW days (played_songs).
    :return: (genre, seed songs) pairs.
    """
    seeds, weight = defaultdict(list), {s["songid"]: recency(s) for s in played}
    for song in played:
        for genre in song["genre"]:
            seeds[genre].append(song)

    def weighed(songs: Iterable[dict]) -> float:
        return sum(weight[song["songid"]] for song in songs)

    chosen, seeding = [], set()
    for genre in sorted(seeds, key=lambda g: weighed(seeds[g]), reverse=True):
        songs = seeds[genre]
        shared = weighed(song for song in songs if song["songid"] in seeding)
        artists = {artist for song in songs for artist in credits(song)}
        if len(artists) < DAILY_SEEDS or shared > weighed(songs) / 2:
            continue
        seeding.update(song["songid"] for song in songs)
        chosen.append((genre, songs))
        if len(chosen) == DAILY_MIXES:
            break
    # the genre you're on now leads (N88), "YYYY-MM-DD HH:MM:SS" sorting as dates
    return sorted(
        chosen, key=lambda pair: max(s["lastplayed"] for s in pair[1]), reverse=True
    )


def genre_mix(genre: str, seeds: Sequence[dict]) -> dict:
    """
    A genre's mix, the same draw for a card and Start mix: seeded by the songs you
    played in it, the newest likeliest first (by_weight), leaning on their artists,
    similar to the DAILY_SEEDS most played.

    :param genre: Genre name.
    :param seeds: Songs played in it lately (played_songs); none for its songs alone.
    :return: Mix dict: songs in play order, leads and the similar artists drawn with.
    """
    from resources.lib.plugin.music import similar_to

    counts = Counter(artist for song in seeds for artist in credits(song))
    leads = [artist for artist, _ in counts.most_common(DAILY_SEEDS)]
    similar = similar_to(leads, "mix") if leads else []
    songs = mix_songs(
        by_weight(seeds),
        MIX_SIZE,
        share=DAILY_ARTIST_SHARE,
        similar=similar,
        keep=genre_rule([genre]),
        familiar=round(MIX_SIZE * DAILY_ARTIST_SHARE) // 2,
    )
    return {"songs": songs, "leads": leads, "similar": similar}


def _mix_key(genre: str) -> str:
    """
    A genre's kept mix's api_cache key: one row a genre, replaced in place.

    :param genre: Genre name.
    :return: Key.
    """
    return f"library:mix:{genre}"


def kept_mix(genre: str, seeds: Sequence[dict] | None = None) -> dict:
    """
    A genre's mix as kept until midnight, so a card names what its click plays;
    drawn (genre_mix) and kept when there's none fresh.

    :param genre: Genre name.
    :param seeds: Songs played in it lately, if in hand; else read for a draw.
    :return: Mix dict (genre_mix).
    """
    store, key = ApiCacheHandler(), _mix_key(genre)
    if (hit := store.get(key)) and hit[1]:
        return hit[0]
    mix = genre_mix(genre, played_songs([genre]) if seeds is None else seeds)
    now = datetime.now()
    midnight = datetime.combine(now.date() + timedelta(days=1), time())
    store.put(key, mix, int((midnight - now).total_seconds()) + 1)
    return mix


def recheck_similar(genre: str, mix: dict) -> None:
    """
    Marks a kept mix stale when its leads' similar artists answer otherwise now, as
    a script may look up what the plugin had no cache for: the next rail load redraws.

    :param genre: Genre name.
    :param mix: Its kept mix dict.
    """
    from resources.lib.plugin.music import similar_to

    if mix["leads"] and similar_to(mix["leads"], "start_mix") != mix["similar"]:
        ApiCacheHandler().expire(_mix_key(genre))
