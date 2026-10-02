# Speed Dial

`info=speed_dial` fills a container with the music the user plays most readily:
the entries they pinned, then what they played recently. Use it as a music widget.

```xml
<control type="list" id="5000"><!-- id is an example -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=speed_dial&amp;v=$INFO[Window(home).Property(speed_dial_version)]</content>
</control>
```

The `v=` parameter is not read. It changes whenever speed dial changes, so the path
changes and Kodi fetches the list again. Without it, the list only updates when Kodi
reloads the container for some other reason.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `limit` | whole number | all | Most items to return |

---

## What is in the list

An entry is an album, an artist, a song or a music playlist (`.xsp` or `.m3u`).

1. **Pinned entries**, in the order they were pinned or moved. A new pin goes to the
   front.
2. **Recent entries**, most recent first, up to 30. An entry that is also pinned is
   not shown twice.

Entries whose album, artist or song is no longer in the library are left out.

### How entries are added

- **Pinned:** with [`pin`](../script/actions.md#pin), or the **Pin to speed dial**
  item the helper adds to Kodi's context menu.
- **Recent:** the background service adds an entry each time music starts playing
  (see [Player properties](../service/player.md#speed-dial)). It works out what the
  user started:
  - [`shuffle`](../script/actions.md#shuffle) and
    [`start_mix`](../script/actions.md#start_mix) say what they played. A genre or
    year adds nothing.
  - Otherwise, when a new queue starts: the music playlist open in the Music window,
    else the album every queued song shares, else an artist every queued song
    shares, else the song itself.
  - Moving on to the next song in the same queue adds nothing. Songs that are not in
    the library add nothing.

Speed dial is stored in the helper's add-on data folder, in `speed_dial.json`. It is
shared by every skin.

---

## The items

| Entry | Label | Opens | `ListItem.DBType` |
|---|---|---|---|
| Album | Album title | `musicdb://albums/<id>/` (a folder) | `album` |
| Artist | Artist name | `musicdb://artists/<id>/` (a folder) | `artist` |
| Song | Song title | The song file (plays it) | `song` |
| Playlist | The file name, without `.xsp` or `.m3u` | The playlist (a folder) | — |

- Albums, artists and songs carry their library artwork, `DBID`, `Artist`, `Genre`
  and `UserRating`. Albums and songs also carry `Title` and `Year`. Songs also carry
  `Album`, `Duration` and `TrackNumber`.
- `ListItem.Art(icon)` is Kodi's default icon for the type (`DefaultAlbumCover.png`,
  `DefaultArtist.png`, `DefaultMusicSongs.png`, `DefaultMusicPlaylists.png`).
- Pinned items have `ListItem.Property(speed_dial_pinned)` set to `true`.
- Pinned items have three extra context menu items: **Unpin**, **Move up** and
  **Move down**. They run [`unpin`](../script/actions.md#unpin) and
  [`move_pin`](../script/actions.md#move_pin).

Clicking a song plays it. To do something else, give the container your
own `<onclick>`. Example from Copacetic, which starts a mix from a song and lets
albums, artists and playlists open as normal:

```xml
<onclick condition="String.IsEqual(Container(5000).ListItem.DBType,song)">RunScript(script.copacetic.helper,action=start_mix,type=song,id=$INFO[ListItem.DBID])</onclick>
```

## Window properties

| Property | Value | Set when |
|---|---|---|
| `speed_dial_version` | A new number each time | Speed dial is changed: a pin, an unpin, a move, or a newly recorded play |
