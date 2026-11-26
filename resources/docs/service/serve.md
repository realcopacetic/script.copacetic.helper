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

1. The skin **rings**: `NotifyAll(script.copacetic.helper,serve?…)`, once an item has
   come to rest, or when a selection changed without a focused-layout arrival. The ring
   names the lists to fill and, for each, its **probe**: a hidden label beside it
   holding that list's params.
2. The service hears it on a thread of its own and fills the lists one after another,
   in the order given. For each it reads the probe and runs the handler it names.
3. It **binds** the handler's items to the list: the list's items are replaced in one
   go, with no `<content>` and no job.

A newer ring stops the serve in flight before its next bind; a list that was stopped
binds nothing and keeps what it showed.

The helper knows none of your ids: every list, probe and dialog comes in the ring, so
adding a served list is a change to your skin alone.

## The list and its probe

A served list must have **no `<content>` element** at all: an empty one still makes a
provider, which ignores the bind. Its probe is a hidden label in the same window:

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

Ring the lists in the order they read each other: a list whose probe reads an earlier
list (a favourite's rows read its library item; the typewriter's label reads the
details) then finds it already bound.

## The probe

The service reads a probe with `Control.GetLabel(<id>)` when its list's turn comes, so
Kodi works out the label's text at that moment, in the probe's own window. It says one
of four things:

| Probe text | The service |
|---|---|
| empty | skips the list (not mounted here) |
| `info=<handler>&…` | runs that handler with those params, as a plugin path would (a `plugin://script.copacetic.helper/?` prefix is dropped) |
| `none` | binds one blank item: nothing for this item, but the list answered |
| `wait` | looks again every 100 ms while the ring is the newest, and holds the lists after it; after 5 s it counts as `none` (the net serves it once the probe says more, see [the net](#the-net)) |

Use `wait` for a state that has no event of its own: art Kodi hasn't filled in yet
(`ListItem.Property(libraryartfilled)`), a rail still loading, a dwell your layout
wants. End the variable in `none`, so a mounted list always answers.

Leave out of a probe's rows what only a watched URL needed: `visit`, the held count,
the version bumps. A probe is read off the main thread, and the net compares it with
what was served, so keep its rows to settled state (the view, a setting, the item),
not a latch the skin times to the frame.

Art URLs: name each image by its source (`clearlogo_source`, `icon_source`,
`background_source`, see [artwork](../plugins/artwork.md#the-three-images)) and leave
the `*_url` copies out; a served call is always read with its window on top, so the
read stands alone. For art a variable picks, put the variable in a hidden label of its
own and pass `background_source=Control.GetLabel(<id>)`: the read then parses no `$VAR`
on the service's thread.

An artwork call served in a dialog over the window it reads as its own (it passes no
`dialog=true`, a settings dialog's preview) has its reads never on top. Keep
`background_var` and its `background_url` copy on that row: only a read the copy vouches
for stands.

An artwork row whose family should turn names the list it turns on and that list's own
probe: `slides=<list>:<probe>` (see [multiart](#the-services-own-news)).

## The ring

`NotifyAll(script.copacetic.helper,serve?<fields>)`, from an `<onfocus>`, `<onload>`,
`<onclick>` or a timer. The fields are a query string; nothing in it may be a comma or a
quote, which Kodi's builtin parser acts on:

| Field | Means |
|---|---|
| `lists` | the lists to fill and their probes, `<list>:<probe>` pairs, dot-separated, in serving order |
| `mark` | the Home property naming this arrival: a cursor the skin writes at each arrival, or a token it writes for a move |
| `is` | the mark's value at the ring. The serve goes on only while `Window(home).Property(<mark>)` still is it, and each bind names it |
| `wait` | milliseconds a newer ring may come before the service serves (a move's own settle); absent, at once |
| `window` | the ids of the dialogs the lists are in, dot-separated: served in the one on top; under any other dialog (a menu, the spinner) the serve waits until one is (or none is open); absent, the active window |
| `item` | a container whose item each bind names, read at the serve (a cursor's value names its list); absent, the part of `is` before its last `/` |
| `echo` | text bound back as `Property(echo)` (an info dialog's open token on its rails' rings) |

With no `lists`, the ring serves the window's last request again under its own mark (an
info dialog closing back to its window). Bare, `serve` is [the net](#the-net).

### An item comes to rest

Put the ring on a hidden button in the container's focused layout with a `Focus`
animation of the settle time, so its `<onfocus>` runs once, that long after the last
item change:

```xml
<control type="button">
  <visible allowhiddenfocus="true">false</visible>
  <onfocus>NotifyAll(script.copacetic.helper,serve?lists=9000:6900.9010:6910.9300:6930&amp;mark=artwork_cursor_primary&amp;is=$INFO[Window(home).Property(artwork_cursor_primary)])</onfocus>
  <animation effect="slide" end="0,0" time="225" reversible="false">Focus</animation>
</control>
```

The mark here is a cursor the skin writes at each arrival, as
`<list>/<position>/<dbid>/<visit>` (see
[artwork](../plugins/artwork.md#the-value-of-current)), so a serve stops once the cursor
changes. A list already bound for this `is` from the same probe text is not served
again (a layout rebuilt on the same item).

### A selection changes with no arrival

A jump to a letter, a tab, a typed search, a window opening on a control that isn't a
list. Write a new token to a Home property first, then ring with it as the mark, a
`wait` and the container that moved:

```xml
<onclick>SetProperty(moved_primary,m$INFO[System.Time(hh:mm:ss)]$INFO[Container(50).CurrentItem],home)</onclick>
<onclick>NotifyAll(script.copacetic.helper,serve?lists=9000:6900.9010:6910&amp;mark=moved_primary&amp;is=$INFO[Window(home).Property(moved_primary)]&amp;wait=225&amp;item=50)</onclick>
```

Clear the token at the next arrival, when the cursor is written.

### The service starting

Kodi may start the service after the window's own ring (Kodi's start, an add-on
update). Leave the window's load ring, without its `is`, in
`Window(home).Property(serve_load)` and ring from it, so it is written once; the
service, when it starts, serves what it finds there under a new token it writes to
the mark:

```xml
<onload>SetProperty(serve_load,serve?lists=9000:6900.9010:6910&amp;mark=moved_primary&amp;wait=225,home)</onload>
<onload>SetProperty(moved_primary,m$INFO[System.Time(hh:mm:ss)]Load,home)</onload>
<onload>NotifyAll(script.copacetic.helper,$INFO[Window(home).Property(serve_load)]&amp;is=$INFO[Window(home).Property(moved_primary)])</onload>
```

### From Python

[`set_search_query`](../script/actions.md#set_search_query) and
[`search_backspace`](../script/actions.md#search_backspace) take a `ring` param, sent
once the query is published; [`art_artist`](../script/actions.md#art_artist) once
the artist is set, [`art_details_refresh`](../script/actions.md#art_details_refresh)
once the picture is found again; and the
[`dynamic_settings_window`](../script/actions.md#dynamic_settings_window)'s `ring` is
sent at each row change, in the editor's own window. Each is a ring with no `is`: the
helper writes a new token to its mark and adds it.

## The net

A probe is read once, at its list's turn. When what it would say changes with no
arrival (art Kodi fills late, a rail landing after the backstop, a setting changed at
rest), ring `serve` bare: the service serves the window on top's last request again,
for the lists whose probe no longer reads as their `Property(params)`. It is let be
while a serve is waiting or in hand, and for a list whose handler stopped on that same
text; a net ring that binds nothing lets that window's net be until its next ring, or
until one of its probes reads differently. Let a skin timer watch for it:

```xml
<timer>
  <name>serve_net</name>
  <start>Control.IsVisible(6939)</start>
  <stop>true</stop>
  <onstart>NotifyAll(script.copacetic.helper,serve)</onstart>
</timer>
```

with a hidden group (here `6939`) in each served window whose `<visible>` is, per served
list,
`!String.IsEmpty(Control.GetLabel(<probe>)) + !String.IsEqual(Control.GetLabel(<probe>),wait) + !String.IsEqual(Control.GetLabel(<probe>),none) + !String.IsEqual(Control.GetLabel(<probe>),Container(<list>).ListItem.Property(params))`,
OR-ed: a probe that names a handler and no longer reads as what its list holds. A
`none` never rings (a `none` that becomes params still does). A timer reads the topmost
dialog first, so a menu over the window reads false. Kodi tests it twice a second; no
Python runs until a probe has changed.

**The rule.** A list that is in no ring of a window (another region's, say, while its
rail has no focus) must have its probe read empty or `none` there, or guard its term
with the same condition: the net only serves lists of the window's last ring, so any
other probe that names a handler would ring for ever. Put the group outside anything
that hides while the window rests: a hidden group stops updating its children's
visibility.

## The bind

The first bound item carries four properties the skin compares to tell whether the
list answers what is on screen:

| Property | Value |
|---|---|
| `current` | The ring's `is`: a cursor, visit and all, or a move's token |
| `item` | The item served, `<list>/<position>/<dbid>/`; empty for a move with no `item` |
| `echo` | The ring's `echo`, so a kept dialog's last item never matches this open's |
| `params` | The probe's text the list was served from (`none` for the blank item) |

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
under the dialog is owed the same way. A dialog that opens during a probe's read, or
during an artwork call's art reads, is waited out and the list read again.

## The service's own news

- **A late answer.** A served [metadata](../plugins/metadata.md) or artwork call reads
  TMDb from the cache only and fetches on a thread of its own; when the answer lands,
  that list is served again for the same arrival, if it is still the window's last.
  So does music info's popularity word when Deezer answers. A serve still running
  reaches the list itself if it hasn't yet, or serves it again once it ends; one that
  lands while another ring has the window is served by its arrival's next ring. The
  line follows, as its label can change. A served [progress bar](../plugins/progressbar.md)
  of a show or season with `follow_tmdb=true` asks nothing itself, but follows a fetch
  the metadata serve asked for the same show (with art or not): it carries
  `tmdb_pending` meanwhile and is served again when that fetch ends, news or not, so
  the skin can hide its rows for the wait and fade them in once. It follows only a
  fetch already asked, so name the metadata list before the bar's in `lists=`.
- **An album's play counts.** A song heard serves again the list the window on top
  last served with the [progress bar](../plugins/progressbar.md).
- **Multiart.** When an artwork row that names `slides=<list>:<probe>` binds a family
  (`multiart`, `multiart1` …, two images or more), the service turns it on that list:
  every 5 s it makes the next slide with the params in that probe and binds one item
  carrying the slide (`Art(slide)`), its blur and band, the arrival's `current` and the
  artwork list's `Property(identity)`, so picture and blur change together. The turn
  stops at the next ring or once the slide probe reads other than the params a slide
  was made with, and holds while another window is on top; a ring that finds the list
  still holding its answer (the same arrival rung again) turns the family again if its
  turn had ended. No FadeLabel register is needed.
- **The line.** The [typewriter](../plugins/typewriter.md) answers at once and types on
  a thread of its own, so the lists after it aren't held; the skin's lease
  (`Window(home).Property(typewriter_current_<target_id>)`) stops it at the next move. A
  ring leaves a line that still stands alone.

## What stays a plugin call

Every list you keep on `<content>`. Copacetic 2 keeps its visualisation's lists, the
music OSD's playing song under its rails, the TV guide's, and the dialogs with a single
blur as plugin calls: they follow the player or rarely change, so a run per change
costs little. The music OSD's rails are served, in the OSD (`window=10120`), as an info
dialog's are.

## Log lines

With the helper's debug logging on, each bind logs
`Server → 9300 served: 62ms ring to start, 14ms handler, 1ms bind, artwork_cursor_primary 50/3/12/v`,
and a list that already held its answer `Server → repeat, not served: …`.
