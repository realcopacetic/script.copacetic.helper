# Library Listings

These plugin paths fill a container with items from your video library (`random_albums`,
`genre_music`, `random_genre` with a music type, `top_songs`, `discography`: your music library; `soundtracks`: both). Use them as widgets or in any list. Each item carries the usual
library infolabels and artwork, so your existing layouts work with them.

| `info=` | What it lists |
|---|---|
| `in_progress` | Movies and episodes you have started but not finished. |
| `next_up` | The next unwatched episode of each TV show you are watching. |
| `random_movies` | Movies in random order. |
| `random_tvshows` | TV shows in random order. |
| `random_albums` | Music library albums in random order. |
| `random_genre` | Movies, TV shows, albums or artists from one genre, the genre itself picked at random. |
| `cast` | A library movie's, TV show's or episode's cast, in billing order. |
| `actor_credits` | Movies and TV shows with a given actor. |
| `director_credits` | Movies and music videos by a given director. |
| `writer_credits` | Movies and episodes by a given writer. |
| `genre_credits` | Movies and TV shows in a given genre. |
| `studio_credits` | Movies and TV shows from a given studio or network. |
| `artist_credits` | Music videos by a given artist. |
| `genre_music` | Library artists, albums or songs in any of the given genres. |
| `top_songs` | A library artist's most popular songs (ListenBrainz all-time, Deezer now, blended), then its most played. |
| `discography` | A library artist's albums, most popular (ListenBrainz and Deezer, blended) first. |
| `soundtracks` | A movie's, TV show's or season's soundtrack albums, or the movie or TV show an album is from. |

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
- TV shows carry the episode counts Kodi's own library items have:
  `ListItem.Property(TotalSeasons)`, `TotalEpisodes`, `WatchedEpisodes`,
  `UnWatchedEpisodes` and `WatchedEpisodePercent`.
- `in_progress`, `next_up`, `random_movies`, `random_tvshows` and `random_genre` leave out stream
  details, directors and writers to keep them fast. So `ListItem.Director`,
  `ListItem.Writer` and the `ListItem.VideoResolution` family are empty on those
  lists.
- TV shows are folders, with the path `videodb://tvshows/titles/<DBID>/`, so
  selecting one opens the show as in the library. Other video items are not folders;
  their path is the library file path.
- Music albums (`random_albums`, `genre_music`, `discography`, `soundtracks`) carry
  the album's artist credit in `ListItem.Artist`, as Kodi's own album items do, for
  example `JAY-Z & Kanye West`. So it matches `ListItem.AlbumArtist` on the album's
  songs. Songs carry their artist names joined with ` / `.

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
`ListItem.Art(tvshow.fanart)` and so on. Kodi adds the episode's own library artwork
when it loads the item, so `ListItem.Art(thumb)` is the episode's thumbnail
(`DefaultTVShows.png` if it has none). `ListItem.Art(fanart)` is empty unless the
episode has fanart of its own: use `tvshow.fanart`.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `limit` | whole number | — | Most episodes to return, one per show. A show with only specials left gives no episode, so more shows are read until the list is full or there are no more. Without it, every show you are part-way through is read. |

```xml
<content>plugin://script.copacetic.helper/?info=next_up&amp;limit=20</content>
```

## `random_movies`

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `limit` | whole number | — | Most movies to return. |
| `randomise` | any text | — | A seed. The same seed gives the same order, and a movie added to or removed from the list moves no other. A path with other parameters gets its own order from the same seed; `limit` only cuts it. Without it, the order changes on every call. |
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
| `randomise` | any text | — | A seed. The same seed gives the same order, and a show added to or removed from the library moves no other. Without it, the order changes on every call. |

```xml
<content>plugin://script.copacetic.helper/?info=random_tvshows&amp;limit=20&amp;randomise=$INFO[Window(home).Property(my_random_seed)]</content>
```

## `random_albums`

Music library albums, as in [`genre_music`](#genre_music): `DBType` `album`, opening
as `musicdb://` folders. The container's content is `albums`.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `limit` | whole number | — | Most albums to return. |
| `randomise` | any text | — | A seed. The same seed gives the same order, and an album added to or removed from the library moves no other. Without it, the order changes on every call. |

```xml
<content sortby="userpreference">plugin://script.copacetic.helper/?info=random_albums&amp;limit=20&amp;randomise=$INFO[Window(home).Property(my_random_seed)]</content>
```

`sortby="userpreference"` keeps the helper's order, as for
[`genre_music`](#genre_music).

## `random_genre`

One genre's movies, TV shows, albums or artists in random order, with the genre itself
picked at random by the same seed. So one seed gives one genre and one order: a refetch
(a trailer ending, a library update) keeps both, and a new seed picks again. Only
genres with at least `min_items` items are picked. Albums and artists are counted by
their songs' genres, which Kodi's genre rule then lists (never fewer), not by an
album's own genre text.

Every item carries the genre as `ListItem.Property(genre_pick)`, so the list can name
itself: `$INFO[Container(5000).ListItem.Property(genre_pick)]`. Items also carry the
seed that picked it as `ListItem.Property(genre_seed)`, so a skin can tell the last
visit's items, still showing while the new seed's list loads, from the new ones. The
container's plugin category is the genre too, but Kodi only shows that in a media window
(`Container.PluginCategory`).

The items are as in [`random_movies`](#random_movies) and
[`random_tvshows`](#random_tvshows) for video, and as in [`genre_music`](#genre_music)
for music. The container's content is `movies`, `tvshows`, `albums` or `artists`.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `movie`, `tvshow`, `album`, `artist` | required | What to list |
| `limit` | whole number | all | Most items, picked at random |
| `min_items` | whole number | `10` | Fewest items a genre must hold to be picked |
| `slot` | whole number | `0` | Which pick to take: `0` the first genre in the seeded order, `1` the second, and so on. Give lists of the same type slots `0`, `1`, `2` … and they show different genres, as long as that many genres qualify; past that, it counts round again from the first. |
| `randomise` | any text | — | A seed. The same seed gives the same genre and the same order. A different `type` gets its own genre order from the same seed. Without it, the genre and order change on every call. |

```xml
<content sortby="userpreference">plugin://script.copacetic.helper/?info=random_genre&amp;type=movie&amp;limit=20&amp;slot=0&amp;randomise=$INFO[Window(home).Property(my_random_seed)]</content>
<content sortby="userpreference">plugin://script.copacetic.helper/?info=random_genre&amp;type=movie&amp;limit=20&amp;slot=1&amp;randomise=$INFO[Window(home).Property(my_random_seed)]</content>
```

Picking the genre costs one query that reads every item's genres (and one for the genre
names, for music), then the two queries [`random_movies`](#random_movies) makes.

## `cast`

The cast of one library item, as Kodi's own info dialog lists it (an episode's guest
stars, then its show's cast). Each item's label is the actor's name, `Label2` the role,
`Art(thumb)` the actor's picture (empty without one) and `Art(icon)` `DefaultActor.png`.
Items are not library items (no `DBType`) and their path is a placeholder, so give
the list its own `<onclick>`. Pass a focused actor's
`ListItem.Label` on to [`actor_credits`](#actor_credits-director_credits-writer_credits-genre_credits-studio_credits-artist_credits).

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `movie`, `tvshow`, `episode` | — | The library type of the item. |
| `id` | a library id | — | The item's `DBID`. |
| `limit` | whole number | all | Most actors, from the top of the billing. |

```xml
<!-- the playing film's cast, in a video OSD -->
<content>plugin://script.copacetic.helper/?info=cast&amp;type=movie&amp;id=$INFO[VideoPlayer.DBID]&amp;limit=25</content>
```

One JSON-RPC call (`VideoLibrary.Get…Details` with `cast`).

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
| `sort` | a JSON-RPC sort method (`year`, `votes` …), or `random` | `year` | The order Kodi fetches in, descending. `random` is ordered by the helper, by `randomise`. |
| `randomise` | any text | — | With `sort=random`: a seed, as in [`random_movies`](#random_movies). The same seed gives the same order, so a refetch keeps it, and a title added to or removed from the library moves no other. A different `label` or `exclude_value` gets its own order from the same seed. |
| `limit` | whole number | all | Most items of each kind, after the sort. The kinds add up, so the list can hold up to twice this. |

```xml
<content>plugin://script.copacetic.helper/?info=director_credits&amp;label=$INFO[ListItem.Director]&amp;exclude_value=$INFO[ListItem.Title]&amp;limit=25</content>
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
artwork, `Genre`, `Artist`, `Year` and so on; artists also carry the dates Kodi's own
artist items do (`ListItem.Property(Artist_Born)`, `Artist_Formed`, `Artist_YearsActive`,
`Artist_Disbanded`, `Artist_Died`). `Art(icon)` is always Kodi's default icon
for the type. The container's content is `artists`, `albums` or `songs`.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `artist`, `album`, `song` | required | What to list |
| `label` | genres, ` / ` joined | — | The genres, as the library names them (`R&B` is fine); items in any of them |
| `id` | an artist's `DBID` | — | Add the genres of that artist's albums. An artist's own `ListItem.Genre` is the scraper's (TheAudioDB's "Alternative"), while Kodi matches an artist's genre through its songs' tags, so pass it for an artist |
| `exclude_value` | a name | — | Leave out the artist, album or song (by title) with this name |
| `limit` | whole number | all | Most items, picked at random |
| `randomise` | any text | — | A seed. The same seed gives the same items in the same order, and a title added to or removed from the library moves no other. A different `label`, `id` or `exclude_value` gets its own order from the same seed. |

```xml
<content sortby="userpreference">plugin://script.copacetic.helper/?info=genre_music&amp;type=artist&amp;id=$INFO[ListItem.DBID]&amp;label=$INFO[ListItem.Genre]&amp;exclude_value=$INFO[ListItem.Artist]&amp;limit=20</content>
<content sortby="userpreference">plugin://script.copacetic.helper/?info=genre_music&amp;type=album&amp;label=$INFO[ListItem.Genre]&amp;exclude_value=$INFO[ListItem.Album]&amp;limit=20&amp;randomise=$INFO[Window(home).Property(my_random_seed)]</content>
```

`sortby="userpreference"` keeps the helper's order. Kodi refetches a list sorted
`none` on every play and stop, and `random` re-draws its own order on every fetch.

## `top_songs`

One library artist's songs, most popular first, then the artist's other played songs,
most played first. Two sources rank them, each used when it is on:

- [ListenBrainz](https://listenbrainz.org) (MetaBrainz's free popularity API,
  `/1/popularity/top-recordings-for-artist/<artist MBID>`): listens since
  ListenBrainz began, so an artist's early peak leads and a new album barely shows.
- [Deezer](https://www.deezer.com) (`/artist/<id>/top`, its top 100 tracks): what is
  streamed now, so a new album shows within days.

With both on, each source's list becomes places among the songs the library has
(a source's songs the library lacks take no place; a title listed twice counts once,
at its first place), and a song scores `1 / (10 + place)` in each list that has it,
summed (reciprocal rank fusion): songs both rank lead, then the two lists alternate.
Equal scores go by play count. With one on, its order stands.

**Add-on settings needed** (each is the user's consent; with neither, the path
returns nothing, sends nothing and reads no cache):

- **ListenBrainz user token** (`listenbrainz_token`, empty by default): the token from
  the user's free ListenBrainz account (listenbrainz.org/settings). ListenBrainz
  refuses this endpoint without one; every request sends it as
  `Authorization: Token <token>` with the artist's MusicBrainz ID.
  **Test ListenBrainz access** checks it. A skin can test for it with
  `!String.IsEmpty(Addon.SettingStr(script.copacetic.helper,listenbrainz_token))`.
- **Rank music with Deezer** (`deezer`, off by default): Deezer needs no account; the
  helper sends the artist's name (a search) and a Deezer artist id, nothing else, and
  keeps only ids, titles and album titles (no images or audio). A skin can test for
  it with `Addon.SettingBool(script.copacetic.helper,deezer)`.

A song matches a ListenBrainz recording by its MusicBrainz recording id
(`musicbrainztrackid`, Picard's "MusicBrainz Track Id"), else by title: case, accents,
punctuation and a trailing `(feat. …)`, `[Remaster]` or ` - Live` part are ignored.
Deezer has no MusicBrainz ids, so its tracks match by title (Deezer's title without
its version, such as "(Album Version)"). Each title appears once, from its earliest
dated release unless a recording id matched another. The path returns nothing when
no source answers for the artist or no song matches, so a list never holds the play
counts alone. The items are music library songs, as in [`genre_music`](#genre_music);
the container's content is `songs`.

**Finding the Deezer artist.** The helper searches Deezer for the library artist's
name, keeps the artists whose name is the same (case, accents and punctuation
aside), and tries up to three, most followed first: the first whose top tracks share
three song titles with the library artist's songs (all of them, for an artist with
fewer), or one song title and an album title, is taken. An artist whose name has no
letters or digits ("!!!") isn't looked up. Its id is kept, keyed by the artist's
MusicBrainz id, else by its name, so later opens skip the search; **Refresh cached
data** on the artist searches again (a different pick needs a changed library or
Deezer answer: the check is the same).

Answers are kept in the add-on's `_lookup.db` (`api_cache`):

- ListenBrainz: two weeks for a list, three days for an empty one, a week when
  ListenBrainz refuses the id, as long as it asks after "too many requests", and five
  minutes when it refuses the token (logged as a warning) or is unreachable.
- Deezer: 90 days for the matched artist (a week when none was found), a week for
  its top tracks (a day when empty), a week when Deezer has no data or rejects the
  query, a minute after a quota answer, and five minutes when it is busy,
  unreachable or answers in a shape the helper doesn't expect.

An older answer is shown while a source is unreachable. **Clear addon cache** forgets
them all; *Cache › Clear TMDb / ListenBrainz / Deezer data* forget one source's, and
**Refresh cached data** one artist's.
ListenBrainz requests are spaced at least a second apart across all plugin calls, as
ListenBrainz asks: a call inside that second waits its turn (an artist's info opens
three at once, so the last fills about two seconds in). When the queue is more than
three seconds long, the call shows the saved answer or nothing, and the next open
fetches. Deezer needs no spacing: a first open of an artist makes two requests
(search and top tracks), later opens none until the week is up. The log has one
`api_cache →` line per lookup (miss, fresh, stale or stored, with its size); with the
add-on setting **Include json call/response logs** on, the payload follows it.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | an artist's `DBID` | required | The artist |
| `limit` | whole number | all | Most songs |

```xml
<content sortby="userpreference">plugin://script.copacetic.helper/?info=top_songs&amp;id=$INFO[ListItem.DBID]&amp;limit=10</content>
```

## `discography`

One library artist's albums (the same albums as `musicdb://albums/?artistid=`), most
popular first, then the albums no source ranks, newest first. The two sources and
settings are `top_songs`':

- ListenBrainz ranks release groups
  (`/1/popularity/top-release-groups-for-artist/<artist MBID>`). An album matches by
  its release group (`musicbrainzreleasegroupid`), else by title as in `top_songs`, so
  a deluxe edition sits next to the original.
- Deezer has no album popularity, so its top tracks rank the albums: each top track
  the library has credits the album the library holds it on (the album of the same
  title when there is one, so a live track credits a live album), `1 / (10 + place)`,
  and albums go by their total credit.

Both lists are blended as in `top_songs`. With neither source on, no MusicBrainz id
for ListenBrainz alone, or no answer, all albums come newest first; with neither on
nothing is sent. Same cache and spacing as `top_songs` (the same Deezer answers).

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | an artist's `DBID` | required | The artist |
| `limit` | whole number | all | Most albums |

```xml
<content sortby="userpreference">plugin://script.copacetic.helper/?info=discography&amp;id=$INFO[ListItem.DBID]</content>
```

## `soundtracks`

Links your music library's soundtrack albums to your movies and TV shows by title.
For a movie, TV show, season or episode it lists the soundtrack albums; for an album
it lists the movie or TV show the album is from (nothing if it isn't a soundtrack).

The albums are music library albums, as in [`genre_music`](#genre_music), oldest
first; the container's content is `albums`. The movie or TV show is one video item,
as in [The items](#the-items); the container's content is `movies` or `tvshows`.

**What counts as a soundtrack.** An album whose type, genre, style or title says
"soundtrack". MusicBrainz Picard writes the type (`Album / Soundtrack`), so a tagged
library needs nothing else.

**How titles match.** The album's title must be the movie's or show's title or
original title, either whole (*Black Swan*) or followed only by soundtrack wording
after a `:`, a dash with a space each side (` - `, ` – ` or ` — `), a `,` or a
bracket (*Batman Begins: Original Motion Picture Soundtrack*, *Halt and Catch Fire,
Vol. 2 (Original Television Series Soundtrack)*).
Case, accents, punctuation and `&`/`and` don't matter, but "The" does: *The Batman*'s
album isn't *Batman*'s. A subtitle that isn't soundtrack wording keeps the whole name,
so *Batman: Arkham Asylum: Original Video Game Score* doesn't match *Batman*.

From an album, the helper first asks Kodi for movies and TV shows whose title or
original title starts with the album's title up to its first `:`, spaced dash, `,`
or bracket (*Mission* for *Mission: Impossible – Fallout (Music from the Motion
Picture)*), then matches those as above. That search compares the spelling as
written, so accents, punctuation and `&`/`and` in that first part must be the same in
both libraries.

**Same-titled movies and shows.** When the library has more than one (*The Lion King*
1994 and 2019, or a *Watchmen* movie and show), the album goes to the one its wording
names ("Motion Picture", "Film" or "Movie" for a movie; "Television", "TV", "Series",
"Season", "HBO", "Netflix" or "Channel" for a show), then to the one nearest its first release year. The year is the album's
original date when the tags have one, so a reissue still finds its movie. With only
one candidate the year is never checked.

**Seasons.** An album's title can name seasons: "Season 3", "Season One", "Seasons 3 &
4", "Seasons 1–3", "Series 2". A season (or episode) lists the albums naming it first,
then the albums naming no season (volumes, a limited series), oldest first; albums
naming other seasons are left out, so specials (season 0) list only the albums naming
no season. A TV show lists all of them, oldest first. For an
album, the movie or TV show item carries the seasons the album names in
`ListItem.Property(soundtrack_seasons)` (`3, 4`); it is empty when the album names
none.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `movie`, `tvshow`, `season`, `episode`, `album` | required | The item's type |
| `id` | the item's `DBID` | required | The item |

```xml
<content sortby="userpreference">plugin://script.copacetic.helper/?info=soundtracks&amp;type=$INFO[ListItem.DBType]&amp;id=$INFO[ListItem.DBID]</content>
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
(`musicbrainztrackid`). Another type, no id in the library, no count from
ListenBrainz or no token: no item.

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
