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

The service only works for a skin that opts in; in any other skin it does nothing
and the helper's context menu items stay hidden. A skin opts in by shipping the
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

The service checks again whenever the active skin changes or is updated in place
(same folder, new version), so the user can switch to your skin (or away from it) at
any time without restarting Kodi.

## What runs when

### When a skin that opts in becomes active

This happens at start-up and each time the user switches to such a skin. After an
in-place update (same folder, new version, once Kodi has registered it) only step 1
runs again: the player monitor and slideshow keep running, so playback isn't
interrupted. In order:

1. The build check runs on the skin's own runtime state and resolver cache
   ([one pair per skin](../builders/09-runtime-state.md#life-of-the-file); in
   Copacetic 2 it first takes over the pair older helpers shared, while it has no
   runtime state of its own):
   - **Dev mode off (default):** the service seeds the runtime state if needed. It
     rebuilds every output if the runtime state was just seeded, or the resolver
     cache is missing or was built for another skin or another version of the skin
     or helper, or an output on disk isn't the one its build wrote: Kodi profiles
     share the skin's folder, but each keeps its own runtime state and cache, so a
     switch to a profile whose choices differ rebuilds. Otherwise it only builds
     outputs that are missing. A file is written
     only when its content changed; if one was, it then runs `ReloadSkin()`, so the
     skin loads the new files at once. The reload first waits until Kodi has run the
     commands already queued, and repeats that until no yes/no dialog showed
     meanwhile: a skin still loading, or a *Yes* to an install's switch prompt, would
     otherwise get the reload inside the next *Keep this skin?* dialog, which a reload
     answers no. The wait gives up after a minute. If the user switched skin since
     the check began, the reload is dropped; if the skin started updating, it waits
     for the next check. For a skin update it first sets `helper_reloading` to
     `reload`, so the skin can cover the reload, and clears it if the reload is dropped
     or postponed. It doesn't set it during fullscreen video, or on a start, a switch
     into the skin or a helper restart. If nothing was written, the skin is not
     reloaded. The output files are generated, not for editing: a hand edit lasts until
     the next check or rebuild. Reinstalling the same version brings back the zip's
     factory files, and they stay until the next start, a switch back into the skin,
     `action=rebuild` or a settings change.
   - **Dev mode on:** the service rebuilds every output, then runs `ReloadSkin()`,
     waiting, dropped or postponed as above, with the same `helper_reloading`. If *Reset on next start* is also on for this skin, it
     first deletes the skin's outputs, runtime state and resolver cache, then turns
     that setting off again.

   Dev mode (`dev_mode`) and *Reset on next start* (`dev_reset`) are settings of the
   helper add-on, in its *Developers* category. Dev mode is one switch for every skin
   in the profile, so it applies to whichever skin is active. A reset belongs to the
   skin that was active when it was turned on: the service writes that skin's id to
   `dev_reset.txt` in the add-on's profile folder when the settings are saved, and
   only that skin's next check uses it. Turned on in a skin without the builder
   (Estuary), it waits for the next builder skin it is in: that skin's next check
   (a start, a switch in or an update) or `rebuild` with `reset=true` takes it.
   Other skins leave it on and keep their files; turning it off deletes the file.
   The settings are saved once, on OK, so to move a reset to another skin, turn it
   off and press OK, then turn it on again in that skin.

   If the build raises an exception, the service logs the traceback at error level,
   shows a notification, doesn't reload, and carries on with the steps below on
   whatever XML is there. That may be none after a first install or a skin update,
   which leaves the skin degraded until a build succeeds. The next start tries again.
2. The service attaches the player monitor, which handles playback from now on (see
   [Player properties](player.md) and [Play next](playnext.md)). It sets the
   [speed dial](../plugins/speed_dial.md#window-properties) pinned-item properties and,
   if something is already playing, that file's player properties.
3. It sets `helper_active`, which shows the helper's
   [context menu items](../script/actions.md#items-the-helper-adds-to-the-context-menu),
   and, if the skin's templates or `16x9/` XML name `info=speed_dial`,
   `helper_speed_dial`, which shows Pin to speed dial and Unpin among them. A skin
   update checks for `info=speed_dial` again.
4. The poll loop starts, and with it the slideshow.

### When the active skin changes, or the service stops

Whenever the active skin changes (to any skin, even another that opts in, or one whose
`addon.xml` the helper can't read, which then stays inactive), and when
the service stops (Kodi exits, the profile changes, the helper is updated or
disabled), the service releases what it set. It clears `helper_active` and
`helper_speed_dial`, so the context menu items hide. It stops the trailer it started,
whether it is playing, paused or full screen (rewound first, so nothing is marked
watched), clears the trailer,
player, speed dial and slideshow properties, and detaches the player monitor. If the
new skin opts in, everything [starts again](#when-a-skin-that-opts-in-becomes-active)
for it; otherwise nothing else runs until a skin that opts in is active.

### The poll loop

While the skin opts in and the screensaver is not active, the service runs a loop
once a second. Each pass it:

1. checks the trailer session (see [Trailers](trailers.md));
2. clears `player_seek_offset` once Kodi's seek display is over (see
   [Seek offset](player.md#seek-offset));
3. moves the slideshow on if the interval has passed (see [Slideshow](slideshow.md));
4. moves a held speed dial update from `speed_dial_held` to `speed_dial_version` once
   focus is no longer on a speed dial item (see
   [Speed dial](../plugins/speed_dial.md#plays-dont-reload-a-focused-list));
5. once a day, starting with the first pass, deletes saved TMDb, ListenBrainz and
   Deezer answers in the add-on's `_lookup.db` that expired more than 30 days ago. If the
   database is busy, it tries again an hour later.

When the screensaver starts, the loop pauses; when it stops, the loop resumes. While
paused, or while the skin doesn't opt in, the service checks again every 2 seconds.

### On playback events

The player monitor handles playback start, stop, end and error, seeks, chapter jumps
and speed changes while a skin that opts in is active, including while the screensaver pauses the poll loop.

## Full contract

All window properties are on the Home window (`10000`). In XML, read them with
`Window(home).Property(name)`.

### Window properties the service sets

Whenever the active skin changes, and when the service stops, the service also clears
`helper_active`, `helper_speed_dial` and the trailer session, `player_*`, `speed_dial_*`
and `slideshow_*` properties below; `trailer_return`, `info_hop` and
`trailer_played_item` are left. If the new skin opts in, `helper_active`,
`helper_speed_dial` (if it uses speed dial), the pinned-item properties and, if
something is playing, the `player_*` properties are set again at once. The others come
back with the next play, speed dial change or slide.

| Property | Set when | Value | Cleared when | Page |
|---|---|---|---|---|
| `helper_active` | A skin that opts in becomes active | `true` | The active skin changes, or the service stops | [Opting in](#opting-in) |
| `helper_speed_dial` | As `helper_active`, when the skin's templates or `16x9/` XML name `info=speed_dial`; checked again on a skin update | `True` | As `helper_active`; a skin update that drops `info=speed_dial` | [Context menu items](../script/actions.md#items-the-helper-adds-to-the-context-menu) |
| `helper_reloading` | Just before the service reloads the skin after an in-place update, except during fullscreen video. Not on a start, a switch into the skin or a helper restart | `reload` | Your skin clears it once its window is ready after the reload; the service clears it if the reload is dropped or postponed | [Script actions](../script/actions.md#dynamic_settings_window) |
| `helper_settle` | Just before each `ReloadSkin()` the service runs, through `SetProperty` | A number that changes each time | Cleared once the last number has landed, just before the `ReloadSkin()`; left set if the wait gives up after a minute | [What runs when](#when-a-skin-that-opts-in-becomes-active) |
| `trailer_state` | A trailer starts, goes stale, nears its end or is retired | `playing`, `orphaned`, `fullscreen` | Playback stops, ends or fails; a real video starts, or the user's own media starts during a request | [Trailers](trailers.md) |
| `trailer_file` | A requested trailer starts | The trailer's `Player.Filenameandpath` | As `trailer_state` | [Trailers](trailers.md) |
| `trailer_flight` | A request that waited behind an earlier trailer is handed to Kodi (`play_trailer` sets it too) | The trailer Kodi is resolving or opening | Its audio and video are up, its stream fails to open, other media starts during its resolve, or the poll after it is cancelled as hung | [Trailers](trailers.md) |
| `trailer_return` | A trailer requested with `fullscreen` starts and goes full screen | The `info_current` key at that moment | By the `trailer_return` action | [Trailers](trailers.md#full-screen) |
| `info_hop` | As `trailer_return`, when `info_current` is set and is not a season | `fullscreen` | The info dialog's `<onload>`, or the `trailer_return` action | [Trailers](trailers.md#full-screen) |
| `trailer_played_item` | Never set by the service | — | A trailer fails to play with no newer request waiting, or a request for the item it names never starts | [Trailers](trailers.md) |
| `player_tvshowtitle` | An episode starts | TV show title | Playback stops, ends or fails and nothing else starts; the next file replaces it | [Player properties](player.md) |
| `player_season` | An episode starts | Season number | As above | [Player properties](player.md) |
| `player_tvshowid` | A library episode starts | TV show database id | As above | [Player properties](player.md) |
| `player_setid` | A library movie in a set starts | Movie set database id | As above | [Player properties](player.md) |
| `player_set`, `player_set_path` | A library movie in a set starts | The set's name, and a `videodb://` URL of its other films | As above | [Player properties](player.md) |
| `player_next_path`, `player_season_path` | A library episode starts, not a special | `videodb://` URLs of the next 20 episodes and of the season's unwatched, less the playing file | As above | [Player properties](player.md) |
| `player_subtitle_kind` | A video starts; the `player_stream` and `player_stream_refresh` actions update it | `forced`, `full` or `impaired`; while off, `missing` (no preferred stream for the language an action was given) or empty | As above | [Player properties](player.md#subtitle-type) |
| `player_video_count` | A video starts | Number of video streams | As above | [Player properties](player.md) |
| `player_genre_query`, `player_genre`, `player_director` | A video with a genre or director starts | One genre (as named, and cleaned) and one director, picked once per video and session | As above | [Player properties](player.md#genre-and-director-picks) |
| `player_artist` | A song starts | Artist (all artists in one string) | As above | [Player properties](player.md) |
| `player_artist_1` … `player_artist_3` | A song starts | First, second and third artist | As above | [Player properties](player.md) |
| `player_artistid_1` … `player_artistid_3` | A library song starts | First, second and third artist's database id | As above | [Player properties](player.md) |
| `player_albumartist` | A song starts | Album artist | As above | [Player properties](player.md) |
| `player_album` | A song starts | Album title | As above | [Player properties](player.md) |
| `player_albumid` | A song starts | Album database id | As above | [Player properties](player.md) |
| `player_album_path` | A song starts | The album's folder, `musicdb://albums/<id>/`; empty outside the library or when the music queue is exactly this album's songs | As above | [Player properties](player.md) |
| `player_disc` | A song starts | Disc number | As above | [Player properties](player.md) |
| `player_genres` | A song starts | The song's genres, joined with ` / ` | As above | [Player properties](player.md) |
| `player_songid` | A song starts | Song database id, for matching the others to `MusicPlayer.DBID` | As above | [Player properties](player.md) |
| `player_seek_offset` | A seek with a jump finishes | The jump, signed (`+10:00`, `-00:30`) | 4 seconds after the seek once `Player.HasPerformedSeek(4)` is false; a chapter jump or speed change; a new file starts; playback stops, ends or fails | [Player properties](player.md#seek-offset) |
| `speed_dial_version` | A song starts and the play changes what speed dial shows, or the poll loop releases `speed_dial_held` | A new number each time | Only when the active skin changes or the service stops | [Player properties](player.md#speed-dial) |
| `speed_dial_held` | As `speed_dial_version`, but focus is on a speed dial item | The next `speed_dial_version` | The poll loop moves it to `speed_dial_version` | [Speed dial](../plugins/speed_dial.md#window-properties) |
| `speed_dial_album1` … `speed_dial_album7`, `speed_dial_artist1` … `speed_dial_artist7`, `speed_dial_song1` … `speed_dial_song7`, `speed_dial_playlist` | The skin becomes active | Pinned ids by type and number of digits, or pinned playlist paths, joined with `\|` | Set again on every pin, unpin or move; empty when nothing matches | [Speed dial](../plugins/speed_dial.md#window-properties) |
| `slideshow_fanart` | Each slide | Path to the original fanart; a typed wrapper (`image://music@…/`, `image://video_…@…/`) stays wrapped | Only when the active skin changes or the service stops (replaced by the next slide) | [Slideshow](slideshow.md) |
| `slideshow_blur` | Each slide | Path to the blurred fanart | Only when the active skin changes or the service stops (replaced by the next slide) | [Slideshow](slideshow.md) |
| `slideshow_darken` | Each slide | Darken percentage, `0`–`100` | The slide has no darken value | [Slideshow](slideshow.md) |
| `slideshow_clearlogo` | Each slide | Path to the cropped clearlogo | The slide has no clearlogo | [Slideshow](slideshow.md) |
| `slideshow_title` | Each slide | Item label | The slide has no title | [Slideshow](slideshow.md) |
| `slideshow_clearlogo_a`, `slideshow_clearlogo_b`, `slideshow_title_a`, `slideshow_title_b` | Each slide, one slot at a time | As `slideshow_clearlogo` and `slideshow_title` | As those | [Slideshow](slideshow.md) |
| `slideshow_slot` | Each slide | `a` or `b`, the slot just written | Only when the active skin changes or the service stops | [Slideshow](slideshow.md) |

The service also clears the trailer request properties that `action=play_trailer`
sets (`trailer_request`, `trailer_item`, `trailer_source`, `trailer_focus_ids`,
`trailer_window`, `trailer_fullscreen`, `trailer_viewport`)
when a trailer session ends. It clears `trailer_fullscreen` as the trailer goes full screen, too.

### What the service reads from the skin

| Name | Kind | Read when | Page |
|---|---|---|---|
| `extras/templates/<folder>/` | Skin folder | Start-up and skin change | This page |
| `addon.xml` (`id`) and `System.AddonVersion(<id>)` | Skin file and infolabel | Every pass of the service loop, to notice a skin change or an in-place update | [Opting in](#opting-in) |
| `trailer_state` | Window property | On playback start, stop, end and error, and each poll | [Trailers](trailers.md) |
| `trailer_request` | Window property | When the flight's trailer starts, and each poll | [Trailers](trailers.md) |
| `trailer_item` | Window property | When checking if a trailer is stale | [Trailers](trailers.md) |
| `trailer_source` | Window property | Staleness check and trailer zoom | [Trailers](trailers.md) |
| `trailer_focus_ids` | Window property | When checking if a trailer is stale | [Trailers](trailers.md) |
| `trailer_viewport` | Window property | When a trailer starts | [Trailers](trailers.md) |
| `trailer_fullscreen` | Window property | When a trailer starts | [Trailers](trailers.md#full-screen) |
| `info_current` | Window property | When a trailer goes full screen | [Trailers](trailers.md#full-screen) |
| `trailer_flight`, `trailer_pending_since` | Window property | On playback start, and each poll | [Trailers](trailers.md) |
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
