# Player Properties

Tells your skin more about what is playing than Kodi's own infolabels do. The
service looks up the TV show, movie set and individual artists of the playing item
and stores them in window properties. Use them to mark the playing show, set, artist
or album in any list, even when the list item is not the file that is playing.

All properties are on the Home window (`10000`). They are set for any skin, whether
or not it opts in to the [poll loop](index.md#opting-in).

## When they update

- **Set** when playback of a video or song starts (Kodi's AV started event).
- **Cleared** when playback stops, ends or fails.

Trailers started with `action=play_trailer` do not set these properties. See
[Trailers](trailers.md).

## Video

| Property | Value | Set when |
|---|---|---|
| `player_tvshowtitle` | TV show title | An episode starts |
| `player_season` | Season number | An episode starts |
| `player_tvshowid` | TV show database id | A library episode starts and its show is found |
| `player_setid` | Movie set database id | A library movie starts and it belongs to a set |

When a library episode starts, the service also runs [Play next](playnext.md).

## Music

| Property | Value | Set when |
|---|---|---|
| `player_artist` | The song's artist string, as Kodi gives it (all artists together) | A song starts |
| `player_artist_1` | First artist | A song starts |
| `player_artist_2` | Second artist | A song starts |
| `player_artist_3` | Third artist | A song starts |
| `player_albumartist` | Album artist | A song starts |
| `player_album` | Album title | A song starts |
| `player_disc` | Disc number | A song starts |
| `player_userrating` | User rating | A song starts |

`player_artist_1` to `player_artist_3` hold one artist each, so you can match a single
artist exactly. A song with fewer than three artists leaves the rest empty.

## Example

Show a "now playing" icon on the list item for the show, season, set or artist that is
playing:

```xml
<expression name="item_is_playing">Player.HasMedia + [ListItem.IsPlaying | [String.IsEqual(ListItem.DBType,set) + String.IsEqual(Window(home).Property(player_setid),ListItem.DBID)] | [String.IsEqual(ListItem.DBType,tvshow) + String.IsEqual(Window(home).Property(player_tvshowid),ListItem.DBID)] | [String.IsEqual(ListItem.DBType,season) + String.IsEqual(Window(home).Property(player_tvshowid),ListItem.TVShowDBID) + String.IsEqual(Window(home).Property(player_season),ListItem.Season)] | [String.IsEqual(ListItem.DBType,artist) + [String.IsEqual(Window(home).Property(player_artist_1),ListItem.Artist) | String.IsEqual(Window(home).Property(player_artist_2),ListItem.Artist) | String.IsEqual(Window(home).Property(player_artist_3),ListItem.Artist)]] | [String.IsEqual(ListItem.DBType,album) + String.IsEqual(Window(home).Property(player_albumartist),ListItem.Artist) + String.IsEqual(Window(home).Property(player_album),ListItem.Album)]]</expression>

<control type="image">
  <texture>icons/nowplaying.png</texture>
  <visible>$EXP[item_is_playing]</visible>
</control>
```

For items outside the library, which have no database id, match on title instead:
`String.IsEqual(Window(home).Property(player_tvshowtitle),ListItem.Title)`.
