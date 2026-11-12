# Script Actions

The helper runs one-off jobs when the skin calls it with `RunScript`. Each job is an
**action**: play a set of items, move focus, open a settings window, rebuild the
builder output, and so on. Put the call in any action list — `<onclick>`, `<onload>`,
`<onfocus>`, `<onstop>` — and the helper does the work in the background.

```xml
<onclick>RunScript(script.copacetic.helper,action=play_album,id=$INFO[ListItem.DBID])</onclick>
```

## How parameters are read

- The first parameter is always `action=<name>`. An unknown or missing name does
  nothing (a warning goes to the Kodi log).
- Every other parameter is a `key=value` pair, separated by commas. Order does not
  matter. Parameters an action does not use are ignored.
- **Every value arrives as text.** Each action converts what it needs. Where a table
  says `true`, write `true`. Some options also take `True`, or `1`, `yes` and `on`,
  and their row says so; anything else is off.
- An empty infolabel still sends its key. `key=$ESCINFO[ListItem.Label]` (or `$INFO`)
  on an item with no label reaches the action as `key` with an empty value, which is
  not the same as leaving `key` out: `user_trigger=` is off, but no `user_trigger` is
  on.
- Values are URL-decoded, so `%2C` becomes a comma and `%26` becomes `&`. A literal
  `%` followed by two hex digits is decoded too.
- Keys that start with `_` are dropped.
- If an action fails (for example a number parameter that is not a number), the error
  is written to the Kodi log and nothing else happens.

### Commas, quotes and spaces

Kodi splits `RunScript` parameters on commas before the helper sees them. Kodi does
**not** split on commas inside brackets `( )` or inside double quotes, and it removes
spaces at the start and end of each unquoted parameter.

The helper repairs most comma splits itself: a piece with no `=` is joined back on to
the value before it. So `focus_ids=3200,3201` arrives as `3200,3201`. This fails when
the text after a comma contains an `=`. Titles and paths can contain both, so wrap
the **whole** `key=value` pair in double quotes when the value comes from an
infolabel:

```xml
<onfocus>RunScript(script.copacetic.helper,action=play_trailer,"trailer=$INFO[ListItem.Trailer]","item=$INFO[ListItem.Label]")</onfocus>
```

Quote the whole pair (`"key=value"`), not only the value (`key="value"`).

### Running actions from builder controls

Actions can also run inside an open settings window, from a control's `onclick`
with `"type": "runtime_script"`. The `kwargs` there are the same parameters as
below, written as strings. See [Controls → runtime_script vs
custom](../builders/06-controls.md#runtime_script-vs-custom).

## Actions at a glance

| Action | What it does |
|---|---|
| [`chapter_focus`](#chapter_focus) | Sets `player_chapter_focus` to one chapter's tick, for a `ranges` control |
| [`clean_image_cache`](#clean_image_cache) | Removes this device's cached images no library item uses and nothing showed for 30 days |
| [`clear_api_cache`](#clear_api_cache) | Forgets every saved answer from TMDb, ListenBrainz or Deezer |
| [`clear_art`](#clear_art) | Removes the current artwork of every artist or album in Kodi's list, ready for a refresh |
| [`clear_cache`](#clear_cache) | Deletes the helper's processed artwork and its saved web service answers |
| [`clear_label`](#clear_label) | Empties a fadelabel control |
| [`container_reset`](#container_reset) | Selects a container's first item, or another, without focusing it |
| [`delete_orphans`](#delete_orphans) | Removes builder entries whose parent entry is gone |
| [`dialog_textviewer`](#dialog_textviewer) | Shows an infolabel's text in Kodi's text viewer |
| [`dialog_yesno`](#dialog_yesno) | Asks a yes/no question and runs builtins for the answer |
| [`dynamic_settings_window`](#dynamic_settings_window) | Opens a builder settings window |
| [`focus`](#focus) | Sets focus reliably, optionally selecting an item first |
| [`info`](#info) | Replaces the open info dialog with a library item's info |
| [`info_back`](#info_back) | Steps back along the infoscreen trail |
| [`info_swap`](#info_swap) | Reopens the info dialog on an item Kodi swapped into it |
| [`listenbrainz_test`](#listenbrainz_test) | Checks the ListenBrainz token |
| [`move_pin`](#move_pin) | Moves a pinned speed dial entry up or down |
| [`pin`](#pin) | Pins a music item to the front of speed dial |
| [`play_album`](#play_album) | Plays an album |
| [`play_album_from_track`](#play_album_from_track) | Plays a song's album, starting at that song |
| [`play_item`](#play_item) | Plays one library video from its resume point |
| [`play_items`](#play_items) | Plays every item in a container |
| [`play_radio`](#play_radio) | Old name for `start_mix` |
| [`play_trailer`](#play_trailer) | Plays a trailer in a window, with clean-up when focus moves on |
| [`player_stream`](#player_stream) | Steps the playing video's subtitle, audio or video stream, with no notification |
| [`player_stream_refresh`](#player_stream_refresh) | Updates `player_subtitle_kind` after Kodi changed the subtitle itself |
| [`playlist_goto`](#playlist_goto) | Plays the music queue from one of its songs |
| [`rate_song`](#rate_song) | Sets a song's user rating |
| [`rebuild`](#rebuild) | Rebuilds the builder output and reloads the skin |
| [`refresh_cached`](#refresh_cached) | Makes one library item's web answers and cached images come again |
| [`remove_broken_art`](#remove_broken_art) | Removes artwork links that are gone (web images and files) from the library |
| [`roll_seed`](#roll_seed) | Writes a fresh random number to a window property |
| [`search_backspace`](#search_backspace) | Rewrites `search_query` from the on-screen keys' log, deletes included |
| [`seed_keyboard_layout`](#seed_keyboard_layout) | Fills the `keyboard` mapping from a Kodi keyboard layout |
| [`set_edit`](#set_edit) | Writes text into an edit control |
| [`set_search_query`](#set_search_query) | Copies an edit control's text into a window property |
| [`shuffle`](#shuffle) | Plays an artist, album, genre, year or music playlist, shuffled |
| [`shuffle_artist`](#shuffle_artist) | Plays all of an artist's songs, shuffled |
| [`size_identity`](#size_identity) | Sizes the video OSD's logo control to the playing item's logo |
| [`skip_segment`](#skip_segment) | Seeks past the intro, recap or credits in play |
| [`start_mix`](#start_mix) | Plays a random mix built around a song, album, artist, genre or year |
| [`subtitle_limiter`](#subtitle_limiter) | Switches to a preferred subtitle language |
| [`tmdb_test`](#tmdb_test) | Checks the TMDb token |
| [`toggle_addon`](#toggle_addon) | Enables or disables an add-on |
| [`trailer_fullscreen`](#trailer_fullscreen) | Takes a window's trailer full screen without restarting it |
| [`trailer_return`](#trailer_return) | Reopens the info dialog a full-screen trailer came from |
| [`unpin`](#unpin) | Unpins a speed dial entry |
| [`waveform_background`](#waveform_background) | Makes Waveform the music visualiser, styled for a blurred background, or switches back |

All window properties below are set on the Home window (`Window(home)`), unless the
action lets you choose another window.

## Items the helper adds to the context menu

The helper adds items to Kodi's context menu, all but the last for music. They show only while a skin that
[opts in](../service/index.md#opting-in) is active (the service sets
`Window(home).Property(helper_active)` for it), on the items below, and each one runs
the action named. In any other skin they are hidden.

| Item | Shows on | Runs |
|---|---|---|
| Shuffle | Library artists, albums and genres; years in the music library; music playlists (`.xsp`, `.m3u`) | [`shuffle`](#shuffle) |
| Start mix | Library songs, artists, albums and genres; years in the music library | [`start_mix`](#start_mix) |
| Like | Library songs rated below `Skin.String(like_threshold)` | [`rate_song`](#rate_song), at the threshold |
| Unlike | Library songs rated at or above `Skin.String(like_threshold)` | [`rate_song`](#rate_song) with `rating=0` |
| Pin to speed dial | Library songs, artists and albums, and music playlists, that are not pinned in [speed dial](../plugins/speed_dial.md) | [`pin`](#pin) |
| Unpin | Library songs, artists and albums, and music playlists, that are pinned in speed dial | [`unpin`](#unpin) |
| Refresh cached data | Library films, sets, TV shows, seasons, episodes, music videos, artists, albums and songs | [`refresh_cached`](#refresh_cached) |

On [speed dial](../plugins/speed_dial.md) items, Shuffle, Start mix and Unpin come
from the item's own context rows instead, at the top of the menu.

Music playlists are the files in `special://musicplaylists/` and
`special://profile/playlists/music/`. Genres need a genre name. Years are the year
folders under `musicdb://`.

**Like** and **Unlike** need your skin to set `Skin.String(like_threshold)` to a
rating from `1` to `10`. While it is empty or `0`, neither shows.

**Pin to speed dial** and **Unpin** show only in a skin that uses speed dial: one
whose builder templates (`extras/templates/`) or `16x9/` XML name
`info=speed_dial`, for example in a widget's content path. The service checks when
the skin becomes active and again when it is updated, and sets
`Window(home).Property(helper_speed_dial)` for it. A skin that opts in without speed
dial gets the other five items only.

**Pin to speed dial** and **Unpin** tell a pinned item by the speed dial window
properties (see [Is this item pinned?](../plugins/speed_dial.md#is-this-item-pinned)),
so they show the right way round in any list, not only in speed dial.

Each item passes the clicked item's database id (the year itself for a year), its
type and its path to the action.

---

## chapter_focus

Sets `player_chapter_focus` to the playing video's chapter tick for chapter `chapter`:
the pair from `Player.Chapters` whose end is where that chapter starts. A `ranges`
control with only a right texture on that property draws the one tick, for example to
light the chapter focused in Kodi's bookmarks dialog, whose chapter items carry their
number as `ListItem.Property(chapter)` (1-based, the same n; bookmark items have none,
so call it for chapter items only). Kodi lists no pair for a first chapter that starts
at 0, so that chapter and no playing video empty the property. Clear it yourself when
the list opens: a script still running as it closes can write after its unload.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `chapter` | 1 to `Player.ChapterCount` | required | Kodi's chapter number |

**Sets:**

| Property | Value |
|---|---|
| `player_chapter_focus` | `start,end` percentages ending at the chapter's start; empty without one |
| `player_chapter_focus_number` | The `chapter` it was set for (the script starts a moment after focus moves, so compare it with the focused item's to hide a tick that lags) |

```xml
<!-- VideoOSDBookmarks.xml: a hidden button in list 11's focused layout, focused on each
     item; the Focus animation holds its onfocus until focus has stayed 150 ms. In an
     onfocus condition a bare ListItem is the window's, so name the list -->
<control type="button">
  <visible allowhiddenfocus="true">false</visible>
  <onfocus condition="!String.IsEmpty(Container(11).ListItem.Property(chapter))">RunScript(script.copacetic.helper,action=chapter_focus,chapter=$INFO[Container(11).ListItem.Property(chapter)])</onfocus>
  <animation effect="slide" end="0,0" time="150" reversible="false">Focus</animation>
</control>
<!-- the tick, while the list has focus and the property is this chapter's -->
<control type="ranges">
  <visible>Control.HasFocus(11) + String.IsEqual(Window(home).Property(player_chapter_focus_number),Container(11).ListItem.Property(chapter))</visible>
  <info>Window(home).Property(player_chapter_focus)</info>
  <righttexture>common/white.png</righttexture>
</control>
```

---

## clean_image_cache

Kodi keeps a cached copy of every image it shows (special://thumbnails), including
artwork the library no longer uses. This action lists the cached images that no
library item's own artwork points to (song artists and singles included) and that
Kodi hasn't recorded showing for 30 days (it saves use counts in batches), says how
many and how much space they take, and after a yes/no removes them
(`Textures.RemoveTexture`). The cache belongs to the device, so run it on each Kodi; it
doesn't touch the shared library. An image that is needed again is simply cached again
when it next shows (cast photos and add-on images included). Also in the helper's
settings, under *Library*.

No parameters.

```xml
<onclick>RunScript(script.copacetic.helper,action=clean_image_cache)</onclick>
```

---

## clear_api_cache

Asks first, then forgets every saved answer from one web service, so each is fetched
again the next time it is needed. For one item instead, use
[`refresh_cached`](#refresh_cached). Also in the helper's settings, under *Cache*.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `source` | `tmdb`, `listenbrainz`, `deezer`, `theintrodb` | required | Which service's answers |

```xml
<onclick>RunScript(script.copacetic.helper,action=clear_api_cache,source=listenbrainz)</onclick>
```

---

## clear_art

Asks first, then removes the current artwork (every art type of its own but covers
embedded in the music files, which a refresh never extracts again; or only the web
images) of every artist or album in Kodi's Artists or Albums list (song artists too when
Kodi's "Show song and album artists" setting is on). Kodi's scan only fills art types an
item doesn't already have, so stale or dead artwork stays until it is removed.
Afterwards refresh them all (Artists or Albums, context menu, *Change information
provider*, *Set for all … shown*, then yes to refreshing them all): art comes back from
the files in each folder first, then from the information provider.

Kodi's `AudioLibrary.SetArtistDetails` saves the whole artist, so each one also loses
its discography and its songs' music video links and their thumbnails (Omega reads
the artist without them before saving) and is marked as scraped; the refresh fills
them again. Each save also refreshes the open window and any music rows, so run it
from a screen without music rows; a large library takes a while. Image files are
not touched. Also in the helper's settings, under *Library*.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `artists`, `albums` | empty | Which list; empty asks |
| `online_only` | `true`, `false` | empty | `true` removes only web artwork, so new files in the folders take its place on the refresh and only the remaining gaps are filled online; empty asks |

```xml
<onclick>RunScript(script.copacetic.helper,action=clear_art,type=artists)</onclick>
```

---

## clear_cache

Deletes the helper's processed artwork (blurred, cropped and text images) and resets
its artwork lookup database. It also empties the saved answers from web services
(TMDb, ListenBrainz, Deezer), so they are fetched again, and the saved text truncations,
then compacts the database file. A notification shows how much space was saved.
Images are made again the next time they are needed.

No parameters.

```xml
<onclick>RunScript(script.copacetic.helper,action=clear_cache)</onclick>
```

---

## clear_label

Empties a **fadelabel** control in the current window. Use it in `<onload>`, so a
window kept in memory does not show its last text for a moment when it opens again. Not
in `<onunload>`: the script runs once the next window is current.

Nothing happens if the id is not a positive number. The control must exist in the
current window (the window itself, also while a dialog is open). It only works on
fadelabel controls.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | control id | required | The fadelabel to empty |

```xml
<onload>RunScript(script.copacetic.helper,action=clear_label,id=1500)</onload>
```

---

## container_reset

Selects a container's first item, or another, in the topmost dialog (else the active
window), with no focus change and no wrap (`ControlList.selectItem`). Kodi restores each
list's last selection when a kept-in-memory window opens again, before `<onload>`; this
puts a list back at the start, or on the playing song. `Control.Move` can't for a panel
with more than one row, since it moves a column at a time and wraps.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | container id | required | The container to reset |
| `item` | 1 and up | `1` | The item to select, counted from 1 as `MusicPlayer.PlaylistPosition` and `CurrentItem` count |

Example from Copacetic, for each info dialog rail at open:

```xml
<onload condition="Integer.IsGreater(Container(3211).CurrentItem,1)">RunScript(script.copacetic.helper,action=container_reset,id=3211)</onload>
```

---

## delete_orphans

Removes entries from a builder mapping whose parent entry no longer exists (see
[Runtime State → Parent links](../builders/09-runtime-state.md#parent-links)). If
anything was removed, it rebuilds the builder output, and reloads the skin if that
changed an output file. While a settings window is open, the rebuild waits until the
window closes. The rebuild sets [`helper_reloading`](#dynamic_settings_window), so the
skin can cover it.

Mappings without a `parent_mapping` are left alone.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `child_mapping` | mapping name | required | The mapping to clean |
| `require_parent` | `true` (any case) | off | Also remove entries that have no parent at all |

Inside a settings window, run it as a `runtime_script` control action, not with
`RunScript`. Example from Copacetic's templates:

```json
{ "type": "runtime_script", "action": "delete_orphans", "kwargs": { "child_mapping": "widgets", "require_parent": "true" } }
```

Outside a settings window:

```xml
<onclick>RunScript(script.copacetic.helper,action=delete_orphans,child_mapping=widgets)</onclick>
```

---

## dialog_textviewer

Opens Kodi's text viewer (`DialogTextViewer.xml`) on the text of an infolabel. The
helper reads the label itself, so long text with commas, quotes or `[CR]` never passes
through `RunScript`'s arguments. A bare `ListItem` reads the topmost modal dialog's item
(an info dialog's), else the active window's. Nothing opens when the text is empty.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `heading` | text | required | Dialog heading |
| `label` | an infolabel, without `$INFO[]` | required | The text to show |

```xml
<onclick>RunScript(script.copacetic.helper,action=dialog_textviewer,"heading=$LOCALIZE[24054]",label=ListItem.AddonNews)</onclick>
```

---

## dialog_yesno

Shows a Kodi yes/no dialog, then runs one list of builtins for **Yes** and another for
**No** (No also covers Back).

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `heading` | text | required | Dialog heading |
| `message` | text | required | Dialog text |
| `yes_actions` | builtins separated by `\|` | none | Run in order after **Yes** |
| `no_actions` | builtins separated by `\|` | `Null` | Run in order after **No** |

Commas inside a builtin's brackets are safe — Kodi does not split there.

```xml
<onclick>RunScript(script.copacetic.helper,action=dialog_yesno,heading=Reset view,message=Return this view to its defaults?,yes_actions=Skin.Reset(view_mode)|Notification(Done,View reset))</onclick>
```

---

## dynamic_settings_window

Opens a builder settings window as a dialog. The left-hand list shows the entries of
one mapping; the controls on the right edit the highlighted entry. Every change is
saved at once. The window loads the controls declared for `mapping` (plus any from
`controls_from`). When the window closes, the builder output is rebuilt if something
changed, and the skin reloads only if that changed an output file. A setting no output
file reads (one only mirrored to a skin setting, say) closes without a reload: see
[On close](../builders/09-runtime-state.md#on-close).

The full window contract — required control ids, management buttons, fixed versus
editable lists and hosting — is in
[Runtime State & Dynamic Editor](../builders/09-runtime-state.md#opening-a-settings-window).

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `mapping` | mapping name | required | The mapping this window edits. Without it, nothing opens. |
| `name` | window file name, without `.xml` | `dynamic_window` | Opens `<name>.xml` from your skin |
| `controls_from` | mapping names, comma separated | none | Also load these mappings' controls. They edit the `mapping` above. |
| `parent` | an entry's `runtime_id` | none | Show only the children of this entry; new entries get it as their parent |
| `focus_item` | a mapping item name | first entry | Select the first entry of this mapping item when the window opens |
| `host` | window name | none | The real window this editor stands in for. See [Hosting](../builders/09-runtime-state.md#hosting--binding-an-editor-to-a-real-window). |
| `host_focus` | control id | the list (100) | Control that gets focus when the window opens, with or without `host`. Back on it closes the window. It must be visible and able to take focus when the window opens, as the first action is handled as pressed on it. |

### What your window XML must have

| Control | Id | Notes |
|---|---|---|
| List | 100 | Required. Filled automatically. |
| Textbox or label | 6 | Required. Shows the description of the focused control. |
| Your controls | as declared in the control templates | Missing ones are skipped |
| Add, Move up, Move down, Delete | 410, 411, 412, 413 | Required when a control has `role` `item_picker` or `add_action`. Otherwise never attached, and not hidden for you. |
| Reset, Close | 414, 415 | Optional; Back from the list closes too. Reset asks for confirmation first. |
| Colour labels | 420, 421 | Optional hidden labels holding the focused and unfocused colour. Default `FFFFFFFF` and `80FFFFFF`. |

### Window properties

| Property | While the window is open |
|---|---|
| `active_editor_name` | The `name` of the open window. Cleared on close (or set back to the outer window's name for a window opened from inside another). |
| `current_mapping` | The `mapping`. With `parent`, the name becomes `current_mapping_<parent>`. Cleared on close. |
| `editor_label` | The window's `System.CurrentWindow` label when it opened. Set back to its earlier value on close. |
| `host_exit_target` | You set this (to a window name) to leave a hosted window. The helper clears it. |
| `helper_reloading` | `rebuild` while the builder outputs rebuild on close, then `reload` as the skin reload is sent (also in `rebuild` and `delete_orphans`, and `reload` alone when the service reloads for a skin update, except during fullscreen video), so the skin can cover both, for example with its splash. The skin clears it, once its window is ready after the reload; the helper clears it only when no reload follows: a failed rebuild, a rebuild on close or in `delete_orphans` that changed no output file (unless the editor's host window was opened again meanwhile, which still reloads), or a dropped or postponed reload. |

If the list is empty and it is an editable list, the Add dialog opens straight away.
Cancel it and the window closes.

Each list item also carries the entry's values as list item properties, for example
`Container(100).ListItem.Property(layout)`.

### Windows opened from inside another

A settings window opened while another is open does not rebuild on close. The
outermost window rebuilds once, when it closes. Hosting only applies to the outermost
window.

Examples from Copacetic:

```xml
<!-- the view settings, opened at the current content type -->
<onclick>RunScript(script.copacetic.helper,action=dynamic_settings_window,name=viewsettings,mapping=content_types,focus_item=$INFO[Container.Content])</onclick>

<!-- skin settings: SkinSettings.xml hosts the copaceticsettings editor -->
<onload condition="String.IsEmpty(Window(home).Property(active_editor_name))">RunScript(script.copacetic.helper,action=dynamic_settings_window,name=copaceticsettings,mapping=copacetic,host=skinsettings,host_focus=4610)</onload>
```

From a builder control, use `"type": "custom"` for this action, never
`runtime_script`.

---

## focus

Sets focus to a control and keeps trying, every 20 ms, until focus lands or the time
runs out. Use it where a plain `SetFocus` can be lost, for example straight after a
window opens or a container fills.

It can first select an item in a container: the item whose list item property
matches a value. If no item matches, nothing happens — focus does not move either.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `target` | control id | required | The control to focus |
| `select_container` | container id | none | Container whose selection moves first |
| `select_property` | list item property name | none | Property to compare on each item |
| `select_value` | text | none | Value that identifies the item |
| `timeout` | milliseconds | `500` | How long to keep trying |

The three `select_` parameters work only together.

Example from Copacetic: select a menu item by its `runtime_id`, then focus its
widget list:

```xml
<onclick>RunScript(script.copacetic.helper,action=focus,target=3200,select_container=3000,select_property=runtime_id,select_value=3ad35bab-f50e-5752-be73-c515e4f6b555)</onclick>
```

---

## info

Replaces the open info dialog with the info of a library item, for clicks inside an
info dialog: Kodi has no builtin that opens info for another item there. The helper
force-closes the open info dialogs (`movieinformation`, `musicinformation` and
`songinformation`) and opens the item's info with `xbmcgui.Dialog().info()`.

Before closing anything, the helper looks up video items and songs in the library.
Albums and artists are opened by their `musicdb://` path without a lookup.

- **The item is the one the dialog shows** (its key is `info_current`): nothing is
  reopened or focused, and `info_hop` is cleared. Handle this case in the skin, for
  example by focusing the tab row, and don't call the action.
- **The item can't be opened** (another type, or a video item or song not in the
  library): nothing is closed, and `info_hop` is cleared.
- **Kodi doesn't open the item** (it declines it, or the user cancels the busy dialog
  while music info loads): when `Dialog().info()` returns and `info_current` is not
  this item's key, the helper clears `info_hop`. The info dialogs are already closed
  by then, so the user is back on the window underneath.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `dbtype` | `movie`, `tvshow`, `episode`, `musicvideo`, `set`, `artist`, `album`, `song` | required | The item's `ListItem.DBType`. Any other value can't be opened. |
| `dbid` | database id | required | The item's `ListItem.DBID` |

Seasons can't be opened this way (Python can't set a season's show and season ids),
so browse to a season instead.

In this example, `3200` is a list in the info dialog, and the skin has already handled
the dialog's own item. A `focus` param from an older skin is ignored.

```xml
<onclick condition="Integer.IsGreater(Container(3200).ListItem.DBID,0) + String.IsEmpty(Window(home).Property(info_hop))">SetProperty(info_hop,forward,home)</onclick>
<onclick condition="Integer.IsGreater(Container(3200).ListItem.DBID,0) + String.IsEmpty(Window(home).Property(info_hop))">RunScript(script.copacetic.helper,action=info,"dbtype=$INFO[ListItem.DBType]","dbid=$INFO[ListItem.DBID]")</onclick>
```

### The trail

The skin keeps a trail of the items shown, as home window properties, so Back can
step back through them. Keys are `<dbtype>:<dbid>`.

| Property | Value | Written by |
|---|---|---|
| `info_current` | Key of the item showing | the skin, in the info dialogs' `<onload>` |
| `info_trail` | Keys of the items before it, newest first, joined by `\|` | pushed by the skin's `<onload>`, popped by `info_back` |
| `info_hop` | `forward` or `back` while a hop runs; `fullscreen` while the dialog is closed for its trailer's full screen | the skin, before `info` or `info_back`; the [metadata plugin](../plugins/metadata.md#in-an-info-dialog-targetitem) before `info_swap`; `info_swap`; going full screen (see [`trailer_fullscreen`](#trailer_fullscreen)); cleared by `<onload>` |

The skin's `<onunload>` clears `info_current` and `info_trail` only while `info_hop`
is empty, so a hop keeps the trail. The helper reads `info_current` after the dialog
it opened closes, to tell whether Kodi opened the item (see above).

Example (from Copacetic), in both info dialogs:

```xml
<onload condition="!String.IsEmpty(Window(home).Property(info_current)) + [String.IsEmpty(Window(home).Property(info_hop)) | String.IsEqual(Window(home).Property(info_hop),forward)]">SetProperty(info_trail,$INFO[Window(home).Property(info_current)]$INFO[Window(home).Property(info_trail),|,],home)</onload>
<onload>SetProperty(info_current,$VAR[info_key],home)</onload>
<onload>ClearProperty(info_hop,home)</onload>
<onunload condition="String.IsEmpty(Window(home).Property(info_hop))">ClearProperty(info_current,home)</onunload>
<onunload condition="String.IsEmpty(Window(home).Property(info_hop))">ClearProperty(info_trail,home)</onunload>

<!-- the item's key; empty for an item outside the library -->
<variable name="info_key">
  <value condition="Integer.IsGreater(ListItem.DBID,0)">$INFO[ListItem.DBType]:$INFO[ListItem.DBID]</value>
</variable>
```

---

## info_back

Steps back to the item shown before this one. It reads `info_current` and
`info_trail`, takes the newest key in the trail that names another item and can be
opened, writes the older keys back to `info_trail` and shows that item, as
[`info`](#info) does. Keys it skips (seasons, the current item, video items or songs
no longer in the library) are dropped. When there is none, it clears `info_hop` and
closes the info dialogs, so the dialog's `<onunload>` clears the trail. No
parameters.

```xml
<onback condition="!String.IsEmpty(Window(home).Property(info_trail)) + String.IsEmpty(Window(home).Property(info_hop))">SetProperty(info_hop,back,home)</onback>
<onback condition="!String.IsEmpty(Window(home).Property(info_trail)) + String.IsEmpty(Window(home).Property(info_hop))">RunScript(script.copacetic.helper,action=info_back)</onback>
```

Copacetic puts these on a control in the dialog, with a third `<onback>` that moves
focus to another control, so Kodi doesn't close the dialog as well.

---

## info_swap

Reopens the info dialog on an item that Kodi swapped into it. Kodi's own
**Information** item in a list's context menu can change the item an open info dialog
shows without opening the dialog again, so its `<onload>` does not run and the trail
misses the item. `info_swap` turns that into a normal hop, as [`info`](#info) does.

You don't need to call it yourself. The [metadata
plugin](../plugins/metadata.md#in-an-info-dialog-targetitem) runs it, with `info_hop`
set to `forward`, when its path has `target=item`.

- **The item can be opened:** the info dialogs are closed and the item's info opens.
- **It can't** (a season, or an item not in the library): the dialog reopens on the
  item it showed before (`info_current`) instead, with `info_hop` set to `back`.
- **Neither can be opened:** `info_hop` is cleared and the info dialogs close.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `key` | `<dbtype>:<dbid>` | required | The item Kodi swapped in |

```xml
<onclick>RunScript(script.copacetic.helper,action=info_swap,key=movie:42)</onclick>
```

---

## listenbrainz_test

Checks the ListenBrainz user token set in the helper's settings with ListenBrainz's
`/1/validate-token`. A notification says whether the token works or the request
failed. With no token set, ListenBrainz is off, and the notification says so.

No parameters.

```xml
<onclick>RunScript(script.copacetic.helper,action=listenbrainz_test)</onclick>
```

---

## move_pin

Moves a pinned [speed dial](../plugins/speed_dial.md) entry up or down among the
pinned entries. It stops at the top and bottom. Pinned speed dial items already carry
**Move up** (except the first) and **Move down** (except the last) in their context
menu, which run this action.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `album`, `artist`, `song`, anything else | none | The entry's type. Anything else means a playlist. |
| `id` | database id | none | The album, artist or song |
| `path` | playlist path | none | The playlist, for a playlist entry |
| `offset` | whole number | `1` | How many places to move. Negative moves up. |

Nothing happens if the entry is not pinned (an error goes to the Kodi log).

```xml
<onclick>RunScript(script.copacetic.helper,action=move_pin,type=album,id=$INFO[ListItem.DBID],offset=-1)</onclick>
```

---

## pin

Pins an album, artist, song or music playlist to the front of
[speed dial](../plugins/speed_dial.md). Pinning an entry that is already pinned moves
it to the front. The context menu's **Pin to speed dial** item runs this action.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `album`, `artist`, `song`, anything else | none | The entry's type. Anything else means a playlist. |
| `id` | database id | none | The album, artist or song |
| `path` | playlist path | none | The playlist, for a playlist entry |

```xml
<onclick>RunScript(script.copacetic.helper,action=pin,type=$INFO[ListItem.DBType],id=$INFO[ListItem.DBID])</onclick>
```

---

## play_album

Clears the playlists and plays an album from the music library, in order.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | album database id | none | The album. Missing, `0` or not a number: nothing happens, and the playlists are left as they are. |

```xml
<onclick>RunScript(script.copacetic.helper,action=play_album,id=$INFO[ListItem.DBID])</onclick>
```

---

## play_album_from_track

Clears the playlists, queues the song's whole album in disc and track order, and
starts playing at that song. Kodi's shuffle is turned off, so the album plays in
order. If the song is not in the library, nothing changes: what was playing carries
on. The album is added to the [speed dial](../plugins/speed_dial.md) recent list.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | song database id | required | The song to start from |

```xml
<onclick>RunScript(script.copacetic.helper,action=play_album_from_track,id=$INFO[ListItem.DBID])</onclick>
```

---

## play_item

Plays one library movie, episode or music video, from its resume point if it has one,
in place of whatever is playing. Kodi makes it the only item in the video playlist, so
[Play next](../service/playnext.md) queues on from an episode. Started over JSON-RPC,
it keeps a full-screen video full screen (a list's own click goes through `PlayMedia`,
which leaves full screen first).

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `movie`, `episode`, `musicvideo` | required | The item's library type |
| `id` | library id | required | The item's database id |

Example from Copacetic, a rail in the video OSD:

```xml
<onclick>RunScript(script.copacetic.helper,action=play_item,type=episode,id=$INFO[Container(3254).ListItem.DBID])</onclick>
```

---

## play_items

Clears the playlists, queues every item in a container and starts playing. In party
mode it turns party mode off first, as it would otherwise refill the queue.

- With `type=music`, every item is queued by its path (`ListItem.FileNameAndPath`) in
  the music playlist. Items with no path are left out. A library song
  (`ListItem.DBType` `song`) also carries its `ListItem.DBID`, so a
  [`rate_song`](#rate_song) on it while it plays shows straight away.
- Otherwise the items go in the video playlist. Library movies, episodes and music
  videos are queued by database id. Other items are queued by their path.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | container id | required | The container to play |
| `method` | `from_here`, `shuffle` | none | `from_here` starts at the selected item and plays to the end. `shuffle` plays the whole container shuffled. Anything else plays the whole container in order. |
| `type` | `music` | video | `music` uses the music playlist. Anything else uses the video playlist. |
| `select` | container id | none | With `type=music`: a list of the music queue (`playlistmusic://`) to select the new queue's first song in, once that list has refetched (up to 3 s). Kodi keeps a refetched list's selection by path, which can be a later song. |

Example from Copacetic:

```xml
<onclick>RunScript(script.copacetic.helper,action=play_items,id=3201,type=music,method=from_here)</onclick>
```

---

## play_radio

The old name for [`start_mix`](#start_mix), kept so older skins still work. It takes
the same parameters. Without `type`, it starts a mix from a song.

```xml
<onclick>RunScript(script.copacetic.helper,action=play_radio,id=$INFO[ListItem.DBID])</onclick>
```

---

## play_trailer

Plays a trailer without switching to full screen, so the skin can show it inside a
window (a `videowindow` control). If a skin that
[opts in](../service/index.md#opting-in) is active, the helper's background service then
watches it:

- If focus moves to another item, before or during playback, the trailer is paused
  and hidden instead of stopped.
- A trailer that reaches its last 2 seconds is paused and hidden too, so it never
  ends on its own.
- A paused, hidden trailer is rewound to the start, then stopped after 10 seconds
  without input. So Kodi never marks a trailer as watched.
- A request that never starts is dropped after 5 seconds.
- A request for the trailer already playing for the same `item` and `window` does
  nothing, so it plays on instead of restarting.
- If the user starts a film or song while the trailer is still on its way, that
  plays instead (a film full screen) and the request is dropped.
- With `viewport`, the service zooms the video to fill that area.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `trailer` | path or `plugin://` URL | required | The trailer to play. Empty does nothing. |
| `item` | text | none | The focused item's label when the request was made. If the item under `source_prefix` has a different label when playback starts, the trailer is treated as out of date. |
| `focus_ids` | control ids, comma separated | none | If none of these has focus when playback starts, the trailer is treated as out of date |
| `source_prefix` | container id, or an infolabel prefix such as `Container(50).ListItem` | none | Where to read the current item's label for the `item` check. A plain number means `Container(<id>).ListItem`. |
| `viewport` | `WxH`, in skin coordinates, with a lower-case `x` | none | Size of the area the trailer is shown in. Turns on zoom to fill it. Not checked: see [Zoom](../service/trailers.md#zoom). |
| `window` | text | none | The window or page the trailer plays in, stored in `trailer_window` so the skin can show it only there. |
| `fullscreen` | any text | none | Any value that isn't empty takes the trailer full screen as soon as it starts, as [`trailer_fullscreen`](#trailer_fullscreen) does. Each request sets this again, so a full-screen request that never started can't carry over to the next trailer. |

**Sets** (while the trailer request is live):

| Property | Value |
|---|---|
| `trailer_state` | `pending` when requested. The service changes it to `playing`, `fullscreen`, or `orphaned` once paused and hidden. Cleared when playback stops. |
| `trailer_item`, `trailer_focus_ids`, `trailer_source`, `trailer_viewport`, `trailer_window`, `trailer_fullscreen` | The values passed |
| `trailer_request` | The `trailer` param |
| `trailer_flight`, `trailer_pending_since` | The trailer and the time it was handed to Kodi; only when no earlier trailer is still resolving or opening, else it waits for the service to start it |

For example, show your `videowindow` only while
`String.IsEqual(Window(home).Property(trailer_state),playing)`.

Example from Copacetic (simplified). The whole `key=value` pairs are quoted because
titles and paths can contain commas:

```xml
<onfocus>RunScript(script.copacetic.helper,action=play_trailer,"trailer=$INFO[ListItem.Trailer]","item=$INFO[ListItem.Label]","focus_ids=3200,3201",source_prefix=3200,viewport=1920x1080)</onfocus>
```

---

## player_stream

Changes the playing video's subtitle, audio or video stream, for buttons in the video
OSD. It sets the stream directly, so Kodi shows no notification, as its own
`NextSubtitle`, `AudioNextLanguage` and `VideoNextStream` actions do.

- **Audio or video:** steps to the next stream, and from the last back to the first.
  With one stream, nothing happens. When the selected subtitle is forced, shown or
  hidden, Kodi swaps it for the new audio language's forced subtitle and shows or hides
  it without telling anyone, so after every audio step the action waits about a second
  and updates `player_subtitle_kind` (not if Kodi is shutting down meanwhile). Pass the
  Subtitles button's `lang` and `kind` on the Audio button too, so the update can read
  `missing`.
- **Subtitles with `lang`:** turns the preferred stream on, or off if it is already
  showing. If another stream is showing, it switches to the preferred one. The
  preferred stream is the first in that language of the type `kind` asks for. When
  there is none, it takes the other type below. When there is none of either, it
  turns subtitles off (if they are showing) and sets `player_subtitle_kind` to
  `missing`, so the skin can say there are no preferred subtitles.

  | `kind` | Looks for, in order |
  |---|---|
  | `full` | full, then hearing impaired |
  | `impaired` | hearing impaired, then full |
  | `forced` | forced only |

- **Subtitles without `lang`:** each stream in turn, then off. From off, it starts at
  the first stream.

A subtitle's type comes from its flags (`isforced`, `isimpaired` in JSON-RPC), then from
words in its name: `forced` is forced, unless `non` or `not` comes straight before it
(`Non-Forced`, `Not forced`; `Forced (non-English parts)` stays forced); `SDH`, `CC` or `HI` is hearing impaired. Anything else is full.

A subtitle file next to the video carries only the forced flag, so name a hearing
impaired file with `sdh` or `cc` (`Film.en.sdh.srt`). Avoid `hi` there: it is also
Hindi's language code, and Kodi reads the words from the end, so `Film.en.hi.srt` is a
Hindi subtitle. `hi` works only before the language (`Film.hi.en.srt`).

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `subtitle`, `audio`, `video` | required | The stream to change |
| `lang` | a language code or English name: `eng`, `en`, `deu`, `English` | none | The preferred subtitle language, read as the ISO 639-2/B code streams carry: `xbmc.convertLanguage` to ISO 639-1, then to 639-2, as Kodi compares languages, so `deu`, `fra` and `zho` read as `ger`, `fre` and `chi`. A language Kodi doesn't know is kept as given, so it finds nothing. Empty cycles every stream. With `type=audio`, used for the update after the step. |
| `kind` | `forced`, `full`, `impaired` | `full` | The preferred subtitle type, with `lang`. Empty counts as `full`. |

**Sets** (for `type=subtitle`, and about a second after a `type=audio` step):

| Property | Value |
|---|---|
| `player_subtitle_kind` | `forced`, `full` or `impaired` for the stream turned on. While off: `missing` when `lang` is set and has no preferred stream (with the fallback), otherwise empty |

The service also sets it when a video starts, without a language, so never `missing`
there. When the subtitle changes some other way (Kodi's subtitle settings dialog, a
remote key), or to show `missing` before the first press, call
[`player_stream_refresh`](#player_stream_refresh) with the same `lang` and `kind`.

For example, in the video OSD, with the preferred language and type in skin strings:

```xml
<onclick>RunScript(script.copacetic.helper,action=player_stream,type=subtitle,lang=$INFO[Skin.String(subtitle_language)],kind=$INFO[Skin.String(subtitle_kind)])</onclick>
<onclick>RunScript(script.copacetic.helper,action=player_stream,type=audio,lang=$INFO[Skin.String(subtitle_language)],kind=$INFO[Skin.String(subtitle_kind)])</onclick>
```

---

## player_stream_refresh

Reads the playing video's subtitle again and updates `player_subtitle_kind`. Kodi sends
no event when the subtitle changes in its own subtitle settings dialog or from a remote
key (and changing the audio stream can swap a forced subtitle), so call this where the
property is about to be shown: when the video OSD opens, and when the subtitle or audio
settings dialog closes. Pass the same `lang` and `kind` as the Subtitles button, so
`missing` shows before the first press. With no video playing (a dialog closing as
playback stops), it empties the property.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `lang` | as [`player_stream`](#player_stream) | none | With subtitles off, `missing` when this language has no preferred stream |
| `kind` | as [`player_stream`](#player_stream) | `full` | The preferred type, with `lang` |

**Sets:**

| Property | Value |
|---|---|
| `player_subtitle_kind` | As [`player_stream`](#player_stream): the type of the subtitle showing; `missing` or empty while off; empty with no video |

```xml
<!-- VideoOSD.xml -->
<onload>RunScript(script.copacetic.helper,action=player_stream_refresh,lang=$INFO[Skin.String(subtitle_language)],kind=$INFO[Skin.String(subtitle_kind)])</onload>
<!-- DialogSettings.xml, which Kodi also uses for the subtitle and audio settings -->
<onunload condition="Window.IsVisible(videoosd)">RunScript(script.copacetic.helper,action=player_stream_refresh,lang=$INFO[Skin.String(subtitle_language)],kind=$INFO[Skin.String(subtitle_kind)])</onunload>
```

---

## playlist_goto

Plays the music queue from one of its songs, through JSON-RPC `Player.GoTo`, so the queue
stays as it is. A list showing the queue (`playlistmusic://`) would otherwise play the
clicked song on its own, through `PlayMedia`.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `position` | 1 and up | required | The song's place in the queue, as the list's `CurrentItem` gives it |

Example from Copacetic, the music OSD's Playlist rail:

```xml
<onclick>RunScript(script.copacetic.helper,action=playlist_goto,position=$INFO[Container(3220).CurrentItem])</onclick>
```

---

## rate_song

Sets a song's user rating in the music library. If that song is playing,
`MusicPlayer.UserRating` shows the new rating straight away; Kodi updates it itself.
That includes songs the helper queues by file path ([`start_mix`](#start_mix),
[`shuffle`](#shuffle) a year, [`play_album_from_track`](#play_album_from_track),
[`play_items`](#play_items) `type=music`): each one carries its song id, which is how
Kodi matches the playing song to the update. Kodi also copies the update over the
song's queue entry and resets its place in the play order, so turning shuffle on or
off after a like can lose the queue's place (a Kodi bug, for any library song).

The context menu's **Like** and **Unlike** items run this action (see
[Items the helper adds to the context menu](#items-the-helper-adds-to-the-context-menu)).

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | song database id | `ListItem.DBID` | The song to rate |
| `rating` | whole number, `0`–`10` | `Skin.String(like_threshold)` | The rating. `0` removes it. |

A value that is empty or not a whole number counts as `0`. So with no `rating` and an
empty `like_threshold`, the song's rating is removed.

**Sets:** `Window(home).Property(liked_songs_version)` — a new token on every call.
Put it in a liked songs list's path (for example as an extra key in its `xsp`) so the
list refetches after a like: Kodi skips the library's update for a list that was empty.

Example: like and unlike the playing song from a button in the music OSD:

```xml
<onclick>RunScript(script.copacetic.helper,action=rate_song,id=$INFO[MusicPlayer.DBID])</onclick>
<altclick>RunScript(script.copacetic.helper,action=rate_song,id=$INFO[MusicPlayer.DBID],rating=0)</altclick>
```

---

## rebuild

Rebuilds all builder output (includes, variables, expressions), adds entries for any
new mappings, refreshes the resolver cache and reloads the skin. User settings are
kept unless you ask for a reset. A notification confirms it, or says the build failed,
with no reload; the next start tries again. The rebuild sets
[`helper_reloading`](#dynamic_settings_window), so the skin can cover it. See [Runtime State →
Reset vs rebuild](../builders/09-runtime-state.md#reset-vs-rebuild).

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `reset` | `true` | off | First delete all settings and output files, so everything is rebuilt from your template defaults. Also turns off the helper's "Reset on next start" setting if it was turned on in this skin; one meant for another skin stays on (to move it to this skin, turn it off and press OK, then turn it on again). |

```xml
<onclick>RunScript(script.copacetic.helper,action=rebuild)</onclick>
<onclick>RunScript(script.copacetic.helper,action=rebuild,reset=true)</onclick>
```

---

## refresh_cached

Makes what was saved for one library item come again when next shown, and refreshes
the list in a media window (on Home a widget fetches again when its content next
loads). The context menu's **Refresh cached data** item runs it. A notification says
whether anything was cached for the item. Checking the sources takes up to six
seconds.

- **Web answers** are marked out of date rather than deleted: a film's TMDb details
  and TheIntroDB skip times;
  for a TV show, season or episode, the show's and all its seasons'; for an artist,
  album or song, its ListenBrainz answers (by its MusicBrainz id: an artist's top
  songs, top albums and listener count); for an artist, also its Deezer match and
  top tracks, so the next open searches Deezer again; for a TV show, season or
  episode, also TheIntroDB's skip times for all the show's episodes. Each is fetched
  again when next needed, and the old answer still shows if that fetch fails (offline,
  service down).
- **Processed artwork** (blurred, cropped) of the item's own artwork that was made
  before Kodi had cached the image is forgotten, so it is made again. The rest is
  keyed by the image's content, so it is made again by itself once the image changes.
- **This device's cached copies** of that artwork (`Textures.RemoveTexture`) and of
  its processed images are removed, so an image file replaced under the same name is
  read again when next loaded rather than after Kodi's daily check. An image on screen
  at the time keeps its copy in memory: move focus off it for a few seconds (Kodi
  frees a large image two seconds after it leaves the screen) and it reloads. A
  source that can't be read right now keeps its copy, as it may be the only one
  left: a missing file, a share or web address that doesn't answer within a few
  seconds, or one that answers with anything but an image.

It doesn't change the library: art links and information stay as they are (for
those, Kodi's *Refresh* in the information dialog). Art a parent lends the item
(`tvshow.poster` on an episode) is the parent's, so refresh the parent for that.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | database id | required | The item |
| `type` | `movie`, `set`, `tvshow`, `season`, `episode`, `musicvideo`, `artist`, `album`, `song` | required | Its type (`ListItem.DBType`) |

```xml
<onclick>RunScript(script.copacetic.helper,action=refresh_cached,id=$INFO[ListItem.DBID],type=$INFO[ListItem.DBType])</onclick>
```

---

## remove_broken_art

Reads the artwork of every artist (song artists too), album (singles
too), film, set, TV show and season, checks each link once (eight at a time), and lists
the dead ones:

- a web image that answers 404 or 410 to both a HEAD and a one-byte GET;
- a file on an smb:// or nfs:// share that answers, which is missing and absent from its
  folder's listing (or whose folder is absent from its parent's). A share that is asleep
  or refuses this device checks nothing, and local paths are never checked: the library
  is shared, and a path can exist on one device and not another;
- a web server whose name doesn't exist, looked up again after the check. These are
  listed by name in a second question, as a name only your network knows (`.local`,
  a VPN) would look the same; `.local`, `.lan`, `.home`, `.internal`, `.arpa` and
  single-word names are never offered.

Anything uncertain (a timeout, a server refusing the check) counts as fine, a server
that times out or refuses three times in a row has its other images skipped for the run, and images Kodi
makes itself (embedded art, video thumbnails) are skipped; the log counts what was
skipped. Run it on a device whose share login can read every art folder: a server that
hides folders a login can't read makes them look missing. It needs a working
internet connection before and after the check. After a yes/no it removes the dead
links from the library and logs each item it changed.

Artists and albums get new art from a refresh of them all (see [`clear_art`](#clear_art));
an artist it changes also loses its discography and music video links until then, and a
song-only artist comes back on the refresh-all only with Kodi's "Show song and album
artists" setting on. A film or show shows its other art until you refresh it or choose
art for it; a TV show is saved whole (Omega's `SetTVShowDetails` rewrites its details
from the library's own copy). Each save refreshes the open window. Also in the helper's
settings, under *Library*.

No parameters.

```xml
<onclick>RunScript(script.copacetic.helper,action=remove_broken_art)</onclick>
```

---

## roll_seed

Writes a new random whole number (0 to 2147483647) to a window property. Use it to
make random choices in XML that stay the same until you roll again.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `prop` | property name | required | The window property to write |
| `window_id` | window id | `10000` (Home) | The window that holds the property. Not a number falls back to `10000`. |

Example from Copacetic, on window load:

```xml
<onload>RunScript(script.copacetic.helper,action=roll_seed,prop=random_seed)</onload>
```

---

## search_backspace

For an on-screen keyboard whose keys append to `Window(home).Property(search_query)`
in XML rather than typing into an edit control. XML can't remove a character, so the
delete key needs a script, and a script starts a moment after the click (about 0.25 s
on a Mac, longer on slower boxes). Until its first write the deleted character is still
in the query, and anything reading the query, such as search rails, sees it.

So every key also appends to a log, `Window(home).Property(search_log)`, in the same
click: a letter key its text, the delete key `←`. This action replays the log (each `←`
removes the character before it) and writes the result to `search_query`. It reads the
log again after the write and repeats until the log hasn't changed. The write is a
`SetProperty` builtin run with `wait`, which Kodi runs on its main thread between
frames, never in the middle of a click. So keys pressed while the script runs, and
several delete scripts in any order, end on the log's text. Removing the only character
leaves the property empty.

The property holds the text itself: letters, digits and spaces as the keys wrote them,
not the encoded text [`set_search_query`](#set_search_query) writes. A letter or digit,
in any alphabet, needs no encoding in a search path's xsp, and a space only needs its
quotes kept. Keep key values to those characters (Copacetic's key editor uses
`plain_text`, see [Controls → edit](../builders/06-controls.md#edit--free-text)): `"`
breaks the keys' `SetProperty` and this action's, and `&`, `+`, `%` and `|` change a
library path's options.

Clear `search_log` whenever you clear `search_query` by other means, and clear a
`search_query` that has no log, so the two always agree.

No params.

**Sets:** `Window(home).Property(search_query)`.

Examples from Copacetic:

```xml
<!-- a letter key: $INFO resolves when the click runs, and the quotes keep a trailing space -->
<onclick>SetProperty(search_query,"$INFO[Window(home).Property(search_query)]a",home)</onclick>
<onclick>SetProperty(search_log,"$INFO[Window(home).Property(search_log)]a",home)</onclick>
<!-- delete key -->
<onclick>SetProperty(search_log,"$INFO[Window(home).Property(search_log)]←",home)</onclick>
<onclick>RunScript(script.copacetic.helper,action=search_backspace)</onclick>
```

---

## seed_keyboard_layout

Fills the builder mapping called `keyboard` with the letters and then the digits of a
Kodi keyboard layout, one entry per character (at most 48). Each entry's `value`
field holds its character. Use it to build an on-screen keyboard from templates.

Your skin must define a mapping named `keyboard` whose items are `slot1`, `slot2`, …
with at least as many items as the layout has characters. If there are too few, the
action fails and nothing is written.

Where a language has several layouts, one whose letters run in code-point order (the
alphabetical one, for English-style layouts) is used, even if you name another;
otherwise the one you name, or the language's first layout if none has that name. A
language Kodi doesn't have, or one with only coding-table layouts, falls back to
English ABC.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `layout` | `<language> <layout>`, as in Kodi's keyboard layout files (for example `English ABC`, `Russian АБВ`) | ask | Without it, a dialog lists every layout to choose from, except the coding-table ones (Chinese, Japanese and Korean input). Cancel writes nothing. |

It does not rebuild by itself. Run it from a control inside a settings window, so
the rebuild happens when the window closes. Example from Copacetic's templates:

```json
{ "type": "runtime_script", "action": "seed_keyboard_layout" }
```

---

## set_edit

Writes text into an edit control, as if the user typed it. Use it to build your own
on-screen keyboard from buttons.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | edit control id | required | The edit control |
| `mode` | `set`, `append`, `backspace`, `space`, `clear` | `set` | `set` replaces the text with `text`. `append` adds `text` to the end. `backspace` removes the last character. `space` adds a space. `clear` empties it. Any other value works like `set`. |
| `text` | text | empty | The text for `set` and `append` |
| `return_id` | control id | none | Control to focus again afterwards |

The edit control is focused while the text is written, which fires its
`<ontextchange>`. Focus moves when the script runs, a moment after the click, so a
move the user makes in between is undone. For a search box, the keys can write the
query property themselves instead (see [`search_backspace`](#search_backspace)).

Example from Copacetic, the view menu's clear button, which empties the filter box:

```xml
<onclick>RunScript(script.copacetic.helper,action=set_edit,id=19,return_id=19)</onclick>
```

---

## set_search_query

Copies an edit control's text into a window property, ready to use in a search
path: JSON-escaped and URL-encoded, so it drops between `$ESCINFO[…]`'s quotes in an
xsp value and `&`, `+` and `%` survive. It isn't meant for a label (a space shows as
`%20`). Text shorter than `min_length` clears the property instead.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | edit control id | required | The edit control to read |
| `min_length` | whole number | `3` | Fewest characters before the text is copied |

**Sets:** `Window(home).Property(search_query)`.

Example from Copacetic:

```xml
<!-- on the edit control: typing and Kodi's keyboard -->
<ontextchange>RunScript(script.copacetic.helper,action=set_search_query,id=4200,min_length=1)</ontextchange>
<!-- on a results container: movies whose title contains the query -->
<content>videodb://movies/titles/?xsp=%7B%22rules%22%3A%7B%22and%22%3A%5B%7B%22field%22%3A%22title%22%2C%22operator%22%3A%22contains%22%2C%22value%22%3A%5B$ESCINFO[Window(home).Property(search_query)]%5D%7D%5D%7D%2C%22type%22%3A%22movies%22%7D</content>
```

---

## shuffle

Clears the playlists and plays an artist, album, genre, year or music playlist in
random order. The context menu's **Shuffle** item runs this action.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `artist`, `album`, `genre`, `year`, anything else | `artist` | What to play. Anything else plays the folder or playlist in `path`. |
| `id` | database id, or the year itself for `year` | none | The artist, album, genre or year |
| `path` | a music playlist or folder path | none | What to play when `type` is not one of the four above |

A `year` plays every song from that year, queued in random order with Kodi's shuffle
turned off. The others play the whole artist, album, genre or playlist with Kodi's
shuffle turned on.

Except for a genre or a year, what was played is added to the
[speed dial](../plugins/speed_dial.md) recent list.

```xml
<!-- an album -->
<onclick>RunScript(script.copacetic.helper,action=shuffle,type=album,id=$INFO[ListItem.DBID])</onclick>
<!-- a playlist: quote the pair, as paths can hold commas -->
<onclick>RunScript(script.copacetic.helper,action=shuffle,type=playlist,"path=$INFO[ListItem.FolderPath]")</onclick>
```

---

## shuffle_artist

Plays all of an artist's songs, shuffled. It is the same as
[`shuffle`](#shuffle) with `type=artist`, kept so older skins still work.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | artist database id | none | The artist |

```xml
<onclick>RunScript(script.copacetic.helper,action=shuffle_artist,id=$INFO[ListItem.DBID])</onclick>
```

---

## start_mix

Replaces what is playing with a random mix of up to 50 songs from your music
library. The context menu's **Start mix** item runs this action. The mix is chosen
first, so music or video that is playing carries on until the new songs are ready.
Then the playlists are cleared and the mix plays in order from its first song, with
Kodi's shuffle turned off.

- **Song, album or artist:** the mix starts with one song. For a song, that is the
  song itself. For an album or artist, it is one of its five most played songs,
  picked at random. Up to seven more songs are by the same artist, spread evenly
  through the mix. The rest are random songs by other artists that share the first
  song's genres. A first song with no genre takes the genres of its artist's other
  songs; if none of them has one either, the mix is songs by its artist only.
- **Genre or year:** 50 random songs of that genre or year.

If the album or artist has no songs, or the song is not found, nothing changes: what
was playing carries on. A genre or year with no songs clears the playlists and plays
nothing.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `song`, `album`, `artist`, `genre`, `year` | `song` | What the mix is built around |
| `id` | database id, or the year itself for `year` | `ListItem.DBID` (not for `genre` or `year`) | The item |

A mix from a song, album or artist adds that item to the
[speed dial](../plugins/speed_dial.md) recent list.

```xml
<onclick>RunScript(script.copacetic.helper,action=start_mix,type=artist,id=$INFO[ListItem.DBID])</onclick>
```

---

## subtitle_limiter

[`player_stream`](#player_stream) replaces this action: it also picks a subtitle type
and shows no notification. This one stays for skins that call it.

Turns on subtitles in a preferred language, so one button skips the other subtitle
streams. If that language is not available, it steps to the next subtitle stream
instead (`Action(NextSubtitle)`). If subtitles in that language are already on,
pressing again turns subtitles off.

Does nothing if the playing video has no subtitles.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `lang` | a subtitle language as Kodi reports it, for example `eng` | required | The preferred language |
| `user_trigger` | `false` | on | When on, a stream already in the preferred language is turned on if hidden, and off if showing. `false` leaves a stream already in that language as it is, shown or hidden. `true`, `1`, `yes` and `on` count as on; any other value, empty included, as off. |

What `false` does not change: when the current stream is in another language, the
action still switches, and switching to the preferred stream always makes subtitles
visible. When no stream is in that language, `Action(NextSubtitle)` still runs: Kodi
shows its subtitle notification, turns hidden subtitles on, and after the last stream
turns them off.

The current stream counts as the preferred language when its language contains `lang`;
a stream to switch to must match it exactly, so pass the language as Kodi reports it
(`eng`, not `en`).

Example from Copacetic, in the video OSD:

```xml
<onclick condition="Skin.String(Subtitle_Limiter)">RunScript(script.copacetic.helper,action=subtitle_limiter,lang=$INFO[Skin.String(Subtitle_Limiter)])</onclick>
```

---

## size_identity

Sizes control `4045` in the video OSD or the seek bar dialog to the playing item's
logo, as the service does when a video starts, then sets `player_identity_<window>`.
See [Identity and clean names](../service/player.md#identity-and-clean-names).

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `window` | `videoosd`, `seekbar` | `videoosd` | Which window's logo control |

Examples from Copacetic. The video OSD sizes only when it isn't sized for this logo yet;
the seek bar dialog, opened when video goes full screen (and after a skin reload), sizes
itself and has the OSD size again on its next open:

```xml
<onload condition="!String.IsEqual(Window(home).Property(player_identity_videoosd),Window(home).Property(player_clearlogo))">RunScript(script.copacetic.helper,action=size_identity)</onload>
```

```xml
<onload>ClearProperty(player_identity_videoosd,home)</onload>
<onload>RunScript(script.copacetic.helper,action=size_identity,window=seekbar)</onload>
```

---

## skip_segment

Seeks to the end of a skip segment (see
[Skip segments](../service/player.md#skip-segments)), exactly. Pass
`player_skip_seek`. The service moves on to the next segment as one ends, so check
first that the segment is still the one the button opened on (hold
`player_skip_start` when it opens and compare). Don't send `PlayerControl(Next)` for a
segment ending on a chapter: with a playlist of two or more (Play next's queued
episode), Kodi's playlist takes Next first and plays the next file.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `seek` | Seconds | required | Where to seek to |

Example from Copacetic, the skip button's OK (`skip_live` compares the held start and
checks the playhead is still inside):

```xml
<onclick condition="$EXP[skip_live]">RunScript(script.copacetic.helper,action=skip_segment,seek=$INFO[Window(home).Property(player_skip_seek)])</onclick>
```

---

## tmdb_test

Checks the TMDb token set in the helper's settings with a test request. A
notification says whether the token works or the request failed. With no token set,
TMDb is off, and the notification says so.

No parameters.

```xml
<onclick>RunScript(script.copacetic.helper,action=tmdb_test)</onclick>
```

---

## toggle_addon

Enables an add-on if it is disabled, or disables it if it is enabled. A notification
shows the new state.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | add-on id | required | The add-on to switch |

```xml
<onclick>RunScript(script.copacetic.helper,action=toggle_addon,id=script.module.example)</onclick>
```

---

## trailer_fullscreen

Takes the trailer that a window or page plays full screen. It takes the same
parameters as [`play_trailer`](#play_trailer), but `window` is required, and
`fullscreen` is always on. `window` says whose trailer it is:

- Its trailer is `playing`: it goes full screen at once and carries on from where it
  is (`Action(FullScreen)`, no new `PlayMedia`).
- Its trailer is `pending`: it goes full screen as soon as it starts.
- Otherwise: the trailer is requested now and goes full screen as soon as it starts.

Without `window`, the trailer never counts as this window's, so every press starts
it again from the beginning.

Going full screen sets `trailer_state` to `fullscreen`, sets the view mode to normal
and copies `info_current` into `trailer_return`, the info dialog to reopen when full
screen closes (see [`trailer_return`](#trailer_return)). Kodi closes the video info
dialog first (`CGUIWindowManager::SwitchToFullScreen`). Unless the item is a season,
which can't be reopened, `info_hop` is set to `fullscreen` first, so the close is a
hop: the trail survives and the window underneath stays covered until the reopen. Within 2 seconds of its end,
the service rewinds and stops a full-screen trailer.

```xml
<onclick>RunScript(script.copacetic.helper,action=trailer_fullscreen,"trailer=$INFO[Container(9000).ListItem.Trailer]","item=$INFO[Container(9000).ListItem.Label]",focus_ids=4611,source_prefix=ListItem,viewport=16x9,window=infoscreen)</onclick>
```

---

## trailer_return

Run it once full screen has closed on a trailer that
[`trailer_fullscreen`](#trailer_fullscreen) took there. It clears `trailer_return`
and reopens the info dialog it names, as [`info`](#info) does. If the trailer is
still playing, it gets its zoom back first; your skin's `<onload>` sets
`trailer_state` back to `playing`. With no dialog to reopen, `info_hop` is cleared and
the trailer is stopped.

No parameters. Copacetic runs it from a skin timer:

```xml
<start reset="true">[!String.IsEmpty(Window(home).Property(trailer_return)) | String.IsEqual(Window(home).Property(trailer_state),fullscreen)] + !Window.IsActive(fullscreenvideo) + !System.HasActiveModalDialog</start>
<onstart>RunScript(script.copacetic.helper,action=trailer_return)</onstart>
```

---

## unpin

Unpins a [speed dial](../plugins/speed_dial.md) entry. If it was played recently, it
stays in speed dial among the recent entries. The context menu's **Unpin** item runs
this action. It shows on any pinned item.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `type` | `album`, `artist`, `song`, anything else | none | The entry's type. Anything else means a playlist. |
| `id` | database id | none | The album, artist or song |
| `path` | playlist path | none | The playlist, for a playlist entry |

```xml
<onclick>RunScript(script.copacetic.helper,action=unpin,type=playlist,"path=$INFO[ListItem.FolderPath]")</onclick>
```

---

## waveform_background

For a skin that draws Kodi's Waveform visualiser over its own blurred background.

**On** (`enabled=true`):

1. Waveform (`visualization.waveform`) is installed if it is missing (Kodi asks
   first, after the master lock's code if one is set) or enabled if it is turned off.
   If it still isn't enabled (the user said no, the install failed, or no repository
   offers it), a notification says so and nothing else changes.
2. Waveform's own settings are kept in the skin string `waveform_look`, then written:
   calm curves (*Points per line* 250, the fewest), a thin line (*Line thickness* 2)
   in the skin's near-white `ghosted` (Waveform draws without blending, so the line
   can't be see-through: the skin dims it under a veil of its blur) and no background
   colour, so whatever is behind the visualisation shows through.
3. The current visualiser (Kodi's *Settings › Player › Music › Visualisation*) is
   kept in the skin string `waveform_restore`, and Waveform becomes the visualiser.

**Off** (anything else): if Waveform is still the visualiser, the one kept in
`waveform_restore` comes back (empty means none, and so does one that has since been
removed or disabled); if the user has picked another
visualiser since, it is left alone. Either way, Waveform's own settings go back to
those kept in `waveform_look` while Waveform is still installed and enabled, and
`waveform_look` is then emptied.

It runs once per switch, nothing is enforced afterwards. A visualiser reads its
settings when it starts, so a visualisation already on screen keeps its old look
until it next opens.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `enabled` | `true`, anything else | required | On or off |

From a builder radiobutton, `{waveform_background}` is the field's new value:

```json
"onclick": { "type": "custom", "action": "RunScript(script.copacetic.helper,action=waveform_background,enabled={waveform_background})" }
```
