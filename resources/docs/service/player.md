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

When a library episode starts, the service also runs [Play next](playnext.md).

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
`ChapterOrBigStepBack`) reports no jump, so it sets `player_seek_chapter` instead, and a
seek with a jump clears it. Show the chapter's name (`Player.ChapterName`) while it is
set and `Player.HasPerformedSeek` holds. Both are cleared:

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
| `player_album_path` | The album's folder, `musicdb://albums/<id>/`, for a rail of its songs. Empty outside the library, and when the music queue is exactly this album's songs (it would only repeat the queue); a queue of some of them, or of more, keeps it. The queue is read when it changes (by its length or first song) and the album's songs when the album does, not on every song, so a queue edit that keeps both shows on the next queue. | A song starts |
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
