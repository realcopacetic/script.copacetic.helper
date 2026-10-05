# Library Listings

These plugin paths fill a container with items from your video library. Use them as
widgets or in any list. Each item carries the usual library infolabels and artwork,
so your existing layouts work with them.

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
- No item is a folder, not even a TV show. Its path is the library file path. To
  open a TV show, use your own `<onclick>`, for example
  `ActivateWindow(Videos,videodb://tvshows/titles/$INFO[ListItem.DBID]/,return)`.

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

## `actor_credits`, `director_credits`, `writer_credits`, `genre_credits`, `studio_credits`

Everything in the library credited to one person, genre or studio. Each kind of item is sorted newest
first, and the kinds follow each other in the order below.

| `info=` | Searches |
|---|---|
| `actor_credits` | movies, then TV shows |
| `director_credits` | movies, then music videos |
| `writer_credits` | movies, then episodes |
| `genre_credits` | movies, then TV shows |
| `studio_credits` | movies, then TV shows |

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `label` | a name | — | The person, genre or studio to search for, as the library names it. |
| `type` | a media type from the table above | — | Search that kind only, e.g. `movie` for a movie's "more from" rail. |
| `exclude_value` | any text | — | Leave out items whose `exclude_key` field equals this. Use it to hide the item you came from. |
| `exclude_key` | a Kodi library filter field | `title` | The field `exclude_value` is compared with. |

```xml
<content>plugin://script.copacetic.helper/?info=director_credits&amp;label=$INFO[ListItem.Director]&amp;exclude_value=$INFO[ListItem.Title]</content>
```

Pass one name in `label`. `ListItem.Director` holds several names, separated by
` / `, when an item has more than one director; that string matches nobody. The
[`metadata`](metadata.md#metadata) path with `random_pick=true` gives one director
and one genre, and always one studio. Names and titles may hold `&` (`Action &
Adventure`): the helper splits its parameters only where `&name=` follows, where a
`videodb://` filter in the path would cut the value at the `&`. For a random order,
add `sortby="random"` to the container's `<content>`.

---

## The add-on's own directory

Opening `plugin://script.copacetic.helper/` with no `info=` lists two folders, so
users can add them as widgets from Kodi's add-on browser:

| Folder | Path |
|---|---|
| Continue watching | `plugin://script.copacetic.helper/?info=in_progress&type=mixed` |
| Next up | `plugin://script.copacetic.helper/?info=next_up&type=tvshow` |

A plugin path with an `info=` the add-on does not know returns an empty list.
