# Background Service

The helper runs a background service from the moment Kodi starts. It does work your
skin doesn't have to ask for: it builds the skin's generated XML files, watches the
player, plays and tidies up trailers, queues the next episode, and runs a background
slideshow. It talks to your skin through window properties on the Home window and
reads skin settings and skin strings that your skin owns.

This page is the overview and the full list of everything the service sets and reads.
Each feature has its own page:

- [Trailers](trailers.md) — the trailer session that `action=play_trailer` starts.
- [Player properties](player.md) — window properties for the item that is playing.
- [Play next](playnext.md) — queues the next episode of a TV show.
- [Slideshow](slideshow.md) — a background slideshow of library fanart.

The service does not process artwork for the focused item. That is done by the
[artwork plugin](../plugins/artwork.md), which your skin calls from a container.

## Opting in

The service only polls for a skin that opts in. A skin opts in by shipping the
builder folder structure: at least one of these folders inside
`extras/templates/` in the skin:

| Folder | Used for |
|---|---|
| `mappings/` | Builder mappings |
| `configs/` | Builder configs |
| `controls/` | Builder controls |
| `variables/` | Variables builder |
| `includes/` | Includes builder |
| `expressions/` | Expressions builder |

The folders can be empty. See the [builder docs](../builders/01-overview.md) for what
goes in them.

The service checks again whenever the active skin changes.

## What runs when

### At start-up

1. The service starts and attaches the player monitor. From now on, playback events
   are handled for any skin (see [Player properties](player.md) and
   [Play next](playnext.md)).
2. If the skin opts in, the build runs once:
   - **Dev mode off (default):** the service seeds the runtime state if needed. It
     rebuilds every output if the runtime state was just seeded or the templates
     changed. Otherwise it only builds outputs that are missing.
   - **Dev mode on:** the service rebuilds every output, then runs `ReloadSkin()`. If
     *Reset on next start* is also on, it first deletes all outputs and the runtime
     state, then turns that setting off again.

   Dev mode (`dev_mode`) and *Reset on next start* (`dev_reset`) are settings of the
   helper add-on, in its *Skinners* category.

### The poll loop

While the skin opts in and the screensaver is not active, the service runs a loop
once a second. Each pass it:

1. checks the trailer session (see [Trailers](trailers.md));
2. moves the slideshow on if the interval has passed (see [Slideshow](slideshow.md)).

When the screensaver starts, the loop pauses. When the screensaver stops, or the
user switches to a skin that opts in, the loop resumes. While paused, the service
checks again every 10 seconds.

### On playback events

The player monitor handles playback start, stop, end and error. It runs for any skin,
whether or not the poll loop is active.

## Full contract

All window properties are on the Home window (`10000`). In XML, read them with
`Window(home).Property(name)`.

### Window properties the service sets

| Property | Set when | Value | Cleared when | Page |
|---|---|---|---|---|
| `trailer_state` | A trailer starts, goes stale or is retired | `playing`, `orphaned` | Playback stops, ends or fails; a real video starts | [Trailers](trailers.md) |
| `trailer_file` | A requested trailer starts | The trailer's `Player.Filenameandpath` | As `trailer_state` | [Trailers](trailers.md) |
| `trailer_played_item` | Never set by the service | — | A trailer fails to play, or a request never starts | [Trailers](trailers.md) |
| `player_tvshowtitle` | An episode starts | TV show title | Playback stops, ends or fails | [Player properties](player.md) |
| `player_season` | An episode starts | Season number | As above | [Player properties](player.md) |
| `player_tvshowid` | A library episode starts | TV show database id | As above | [Player properties](player.md) |
| `player_setid` | A library movie in a set starts | Movie set database id | As above | [Player properties](player.md) |
| `player_userrating` | A song starts | User rating | As above | [Player properties](player.md) |
| `player_artist` | A song starts | Artist (all artists in one string) | As above | [Player properties](player.md) |
| `player_artist_1` … `player_artist_3` | A song starts | First, second and third artist | As above | [Player properties](player.md) |
| `player_albumartist` | A song starts | Album artist | As above | [Player properties](player.md) |
| `player_album` | A song starts | Album title | As above | [Player properties](player.md) |
| `player_disc` | A song starts | Disc number | As above | [Player properties](player.md) |
| `slideshow_fanart` | Each slide | Path to the original fanart | Never (replaced by the next slide) | [Slideshow](slideshow.md) |
| `slideshow_blur` | Each slide | Path to the blurred fanart | Never (replaced by the next slide) | [Slideshow](slideshow.md) |
| `slideshow_darken` | Each slide | Darken percentage, `0`–`100` | The slide has no darken value | [Slideshow](slideshow.md) |
| `slideshow_clearlogo` | Each slide | Path to the cropped clearlogo | The slide has no clearlogo | [Slideshow](slideshow.md) |
| `slideshow_title` | Each slide | Item label | The slide has no title | [Slideshow](slideshow.md) |

The service also clears the trailer request properties that `action=play_trailer`
sets (`trailer_item`, `trailer_source`, `trailer_focus_ids`, `trailer_viewport`,
`trailer_pending_since`) when a trailer session ends.

### What the service reads from the skin

| Name | Kind | Read when | Page |
|---|---|---|---|
| `extras/templates/<folder>/` | Skin folder | Start-up and skin change | This page |
| `trailer_state` | Window property | On playback start, error and each poll | [Trailers](trailers.md) |
| `trailer_item` | Window property | When checking if a trailer is stale | [Trailers](trailers.md) |
| `trailer_source` | Window property | Staleness check and trailer zoom | [Trailers](trailers.md) |
| `trailer_focus_ids` | Window property | When checking if a trailer is stale | [Trailers](trailers.md) |
| `trailer_viewport` | Window property | When a trailer starts | [Trailers](trailers.md) |
| `trailer_pending_since` | Window property | Each poll while a request is pending | [Trailers](trailers.md) |
| `trailer_file` | Window property | Each poll | [Trailers](trailers.md) |
| `playnext_enabled` | Skin setting (bool) | When a library episode starts | [Play next](playnext.md) |
| `slideshow_source`, `slideshow2_source` | Skin string | Each poll | [Slideshow](slideshow.md) |
| `slideshow_path`, `slideshow2_path` | Skin string | Each poll | [Slideshow](slideshow.md) |
| `slideshow2` | Skin setting (bool) | Each poll | [Slideshow](slideshow.md) |
| `slideshow_start`, `slideshow2_start` | Skin string | Each poll, when `slideshow2` is on | [Slideshow](slideshow.md) |
| `slideshow_interval` | Skin string | After each slide | [Slideshow](slideshow.md) |
| `slideshow_artwork_params` | Window property | Before each slide | [Slideshow](slideshow.md) |

The service expects no control ids of its own. The trailer feature uses the control
ids your skin passes in `focus_ids`.
