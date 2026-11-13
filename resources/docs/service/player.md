# Player Properties

Tells your skin more about what is playing than Kodi's own infolabels do. The
service looks up the TV show, movie set and individual artists of the playing item
and stores them in window properties. Use them to mark the playing show, set, artist
or album in any list, even when the list item is not the file that is playing.

All properties are on the Home window (`10000`). They are set only while a skin that
[opts in](index.md#opting-in) is active, and cleared whenever the active skin changes or
the service stops.

## When they update

- **Set** when playback of a video or song starts (Kodi's AV started event), and at
  once when the user switches to a skin that opts in while something is playing.
- **Cleared** when playback stops, ends or fails and nothing else starts. A skip or a
  playlist advance replaces them in place, so they never blank between files.

Trailers started with `action=play_trailer` do not set these properties. See
[Trailers](trailers.md).

## Video

| Property | Value | Set when |
|---|---|---|
| `player_tvshowtitle` | TV show title | An episode starts |
| `player_season` | Season number | An episode starts |
| `player_tvshowid` | TV show database id | A library episode starts and its show is found |
| `player_setid` | Movie set database id | A library movie starts and it belongs to a set |
| `player_set` | Movie set name | As above |
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
| `player_identity_<window>` | `player_clearlogo` once that window's logo control is sized to it (`seekbar`, `videoosd`) | A video starts; for `videoosd`, also the [`size_identity`](../script/actions.md#size_identity) action |
| `player_clean_title`, `player_clean_year` | A film's title and year, by Kodi's own clean-up of its file name | A video outside the library starts whose title is its file name |
| `player_clean_tvshowtitle`, `player_clean_episode`, `player_clean_title` | For a file named like an episode (`S01E07` or `1x07`): the show, the `1x07` code and the episode title | As above |

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
   by the film's (or the episode's show's) TMDb id, then TVDB, then IMDb (a TMDb lookup
   reads TMDb's episode numbering, as a TMDb-scraped library has), sending the file's
   length so the answer comes from the nearest release. Every segment of a kind is
   kept, as a film's credits split by a mid-credits scene are; of overlapping takes on
   one, the most trusted. Answers are kept 180 days (an episode with none,
   3 days) in the API cache: offline, and on a rewatch, the last answer is used. A time
   within 3 seconds of a chapter mark takes the mark; an answer from a release more than
   2 % longer or shorter than the file is used only on marks.
3. **The tick pattern**, when TheIntroDB has nothing: chapter marks shaped like a
   streaming release's. Two marks in the first 10 minutes, 20 to 120 seconds apart,
   are the intro. One mark in the last 10 % starts the credits. A file can have either
   or both, but no other marks: one anywhere else, a third early mark or a second late
   one, and the pattern is not used. Files under 15 minutes are left alone.

**What TheIntroDB is sent.** One id for the film or the episode's show (TMDb, TVDB or
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
`player_skip_dismissed` (Home) has it cleared at each new video too.

### Identity and clean names

The identity properties let a skin put a two-line label right beside the playing item's
logo. Kodi images can't size themselves to their picture, so the service crops the logo,
works out its width in a 600 x 90 box, and sets the width of control `4045` (the logo)
in the seek bar dialog at once, and in the video OSD if it is open. Mount the logo as
control `4045` with `<aspectratio aligny="center">keep</aspectratio>` and left
alignment, and show the label beside it once `player_identity_<window>` equals
`player_clearlogo`. A window the service didn't size (the video OSD's first open
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

`player_artist_1` to `player_artist_3` hold one artist each, so you can match a single
artist exactly, and `player_artistid_1` to `player_artistid_3` hold their database ids
in the same order, so two artists with one name stay apart. A song with fewer than
three artists leaves the rest empty.

For the playing song's rating, use Kodi's own `MusicPlayer.UserRating`. It updates
straight away when [`rate_song`](../script/actions.md#rate_song) changes the rating.

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

Show a "now playing" icon on the list item for the show, season, set, artist, album or
disc that is playing:

```xml
<expression name="item_is_playing">Player.HasMedia + [ListItem.IsPlaying | [String.IsEqual(ListItem.DBType,set) + String.IsEqual(Window(home).Property(player_setid),ListItem.DBID)] | [String.IsEqual(ListItem.DBType,tvshow) + String.IsEqual(Window(home).Property(player_tvshowid),ListItem.DBID)] | [String.IsEqual(ListItem.DBType,season) + String.IsEqual(Window(home).Property(player_tvshowid),ListItem.TVShowDBID) + String.IsEqual(Window(home).Property(player_season),ListItem.Season)] | [String.IsEqual(ListItem.DBType,artist) + !String.IsEmpty(ListItem.DBID) + [String.IsEqual(Window(home).Property(player_artistid_1),ListItem.DBID) | String.IsEqual(Window(home).Property(player_artistid_2),ListItem.DBID) | String.IsEqual(Window(home).Property(player_artistid_3),ListItem.DBID)]] | [String.IsEqual(ListItem.DBType,artist) + String.IsEmpty(ListItem.DBID) + [String.IsEqual(Window(home).Property(player_artist_1),ListItem.Artist) | String.IsEqual(Window(home).Property(player_artist_2),ListItem.Artist) | String.IsEqual(Window(home).Property(player_artist_3),ListItem.Artist)]] | [String.IsEqual(ListItem.DBType,album) + !String.IsEmpty(ListItem.DBID) + String.IsEmpty(ListItem.Property(musicvideomediatype)) + String.IsEqual(Window(home).Property(player_albumid),ListItem.DBID) + [String.IsEmpty(ListItem.DiscNumber) | String.IsEqual(Window(home).Property(player_disc),ListItem.DiscNumber)]] | [String.IsEqual(ListItem.DBType,album) + String.IsEmpty(ListItem.DBID) + String.IsEqual(Window(home).Property(player_albumartist),ListItem.Artist) + String.IsEqual(Window(home).Property(player_album),ListItem.Album)]]</expression>

<control type="image">
  <texture>icons/nowplaying.png</texture>
  <visible>$EXP[item_is_playing]</visible>
</control>
```

The `musicvideomediatype` test keeps a music video album node (Videos → Music videos →
Albums: an `album` item whose id is a music video's) from lighting when a song with the
same album id plays.

For items outside the library, which have no database id, match on title instead:
`String.IsEqual(Window(home).Property(player_tvshowtitle),ListItem.Title)`.
