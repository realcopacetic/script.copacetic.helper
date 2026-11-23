# Served Lists

The service can fill a skin's per-focus helper lists itself, in place of a plugin call
per list. The handlers, their params and the items they return are the same as the
plugin paths' (each handler page lists them); what changes is who starts the work and
how the result lands. A plugin call starts an interpreter for every list on every
focus change and queues behind the skin's other plugin listings; a served list costs
one notification and runs in the service, which is already warm.

Both transports stay. A list you don't move keeps its `<content>` and works as before,
beside the served ones.

## How it works

1. The skin **rings**: `NotifyAll(script.copacetic.helper,<message>)`, once an item
   has come to rest, or when a selection changed without a focused-layout arrival.
2. The service hears it on a thread of its own and fills the lists the ring names, one
   after another, in the order given. For each it reads the list's **probe**, a hidden
   label holding that list's params, and runs the handler the probe names.
3. It **binds** the handler's items to the list: the list's items are replaced in one
   go, with no `<content>` and no job.

A newer ring stops the serve in flight before its next bind; a list that was stopped
binds nothing and keeps what it showed.

## The lists and their probes

The ids are fixed: a served list is one of these, with its probe beside it in the same
window.

| List | Probe | Usually holds |
|---|---|---|
| `9040` | `6904` | a favourite's library item ([favourite](../plugins/favourite.md)) |
| `9000` | `6900` | the focused item's [metadata](../plugins/metadata.md) (or [clean_name](../plugins/clean_name.md)) |
| `9100` | `6901` | the secondary rail's metadata |
| `9010` | `6910` | the [progress bar](../plugins/progressbar.md) |
| `9300` | `6930` | the [artwork](../plugins/artwork.md) |
| `9301` | `6931` | a second artwork call (a show's logo) |
| `9020` | `6920` | the [typewriter](../plugins/typewriter.md) |

Serve them in the order above: a list whose probe reads an earlier list (a favourite's
rows read `9040`; the typewriter's label reads `9000`) finds it already bound.

Three regions are served in a dialog instead of the active window, with probes of their
own:

| Region | Lists → probes | Dialog |
|---|---|---|
| `item` | `9000` → `6900`, `9300` → `6933`, `9030` → `6903`, `9360` → `6936`, `9010` → `6911` | an info dialog's own item |
| `infoscreen` | `9100` → `6901`, `9010` → `6910`, `9300` → `6930`, `9020` → `6920` | an info dialog's rails |
| `preview` | `9370` → `6937` | the topmost dialog (a settings dialog's preview) |

A served list must have **no `<content>` element** at all: an empty one still makes a
provider, which ignores the bind.

```xml
<control type="label" id="6930">
  <visible>false</visible>
  <label>$VAR[MyArtworkParams]</label>
</control>
<control type="list" id="9300">
  <itemlayout />
  <focusedlayout />
</control>
```

## The probe

The service reads a probe with `Control.GetLabel(<id>)` when its list's turn comes, so
Kodi works out the label's text at that moment, in the probe's own window. It says one
of four things:

| Probe text | The service |
|---|---|
| empty | skips the list (not mounted here, or not this region's) |
| `info=<handler>&…` | runs that handler with those params, as a plugin path would (a `plugin://script.copacetic.helper/?` prefix is dropped) |
| `none` | binds one blank item: nothing for this item, but the list answered |
| `wait` | looks again every 100 ms while the ring is the newest, and holds the lists after it; after 30 s it counts as `none` |

Use `wait` for a state that has no event of its own: art Kodi hasn't filled in yet
(`ListItem.Property(libraryartfilled)`), a rail still loading, a dwell your layout
wants. End the variable in `none`, so a mounted list always answers.

Leave out of a probe's rows what only a watched URL needed: `visit`, the held count,
the version bumps. A probe is read off the main thread, so keep its rows to settled
state (the view, a setting, the item), not a latch the skin times to the frame.

Art URLs: name each image by its source (`clearlogo_source`, `icon_source`,
`background_source`, see [artwork](../plugins/artwork.md#the-three-images)) and leave
the `*_url` copies out; a served call is always read with its window on top, so the
read stands alone. For art a variable picks, put the variable in a hidden label of its
own and pass `background_source=Control.GetLabel(<id>)`: the read then parses no `$VAR`
on the service's thread.

The `preview` region is the exception: an artwork call there takes the active window
as its own (it passes no `dialog=true`), with the dialog over it, so its reads are
never on top. Keep `background_var` and its `background_url` copy on that row: only a
read the copy vouches for stands.

## The rings

Each is a `NotifyAll` from an `<onfocus>`, `<onload>` or `<onclick>`. The lists are
dot-separated, in serving order; a list not in the region's table is ignored.

### `settle/<region>/<lists>/<cursor>`

An item has come to rest. Put it on a hidden button in the container's focused layout
with a `Focus` animation of the settle time, so its `<onfocus>` runs once, that long
after the last item change:

```xml
<control type="button">
  <visible allowhiddenfocus="true">false</visible>
  <onfocus>NotifyAll(script.copacetic.helper,settle/primary/9040.9000.9010.9300.9301.9020/$INFO[Window(home).Property(artwork_cursor_primary)])</onfocus>
  <animation effect="slide" end="0,0" time="225" reversible="false">Focus</animation>
</control>
```

`<cursor>` is the region's cursor, `Window(home).Property(artwork_cursor_<region>)`,
which the skin writes at each arrival as `<list>/<position>/<dbid>/<visit>` (see
[artwork](../plugins/artwork.md#the-value-of-current)). The `infoscreen` region's
settles carry the `primary` cursor. A serve stops once the cursor changes.

A settle equal to the last one served whole does nothing while its lists still hold
its answer (a layout rebuilt on the same item).

### `move/<region>/<lists>/<container>/<token>`

The selection changed with no focused-layout arrival: a jump to a letter, a tab, a
typed search, a window opening on a control that isn't a list. Write a new token to
`Window(home).Property(moved_<region>)` first, then ring with it; the service waits
225 ms for another ring before it serves (an `item` move doesn't wait). Clear the token
at the next arrival, when the cursor is written.

`<container>` is the list that moved, whose item the served lists name: its id, `view`
for the cursor's list, or empty for none.

`move////<token>`, with no region or lists, serves the window's last request again as a
new arrival (an info dialog closing back to its window). The service also rings one
move itself when it starts, for whatever is on screen.

From Python, [`set_search_query`](../script/actions.md#set_search_query) rings the
primary's move once a typed query is published, and the
[`dynamic_settings_window`](../script/actions.md#dynamic_settings_window)'s `ring` param rings a region's move at each row
change.

## The bind

The first bound item carries three properties the skin compares to tell whether the
list answers what is on screen:

| Property | Value |
|---|---|
| `current` | What the ring answered: a settle's `<list>/<position>/<dbid>/`, or a move's token |
| `item` | The item served, `<list>/<position>/<dbid>/`; empty for a move with no container |
| `open` | For a dialog region, the dialog's open token (`Window(home).Property(moved_item)`), so a kept dialog's last item never matches |

`Container(id).IsUpdating` is always false for a served list. A readiness expression
in its place, for a window's list:

```xml
<expression name="DetailsReady">[!String.IsEmpty(Container(9000).ListItem.Property(item)) + String.IsEmpty(Window(home).Property(moved_primary)) + String.StartsWith(Window(home).Property(artwork_cursor_primary),Container(9000).ListItem.Property(item))] | [!String.IsEmpty(Container(9000).ListItem.Property(current)) + String.IsEqual(Container(9000).ListItem.Property(current),Window(home).Property(moved_primary))]</expression>
```

The item leaves the visit out, so a kept window's list reads as answered on return.

## Under a dialog

A list is served only while its window is on top: Python reads the topmost modal
dialog's controls. While a menu, the busy spinner or another dialog covers it, the
serve waits (a look every 100 ms) and runs once the window is back on top; a ring
under the dialog is owed the same way.

## The service's own news

- **A late answer.** A served [metadata](../plugins/metadata.md) or artwork call reads
  TMDb from the cache only and fetches on a thread of its own; when the answer lands,
  that list is served again for the same arrival, if it is still the window's last.
  So does music info's popularity word when Deezer answers. A serve still running
  reaches the list itself if it hasn't yet, or serves it again once it ends. The
  typewriter's line follows, as its label can change.
- **An album's play counts.** A song heard serves the bar (`9010`) again.
- **Multiart.** When `9300` binds a family (`multiart`, `multiart1` …, two images or
  more), the service turns it on `9400`: every 5 s it makes the next slide with the
  params in probe `6932` and binds one item carrying the slide (`Art(slide)`), its
  blur and band, the arrival's `current` and `9300`'s `Property(identity)`, so
  picture and blur change together. The turn stops at the next ring, and holds while another window is on top.
  No FadeLabel register is needed.
- **The typewriter.** Its line types on a thread of its own, so the lists after it
  aren't held; the skin's lease (`Window(home).Property(typewriter_current_<target_id>)`)
  stops it at the next move. A repeat ring leaves a line that still stands alone.

## What stays a plugin call

Anything the table doesn't name, and every list you keep on `<content>`. Copacetic 2
keeps its visualisation and music OSD lists, the TV guide's, and the dialogs with a
single blur as plugin calls: they follow the player or rarely change, so a run per
change costs little.

## Log lines

With the helper's debug logging on, each bind logs
`Server → 9300 served: 62ms ring to start, 14ms handler, 1ms bind, settle 50/3/12/v`,
and a repeat `Server → repeat, not served: …`.
