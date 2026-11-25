# Progress Bar Helper

Works out how much of the focused item has been watched, returns it on a list item,
and moves and sizes a progress bar group to fit your layout. The same item carries
short context values for labels beside the bar: time left and the end time, the next
episode and its runtime, a "new" flag, the next air date, a newly aired episode,
whether a show has ended, and the track to play next on an album.

It handles movies, episodes, TV shows, seasons, movie sets and music albums. For a set
it counts the watched movies in the set; for an album, the songs heard (see
[Albums](#albums)). With `resolution_span` it measures a picture's size instead (see
[Pictures](#pictures)).

## Plugin path

```xml
<control type="list" id="9500"><!-- hidden helper container; id is an example -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=progressbar&amp;target=50&amp;focus_guard=$INFO[Container(50).CurrentItem]&amp;target_id=4010&amp;anchor_id=4000&amp;valign=bottom&amp;track_h=4</content>
</control>
```

**Served.** As a [served list](../service/serve.md) (Copacetic's `9010` with probe
`6910`; an info dialog's own item with `6911`), the probe holds these params without the
`plugin://…?` prefix, and an album's bar is served again by the service itself
([Albums](#albums)).

## Controls the skin provides

`target_id` is the id of a group in the current window (with `dialog=true` or
`target=item`, in the info dialog). The helper finds the other controls by adding
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
| `dialog` | `true`, `false` | `false` | The controls are in an info dialog, not the current window. `target=item` implies it. See [Plugin Helpers](plugin_helpers.md#the-focus-guard). |
| `progress_id` | control id | `target_id + 1` | Progress control id. |
| `btn_id` | control id | `target_id + 2` | Button id. |
| `img_id` | control id | `target_id + 3` | Image id. |
| `img_h` | whole number | the bar height | Height of the image. |
| `album_days` | whole number | `14` | How far back a song's last play counts towards an [album's](#albums) progress. |
| `resolution_span` | whole number | none | Measure a [picture](#pictures): the bar is its long edge against this many pixels. |
| `new_days` | whole number | `30` | How long an item stays `new`: a film or album was added, or an episode (for a show, its newest unwatched one, specials included) first aired, at most this many days ago. It also bounds `new_episode`: TMDB's last aired episode must have aired within it. |
| `date_format` | [strftime](https://docs.python.org/3/library/datetime.html#format-codes) codes | `%d %b` | Format of `next_air`, e.g. `14 Nov`. `%b` is Kodi's own short month name, in its GUI language; the other codes follow Python's C locale (English names). A literal `%%b` isn't supported. Write `%` as `%25` in the URL when the next two characters could read as hex (`%Bd`). |
| `language`, `tmdb_id`, `type`, `id`, `tvshowid`, `season` | | | Used only to find the TMDB data `next_air`, `next_air_episode`, `new_episode` and `show_status` read, as in [TMDB lookups](metadata.md#tmdb-lookups). Pass the same `language` as your `metadata` call, or leave it out in both. |
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

An album skips these rules; see [Albums](#albums). So does any item when the call
has `resolution_span`; see [Pictures](#pictures).

## Pictures

With `resolution_span` (Copacetic passes `3840` in its Pictures window's Listings view)
the value is the focused picture's long edge as a share of that many pixels, capped at
100: a 1920 × 1520 picture against 3840 is 50. The edge comes from
`ListItem.PictureResolution`, which Kodi writes as `1920 x 1520` once it has read the
picture's tags (`pictures.usetags`, on by default); a picture it couldn't read (Kodi
reads JPEG headers itself, other formats only through an image decoder add-on) is 0,
no bar. A picture has no library id or play count, so its item carries no context
values and costs no library call. It carries the picture's own labels instead,
`picture_resolution` and `picture_size` (see [What you get back](#what-you-get-back)):
a label beside the bar that reads them changes with the bar, never ahead of it, and a
picture with no resolution still has its size.

## Albums

A library album (`ListItem.DBType` `album`) is measured from its songs, with one
`AudioLibrary.GetSongs` call made before the bar moves. Its own
`ListItem.PlayCount` is no use: Kodi gives an album the rounded average of its songs'
play counts. A song counts as heard when it has a play count and its last play falls
within `album_days`. Kodi counts a song as played once 90% of it has played
(`audio` `playcountminimumpercent` in advancedsettings), so a skipped song isn't
heard.

- **Part-heard** (some of its running time heard within `album_days`, not all): the
  value is the share of the running time heard, and the album gets a film's labels:
  `ListItem.Duration` is its length, the resume point is the time heard, `time_left`
  is the length still to hear and `ListItem.EndTimeResume` the time it would end.
  Listening again a year later counts afresh.
- **Heard through, or untouched within `album_days`:** 0, no bar.
- **Resume point** (part-heard only): `album_next_track`, `album_next_title` and,
  on an album of more than one disc, `album_next_disc` name the track to play next,
  in disc and track order: the one after the song heard last, or, when that was the
  album's last track, the first not heard within `album_days`. Songs with the same
  last play (marked played together) count the latest track as heard last. Disc 0
  (no disc tag) is no disc of its own, so an album of discs 0 and 1 is one disc. A
  next track numbered 0 (no track tag) gives no resume point. A heard-through or
  untouched album has none. From the same `GetSongs` call (`disc`, `track`,
  `title`).
- **Kept current:** the bar and its resume point are served again when one of its
  songs is heard (from a library window or a helper queue), or it is marked: a
  [served](../service/serve.md) bar by the service itself, a plugin bar if the
  skin puts the service's `progress_version` in its URL (see
  [the service](../service/index.md#on-song-updates)): Kodi doesn't refresh the
  video-tagged progress item on a music library update.
- **New:** `new` is `true` for an album none of whose songs has ever played that
  was added within `new_days`. That costs one `AudioLibrary.GetAlbumDetails` call.

An album's item also carries `ListItem.Property(album)` `true`: the service skips its
re-serve only while the bar on top is another item's. The service reads the bar's
item in the topmost dialog, else the active window: from the list it last served the
bar in, or for a plugin bar container `9010`, so give that helper container this id
for the skip to work. The serve also writes the focused album's id to
`Window(home).Property(album_played)`
when every song has played and none is part-heard, or to `album_unplayed` when none
has, and clears the other; and to `album_resume` when its resume point is past the
first track, or clears it. The context menu's
[Mark as played and Mark as unplayed](../script/actions.md#mark_album) and
[Resume](../script/actions.md#play_album_resume) read them.

## What you get back

One list item in the helper container:

| Infolabel | Value |
|---|---|
| `ListItem.PercentPlayed` | The value above, 0–100, set as the resume point: in seconds for a part-watched movie or episode with a runtime, or a part-heard album (see below), otherwise out of 100. |
| `ListItem.Duration`, `ListItem.EndTimeResume` | A part-watched movie or episode with a runtime, or a part-heard album: its runtime, and the time it would end if resumed now, e.g. `22:30` (Kodi's own label, kept current). Empty or meaningless for anything else, so test `time_left` first. |
| `ListItem.Property(unwatchedepisodes)` | `ListItem.Property(UnwatchedEpisodes)` of the focused item. For a set, the number of unwatched movies. Empty when the item is watched. |
| `ListItem.Property(plays)` | A film or episode played twice or more: its play count, e.g. `3`. Empty below 2, and for every other type (an album's `ListItem.PlayCount` is its songs' average). |
| `ListItem.Property(time_left)` | A part-watched movie or episode, or a part-heard album: the runtime left, rounded up to the minute, e.g. `1h 23m`, `1h` or `48m`. The units are the add-on's strings 32615 (`h`) and 32616 (`m`), so they follow Kodi's language; `next_runtime` and `epg_time_left` use them too. |
| `ListItem.Property(next_episode)` | A TV show or season with unwatched episodes, started or not: the lowest unwatched episode outside the specials, e.g. `2x10` (`1x01` for a show not yet begun, `3x01` for a Season 3 not yet begun). |
| `ListItem.Property(next_runtime)` | That episode's library runtime, to the nearest minute, e.g. `43m`, `1h` or `1h 2m`. Empty when the library has no runtime for it (a duration only in its stream details isn't read). |
| `ListItem.Property(new)` | `true` for a TV show with an unwatched episode, specials included, started or not, that first aired within `new_days`; for an episode with no resume point and no play count that first aired within `new_days`; or for a film with neither, added within `new_days`; or for an album none of whose songs has played, added within `new_days`. |
| `ListItem.Property(next_air)` | A fully watched TV show: its next episode's air date from the cached TMDB data, in `date_format`. |
| `ListItem.Property(next_air_episode)` | With `next_air`: that episode's season and number, e.g. `3x01`, as `next_episode` writes them. Empty while the cached TMDB data predates it (see below). |
| `ListItem.Property(new_episode)` | A fully watched TV show: TMDB's last aired episode when it is later than the library's newest and first aired within `new_days`, e.g. `3x05`. A notice only: nothing to play. |
| `ListItem.Property(show_status)` | A fully watched TV show: `ended` (TMDB's *Ended* or *Canceled*) or `returning` (*Returning Series*); empty for TMDB's other states. |
| `ListItem.Property(album)` | `true` for a library album; empty otherwise. |
| `ListItem.Property(picture_resolution)` | With `resolution_span` only: the focused item's `ListItem.PictureResolution`, e.g. `1920 x 1520`; empty when Kodi couldn't read it. |
| `ListItem.Property(picture_size)` | With `resolution_span` only: the focused item's `ListItem.Size`, e.g. `1.4 MB`. |
| `ListItem.Property(album_next_track)` | A part-heard album's [resume point](#albums): the next track's number, e.g. `8`. |
| `ListItem.Property(album_next_title)` | With `album_next_track`: that song's title. |
| `ListItem.Property(album_next_disc)` | With `album_next_track`, on an album of more than one disc: that song's disc number, e.g. `2`. |

Each context value is empty when it doesn't apply, so a label can test them in turn
with `String.IsEmpty`. They are worked out after the bar has moved, so the bar is
placed first, but it appears only when the item returns: a skin that shows the bar
once the helper container has finished updating (`!Container(id).IsUpdating`) waits
for them too. The library calls they add, per focus:

| Focused item | Calls | Which |
|---|---|---|
| Show or season with episodes left, started or not (a favourite's season too) | 1 | `GetEpisodes` |
| Fully watched show | 0 to 2 | `GetTVShowDetails` for its TMDB id, only with a TMDB token and no `UniqueID(tmdb)`; `GetEpisodes` for the newest episode, only when TMDB's cached data has a last aired episode |
| Unwatched film (no resume point, no play count) | 1 | `GetMovieDetails` (`dateadded`) |
| Unwatched episode (no resume point, no play count) | 1 | `GetEpisodeDetails` (`firstaired`) |
| Album none of whose songs has played | 1 | `GetAlbumDetails` (`dateadded`) |
| Watched or part-watched film or episode, fully watched or Specials season, set, album with a song played, plugin item | 0 | |

A movie set's value itself costs one `GetMovieSetDetails` call (rule 3 above), and an
album's one `GetSongs` call, both made before the bar moves.

To see the cost on your device, turn on *Troubleshooting → Enable extra debug logs*
in the add-on's settings and look for `PluginHandlers → progressbar took … seconds`
in the Kodi log: compare a show with episodes left with a watched movie.

## How the context values are worked out

- **`time_left`**: `ListItem.Duration` × (100 − `ListItem.PercentPlayed`) / 100.
  `PercentPlayed` is a whole number, so the result is within half a percent of the
  runtime.
- **The resume point in seconds** (a part-watched movie or episode): the returned
  item gets the focused item's `ListItem.Duration` as its runtime and
  `ListItem.Duration` × `ListItem.PercentPlayed` / 100 as its resume point, so Kodi
  works out its `ListItem.EndTimeResume` (now + runtime − resume point) every frame
  and it never goes stale. It ends when `time_left` runs out, within the same half
  percent. `ListItem.PercentPlayed` is the resume point over its total in Kodi, so it
  is the same whole number in either form; with no runtime the item keeps the
  out-of-100 form. No library call: the runtime is the one `time_left` reads.
- **`next_episode`** and **`new`** (shows and seasons): one
  `VideoLibrary.GetEpisodes` call for the unwatched episodes of a show or season with
  any left, started or not (a season's own, or the whole show for *All seasons*,
  which sends no `season`: `GetEpisodes` rejects `-1`). A show or season with none
  left, and anything not in the library, make no episode call. A favourite's season
  (an add-on item, with no `TvShowDBID`) is found by its `Property(tvshowid)`.
  `next_episode` is the episode [`next_up`](library.md#next_up) lists for the show,
  or the season's lowest unwatched one: its first episode if it isn't started, and
  `next_runtime` is its `runtime` from the same call (seconds in JSON-RPC; without
  `streamdetails` asked for, that's the library's runtime alone). The
  Specials season (season 0) has none and makes no call. `new` needs the newest
  `firstaired` among those unwatched episodes, specials included, on or after the
  date `new_days` before today, started or not: a part-watched episode still counts,
  as it has no play count. So a show stays new while you start its new episodes,
  and a show added with its back catalogue isn't new however recently it was added.
  A special counts by its air date like any episode: an old one is never new, a
  recently aired one is. Seasons get no `new`.
- **`new`** (films and episodes): a film or episode with no resume point and no play
  count, read with one `VideoLibrary.GetMovieDetails` or
  `VideoLibrary.GetEpisodeDetails` call. A film's `dateadded` must be within
  `new_days` of now; an episode's `firstaired` (a date) on or after the date
  `new_days` before today. A future air date (a file released early) counts; an
  episode with no air date is never new. `ListItem.DateAdded` and
  `ListItem.Premiered` can't stand in: they print the date in the region's short date
  format, which the user can change.
- **`next_air`**, **`next_air_episode`**, **`new_episode`** and **`show_status`**:
  only for a fully watched show (some episodes watched, none left) with a TMDB token
  set; any other show makes no lookup for them. TMDB's next episode air date, season
  and number, its last aired episode and its status, read from the add-on's cache
  only; this path never asks TMDB. `new_episode` costs one `VideoLibrary.GetEpisodes`
  call for the library's newest episode outside the specials (sorted `episode`,
  descending, limit 1), and is set only when TMDB's is later: an episode missing
  mid-run, or one TMDB numbers differently (TVDB order, episode groups), is no news.
  TMDB's must also have aired within `new_days` (on or after the date `new_days`
  before today), so an ended show's long-past last episode is no news either; the
  call is skipped otherwise.
  A special (season 0) is left out, as `next_episode` leaves it out. The [metadata](metadata.md#tmdb-lookups)
  plugin fills the cache when called with `enrich_with_tmdb=true`. Until it has, all
  four are empty; once the next air date is past, `next_air` and `next_air_episode`
  are empty. An entry cached by an older version of the
  add-on holds the date alone (or no last aired episode, its air date and status), so
  `next_air_episode` (or `new_episode` and `show_status`) stays empty until a
  `metadata` call fetches the show again, once the entry is 7 days old. The cache is kept per
  TMDB language, so a `metadata` call with a `language` fills it for a `progressbar`
  call with the same `language` only.
  A show whose listing has no `UniqueID(tmdb)` (one scraped with TVDB as its
  default id) costs one `VideoLibrary.GetTVShowDetails` call to find its TMDB id, as
  the metadata plugin does.

## Focus guard

The guard is checked before the value is worked out, before any control moves, and
after the move (so before the library call of the context values). Once focus has
moved on, the list item is still returned without the context values, and nothing
else runs: no control moves if it hadn't yet, and no library call is made.

---

## `epg_time_left`

Not the progress bar: one item whose `ListItem.Property(time_left)` is the time left
until a TV guide programme ends, rounded up to the minute (`1h 23m`, `1h` or `48m`).
Kodi has a time left only for the programme it is playing (`PVR.EpgEventRemainingTime`),
so the helper works it out from the URL alone, against the clock: nothing is read from
the window, so a move while the call runs changes nothing.

- **Start:** the end of `programme`, the programme's path. A guide item's path is
  `pvr://guide/<epg id>/<start>.epg`, with the start in UTC as `YYYY-MM-DD HH:MM:SS`, so
  no regional time format is parsed.
- **Runtime:** `runtime`, the programme's `ListItem.Duration(secs)`.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `programme` | `$INFO[ListItem.FolderPath]` | required | The programme's path, unique to it. Echoed as the item's label, so the skin can check the value is for the focused programme. |
| `runtime` | `$INFO[ListItem.Duration(secs)]` | required | The programme's runtime in seconds. |
| `visit` | any text | empty | Echoed as `ListItem.Property(visit)`, so the skin can tell a value from this visit to the window from one it kept from the last. |

Any other parameter, such as `minute` in the example below, is not read: it only
changes the path.

There's no item when the clock is past the programme's end. Kodi keeps a
timeshifted channel's programme on air by its playback time.

The value is fixed when the call returns. To count down, add a parameter that changes
each minute, such as `$INFO[System.Time(hh:mm)]`: Kodi calls the path again when it
changes. Pass the path only while the programme is on air.

```xml
<content>plugin://script.copacetic.helper/?info=epg_time_left&amp;programme=$INFO[ListItem.FolderPath]&amp;runtime=$INFO[ListItem.Duration(secs)]&amp;visit=$INFO[Window(home).Property(pvrguide_visit)]&amp;minute=$INFO[System.Time(hh:mm)]</content>
```
