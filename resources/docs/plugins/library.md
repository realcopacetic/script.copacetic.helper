# Library Listings

These plugin paths fill a container with items from your video library (`genre_music`,
`top_songs`: your music library). Use them as widgets or in any list. Each item carries the usual
library infolabels and artwork, so your existing layouts work with them.

| `info=` | What it lists |
|---|---|
| `in_progress` | Movies and episodes you have started but not finished. |
| `next_up` | The next unwatched episode of each TV show you are watching. |
| `random_movies` | Movies in random order. |
| `random_tvshows` | TV shows in random order. |
| `actor_credits` | Movies and TV shows with a given actor. |
| `director_credits` | Movies and music videos by a given director. |
| `writer_credits` | Movies and episodes by a given writer. |
| `genre_credits` | Movies and TV shows in a given genre. |
| `studio_credits` | Movies and TV shows from a given studio or network. |
| `artist_credits` | Music videos by a given artist. |
| `genre_music` | Library artists, albums or songs in any of the given genres. |
| `top_songs` | A library artist's songs most listened to on ListenBrainz, then its most played. |

```xml
<control type="list" id="5000"><!-- id is an example -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=next_up&amp;limit=20</content>
</control>
```

---

## The items

- Every item has its `DBType` set (`movie`, `episode`, `tvshow` or `musicvideo`),
  its `DBID`, and the usual infolabels: `Title`, `Plot`, `Year`, `Genre`, `Rating`,
  `PlayCount`, `LastPlayed`, `PercentPlayed` (from the resume point) and so on.
- `ListItem.Art(...)` holds the library artwork. When an item has no `icon` or
  `thumb`, Kodi's default icon for its type is used.
- Episodes and TV shows also have `ListItem.Property(tvshowid)`. Episodes carry the
  show's `Studio` and `MPAA`.
- `in_progress`, `next_up`, `random_movies` and `random_tvshows` leave out stream
  details, directors and writers to keep them fast. So `ListItem.Director`,
  `ListItem.Writer` and the `ListItem.VideoResolution` family are empty on those
  lists.
- TV shows are folders, with the path `videodb://tvshows/titles/<DBID>/`, so
  selecting one opens the show as in the library. Other video items are not folders;
  their path is the library file path.

---

## `in_progress`

Movies and episodes that are part-watched. Movies come first, then episodes. The list
offers Kodi's "last played" sort method.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `movie`, `tvshow`, anything else | — | `movie`: movies only. `tvshow`: episodes only. Anything else, or none: both. |
| `limit` | whole number | — | Most movies, and most episodes, to fetch. The limit applies to each on its own, so the list can hold up to twice this. |

```xml
<content>plugin://script.copacetic.helper/?info=in_progress&amp;limit=20</content>
```

## `next_up`

For each TV show you are part-way through, the lowest-numbered unwatched
episode, leaving out specials (season 0). Shows are ordered by when you last watched
them. A show with only unwatched specials left is skipped. The list offers Kodi's
"last played" sort method.

The episodes carry the **show's** artwork, as `ListItem.Art(tvshow.poster)`,
`ListItem.Art(tvshow.fanart)` and so on. The episode's own artwork is not included.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `limit` | whole number | — | Most TV shows to look at. |

```xml
<content>plugin://script.copacetic.helper/?info=next_up&amp;limit=20</content>
```

## `random_movies`

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `limit` | whole number | — | Most movies to return. |
| `randomise` | any text | — | A seed. The same seed gives the same order. Without it, the order changes on every call. |
| `exclude_played_days` | whole number | — | Leave out movies played in the last N days. |

```xml
<content>plugin://script.copacetic.helper/?info=random_movies&amp;limit=20&amp;exclude_played_days=14&amp;randomise=$INFO[Window(home).Property(my_random_seed)]</content>
```

Change the seed property when you want a new order, for example once per visit to
the home screen. A plugin path that never changes is only called once.

## `random_tvshows`

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `limit` | whole number | — | Most TV shows to return. |
| `randomise` | any text | — | A seed. The same seed gives the same order. Without it, the order changes on every call. |

```xml
<content>plugin://script.copacetic.helper/?info=random_tvshows&amp;limit=20&amp;randomise=$INFO[Window(home).Property(my_random_seed)]</content>
```

## `actor_credits`, `director_credits`, `writer_credits`, `genre_credits`, `studio_credits`, `artist_credits`

Everything in the library credited to one person, genre, studio or artist. Each kind
of item is sorted by `sort` (newest first by default) and cut to `limit`, and the kinds
follow each other in the order below.

| `info=` | Searches |
|---|---|
| `actor_credits` | movies, then TV shows |
| `director_credits` | movies, then music videos |
| `writer_credits` | movies, then episodes |
| `genre_credits` | movies, then TV shows |
| `studio_credits` | movies, then TV shows |
| `artist_credits` | music videos |

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `label` | a name | — | The person, genre, studio or artist to search for, as the library names it. |
| `type` | `movie`, `tvshow`, `episode`, `musicvideo` | — | Search that kind only, e.g. `movie` for movies only. A kind the path does not search (see the table) gives an empty list. |
| `exclude_value` | any text | — | Leave out items whose `exclude_key` field equals this. Use it to hide the item you came from. |
| `exclude_key` | a Kodi library filter field | `title` | The field `exclude_value` is compared with. |
| `sort` | a JSON-RPC sort method (`year`, `votes` …), or `random` | `year` | The order Kodi fetches in, descending. `random` is shuffled by the helper, by `randomise`. |
| `randomise` | any text | — | With `sort=random`: a seed, as in [`random_movies`](#random_movies). The same seed gives the same order, so a refetch (a library update) keeps it. |
| `limit` | whole number | all | Most items of each kind, after the sort. The kinds add up, so the list can hold up to twice this. |

```xml
<content>plugin://script.copacetic.helper/?info=director_credits&amp;label=$INFO[ListItem.Director]&amp;exclude_value=$INFO[ListItem.Title]</content>
```

Pass one name in `label`. `ListItem.Director` holds several names, separated by
` / `, when an item has more than one director; that string matches nobody. The
[`metadata`](metadata.md#metadata) path with `random_pick=true` gives one director
(`ListItem.Director`), one genre (`ListItem.Property(genre_query)`) and always one
studio (`ListItem.Studio`), each as the library names it. Names and titles may hold `&` (`Action &
Adventure`): the helper splits its parameters only where `&name=` follows, where a
`videodb://` filter in the path would cut the value at the `&`. Pass the container's
own `limit` and order as `limit` and `sort`, so Kodi never fetches a whole genre or
studio for the container to cut.

## `genre_music`

Library artists, albums or songs in any of the given genres, in random order (fixed by
`randomise`, as in [`random_movies`](#random_movies)). Pass the item's own `ListItem.Genre`, so a genre that holds only this item still leaves the
others. The items are music library items: `DBType` `artist`, `album` or `song` and
their `DBID`; artists and albums open as `musicdb://` folders, songs play their file. They carry their library
artwork, `Genre`, `Artist`, `Year` and so on; `Art(icon)` is always Kodi's default icon
for the type. The container's content is `artists`, `albums` or `songs`.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `artist`, `album`, `song` | required | What to list |
| `label` | genres, ` / ` joined | — | The genres, as the library names them (`R&B` is fine); items in any of them |
| `id` | an artist's `DBID` | — | Add the genres of that artist's albums. An artist's own `ListItem.Genre` is the scraper's (TheAudioDB's "Alternative"), while Kodi matches an artist's genre through its songs' tags, so pass it for an artist |
| `exclude_value` | a name | — | Leave out the artist, album or song (by title) with this name |
| `limit` | whole number | all | Most items, picked at random |
| `randomise` | any text | — | A seed. The same seed gives the same items in the same order. |

```xml
<content sortby="userpreference">plugin://script.copacetic.helper/?info=genre_music&amp;type=artist&amp;id=$INFO[ListItem.DBID]&amp;label=$INFO[ListItem.Genre]&amp;exclude_value=$INFO[ListItem.Artist]&amp;limit=20</content>
<content sortby="userpreference">plugin://script.copacetic.helper/?info=genre_music&amp;type=album&amp;label=$INFO[ListItem.Genre]&amp;exclude_value=$INFO[ListItem.Album]&amp;limit=20&amp;randomise=$INFO[Window(home).Property(my_random_seed)]</content>
```

`sortby="userpreference"` keeps the helper's order. Kodi refetches a list sorted
`none` on every play and stop, and `random` re-draws its own order on every fetch.

## `top_songs`

One library artist's songs in the order of its most listened recordings on
[ListenBrainz](https://listenbrainz.org) (the free popularity API,
`/1/popularity/top-recordings-for-artist/<artist MBID>`, no key), then the artist's
other played songs, most played first. Only with the add-on setting **Enable access to
ListenBrainz API** on (off by default: it sends the artist's MusicBrainz ID to
listenbrainz.org); off, the path returns nothing and sends nothing.

A song matches a recording by its MusicBrainz recording id (`musicbrainztrackid`,
Picard's "MusicBrainz Track Id"), else by title: case, accents, punctuation and a
trailing `(feat. …)`, `[Remaster]` or ` - Live` part are ignored. Each title appears
once, from its earliest dated release. The path returns nothing when the artist has
no MusicBrainz id in the library, ListenBrainz has nothing for it, or no song
matches, so a list never holds the play counts alone. The items are music library
songs, as in [`genre_music`](#genre_music); the container's content is `songs`.

Answers are kept in the add-on's `_lookup.db` (`api_cache`): two weeks for a list,
three days for an empty one, five minutes when ListenBrainz is unreachable (an older
list is shown meanwhile). Requests are spaced at least a second apart across all
plugin calls, as ListenBrainz asks; a call inside that second shows the saved answer
or nothing, and the next open fetches.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | an artist's `DBID` | required | The artist |
| `limit` | whole number | all | Most songs |

```xml
<content sortby="userpreference">plugin://script.copacetic.helper/?info=top_songs&amp;id=$INFO[ListItem.DBID]&amp;limit=10</content>
```

## `listeners`

Not a listing: one item whose `ListItem.Property(listeners)` is how many people
[ListenBrainz](https://listenbrainz.org) counts as having listened to a library
artist, album or song, to two significant figures (`87`, `310K`, `1.2M`). The number
only; the skin adds the word. Same setting, cache and spacing as `top_songs`
(two weeks for a count, three days when ListenBrainz has none).

It asks `POST /1/popularity/artist`, `/release-group` or `/recording` with the
item's MusicBrainz id: an artist's `musicbrainzartistid`, an album's release group
(`musicbrainzreleasegroupid`, so every edition counts) and a song's recording
(`musicbrainztrackid`). No id in the library, no count from ListenBrainz or access
off: no item.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `artist`, `album`, `song` | required | The item's type |
| `id` | the item's `DBID` | required | The item |

```xml
<content>plugin://script.copacetic.helper/?info=listeners&amp;type=$INFO[ListItem.DBType]&amp;id=$INFO[ListItem.DBID]</content>
```

---

## The add-on's own directory

Opening `plugin://script.copacetic.helper/` with no `info=` lists two folders, so
users can add them as widgets from Kodi's add-on browser:

| Folder | Path |
|---|---|
| Continue watching | `plugin://script.copacetic.helper/?info=in_progress&type=mixed` |
| Next up | `plugin://script.copacetic.helper/?info=next_up&type=tvshow` |

A plugin path with an `info=` the add-on does not know returns an empty list.
