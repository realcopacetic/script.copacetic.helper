# Progress Bar Helper

Works out how much of the focused item has been watched, returns it on a list item,
and moves and sizes a progress bar group to fit your layout. The same item carries
short context values for a label beside the bar: time left, the next episode, a "new"
flag and the next air date.

It handles movies, episodes, TV shows, seasons and movie sets. For a set it counts the
watched movies in the set.

## Plugin path

```xml
<control type="list" id="9500"><!-- hidden helper container; id is an example -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=progressbar&amp;target=50&amp;focus_guard=$INFO[Container(50).CurrentItem]&amp;target_id=4010&amp;anchor_id=4000&amp;valign=bottom&amp;track_h=4</content>
</control>
```

## Controls the skin provides

`target_id` is the id of a group in the current window (with `dialog=true` or
`target=item`, in the topmost dialog). The helper finds the other controls by adding
to it:

| Control | Id | Required | What the helper does |
|---|---|---|---|
| Group | `target_id` | yes | Moved to the rectangle's x and y. Grown (never shrunk) to at least the rectangle's size. |
| Progress control | `target_id + 1`, or `progress_id` | yes | Set to the rectangle's width and height. |
| Button | `target_id + 2`, or `btn_id` | no | Centred in the unwatched part of the bar (between the played point and the end), kept inside the bar, and centred vertically. Needs an explicit `<width>` and `<height>`. |
| Image | `target_id + 3`, or `img_id` | no | Set to the rectangle's width and `img_h` tall, centred vertically on the bar. |
| Extra control | `target_id + 4` | no | Set to the rectangle's width and height. |

Put the other controls inside the group. Their positions are relative to the group.

## Parameters

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `target_id` | control id | — | **Required.** The group id. |
| `target` | container id, or `item` | — | Container whose focused item is measured. Omit to use `Container` (the current container); `item` measures the window's own item. |
| `dialog` | `true`, `false` | `false` | The controls are in the topmost dialog, not the current window. `target=item` implies it. See [Plugin Helpers](plugin_helpers.md#the-focus-guard). |
| `progress_id` | control id | `target_id + 1` | Progress control id. |
| `btn_id` | control id | `target_id + 2` | Button id. |
| `img_id` | control id | `target_id + 3` | Image id. |
| `img_h` | whole number | the bar height | Height of the image. |
| `new_days` | whole number | `30` | How long an item stays `new`: its newest unwatched episode (a show) or the film was added at most this many days ago. |
| `date_format` | [strftime](https://docs.python.org/3/library/datetime.html#format-codes) codes | `%d %b` | Format of `next_air`, e.g. `14 Nov`. Write `%` as `%25` in the URL when the next two characters could read as hex (`%Bd`). |
| `language`, `tmdb_id`, `type`, `id`, `tvshowid`, `season` | | | Used only to find the TMDb data `next_air` reads, as in [TMDb lookups](metadata.md#tmdb-lookups). Pass the same `language` as your `metadata` call, or leave it out in both. |
| `focus_guard`, `focus_ids`, `identity_labels`, `identity_container` | | | Focus guard. See [Plugin Helpers](plugin_helpers.md#3-guarding-against-fast-scrolls-and-container-moves). |

Placement parameters (`coords`, `anchor_id`, `inset`, `track_w`, `track_h`,
`halign`, `valign`, `hpad`, `vpad`, `outside`) set the rectangle. See
[Placement Options](placement.md). With no `coords` or `anchor_id`, the item is
still returned but nothing moves.

## How the value is worked out

The first rule that matches wins:

1. The first of `ListItem.PercentPlayed`, `ListItem.Property(WatchedEpisodePercent)`
   and `ListItem.Property(WatchedProgress)` that is a whole number above 0.
2. If the item is watched (`ListItem.Overlay` is `OverlayWatched.png` or
   `ListItem.PlayCount` is above 0): 100.
3. For a movie set: the share of movies in the set with a play count, from
   `VideoLibrary.GetMovieSetDetails`.
4. Otherwise: 0.

## What you get back

One list item in the helper container:

| Infolabel | Value |
|---|---|
| `ListItem.PercentPlayed` | The value above, 0–100 (set as the resume point out of 100). |
| `ListItem.Property(unwatchedepisodes)` | `ListItem.Property(UnwatchedEpisodes)` of the focused item. For a set, the number of unwatched movies. Empty when the item is watched. |
| `ListItem.Property(time_left)` | A part-watched movie or episode: the runtime left, rounded up to the minute, e.g. `1h 23m` or `48m`. |
| `ListItem.Property(next_episode)` | A TV show or season with unwatched episodes, started or not: the lowest unwatched episode outside the specials, e.g. `S02E10` (`S01E01` for a show not yet begun, `S03E01` for a Season 3 not yet begun). |
| `ListItem.Property(new)` | `true` for a TV show whose newest unwatched episode (specials included) was added within `new_days`, and, once the show is started, after it was last played; or for a film with no resume point and no play count, added within `new_days`. |
| `ListItem.Property(next_air)` | A fully watched TV show: its next episode's air date from the cached TMDb data, in `date_format`. |

Each context value is empty when it doesn't apply, so a label can test them in turn
with `String.IsEmpty`. They are worked out after the bar has moved, so the bar is
placed first, but it appears only when the item returns: a skin that shows the bar
once the helper container has finished updating (`!Container(id).IsUpdating`) waits
for them too. The library calls they add, per focus:

| Focused item | Calls | Which |
|---|---|---|
| Started show (anything watched or in progress; for the add-on's own items, anything watched or played) | 1 or 2 | `GetEpisodes`; `GetTVShowDetails` (`lastplayed`) only when its newest unwatched episode was added within `new_days` |
| Unwatched show (not started) | 1 | `GetEpisodes` |
| Fully watched show | 0 or 1 | `GetTVShowDetails` for its TMDb id, only with a TMDb token and no `UniqueID(tmdb)` |
| Season with episodes left, started or not (a favourite's too) | 1 | `GetEpisodes` |
| Unwatched film (no resume point, no play count) | 1 | `GetMovieDetails` (`dateadded`) |
| Watched or part-watched film, fully watched or Specials season, episode, set, plugin item | 0 | |

A movie set's value itself costs one `GetMovieSetDetails` call (rule 3 above), made
before the bar moves.

To see the cost on your device, turn on *Troubleshooting → Enable extra debug logs*
in the add-on's settings and look for `PluginHandlers → progressbar took … seconds`
in the Kodi log: compare a started show with a movie.

## How the context values are worked out

- **`time_left`**: `ListItem.Duration` × (100 − `ListItem.PercentPlayed`) / 100.
  `PercentPlayed` is a whole number, so the result is within half a percent of the
  runtime.
- **Started** (a show, for `new`) means what Kodi's `inprogress` smart-playlist rule
  means, read from the focused item (`WatchedEpisodes`, `InProgressEpisodes`,
  `UnwatchedEpisodes`): some episodes watched and some not, or none watched and at
  least one part-watched. Kodi's own items always carry `InProgressEpisodes` (`0`
  too) and follow that rule exactly. The add-on's own show items (`random_tvshows`,
  credits, favourites) carry none, as JSON-RPC has no in-progress count for a show,
  so one of them is started when any episode is watched or it has a
  `ListItem.LastPlayed`: played at all, even stopped before a resume point was kept.
  So the same show can read started on an add-on tile and unstarted in Kodi's own
  library views, and its `new` can differ between the two. To reset such a show
  whose plays are all unfinished, use *Mark as watched* then *Mark as unwatched*:
  *Mark as unwatched* alone isn't offered without a watched episode, and it skips
  episodes with no play count, so their last-played dates stay.
- **`next_episode`** and **`new`** (shows and seasons): one
  `VideoLibrary.GetEpisodes` call for the unwatched episodes of a show or season with
  any left, started or not (a season's own, or the whole show for *All seasons*,
  which sends no `season`: `GetEpisodes` rejects `-1`). A show or season with none
  left, and anything not in the library, make no episode call. A favourite's season
  (an add-on item, with no `TvShowDBID`) is found by its `Property(tvshowid)`.
  `next_episode` is the episode [`next_up`](library.md#next_up) lists for the show,
  or the season's lowest unwatched one: its first episode if it isn't started. The
  Specials season (season 0) has none and makes no call. `new` needs the newest
  unwatched episode's `dateadded` within `new_days` of now. For a started show it
  must also be later than the show's `lastplayed`, read with one
  `VideoLibrary.GetTVShowDetails` call, made only when the first test passes
  (`ListItem.LastPlayed` gives a date with no time). Seasons get no `new`.
- **`new`** (films): a film with no resume point and no play count whose `dateadded`
  is within `new_days`, read with one `VideoLibrary.GetMovieDetails` call.
  `ListItem.DateAdded` can't stand in: it prints the date in the region's short date
  format, which the user can change, and with no time.
- **`next_air`**: only for a fully watched show (some episodes watched, none left)
  with a TMDb token set; any other show makes no lookup for it. TMDb's next episode
  air date, read from the add-on's cache only; this path never asks TMDb. The
  [metadata](metadata.md#tmdb-lookups) plugin fills the cache when called with
  `enrich_with_tmdb=true`. Until it has, and once the date is past, `next_air` is
  empty. The cache is kept per TMDb language, so a `metadata` call with a `language`
  fills it for a `progressbar` call with the same `language` only.
  A show whose listing has no `UniqueID(tmdb)` (one scraped with TVDB as its
  default id) costs one `VideoLibrary.GetTVShowDetails` call to find its TMDb id, as
  the metadata plugin does.

## Focus guard

The guard is checked before the value is worked out, before any control moves, after
the move (so before the first library call of the context values), and between the
two library calls for a started show. Once focus has moved
on, the list item is still returned without the context values, and nothing else
runs: no control moves if it hadn't yet, and no further library call is made.
