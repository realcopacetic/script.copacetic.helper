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

The `v=` parameter is not read. It changes whenever what speed dial shows changes, so
the path changes and Kodi fetches the list again. Without it, the list only updates
when Kodi reloads the container for some other reason. See
[Window properties](#window-properties) for when it changes.

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

- Albums, artists and songs carry their library artwork, `DBID`, `Artist` and
  `Genre`. Albums and songs also carry `Title`, `Year` and `UserRating`. Songs also
  carry `Album`, `Duration` and `TrackNumber`.
- `ListItem.Art(icon)` is Kodi's default icon for the type (`DefaultAlbumCover.png`,
  `DefaultArtist.png`, `DefaultMusicSongs.png`, `DefaultMusicPlaylists.png`).
- Every item has `ListItem.Property(speed_dial)` set to `true`. The helper reads it
  to tell when focus is on a speed dial list (see
  [Window properties](#window-properties)).
- Each item's context menu opens with its own rows, before Kodi's: **Start mix**
  (not on playlists), **Shuffle** (not on songs), **Move up** unless it is the first
  pin, **Move down** unless it is the last, and **Unpin** on a pinned entry. A single
  pin has no Move rows; a recent entry has neither Move nor Unpin. They run
  [`start_mix`](../script/actions.md#start_mix), [`shuffle`](../script/actions.md#shuffle),
  [`move_pin`](../script/actions.md#move_pin) and [`unpin`](../script/actions.md#unpin).
- The helper's own Shuffle, Start mix and Unpin context menu items hide on speed dial
  items (they check `ListItem.Property(speed_dial)`), so nothing shows twice. Like,
  Unlike and Pin to speed dial still come from them, after Kodi's rows (see
  [Items the helper adds to the context menu](../script/actions.md#items-the-helper-adds-to-the-context-menu)).
- A playlist pinned from `special://musicplaylists/` is stored, and opened, as the
  same file under `special://profile/playlists/music/`. Both are the same folder.

Clicking a song plays it. To do something else, give the container your
own `<onclick>`. Example from Copacetic, which starts a mix from a song and lets
albums, artists and playlists open as normal:

```xml
<onclick condition="String.IsEqual(Container(5000).ListItem.DBType,song)">RunScript(script.copacetic.helper,action=start_mix,type=song,id=$INFO[ListItem.DBID])</onclick>
```

## Window properties

All on the Home window: read them with `Window(home).Property(name)`.

| Property | Value | Set when |
|---|---|---|
| `speed_dial_version` | A new number each time | A pin, an unpin or a move, at once. A recorded play, only when it changes what speed dial shows (see below). |
| `speed_dial_held` | The next `speed_dial_version` | A recorded play changes speed dial while focus is on a speed dial item. Cleared when it is moved to `speed_dial_version`. |
| `speed_dial_album1` … `speed_dial_album7` | Pinned album ids with that many digits, joined with `\|` | The service starts, and on every pin, unpin or move. Empty when there are none. |
| `speed_dial_artist1` … `speed_dial_artist7` | The same, for artists | As above |
| `speed_dial_song1` … `speed_dial_song7` | The same, for songs | As above |
| `speed_dial_playlist` | Pinned playlist paths, each in both spellings (`special://profile/playlists/music/…` and `special://musicplaylists/…`), joined with `\|` | As above |

`speed_dial_version` is never cleared.

### Plays don't reload a focused list

Replaying the most recent entry, or a pinned one, changes nothing on screen, so
`speed_dial_version` stays the same. When a play does change speed dial and the
focused item is a speed dial item (`ListItem.Property(speed_dial)`), the new value
waits in `speed_dial_held`. About once a second the service checks again, and moves it
to `speed_dial_version` once focus has left the list. So pressing Play in speed dial
doesn't reload the list under the user.

That check is part of the service's [poll loop](../service/index.md#the-poll-loop),
which only runs for a skin that opts in. In other skins, a held value waits until the
next pin, unpin or move, or the next play that changes speed dial while focus is
elsewhere.

### Is this item pinned?

The id properties are split by the number of digits, so that `String.Contains` can
only match a whole id: `12` never matches inside a pinned `123`. Test the list item's
`DBID` against the property for its length. Ids up to seven digits are covered.

```xml
<!-- example: a pinned album, for ids of one to three digits -->
<visible>String.IsEqual(ListItem.DBType,album) + [String.Contains(Window(home).Property(speed_dial_album1),ListItem.DBID) | [Integer.IsGreater(ListItem.DBID,9) + String.Contains(Window(home).Property(speed_dial_album2),ListItem.DBID)] | [Integer.IsGreater(ListItem.DBID,99) + String.Contains(Window(home).Property(speed_dial_album3),ListItem.DBID)]]</visible>
<!-- example: a pinned playlist -->
<visible>String.Contains(Window(home).Property(speed_dial_playlist),ListItem.FolderPath)</visible>
```

The helper's **Pin to speed dial** and **Unpin** context menu items use the same
tests, for all seven lengths.
