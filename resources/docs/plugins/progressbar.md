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
| `date_format` | [strftime](https://docs.python.org/3/library/datetime.html#format-codes) codes | `%d %b` | Format of `next_air`, e.g. `14 Nov`. Write `%` as `%25` in the URL when the next two characters could read as hex (`%Bd`). |
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
| `ListItem.Property(next_episode)` | A started TV show or season with unwatched episodes: the lowest unwatched episode outside the specials, e.g. `S02E10`. |
| `ListItem.Property(new)` | `true` for a started TV show whose newest unwatched episode (specials included) was added after the show was last played. |
| `ListItem.Property(next_air)` | A TV show: its next episode's air date from the cached TMDb data, in `date_format`. |

Each context value is empty when it doesn't apply, so a label can test them in turn
with `String.IsEmpty`. They are worked out after the bar has moved, so they never
delay the placement; the item itself returns once they are ready.

## How the context values are worked out

- **`time_left`**: `ListItem.Duration` × (100 − `ListItem.PercentPlayed`) / 100.
  `PercentPlayed` is a whole number, so the result is within half a percent of the
  runtime.
- **Started** means what Kodi's `inprogress` smart-playlist rule means for a show,
  read from the focused item (`WatchedEpisodes`, `InProgressEpisodes`,
  `UnwatchedEpisodes`): some episodes watched and some not, or none watched and at
  least one part-watched. A show or season that isn't started, is fully watched or
  isn't in the library makes no episode call.
- **`next_episode`** and **`new`**: one `VideoLibrary.GetEpisodes` call for the
  started show's unwatched episodes (a season's own, or the whole show for
  *All seasons*, which sends no `season`: `GetEpisodes` rejects `-1`).
  `next_episode` is the episode [`next_up`](library.md#next_up) lists for the show.
  For `new`, one `VideoLibrary.GetTVShowDetails` call reads the show's `lastplayed`:
  `ListItem.LastPlayed` gives a date with no time.
- **`next_air`**: TMDb's next episode air date, read from the add-on's cache only;
  this path never asks TMDb. The [metadata](metadata.md#tmdb-lookups) plugin fills
  the cache when called with `enrich_with_tmdb=true` and a TMDb token is set. Until
  it has, and once the date is past, `next_air` is empty.

## Focus guard

The guard is checked before the value is worked out and again before any control
moves. If focus moved on in between, the list item is still returned without the
context values, and no control moves.
