# Player Properties

Tells your skin more about what is playing than Kodi's own infolabels do. The
service looks up the movie set, episode rails and individual artists of the playing
item and stores them in window properties. Use them to mark the playing artist or
album in any list, even when the list item is not the file that is playing.

All properties are on the Home window (`10000`). They are set only while a skin that
[opts in](index.md#opting-in) is active, and cleared whenever the active skin changes or
the service stops.

## When they update

- **Set** when playback of a video or song starts (Kodi's AV started event), and at
  once when the user switches to a skin that opts in while something is playing.
- **Cleared** when playback stops, ends or fails and nothing else starts. A skip or a
  playlist advance replaces them in place, so they never blank between files.

Trailers started with `action=play_trailer` do not set these properties. See
[Trailers](trailers.md). A game sets none of the video properties below, though Kodi
reports it as video: it sets its own (see [Games](games.md)).

## Video

| Property | Value | Set when |
|---|---|---|
| `player_set` | Movie set name | A library movie starts and it belongs to a set |
| `player_set_path` | A `videodb://` URL of the set's other films (the playing file left out), ready for a list's `<content>` | As above |
| `player_next_path` | A `videodb://` URL of the next 20 episodes in season and episode order, into later seasons, less the playing file (and its other parts) | A library episode starts and its show is found; not for a special (season 0) |
| `player_season_path` | A `videodb://` URL of the season's unwatched episodes, less the playing file | As above |
| `player_subtitle_kind` | The subtitle showing: `forced`, `full` or `impaired` (hearing impaired). While off: `missing` when the actions were given a language with no preferred stream, otherwise empty | A video starts; `player_stream` and `player_stream_refresh` update it |
| `player_video_count` | How many video streams the file has, so a skin can dim a video stream button that would do nothing | A video starts |
| `player_genre_query` | One of the video's genres, as the library names it (`Action & Adventure`) | A video with a genre starts (an episode has its show's) |
| `player_genre` | The same pick, cleaned for a label (`Adventure`), as `metadata` does | As above |
| `player_director` | One of the video's directors | A video with a director starts |
| `player_start` | The playing file's path, for a skin's start-of-playback label; a skin clears it when its label is done | A video starts, not when the skin is entered mid-playback |
| `player_clearlogo` | The playing item's clearlogo (an episode's show's), cropped to its visible edges; the original if cropping fails | A video with a clearlogo starts |
| `player_clearlogo_width` | That logo's width when fitted into a 600 x 90 box, in skin pixels | As above |
| `player_clearlogo_height` | That logo's height when fitted into an 840 x 200 box (full-screen info's), in skin pixels | As above |
| `player_identity_<window>` | `player_clearlogo` once that window's logo control is sized to it (`seekbar`, `videoosd`, `fullscreeninfo`) | A video starts; for `videoosd` and `fullscreeninfo`, also the [`size_identity`](../script/actions.md#size_identity) action |
| `player_clean_title`, `player_clean_year` | A film's title and year, by Kodi's own clean-up of its file name | A video outside the library starts whose title is its file name |
| `player_clean_tvshowtitle`, `player_clean_episode`, `player_clean_title` | For a file named like an episode (`S01E07` or `1x07`): the show, the `1x07` code and the episode title | As above |

For the playing show and season, use Kodi's own `VideoPlayer.TVShowTitle`,
`VideoPlayer.TvShowDBID` and `VideoPlayer.Season`.

When a library episode starts, the service also runs [Play next](playnext.md).

### Skip segments

With the skin setting `skip_segments` on (`Skin.HasSetting(skip_segments)`), the
service finds where a video's intro, recap and credits are and publishes the next one,
for a skip button and for opening Play next when the credits start. The sources, in
order:

1. **Named chapters.** Entering a chapter with one of these names (case and spaces
   around it ignored) makes that chapter the segment, over anything else there. Kodi
   gives a chapter's name only while it plays (`Player.ChapterName`), so these are
   found on entering.

   | Chapter name | Segment |
   |---|---|
   | `Intro`, `Opening`, `Opening Credits`, `OP` | `intro` |
   | `Recap`, `Previously`, `Previously On` | `recap` |
   | `Credits`, `End Credits`, `Ending`, `ED`, `Outro` | `credits` |
   | `Preview`, `Next Episode`, `Next Time` | `preview` |

   The last chapter counts only as credits or a preview, which run to the end of the
   file. Any other name (`Prologue`, a cold open) is not a segment.
2. **[TheIntroDB](https://theintrodb.org)**, for a library film or episode, while the
   helper's *TheIntroDB* setting is on (the default). The service asks once at AV start
   by the film's (or the episode's show's) TMDB id, then TVDB, then IMDb (a TMDB lookup
   reads TMDB's episode numbering, as a TMDB-scraped library has), moving on only while
   a TMDB or IMDb id or its numbering is unknown there. A "no submissions" answer ends
   it: TheIntroDB keys its records by TVDB id and answers so for any TVDB id or episode
   without times, known or not, and an IMDb id finds the same record. The service sends
   the file's length so the answer comes from the nearest release. Every segment of a
   kind is kept, as a film's credits split by a mid-credits scene are; of overlapping
   takes on one, the most trusted. Answers are kept 180 days (a film or episode with
   none, 3 days) in the API cache: offline, and on a rewatch, the last answer is used.
   TheIntroDB's rate limit pauses every lookup for the wait it sends; its limit on one
   film or episode pauses only that one's. A time within 3 seconds of a chapter mark
   takes the mark; an answer from a release more than 2 % longer or shorter than the
   file is used only on marks, except a film's file up to 5 % longer (a tail after
   the credits).
3. **The tick pattern**, when TheIntroDB has nothing: chapter marks shaped like a
   streaming release's. Two marks in the first 10 minutes, 20 to 120 seconds apart,
   are the intro. One mark in the last 10 % starts the credits. A file can have either
   or both, but no other marks: one anywhere else, a third early mark or a second late
   one, and the pattern is not used. Files under 15 minutes are left alone.

**What TheIntroDB is sent.** One id for the film or the episode's show (TMDB, TVDB or
IMDb, in that order, until one is known), the season and episode number for an
episode, and the file's length. No account is needed. Requests are spaced at least a
second apart; a request that would wait more than 3 seconds is skipped, and the last
answer (if any) is used. The setting is `theintrodb` in the helper's settings, on by
default: off, nothing is sent and only chapters are used. A skin can test for it with
`Addon.SettingBool(script.copacetic.helper,theintrodb)`. *Cache › Clear TheIntroDB
data* forgets every saved answer; **Refresh cached data** one film's or show's (see
[`refresh_cached`](../script/actions.md#refresh_cached)).

| Property | Value |
|---|---|
| `player_skip_kind` | `intro`, `recap`, `credits` or `preview`: the segment the playhead is in or comes to next |
| `player_skip_start`, `player_skip_end` | Its start and end in whole seconds, for `Player.Time(secs)` (which Kodi rounds: the start is rounded up past it, so it reads only once reached) |
| `player_skip_seek` | Its exact end in seconds, for [`skip_segment`](../script/actions.md#skip_segment) |
| `player_credits` | Where credits (or a preview) run to the end of the file, in whole seconds, rounded up as the start is |

Credits that end before the file does (a scene after them) are a `credits` segment;
credits that run to the end, or end where a preview running to the end starts, set
`player_credits` instead. The properties update each
second and clear when the video stops. A skin that remembers a dismissed button in
`player_skip_dismissed` (Home) has it cleared at each new video too, and whenever the
playhead leaves the segment it was in (played or skipped past its end, or a seek back
before its start) or goes back more than a second (a seek or a chapter back, within the
segment too: to 0:00 in an intro that starts there), so the button shows again when
playback comes back to it.

### Identity and clean names

The identity properties let a skin put a two-line label right beside the playing item's
logo. Kodi images can't size themselves to their picture, so the service crops the logo,
works out its width in a 600 x 90 box, and sets the width of control `4045` (the logo)
in the seek bar dialog at once, and in the video OSD if it is open. Mount the logo as
control `4045` with `<aspectratio aligny="center">keep</aspectratio>` and left
alignment, and show the label beside it once `player_identity_<window>` equals
`player_clearlogo`. Full-screen info's control `4045` is sized by height instead, its
logo's in an 840 x 200 box, so the lines stacked under it close up to the logo (and at
once if the dialog is open). A window the service didn't size (the video OSD's first open
after a new file; either window after a skin reload, which rebuilds its controls) runs
[`size_identity`](../script/actions.md#size_identity) from its `<onload>`. A window
without control `4045` is left alone, and its stamp isn't set.

The clean names use Kodi's own clean-up (`xbmc.getCleanMovieTitle`, which follows the
user's `cleanstrings` in `advancedsettings.xml`): `Batman.Begins.2005.1080p.BluRay.mkv`
gives `Batman Begins` and `2005`. A file named like an episode is split at its
`S01E07` or `1x07` and each side is cleaned: the show before it, the episode title
after it. The same clean-up is available for any file through the
[`clean_name`](../plugins/clean_name.md) plugin path.

### Genre and director picks

`player_genre_query` and `player_director` hold one name each, so they can be passed as
`label` to [`genre_credits` and `director_credits`](../plugins/library.md#actor_credits-director_credits-writer_credits-genre_credits-studio_credits-artist_credits)
for "more like this" rails under the playing video; `player_genre` names the pick in the
rail's heading. Each is picked at random once per video and Kodi session, so a replay
keeps its rails, as the [`metadata`](../plugins/metadata.md#metadata) path's
`random_pick` does.

### Subtitle type

`player_subtitle_kind` reads the subtitle's flags, then its name, as
[`player_stream`](../script/actions.md#player_stream) does, which sets it straight away
(after an audio step, a second later, as Kodi may swap a forced subtitle).
Kodi sends no event when a subtitle changes in its own subtitle settings dialog or from
a key, so the service doesn't follow those changes: call
[`player_stream_refresh`](../script/actions.md#player_stream_refresh) before the
property is shown, for example from the video OSD's `<onload>` and the subtitle and
audio settings dialogs' `<onunload>`.

The service knows nothing of the skin's preferred language, so at video start the value
is never `missing`; pass `lang` and `kind` to `player_stream_refresh` and it is.

### Chapter ticks

The service publishes no chapter ticks. To light one chapter's tick (the chapter
focused in the bookmarks dialog), call
[`chapter_focus`](../script/actions.md#chapter_focus) as focus moves; it sets
`player_chapter_focus` for a single `ranges` control.

### Seek offset

Kodi's `Player.SeekOffset` is often empty by the time a step seek has finished
(handling the seek usually resets it to zero), so a "+10:00" label can show nothing.
The service keeps the jump of the last seek in `player_seek_offset`, for any video or
song, as a fallback for that label.

| Property | Value | Set when |
|---|---|---|
| `player_seek_offset` | The jump, signed: `+10:00`, `-00:30`, `+01:30:00` (hours only when there are any) | A seek with a jump finishes |
| `player_seek_chapter` | The chapter a chapter jump went to (`4`) | A chapter jump finishes |

A chapter jump (Kodi's `ChapterOrBigStepForward` in a file with chapters, or
`ChapterOrBigStepBack`) reports no reliable jump, so it sets `player_seek_chapter`
instead, and any other seek clears it. While it is set and `Player.HasPerformedSeek`
holds, show the chapter's name (`Player.ChapterName`) in place of a jump label: hide
any jump label then, as Kodi's `Player.SeekOffset` can hold a stray value after a chapter
jump. Both are cleared:

- once Kodi's own seek display is over: 4 seconds after the seek, when
  `Player.HasPerformedSeek(4)` is no longer true;
- on a speed change (fast forward, rewind), which reports no jump;
- when a new file starts, and when playback stops, ends or fails.

Use Kodi's value first and the service's when Kodi's is empty:

```xml
<variable name="seek_offset">
  <value condition="!String.IsEmpty(Player.SeekOffset)">$INFO[Player.SeekOffset]</value>
  <value>$INFO[Window(home).Property(player_seek_offset)]</value>
</variable>
```

## Music

| Property | Value | Set when |
|---|---|---|
| `player_artist` | The song's artist string, as Kodi gives it (all artists together) | A song starts |
| `player_artist_1` | First artist | A song starts |
| `player_artist_2` | Second artist | A song starts |
| `player_artist_3` | Third artist | A song starts |
| `player_artistid_1` | First artist's database id | A library song starts |
| `player_artistid_2` | Second artist's database id | A library song starts |
| `player_artistid_3` | Third artist's database id | A library song starts |
| `player_albumartist` | Album artist | A song starts |
| `player_album` | Album title | A song starts |
| `player_albumid` | Album database id (`-1` outside the library) | A song starts |
| `player_album_path` | The album's songs, every disc in one list, `musicdb://songs/?albumid=<id>`, for a rail of them (the album's folder would list a multi-disc album's discs). Empty outside the library, and when the music queue is exactly this album's songs (it would only repeat the queue); a queue of some of them, or of more, keeps it. The queue is read when it changes (by its length or first song) and the album's songs when the album does, not on every song, so a queue edit that keeps both shows on the next queue. | A song starts |
| `player_disc` | Disc number | A song starts |
| `player_genres` | The song's genres, joined with ` / ` as `MusicPlayer.Genre` reads them; unlike that infolabel it changes with the other properties, not ahead of them | A song starts |
| `player_songid` | The song's database id (`-1` outside the library). These properties hold the previous song's values until the new one starts, so match it to `MusicPlayer.DBID` before acting on them | A song starts |
| `player_title` | The title these were made from, as `MusicPlayer.Title` read it at the song's start. Match the two (and `player_artist` to `MusicPlayer.Artist`, for two songs of one title) before showing `player_title_name` and `player_title_version`: unlike `player_songid` this works outside the library, and a stream whose title changes mid-play no longer matches. It is written after the other two | A song starts |
| `player_title_name` | The title less a version at its end: `Pyramid Song` from `Pyramid Song (Live)`. The whole title when there is none | A song starts |
| `player_title_version` | That version, without its brackets or dash: `Live`, `Bright-Side Mix`, `Remastered 2015`. Empty when there is none | A song starts |

`player_artist_1` to `player_artist_3` hold one artist each, so you can match a single
artist exactly, and `player_artistid_1` to `player_artistid_3` hold their database ids
in the same order, so two artists with one name stay apart. A song with fewer than
three artists leaves the rest empty.

A version is the last `(…)`, `[…]` or ` - …` of a title when it holds one of these
whole words, in any case: mix, remix, edit, remaster, remastered, version, live,
acoustic, demo, take with its number (`Take 2`), session, mono, stereo, instrumental,
radio, extended, single, dub, unplugged, feat., ft. A bracket that opens a title
(`(I Can't Get No) Satisfaction`) is never one, and a title that is only a bracket
stays whole.

For the playing song's rating, use Kodi's own `MusicPlayer.UserRating`. It updates
straight away when [`rate_song`](../script/actions.md#rate_song) changes the rating.

## Lyrics

With the skin setting `lyrics` on (`Skin.HasSetting(lyrics)`), the service finds the
playing song's lyrics and follows them line by line, for a lyrics column that scrolls
with the song. It never shows a notification and never takes focus. The sources, in
order, the first with any winning:

1. **A `.lrc` file** of the same name beside the song (`Song.flac` and `Song.lrc`),
   read through Kodi's file system, so shares work too; not for a stream. UTF-8 and
   UTF-16 (with its byte order mark) are read as such, anything else as Windows-1252
   (older Chinese, Japanese or Korean files in their own encodings come out garbled).
2. **The song's tags**: the lyrics Kodi reads from the file when it plays
   (`MusicPlayer.Lyrics`). Lyrics with LRC time stamps are synced; without, plain.
3. **[LRCLIB](https://lrclib.net)**, a free, open lyrics database, while the
   helper's *LRCLIB* setting is on (the default), for a song whose title, artist
   and length are known. The service asks by the song's
   title, artist, album and length (whole seconds); for a song it doesn't find, it
   searches once by title and artist and takes the result whose length is nearest
   the song's, within 2 seconds (synced lyrics first among equally near). Answers are
   kept in the API cache: lyrics 180 days, a song LRCLIB has with no lyrics 30 days,
   one it doesn't know 7 days. Offline, the last answer is used.

LRC files can have several time stamps on a line, `[mm:ss]`, `[mm:ss.xx]` or
`[mm:ss.xxx]` stamps (some writers use a colon: `[mm:ss:xx]`), an `[offset:]` tag and metadata tags (ignored); an empty
stamped line is a gap between verses. Enhanced LRC's word stamps (`<mm:ss.xx>`)
are removed. Text with no stamps the service can time is plain, less any LRC tags
and stamps (a lyric's own `[Chorus]` stays); a `.lrc` with nothing else in it holds
no lyrics, and the next source is tried.

Each song is looked up when it starts (`lyrics_state` reads `searching` meanwhile,
`lyrics_source` and `lyrics_instrumental` empty). A `.lrc`, the tags or a saved
LRCLIB answer show at once; a request to LRCLIB runs in the background and its
answer shows within 0.2 seconds of arriving, so nothing else the service does waits
on it. The next song in the queue is asked for in the background too, so it is ready
when it starts; that includes a song the [endless queue](#endless-queue) adds as the
playing one starts. Only an answer is saved then, so a failed request can't hide that
song's lyrics, and one song is never asked for twice at once. Turning the setting on
mid-song looks the song up then; off clears everything. The properties stay up until
the next song's are ready, and clear when playback stops or a video starts.

**What LRCLIB is sent.** The song's title, artist, album and length, for the playing
song and the next one in the queue (even when that one has lyrics of its own). No
account or key is needed; requests carry the helper's name and project page, as
LRCLIB asks.
The setting is `lrclib` in the helper's settings, on by default: off, nothing is
sent and only `.lrc` files and tags are used. A skin can test for it with
`Addon.SettingBool(script.copacetic.helper,lrclib)`. *Cache › Clear LRCLIB data*
forgets every saved answer; **Refresh cached data** one library song's (see
[`refresh_cached`](../script/actions.md#refresh_cached)).

| Property | Value |
|---|---|
| `lyrics_state` | `searching`, then `synced`, `plain` or `none`; empty when no song is playing or the setting is off |
| `lyrics_source` | Where they came from: `file` (a `.lrc` beside the song), `embedded` (its tags) or `lrclib`; empty for none |
| `lyrics_revision` | A new value each time a song's lyrics are ready: put it in the plugin path below, so the list refetches |
| `lyrics_index` | The current line's index (synced only); `-1` before the first line |
| `lyrics_m2`, `lyrics_m1`, `lyrics_p1` ... `lyrics_p5` | The indices of the lines two above to five below the current one, to compare with `ListItem.Property(index)` for a fade by distance |
| `lyrics_plain` | The whole text (plain only) |
| `lyrics_instrumental` | `true` when LRCLIB marks the song instrumental (with no lyrics, `lyrics_state` is then `none`) |

**The lines** come from the plugin path
`plugin://script.copacetic.helper/?info=lyrics&revision=$INFO[Window(home).Property(lyrics_revision)]`:
one item per synced line, in order, with a gap first when the first line has text
and starts after 0 (an intro), so its dots can sit above that line. The label is the line's
text, empty for a gap;
the properties are `index` (from 0), `time` (milliseconds, with any `[offset:]`
applied), `gap` (`true` on an empty line), `long` (`true` when the line needs more than
two lines 660 px wide in the font named `title_identity` in the skin's `Font.xml` (its
first fontset), as Kodi wraps it, so a skin can draw it smaller in its playing line's
box; without that font no line is marked) and `m2`, `m1`, `p1` ... `p5` (the
indexes two above to five below this line). The last are for a fade by distance from
the selected line while the list is browsed: compare a row's
`ListItem.Property(index)` with `Container(<id>).ListItem.Property(m1)` and so on.
Kodi reads `Container(<id>).ListItem(<offset>)` from the selected item whatever the
offset when it is compared inside a list's layout, so it can't do this. Plain lyrics
list nothing here. The path reads no parameter: `revision` only changes the
path, so Kodi fetches it again. The lines come from
`Window(home).Property(lyrics_lines)`, which the service sets; don't set or clear it
from the skin.

**Plain lyrics** come one line an item from
`plugin://script.copacetic.helper/?info=lyrics_plain&wrap_width=660&wrap_font=<font>&revision=$INFO[Window(home).Property(lyrics_revision)]`,
for a list that scrolls a whole line at a time. The label is the line's text, empty for
the blank line between verses. With `wrap_width` (skin pixels) and `wrap_font` (a font
name in the skin's `Font.xml`, its first fontset), a line wider than that is split
where Kodi would wrap it, one item each part; without them, or for a font that isn't
there, each line is one item. Every item has the same path, so when the list fetches a
new song's lines Kodi selects the first. The text is also `lyrics_plain`, for a textbox.

**A library song's lyrics**, playing or not (an info dialog's Lyrics page): add
`type=song&id=<DBID>` to the plain path, with no `revision`. The lines are the same
kind of items, from the same sources in the same order: a `.lrc` beside the file, its
tags (an MP3's ID3v2 lyrics frame or a FLAC file's `LYRICS` comment, the ones Kodi
reads), then LRCLIB's saved answer. Synced lyrics come without their time stamps, one
item per line, an empty one between verses. An instrumental, or none found, lists
nothing; so does every song while the skin's `lyrics` setting is off, the switch the
[CU LRC Lyrics clash](index.md#add-ons-that-clash) keys on. A song LRCLIB has never
been asked for is asked then (with the helper's LRCLIB setting on): a plugin call
waits for the answer; a [served](serve.md) call answers at
once with one empty item carrying `lyrics_pending` = `true`, and serves the list again
when LRCLIB's answer lands, so the skin can mask lines that arrive late. The playing
song's lookup and properties are untouched, and the two share one saved answer.

**Following the song.** On each line's time, and every 0.2 seconds while the
visualisation shows, the service puts one list on the current line when it isn't,
with `Control.Move(<id>,<lines>)` by the distance from the list's own selected item
(`Container(<id>).CurrentItem`). A step a dialog took, a list reloaded or shown again
(a new song, the OSD reopening) and a seek are put right within 0.2 seconds. A move
is given half a second to land before the list is moved again, so one step never
lands twice. Lyrics follow under a dim screensaver too. Give the lists these ids:

| Id | List | Moved |
|---|---|---|
| `3510` | The visualisation window's list, which follows the song and never takes focus | While the visualisation is the active window and no dialog is open over it |
| `3511` | The music OSD's list, for browsing the lines | While the music OSD is open and the list does not have focus |

Kodi sends `Control.Move` to the topmost modal dialog, else the active window, and
reads `Container(<id>)` there too, so the service moves nothing while another dialog
is on top. A list shows its selected item in its focused layout with or without
focus, so the current line can be styled there. Each item has its own path, so a
list refreshed by Kodi keeps its selected line. To jump to a line, call
[`lyrics_seek`](../script/actions.md#lyrics_seek) with its `time`.

## Endless queue

With `Skin.HasSetting(endless_queue)` on, the music queue never runs out. When a
library song starts from the music queue and fewer than 10 songs follow it, the
service adds 10 more to the end: a mix seeded by that song, as
[`start_mix`](../script/actions.md#start_mix) makes one (two by its artists,
the rest by its similar artists, then sharing its genres), with no song
already queued. It only adds, so the queue and any list of it just grow; a shuffled
queue plays them after the songs it already had.

After a genre or daily mix the queue keeps to its genres for as long as it grows:
the mix's songs carry `ListItem.Property(mix_genres)`, a JSON list of the genre's
name (a daily mix: every library genre in its card's bucket), and every song the
queue adds to them is of those genres and carries it on. After anything else (a
song, album or artist mix, an album, a playlist) it is free to wander wherever the
songs playing lead it. A narrow genre that runs out of songs simply stops growing.

Each song added carries `ListItem.Property(added_from)`: the seed song's artists,
joined with ` / `. Read it as `MusicPlayer.Property(added_from)` while the song plays,
or on a list of the queue, for a "because you played" line. If the music playlist
window is open, it is refreshed, since a song added from Python doesn't refresh it.
`player_album_path` is set again once the queue grows, so a queue that was exactly
the album's songs now gets the album's path.

It does nothing in party mode (Kodi fills that queue itself), with repeat all on (the
queue loops), for a song outside the library (there is no seed), and when Kodi isn't
playing from the music queue (a library window's song with Kodi's *Play next song
automatically* off). A single song started some other way, from a widget for example,
is a queue of one, so it grows. Speed dial treats the grown queue as the same queue,
so the songs added are not recorded as a new play.

## Speed dial

When a song starts, the service also records what the user started playing in
[speed dial](../plugins/speed_dial.md#how-entries-are-added): a playlist, album,
artist or song. When that changes what speed dial shows, `speed_dial_version` gets a
new value. Add it to your speed dial path, so the list updates.

| Property | Value | Set when |
|---|---|---|
| `speed_dial_version` | A new number each time | A recorded play changes what speed dial shows, or a speed dial action changes it |

If focus is on a speed dial item at that moment, the new value waits in
`speed_dial_held` until focus leaves the list (see
[Speed dial](../plugins/speed_dial.md#plays-dont-reload-a-focused-list)).

`speed_dial_version` is cleared only when the active skin changes or the service
stops; it stays empty until the next change.

## Example

Show a "now playing" icon on the list item for the show, season, artist, album or disc
that is playing:

```xml
<expression name="item_is_playing">Player.HasMedia + [ListItem.IsPlaying | [String.IsEqual(ListItem.DBType,tvshow) + String.IsEqual(VideoPlayer.TvShowDBID,ListItem.DBID)] | [String.IsEqual(ListItem.DBType,season) + String.IsEqual(VideoPlayer.TvShowDBID,ListItem.TVShowDBID) + String.IsEqual(VideoPlayer.Season,ListItem.Season)] | [String.IsEqual(ListItem.DBType,artist) + !String.IsEmpty(ListItem.DBID) + [String.IsEqual(Window(home).Property(player_artistid_1),ListItem.DBID) | String.IsEqual(Window(home).Property(player_artistid_2),ListItem.DBID) | String.IsEqual(Window(home).Property(player_artistid_3),ListItem.DBID)]] | [String.IsEqual(ListItem.DBType,artist) + String.IsEmpty(ListItem.DBID) + [String.IsEqual(Window(home).Property(player_artist_1),ListItem.Artist) | String.IsEqual(Window(home).Property(player_artist_2),ListItem.Artist) | String.IsEqual(Window(home).Property(player_artist_3),ListItem.Artist)]] | [String.IsEqual(ListItem.DBType,album) + !String.IsEmpty(ListItem.DBID) + String.IsEmpty(ListItem.Property(musicvideomediatype)) + String.IsEqual(Window(home).Property(player_albumid),ListItem.DBID) + [String.IsEmpty(ListItem.DiscNumber) | String.IsEqual(Window(home).Property(player_disc),ListItem.DiscNumber)]] | [String.IsEqual(ListItem.DBType,album) + String.IsEmpty(ListItem.DBID) + String.IsEqual(Window(home).Property(player_albumartist),ListItem.Artist) + String.IsEqual(Window(home).Property(player_album),ListItem.Album)]]</expression>

<control type="image">
  <texture>icons/nowplaying.png</texture>
  <visible>$EXP[item_is_playing]</visible>
</control>
```

The `musicvideomediatype` test keeps a music video album node (Videos → Music videos →
Albums: an `album` item whose id is a music video's) from lighting when a song with the
same album id plays.

For items outside the library, which have no database id, match on title instead:
`String.IsEqual(VideoPlayer.TVShowTitle,ListItem.Title)`.
