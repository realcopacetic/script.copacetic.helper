# Trailers

Plays a trailer for the focused item inside your skin, and cleans up after it. Your
skin starts the trailer with `action=play_trailer`. The service then watches the
trailer: it zooms the picture to fit your video window, pauses the trailer if the user
moves on, and stops it once the user has settled somewhere else.

All properties on this page are on the Home window (`10000`).

## How it works

A trailer session moves through these states, stored in
`Window(home).Property(trailer_state)`:

| State | Set by | Meaning |
|---|---|---|
| *(empty)* | Service | No trailer session. |
| `pending` | `action=play_trailer` | A trailer was requested and has not started yet. |
| `cancelled` | Your skin | The user left the window while the request was `pending`. The service stops the trailer as soon as it starts. |
| `playing` | Service | The requested trailer is playing and still belongs to the focused item. |
| `interrupted` | Your skin | The user moved away. Your skin sets this; the service then pauses and later stops the trailer. |
| `orphaned` | Service | The trailer no longer belongs to the focused item. It is paused and waiting to be stopped. |

1. Your skin runs `action=play_trailer`. The action sets `trailer_state` to `pending`,
   stores the request properties below, and plays the trailer.
2. When the video starts, the service stores its path in `trailer_file`. It then
   checks that the trailer is still wanted (see [Stale trailers](#stale-trailers)):
   - Still wanted: `trailer_state` becomes `playing` and the zoom is applied.
   - Not wanted: the trailer is paused and `trailer_state` becomes `orphaned`.
   - `cancelled`: the trailer is stopped at once. A video that starts fullscreen is
     not a trailer (trailers start windowed), so it plays as normal.
3. Once a second, the poll loop checks the session:
   - `pending` or `cancelled` for 5 seconds or more with nothing new playing: the request is
     retired. If an older paused trailer is still playing, it goes back to
     `orphaned`; otherwise the session is cleared.
   - `playing` and stale, or within 2 seconds of its end: the trailer is paused and
     becomes `orphaned`.
   - `interrupted` or `orphaned`, and the trailer is still the video that is
     playing: if it is not paused, the service pauses it. If it is past its first
     second and Kodi can seek in it, the service rewinds it to the start. Once the
     user has been idle for 10 seconds (`System.IdleTime(10)`), the service runs
     `PlayerControl(Stop)`.
4. When playback stops, ends or fails, the session is cleared. A newer `pending`
   request is left alone.

If a video starts that the skin did not request as a trailer, any trailer session is
cleared and the video is treated as normal playback.

A trailer never plays to its natural end, and a stopped trailer is always rewound
first, so Kodi does not mark the trailer as watched.

The service only pauses, rewinds or stops a video whose path matches `trailer_file`.
It never acts on a film the user started.

## Starting a trailer

Run the `play_trailer` action. See [script actions](../script/actions.md) for the
full action reference.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `trailer` | Player path or plugin URL | *(required)* | The trailer to play. Nothing happens if empty. |
| `item` | Any text, usually `$INFO[ListItem.Label]` | empty | Label of the item the trailer is for. Used to detect that focus moved to another item. |
| `focus_ids` | Comma-separated control ids | empty | Controls that must keep focus while the trailer plays. Empty means no focus check. |
| `source_prefix` | A container id (e.g. `50`) or an infolabel prefix (e.g. `ListItem`) | empty | Where to read the item's label and aspect ratio. A number becomes `Container(<id>).ListItem`. |
| `viewport` | `WxH` in skin coordinates, e.g. `1088x612` | empty | Size of the video window the trailer plays in. Turns on zoom. |
| `window` | Any name, e.g. `home` | empty | The window or page the trailer plays in, so your skin can show it only there. |

Quote any `key=value` token whose value can contain a comma, such as titles and paths.

```xml
<control type="button" id="5100">
  <onfocus condition="!Player.HasMedia + !String.IsEmpty(ListItem.Trailer)">RunScript(script.copacetic.helper,action=play_trailer,"trailer=$INFO[ListItem.Trailer]","item=$INFO[ListItem.Label]",focus_ids=50,source_prefix=50,viewport=1088x612)</onfocus>
</control>
```

The action sets these properties, which the service reads:

| Property | Value |
|---|---|
| `trailer_state` | `pending` |
| `trailer_pending_since` | Time of the request, in seconds since the epoch |
| `trailer_item` | The `item` param |
| `trailer_source` | The `source_prefix` param |
| `trailer_focus_ids` | The `focus_ids` param |
| `trailer_viewport` | The `viewport` param |
| `trailer_window` | The `window` param |

## Stale trailers

A trailer is stale when any of these is true:

- `trailer_focus_ids` is set and none of those controls has focus.
- A modal dialog is open, such as the context menu, and it is not Kodi's busy dialog
  (`busydialog` or `busydialognocancel`). With `trailer_focus_ids` set, the focus
  check covers this instead: Kodi reads focus in the topmost modal dialog, so a
  trailer requested inside a dialog that holds those controls is not stale.
- `trailer_item` and `trailer_source` are both set, no modal dialog is open, and
  `<source>.Label` is not empty and differs from `trailer_item`.

The busy dialog doesn't make a trailer stale, because it shows while a trailer
resolves. The label check is skipped while it is open.

## Zoom

When a trailer starts playing, the service sets the player's view mode:

- **`trailer_viewport` set:** the service works out a zoom that fills the viewport
  in both directions, so burned-in black bars are cropped. It adds a 4% overshoot.
  The content aspect ratio comes from, in order:
  1. the trailer itself (`Player.Process(VideoDAR)`), unless it reports 16:9;
  2. `<source>.VideoAspect`;
  3. for a TV show (`<source>.DBType` is `tvshow`), the first episode's aspect ratio
     from the library.

  If no aspect ratio is found, no zoom is applied.
- **`trailer_viewport` empty:** the view mode is set to normal. This overrides any
  zoom Kodi stored for the file.

`trailer_viewport` must use a lower-case `x`, e.g. `1088x612`.

## Window properties set

| Property | Value | Set when | Cleared when |
|---|---|---|---|
| `trailer_state` | `playing` | The requested trailer starts and is still wanted | Playback stops, ends or fails; a real video starts |
| `trailer_state` | `orphaned` | The trailer goes stale or nears its end, or a newer request never started | As above |
| `trailer_file` | `Player.Filenameandpath` of the trailer | The requested trailer starts | As above |

When a session is cleared, the service clears `trailer_state`, `trailer_item`,
`trailer_source`, `trailer_focus_ids`, `trailer_window`, `trailer_viewport`,
`trailer_pending_since` and `trailer_file`.

### `trailer_played_item`

The service never sets `trailer_played_item`. Your skin can set it to the label of
the item whose trailer it just started, so the trailer doesn't start again on the
next focus. The service clears it when a trailer fails to play or a request is
retired, so the item can try again.

## What your skin should do

- Set `trailer_state` to `interrupted` when the user moves away from a playing
  trailer. The service pauses it, rewinds it and stops it after 10 idle seconds.
- Show the video window only while the trailer is playing. Compare `trailer_file`
  with the playing file, so a paused trailer stays hidden.
- Stop the trailer when the window closes, and set a `pending` request to `cancelled`
  so it stops as soon as it starts.

Example (from Copacetic):

```xml
<expression name="trailer_file_match">String.IsEqual(Player.Filenameandpath,Window(home).Property(trailer_file))</expression>
<expression name="trailer_playing">String.IsEqual(Window(home).Property(trailer_state),playing) + Player.HasVideo + $EXP[trailer_file_match]</expression>
<expression name="trailer_zombie">Player.HasVideo + $EXP[trailer_file_match] + [String.IsEqual(Window(home).Property(trailer_state),interrupted) | String.IsEqual(Window(home).Property(trailer_state),orphaned)]</expression>

<!-- in the list's onfocus: the user scrolled away from a playing trailer -->
<onfocus condition="[Container(50).OnPrevious | Container(50).OnNext] + $EXP[trailer_playing]">SetProperty(trailer_state,interrupted,home)</onfocus>

<!-- in the window: stop the trailer on close -->
<onunload condition="$EXP[trailer_playing] | $EXP[trailer_zombie]">PlayerControl(Stop)</onunload>
<onunload condition="String.IsEqual(Window(home).Property(trailer_state),pending)">SetProperty(trailer_state,cancelled,home)</onunload>

<!-- video window fades in only while the trailer is playing -->
<control type="videowindow">
  <animation effect="fade" start="0" end="100" time="300" condition="$EXP[trailer_playing]">Conditional</animation>
  <animation effect="fade" start="100" end="0" time="0" condition="!$EXP[trailer_playing]">Conditional</animation>
</control>
```

Kodi's busy dialog shows while a trailer resolves. To hide it, add this to
`DialogBusy.xml`:

```xml
<visible>Window.IsActive(busydialog) + !String.IsEqual(Window(home).Property(trailer_state),pending)</visible>
```
