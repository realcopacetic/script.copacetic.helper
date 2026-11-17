# Background Service

The helper runs a background service from the moment Kodi starts. It does work your
skin doesn't have to ask for: it builds the skin's generated XML files, watches the
player, plays and tidies up trailers, queues the next episode, tops up the music
queue, follows the playing song's lyrics, and runs a background slideshow. It talks to
your skin through window properties on the Home window and reads skin settings and
skin strings that your skin owns.

This page is the overview and the full list of everything the service sets and reads.
Each feature has its own page:

- [Trailers](trailers.md) — the trailer session that `action=play_trailer` starts.
- [Player properties](player.md) — window properties for the item that is playing,
  and its [lyrics](player.md#lyrics).
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
   with dev mode on (a start, a switch in or an update) or `rebuild` with
   `reset=true` takes it. A check with dev mode off leaves it unclaimed.
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
   update checks for `info=speed_dial` again. Then it queues
   `action=check_clashes` behind any reload (see
   [Add-ons that clash](#add-ons-that-clash)).
4. The poll loop starts, and with it the slideshow.

### When the active skin changes, or the service stops

Whenever the active skin changes (to any skin, even another that opts in, or one whose
`addon.xml` the helper can't read, which then stays inactive), and when
the service stops (Kodi exits, the profile changes, the helper is updated or
disabled), the service releases what it set. It clears `helper_active` and
`helper_speed_dial`, so the context menu items hide. It stops the trailer it started,
whether it is playing, paused or full screen (rewound first, so nothing is marked
watched), clears the trailer,
player, lyrics, speed dial and slideshow properties, and detaches the player monitor. If the
new skin opts in, everything [starts again](#when-a-skin-that-opts-in-becomes-active)
for it; otherwise the add-ons the helper switched off for
[clashing](#add-ons-that-clash) are switched back on, and nothing else runs until a
skin that opts in is active.

### The poll loop

While the skin opts in and the screensaver is not active, the service runs a loop
once a second; while a song's synced [lyrics](player.md#lyrics) play, at each line's
time, and every 0.2 seconds while the visualisation shows or LRCLIB is being asked.
Each pass it:

1. checks the trailer session (see [Trailers](trailers.md));
2. clears `player_seek_offset` and `player_seek_chapter` once Kodi's seek display is over (see
   [Seek offset](player.md#seek-offset));
3. publishes the playing video's skip segment in play or next (see
   [Skip segments](player.md#skip-segments));
4. moves the slideshow on if the interval has passed (see [Slideshow](slideshow.md));
5. moves a held speed dial update from `speed_dial_held` to `speed_dial_version` once
   focus is no longer on a speed dial item (see
   [Speed dial](../plugins/speed_dial.md#plays-dont-reload-a-focused-list));
6. once a day, starting with the first pass, deletes saved TMDb, ListenBrainz,
   Deezer, TheIntroDB and LRCLIB answers in the add-on's `_lookup.db` that expired
   more than 30 days ago. If the database is busy, it tries again an hour later;
7. publishes the playing song's current lyric line and moves the lyric list in view
   to it, or looks the song's lyrics up if the skin's `lyrics` setting was just
   turned on, or clears them if it was turned off (see [Lyrics](player.md#lyrics)).

When the screensaver starts, the loop pauses; when it stops, the loop resumes. While
paused, only lyrics carry on, while a song plays (a dim screensaver leaves them in
view). Otherwise, while paused or while the skin doesn't opt in, the service checks
again every 2 seconds.

### On music queue edits

While a skin that opts in is active, each addition, removal, clear or shuffle of the
music queue that the service handles sets `playlist_revision` to a new number (see
the table below). Kodi delivers these events late; those handled while the helper
refills the queue are skipped, and those handled after it still count.

### On song updates

While a skin that opts in is active, library song updates outside a library scan, and
each library song closing (stopped, ended, or giving way to the next), set
`progress_version` to a new number, once for a burst, unless the progress bar on top
then serves another item's bar (see the table below). A skin puts it in its progress
bar URL, so an album's bar is served again after one of its songs is heard, also on
a return from the OSD: Kodi's own refresh of a plugin container doesn't follow music
library updates when its item is video-tagged, as the progress bar's item is. Kodi
counts a heard song however it was queued (it finds the song by its path), but
announces it only for a library path (`musicdb://`), so the player monitor reports
the close of the songs the helper queues by file path (mixes, speed dial,
`play_items`).

With the same bump, if a closed song's play count is no longer what it was when the
song started, `played_version` gets a new number too. Kodi counts a play only past
`playcountminimumpercent` of the song (90 by default, `advancedsettings.xml`'s
`<audio>`), so a skipped song changes neither. A skin puts it in the path of a list
ordered by play count or last played (On repeat), which Kodi doesn't refetch after a
song the helper queued.

### On playback events

The player monitor handles playback start, stop, end and error, seeks, chapter jumps
and speed changes while a skin that opts in is active, including while the screensaver pauses the poll loop.

## Add-ons that clash

Some add-ons do a job the helper's features do, and with both on, both show:

| Add-on | What it does twice | Feature (skin setting) |
|---|---|---|
| CU LRC Lyrics (`script.cu.lrclyrics`) | Opens its own lyrics window | [Lyrics](player.md#lyrics) (`lyrics`) |
| Up Next (`service.upnext`) | Shows its own next episode prompt; it also covers other add-ons' episodes, which Play next doesn't | [Play next](playnext.md) (`playnext_enabled`) |
| TheIntroDB (`plugin.video.tidb`) | Shows its own skip and next episode buttons, or skips on its own | [Skip segments](player.md#skip-segments) (`skip_segments`) or Play next |

The helper never switches one off without asking. Each time a skin that opts in
becomes active, the service runs `action=check_clashes`, queued behind any reload of
the skin. For each add-on that is enabled while a feature it clashes with is on:

- **Not asked about yet:** once Home has been on top for 2 seconds with no dialog over
  it or the screensaver, a yes/no names the add-on and the skin. *Switch off* switches
  it off (Kodi stops its service with it); *Keep both* leaves it. Back asks again the
  next time. If the skin is left first, nothing is asked.
- ***Switch off* chosen:** it is switched off again without asking, also if the user
  switched it back on meanwhile.
- ***Keep both* chosen:** it is never asked about again.

An add-on the helper switched off is switched back on when its features are all off
(at the next entry), and whenever a skin that doesn't opt in becomes active. Kodi
exiting leaves it off for the next start. A feature turned on mid-session is checked
the next time the skin becomes active. The answers and what is switched off are kept
in `clashes.json` in the add-on's profile folder. *Ask again about add-ons that clash*
in the helper's settings (*Troubleshooting*) runs
[`reset_clashes`](../script/actions.md#reset_clashes): it switches them back on,
forgets every answer and asks again.

## Full contract

All window properties are on the Home window (`10000`). In XML, read them with
`Window(home).Property(name)`.

### Window properties the service sets

Whenever the active skin changes, and when the service stops, the service also clears
`helper_active`, `helper_speed_dial` and the trailer session, `player_*`, `lyrics_*`,
`speed_dial_*` and `slideshow_*` properties below; `trailer_return`, `info_hop` and
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
| `playlist_revision` | Songs are added to, removed from or cleared out of the music queue (`Playlist.OnAdd`, `OnRemove`, `OnClear` for playlist 0), or it is shuffled or unshuffled (`Player.OnPropertyChanged` `shuffled`, player 0), while a skin that opts in is active. A move announces nothing: bump it from the skin where songs are moved. Not while the helper itself refills the queue (`playlist_replacing`, set by its play actions until the songs are in): the play that follows refetches the lists | A number that changes each time: put it in a queue list's path (`playlistmusic://?revision=…`), as Kodi's list providers refresh on play, resume and stop, not when the queue changes | Never | [On music queue edits](#on-music-queue-edits) |
| `progress_version` | Half a second after the last of a burst of library song updates outside a scan (`AudioLibrary.OnUpdate`, type `song`, no `transaction`) or library song closes (a song's stop, end, or the next song's start: Kodi saves the play count only once the song has drained, so a close waits the crossfade plus 2 seconds, which an update meanwhile doesn't cut), unless, when it fires, container 9010 on top (the topmost dialog's, else the active window's) serves a bar for something other than an album (its item has a `plugin://` path and no `ListItem.Property(album)`): a song heard, however it was queued, a Like, [`mark_album`](../script/actions.md#mark_album) | A number that changes each time | Never | [Progress bar: albums](../plugins/progressbar.md#albums) |
| `played_version` | When `progress_version` is due (whether or not it is set), if a library song closed since the last time has a play count other than the one Player.GetItem gave at its start: Kodi counted the play (past `playcountminimumpercent`, 90 by default) | A number that changes each time | Never | [On song updates](#on-song-updates) |
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
| `player_start` | A video starts | The playing file's path | As above, or the skin clears it | [Player properties](player.md) |
| `player_clearlogo`, `player_clearlogo_width`, `player_clearlogo_height` | A video with a clearlogo starts | The logo cropped, its width in a 600 x 90 box and its height in an 840 x 200 box | As above | [Player properties](player.md#identity-and-clean-names) |
| `player_identity_seekbar`, `player_identity_videoosd`, `player_identity_fullscreeninfo` | A video starts; `size_identity` for the OSD and full-screen info | The logo the window's control `4045` is sized for | Never cleared; compare with `player_clearlogo` | [Player properties](player.md#identity-and-clean-names) |
| `player_clean_title`, `player_clean_year`, `player_clean_tvshowtitle`, `player_clean_episode` | A video outside the library starts whose title is its file name | Its clean name: title and year, or show, `1x07` and episode title | As above | [Player properties](player.md#identity-and-clean-names) |
| `player_skip_kind`, `player_skip_start`, `player_skip_end`, `player_skip_seek`, `player_credits` | A video plays with the skin's `skip_segments` on | The intro, recap or credits in play or next, and where credits run to the end | Each second; when the video stops | [Player properties](player.md#skip-segments) |
| `player_artist` | A song starts | Artist (all artists in one string) | As above | [Player properties](player.md) |
| `player_artist_1` … `player_artist_3` | A song starts | First, second and third artist | As above | [Player properties](player.md) |
| `player_artistid_1` … `player_artistid_3` | A library song starts | First, second and third artist's database id | As above | [Player properties](player.md) |
| `player_albumartist` | A song starts | Album artist | As above | [Player properties](player.md) |
| `player_album` | A song starts | Album title | As above | [Player properties](player.md) |
| `player_albumid` | A song starts | Album database id | As above | [Player properties](player.md) |
| `player_album_path` | A song starts | The album's songs, every disc in one list, `musicdb://songs/?albumid=<id>`; empty outside the library or when the music queue is exactly this album's songs | As above | [Player properties](player.md) |
| `player_disc` | A song starts | Disc number | As above | [Player properties](player.md) |
| `player_genres` | A song starts | The song's genres, joined with ` / ` | As above | [Player properties](player.md) |
| `player_songid` | A song starts | Song database id, for matching the others to `MusicPlayer.DBID` | As above | [Player properties](player.md) |
| `player_seek_offset` | A seek with a jump finishes | The jump, signed (`+10:00`, `-00:30`) | 4 seconds after the seek once `Player.HasPerformedSeek(4)` is false; a chapter jump or speed change; a new file starts; playback stops, ends or fails | [Player properties](player.md#seek-offset) |
| `player_seek_chapter` | A chapter jump finishes | The chapter it went to (`4`) | 4 seconds after the jump once `Player.HasPerformedSeek(4)` is false; any other seek or a speed change; a new file starts; playback stops, ends or fails | [Player properties](player.md#seek-offset) |
| `lyrics_state`, `lyrics_source`, `lyrics_revision`, `lyrics_plain`, `lyrics_instrumental` | A song starts with the skin's `lyrics` on, or it is turned on mid-song | `searching`, then what was found, where from, and a new revision for the `info=lyrics` path | The setting is turned off; a video starts; playback stops, ends or fails and nothing else starts; the next song's replace them | [Lyrics](player.md#lyrics) |
| `lyrics_index`, `lyrics_m2`, `lyrics_m1`, `lyrics_p1` … `lyrics_p5` | Synced lyrics play, at each line | The current line's index (`-1` before the first) and its neighbours' | As above | [Lyrics](player.md#lyrics) |
| `lyrics_lines`, `lyrics_long` | As `lyrics_state`, for synced lyrics | The lines as JSON, and the indexes of the long ones, read by the `info=lyrics` path; not for the skin | As above | [Lyrics](player.md#lyrics) |
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
| `playnext_enabled` | Skin setting (bool) | When a library episode starts; when the skin becomes active ([add-ons that clash](#add-ons-that-clash)) | [Play next](playnext.md) |
| `skip_segments` | Skin setting (bool) | When a video starts; when the skin becomes active ([add-ons that clash](#add-ons-that-clash)) | [Player properties](player.md#skip-segments) |
| `endless_queue` | Skin setting (bool) | When a library song starts | [Player properties](player.md#endless-queue) |
| `lyrics` | Skin setting (bool) | When a song starts, and each poll while one plays; when the skin becomes active ([add-ons that clash](#add-ons-that-clash)) | [Lyrics](player.md#lyrics) |
| `3510`, `3511` | Container ids (`NumItems`, `CurrentItem`, focus) | At each lyric line, in the visualisation and the music OSD | [Lyrics](player.md#lyrics) |
| `slideshow_source`, `slideshow2_source` | Skin string | Each poll | [Slideshow](slideshow.md) |
| `slideshow_path`, `slideshow2_path` | Skin string | Each poll | [Slideshow](slideshow.md) |
| `slideshow2` | Skin setting (bool) | Each poll | [Slideshow](slideshow.md) |
| `slideshow_start`, `slideshow2_start` | Skin string | Each poll, when `slideshow2` is on | [Slideshow](slideshow.md) |
| `slideshow_interval` | Skin string | After each slide | [Slideshow](slideshow.md) |
| `slideshow_artwork_params` | Window property | Before each slide | [Slideshow](slideshow.md) |

The service expects no control ids of its own but the lyric lists' (`3510`, `3511`,
see [Lyrics](player.md#lyrics)). The trailer feature uses the control ids your skin
passes in `focus_ids`.
