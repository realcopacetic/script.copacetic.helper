# author: realcopacetic

import random
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Iterable, Iterator, Sequence
from datetime import date, datetime, time, timedelta
from functools import reduce
from math import ceil
from operator import itemgetter

from resources.lib.shared.genres import genre_bucket
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import json_call

MIX_SIZE = 50
# A mix's share by its seed's artists, as radios lean 12–36 % on theirs (coding-notes
# audits/2026-11-12-music-popularity.md); Ash, 12 Nov
SEED_SHARE = {"song": 0.25, "album": 0.35, "artist": 0.35}
SIMILAR_CAP = 6  # most songs of a mix by any one similar artist
FILL_CAP = 3  # and by any one artist of its genre fill, while others have songs
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


def card(genre: str) -> str:
    """
    The daily mix card a genre's songs seed: its bucket (shared.genres), else the
    genre itself, as a tag no bucket's rows find.

    :param genre: Genre name.
    :return: Bucket or genre name.
    """
    return genre_bucket(genre) or genre


def card_genres(key: str) -> list[str]:
    """
    The library's genres in a card: a bucket's, or the one genre.

    :param key: Card (card).
    :return: Genre names.
    """
    return [genre for genre in genre_ids() if card(genre) == key]


def credits(song: dict) -> list[str]:
    """
    The artists a song counts for: those of its artists who lead its album, else
    (a compilation, a soundtrack) all of them; never a guest on another's album.

    :param song: Song dict with artist and albumartist.
    :return: Artist names.
    """
    return [a for a in song["albumartist"] if a in song["artist"]] or song["artist"]


def lead_id(song: dict) -> int | None:
    """
    The library id of the first artist a song counts for (credits).

    :param song: Song dict with artist, artistid and albumartist.
    :return: Artist id; None when the song lists no ids for its artists.
    """
    return dict(zip(song["artist"], song["artistid"])).get(credits(song)[0])


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


def heard(song: dict) -> bool:
    """
    Whether a song was played in the last HEARD days, as Kodi's inthelast counts
    them: after the date HEARD days back, compared as text ("lastplayed > '…'").

    :param song: Song dict with lastplayed ("" if never played).
    :return: Heard lately.
    """
    return song["lastplayed"] > f"{date.today() - timedelta(days=HEARD)}"


def spread(own: list, others: list) -> list:
    """
    Spreads own evenly through the gaps of others (before, between, after) from a
    random start (Spotify's offset), keeping the order of each; one a gap, as they fit.

    :param own: Items to spread; at least one.
    :param others: Items to spread them through.
    :return: Merged list.
    """
    # gap j is the keys in (j - 1, j): before others[j], or after the last
    step, start = (len(others) + 1) / len(own), random.random()
    keyed = [
        *enumerate(others),
        *(((n + start) * step - 1, s) for n, s in enumerate(own)),
    ]
    return [s for _, s in sorted(keyed, key=itemgetter(0))]


def shuffled(songs: list[dict]) -> list[dict]:
    """
    Songs in random order with every artist's spread through the rest, the artist
    with most songs last: its songs are spaced exactly, and no two of anyone's meet
    while another's can come between.

    :param songs: Song dicts with artist.
    :return: The songs in play order.
    """
    by_artist = defaultdict(list)
    for song in random.sample(songs, len(songs)):
        by_artist[song["artist"][0]].append(song)
    return reduce(
        lambda mixed, own: spread(own, mixed), sorted(by_artist.values(), key=len), []
    )


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
    A mix grown from seed songs: about share by their artists (the seeds first), then
    similar artists', then their genres' (else their artists') or keep's, each capped
    and spread (shuffled); songs heard in HEARD days fill only what's short.

    :param seeds: Song dicts with artist, albumartist and genre; none for keep alone.
    :param size: Most songs.
    :param exclude: Song ids to leave out: a seed played first, a queue's songs.
    :param share: Fraction of the songs by the seeds' artists.
    :param similar: Library artist names like the seeds' artists.
    :param keep: A songs rule every song must meet (a genre's, a year's); None to roam.
    :param familiar: Most of the seeds themselves to take, in their order.
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
        for operator in ("notinthelast", "inthelast"):
            when = {"field": "lastplayed", "operator": operator, "value": str(HEARD)}
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
    similar = [artist for artist in similar if artist not in leads]  # no second share
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
    songs = own + (pick(by(similar), size - len(own), SIMILAR_CAP) if similar else [])
    uncapped = [by(artists)] if artists else []
    if fill:
        names = [*artists, *similar]
        strangers = {"field": "albumartist", "operator": "isnot", "value": names}
        rule = {"and": [fill, strangers]} if names else fill
        songs += pick(rule, size - len(songs), FILL_CAP)
        uncapped.append(rule)
    for rule in uncapped:  # what the caps left short: the artists' own, then the fill's
        songs += pick(rule, size - len(songs))
    return shuffled(songs)


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

    def key(song: dict) -> tuple[bool, float]:
        return not heard(song), random.random() ** (1 / recency(song))

    return sorted(songs, key=key, reverse=True)


def leading_cards(played: Sequence[dict]) -> list[tuple[str, list[dict]]]:
    """
    The DAILY_MIXES cards (card) with most weight (recency) in the songs played
    lately, the last played first, each with its songs (its mix's seeds); a card
    needs DAILY_SEEDS artists and yields when most of its weight seeds another.

    :param played: Songs played in DAILY_WINDOW days (played_songs).
    :return: (card, seed songs) pairs.
    """
    seeds, weight = defaultdict(list), {s["songid"]: recency(s) for s in played}
    for song in played:
        for key in dict.fromkeys(map(card, song["genre"])):
            seeds[key].append(song)

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


def genre_mix(
    genres: Sequence[str],
    seeds: Sequence[dict],
    owned: Callable[[], dict[str, str]] | None = None,
) -> dict:
    """
    A mix kept to genres (a card's, or a genre node's one), the same draw for a card
    and Start mix: seeded by the songs you played in them, the newest likeliest first
    (by_weight), leaning on their artists, similar to the DAILY_SEEDS most played.

    :param genres: Genre names.
    :param seeds: Songs played in them lately (played_songs); none for their songs.
    :param owned: Returns the album artists' names (similar_to), when draws share it.
    :return: Mix dict: songs in play order, leads, similar artists, genres by plays.
    """
    from resources.lib.plugin.music import similar_to

    counts = Counter(artist for song in seeds for artist in credits(song))
    leads = [artist for artist, _ in counts.most_common(DAILY_SEEDS)]
    similar = similar_to(leads, "mix", owned) if leads else []
    songs = mix_songs(
        by_weight(seeds),
        MIX_SIZE,
        share=DAILY_ARTIST_SHARE,
        similar=similar,
        keep=genre_rule(genres),
        familiar=round(MIX_SIZE * DAILY_ARTIST_SHARE) // 2,
    )
    played = Counter(genre for song in seeds for genre in song["genre"])
    genres = sorted(genres, key=played.__getitem__, reverse=True)
    return {"songs": songs, "leads": leads, "similar": similar, "genres": genres}


def _mix_key(key: str) -> str:
    """
    A card's kept mix's api_cache key: one row a card, replaced in place; v2, as a
    row drawn before cards were buckets has no genres.

    :param key: Card (card).
    :return: Key.
    """
    return f"library:mix:v2:{key}"


def kept_mix(
    key: str,
    seeds: Sequence[dict] | None = None,
    owned: Callable[[], dict[str, str]] | None = None,
    stale: bool = False,
) -> dict:
    """
    A card's mix as kept, drawn (genre_mix, its genres) and kept until midnight when
    there's none fresh; with stale, any kept row is played: the click, as only a rail
    load redraws a card, so the click plays what its card names.

    :param key: Card (card).
    :param seeds: Songs played in it lately, if in hand; else read for a draw.
    :param owned: Returns the album artists' names, shared by a rail's draws.
    :param stale: Take a kept row whatever its age; draw only when there is none.
    :return: Mix dict (genre_mix).
    """
    store, cache_key = ApiCacheHandler(), _mix_key(key)
    if (hit := store.get(cache_key)) and (hit[1] or stale):
        return hit[0]
    genres = card_genres(key)
    mix = genre_mix(genres, played_songs(genres) if seeds is None else seeds, owned)
    if (hit := store.get(cache_key)) and hit[1]:  # another call kept one meanwhile
        return hit[0]
    midnight = datetime.combine(date.today() + timedelta(days=1), time())
    store.put(
        cache_key, mix, int(midnight.timestamp() - datetime.now().timestamp()) + 1
    )
    return mix


def look_up_similar(mix: dict) -> bool:
    """
    Looks a mix's leads' similar artists up, network allowed (after playback starts,
    as the draw read the cache alone), so the cache holds them for the next draw.

    :param mix: Mix dict (genre_mix).
    :return: Whether they answer otherwise than the mix was drawn with.
    """
    from resources.lib.plugin.music import similar_to

    return (
        bool(mix["leads"]) and similar_to(mix["leads"], "start_mix") != mix["similar"]
    )


def recheck_similar(key: str, mix: dict) -> None:
    """
    Marks a card's kept mix stale when its leads' similar artists answer otherwise
    now (look_up_similar): the next rail load redraws it, and the card with it.

    :param key: Card (card).
    :param mix: Its kept mix dict.
    """
    if look_up_similar(mix):
        ApiCacheHandler().put(_mix_key(key), mix, 0)  # this key alone, kept stale
