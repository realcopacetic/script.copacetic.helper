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
  says `true`, only the exact word `true` turns the option on; anything else is off.
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
| [`clean_filename`](#clean_filename) | Tidies a file name into a readable label |
| [`clear_cache`](#clear_cache) | Deletes the helper's processed artwork |
| [`clear_label`](#clear_label) | Empties a fadelabel control |
| [`container_move`](#container_move) | Moves a container one item, with optional stop at the ends |
| [`delete_orphans`](#delete_orphans) | Removes builder entries whose parent entry is gone |
| [`dialog_yesno`](#dialog_yesno) | Asks a yes/no question and runs builtins for the answer |
| [`dynamic_settings_window`](#dynamic_settings_window) | Opens a builder settings window |
| [`focus`](#focus) | Sets focus reliably, optionally selecting an item first |
| [`play_album`](#play_album) | Plays an album |
| [`play_album_from_track`](#play_album_from_track) | Plays a song's album, starting at that song |
| [`play_items`](#play_items) | Plays every item in a container |
| [`play_radio`](#play_radio) | Plays a song, then random songs of the same genre |
| [`play_trailer`](#play_trailer) | Plays a trailer in a window, with clean-up when focus moves on |
| [`rate_song`](#rate_song) | Sets a song's user rating |
| [`rebuild`](#rebuild) | Rebuilds the builder output and reloads the skin |
| [`roll_seed`](#roll_seed) | Writes a fresh random number to a window property |
| [`seed_keyboard_layout`](#seed_keyboard_layout) | Fills the `keyboard` mapping from a Kodi keyboard layout |
| [`set_edit`](#set_edit) | Writes text into an edit control |
| [`set_search_query`](#set_search_query) | Copies an edit control's text into a window property |
| [`shuffle_artist`](#shuffle_artist) | Plays all of an artist's songs, shuffled |
| [`subtitle_limiter`](#subtitle_limiter) | Switches to a preferred subtitle language |
| [`tmdb_test`](#tmdb_test) | Checks the TMDb token |
| [`toggle_addon`](#toggle_addon) | Enables or disables an add-on |

All window properties below are set on the Home window (`Window(home)`), unless the
action lets you choose another window.

---

## clean_filename

Turns a file name into a readable label: dots and underscores become spaces. The
result goes into a window property, so you can show it with `$INFO[]`.

If Kodi's **Show file extensions** setting is on, the last dot is kept, so the
extension stays attached (`My.Home.Video.mkv` → `My Home Video.mkv`).

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `label` | any text | `ListItem.Label` | The text to clean. Empty or missing uses the focused item's label. |

**Sets:** `Window(home).Property(Return_Label)` — the cleaned label.

```xml
<!-- on the list -->
<onfocus>RunScript(script.copacetic.helper,action=clean_filename)</onfocus>
<!-- on a label control -->
<label>$INFO[Window(home).Property(Return_Label)]</label>
```

---

## clear_cache

Deletes the helper's processed artwork (blurred, cropped and text images) and resets
its artwork lookup database. A notification shows how much space was saved. Images
are made again the next time they are needed.

No parameters.

**Sets:** `Window(home).Property(Addon_Data_Folder_Size)` — the size of the helper's
data folder after clearing, for example `1.2 MB`.

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

## container_move

Moves a container's selection with `Control.Move`. With `wrap=false` it stops at the
first and last item instead of wrapping round. Useful for auto-scrolling timers that
should stop at the end of a list.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | container id | the focused control | The container to move |
| `offset` | a whole number | required | Must be present. In the current version the move is always 1 item forward, whatever value you pass. |
| `wrap` | `false` | — | `false` does nothing when the move would pass either end. Any other value lets Kodi wrap as normal. |

Example from Copacetic, at the end of an auto-scroll timer:

```xml
<onstop>RunScript(script.copacetic.helper,action=container_move,id=$INFO[Window(home).Property(autoscroll_id)],offset=1,wrap=false)</onstop>
```

---

## delete_orphans

Removes entries from a builder mapping whose parent entry no longer exists (see
[Runtime State → Parent links](../builders/09-runtime-state.md#parent-links)). If
anything was removed, it rebuilds the builder output and reloads the skin. While a
settings window is open, the rebuild waits until the window closes.

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
`controls_from`). When the window closes, the builder output is rebuilt and the skin
reloads, but only if something changed.

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
| `host_focus` | control id | the list (100) | Control that gets focus when the window opens |

### What your window XML must have

| Control | Id | Notes |
|---|---|---|
| List | 100 | Required. Filled automatically. |
| Textbox or label | 6 | Required. Shows the description of the focused control. |
| Your controls | as declared in the control templates | Missing ones are skipped |
| Add, Move up, Move down, Delete | 410, 411, 412, 413 | Optional. Only shown when a control has `role` `item_picker` or `add_action`. |
| Reset, Close | 414, 415 | Optional. Reset asks for confirmation first. |
| Colour labels | 420, 421 | Optional hidden labels holding the focused and unfocused colour. Default `FFFFFFFF` and `80FFFFFF`. |

### Window properties

| Property | While the window is open |
|---|---|
| `active_editor_name` | The `name` of the open window. Cleared on close (or set back to the outer window's name for a window opened from inside another). |
| `current_mapping` | The `mapping`. With `parent`, the name becomes `current_mapping_<parent>`. Cleared on close. |
| `editor_label` | The window's `System.CurrentWindow` label when it opened. Set back to its earlier value on close. |
| `host_exit_target` | You set this (to a window name) to leave a hosted window. The helper clears it. |

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

## play_album

Clears the playlists and plays an album from the music library, in order.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | album database id | none | The album. Missing or `0` plays nothing. |

```xml
<onclick>RunScript(script.copacetic.helper,action=play_album,id=$INFO[ListItem.DBID])</onclick>
```

---

## play_album_from_track

Clears the playlists, queues the song's whole album in disc and track order, and
starts playing at that song.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | song database id | required | The song to start from |

```xml
<onclick>RunScript(script.copacetic.helper,action=play_album_from_track,id=$INFO[ListItem.DBID])</onclick>
```

---

## play_items

Clears the playlists, queues every item in a container and starts playing. Library
movies, episodes, music videos and songs are queued by database id. Other items are
queued by their path (`ListItem.FileNameAndPath`).

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | container id | required | The container to play |
| `method` | `from_here`, `shuffle` | none | `from_here` starts at the selected item and plays to the end. `shuffle` plays the whole container shuffled. Anything else plays the whole container in order. |
| `type` | `music` | video | `music` uses the music playlist. Anything else uses the video playlist. |

Example from Copacetic:

```xml
<onclick>RunScript(script.copacetic.helper,action=play_items,id=3201,type=music,method=from_here)</onclick>
```

---

## play_radio

Clears the playlists and plays a song followed by 24 random songs from one of its
genres (picked at random if it has several). Nothing plays if the song has no genre.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | song database id | `ListItem.DBID` | The song to start with |

```xml
<onclick>RunScript(script.copacetic.helper,action=play_radio,id=$INFO[ListItem.DBID])</onclick>
```

---

## play_trailer

Plays a trailer without switching to full screen, so the skin can show it inside a
window (a `videowindow` control). The helper's background service then watches it:

- If focus moves to another item, before or during playback, the trailer is paused
  and hidden instead of stopped.
- A paused, hidden trailer is stopped after 10 seconds without input.
- A request that never starts is dropped after 5 seconds.
- With `viewport`, the service zooms the video to fill that area.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `trailer` | path or `plugin://` URL | required | The trailer to play. Empty does nothing. |
| `item` | text | none | The focused item's label when the request was made. If the item under `source_prefix` has a different label when playback starts, the trailer is treated as out of date. |
| `focus_ids` | control ids, comma separated | none | If none of these has focus when playback starts, the trailer is treated as out of date |
| `source_prefix` | container id, or an infolabel prefix such as `Container(50).ListItem` | none | Where to read the current item's label for the `item` check. A plain number means `Container(<id>).ListItem`. |
| `viewport` | `WxH`, in skin coordinates | none | Size of the area the trailer is shown in. Turns on zoom to fill it. |

**Sets** (while the trailer request is live):

| Property | Value |
|---|---|
| `trailer_state` | `pending` when requested. The service changes it to `playing`, or `orphaned` once paused and hidden. Cleared when playback stops. |
| `trailer_item`, `trailer_focus_ids`, `trailer_source`, `trailer_viewport` | The values passed |
| `trailer_pending_since` | Time of the request |

For example, show your `videowindow` only while
`String.IsEqual(Window(home).Property(trailer_state),playing)`.

Example from Copacetic (simplified). The whole `key=value` pairs are quoted because
titles and paths can contain commas:

```xml
<onfocus>RunScript(script.copacetic.helper,action=play_trailer,"trailer=$INFO[ListItem.Trailer]","item=$INFO[ListItem.Label]","focus_ids=3200,3201",source_prefix=3200,viewport=1920x1080)</onfocus>
```

---

## rate_song

Sets a song's user rating in the music library. If that song is playing now, the
helper also stores the rating in a window property, so the player can show it at
once.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | song database id | `ListItem.DBID` | The song to rate |
| `rating` | whole number, `0`–`10` | `Skin.String(Music_Rating_Like_Threshold)` | The rating. `0` removes it. |

Both values must be whole numbers. If the default skin string is empty, nothing
happens.

**Sets:** `Window(home).Property(MusicPlayer_UserRating)` — the new rating, when the
rated song is playing. Cleared when the rating is `0`.

Example from Copacetic (like and unlike in the music OSD):

```xml
<onclick>RunScript(script.copacetic.helper,action=rate_song,id=$INFO[MusicPlayer.DBID],rating=$INFO[Skin.String(Music_Rating_Like_Threshold)])</onclick>
<altclick>RunScript(script.copacetic.helper,action=rate_song,id=$INFO[MusicPlayer.DBID],rating=0)</altclick>
```

---

## rebuild

Rebuilds all builder output (includes, variables, expressions), adds entries for any
new mappings, refreshes the resolver cache and reloads the skin. User settings are
kept unless you ask for a reset. A notification confirms it. See [Runtime State →
Reset vs rebuild](../builders/09-runtime-state.md#reset-vs-rebuild).

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `reset` | `true` | off | First delete all settings and output files, so everything is rebuilt from your template defaults. Also turns off the helper's "Reset on next start" setting. |

```xml
<onclick>RunScript(script.copacetic.helper,action=rebuild)</onclick>
<onclick>RunScript(script.copacetic.helper,action=rebuild,reset=true)</onclick>
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

## seed_keyboard_layout

Fills the builder mapping called `keyboard` with the letters and then the digits of a
Kodi keyboard layout, one entry per character (at most 48). Each entry's `value`
field holds its character. Use it to build an on-screen keyboard from templates.

Your skin must define a mapping named `keyboard` whose items are `slot1`, `slot2`, …
with at least as many items as the layout has characters. If there are too few, the
action fails and nothing is written.

Where a language has several layouts, an alphabetical one is preferred. An unknown
language falls back to English ABC.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `layout` | `<language> <layout>`, as in Kodi's keyboard layout files (for example `English ABC`, `Russian АБВ`) | ask | Without it, a dialog lists every layout to choose from. Cancel writes nothing. |

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
`<ontextchange>`.

**Sets:** `Window(home).Property(edit_scripted_write)` = `true` during the write,
then clears it. Test it to tell these writes from the user's own typing.

Examples from Copacetic:

```xml
<!-- a letter key -->
<onclick>RunScript(script.copacetic.helper,action=set_edit,id=4200,return_id=215,mode=append,text=a)</onclick>
<!-- delete key -->
<onclick>RunScript(script.copacetic.helper,action=set_edit,id=4200,return_id=215,mode=backspace)</onclick>
```

---

## set_search_query

Copies an edit control's text into a window property, ready to use in a search
path. Text shorter than `min_length` clears the property instead.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | edit control id | required | The edit control to read |
| `min_length` | whole number | `3` | Fewest characters before the text is copied |

**Sets:** `Window(home).Property(search_query)`.

Example from Copacetic:

```xml
<!-- on the edit control -->
<ontextchange>RunScript(script.copacetic.helper,action=set_search_query,id=4200,min_length=1)</ontextchange>
<!-- on a results container: movies whose title contains the query -->
<content>videodb://movies/titles/?xsp=%7B%22rules%22%3A%7B%22and%22%3A%5B%7B%22field%22%3A%22title%22%2C%22operator%22%3A%22contains%22%2C%22value%22%3A%5B$ESCINFO[Window(home).Property(search_query)]%5D%7D%5D%7D%2C%22type%22%3A%22movies%22%7D</content>
```

---

## shuffle_artist

Clears the playlists and plays all of an artist's songs, shuffled.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `id` | artist database id | none | The artist |

```xml
<onclick>RunScript(script.copacetic.helper,action=shuffle_artist,id=$INFO[ListItem.DBID])</onclick>
```

---

## subtitle_limiter

Turns on subtitles in a preferred language, so one button skips the other subtitle
streams. If that language is not available, it steps to the next subtitle stream
instead (`Action(NextSubtitle)`). If subtitles in that language are already on,
pressing again turns subtitles off.

Does nothing if the playing video has no subtitles.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `lang` | a subtitle language as Kodi reports it, for example `eng` | required | The preferred language |
| `user_trigger` | empty | on | When on, the action also turns subtitles on if they are hidden, and off if they are showing in the preferred language. Pass it empty (`user_trigger=`) to only switch streams. Any non-empty value, including `false`, counts as on. |

Example from Copacetic, in the video OSD:

```xml
<onclick condition="Skin.String(Subtitle_Limiter)">RunScript(script.copacetic.helper,action=subtitle_limiter,lang=$INFO[Skin.String(Subtitle_Limiter)])</onclick>
```

---

## tmdb_test

Checks the TMDb token set in the helper's settings with a test request. A
notification says whether the token works, the request failed, or TMDb is off.

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
