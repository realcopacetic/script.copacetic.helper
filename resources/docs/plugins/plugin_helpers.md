# Plugin Helpers — Architecture

This page explains how the helper's plugin paths work and how to use them well in your skin.

> A plugin helper is a **dynamic data source** you call from skin XML via a `plugin://` path.
> It runs **on demand**, returns data tailored to the current item or view, and **re-fires whenever its parameters change**.

---

## 1) What is a plugin helper?

- A lightweight helper invoked from skin XML (`<content>plugin://…</content>`).
- Give the container an id, so you can read its item (`Container(9000).ListItem.Art(background)`).
- Runs **only when needed** and produces per-item results (reducing reliance on multiple window properties).
- Each invocation is **isolated** — parameters are part of the path, so **changing them re-runs the helper**.
- Infolabels and variables can be used inside parameters to make paths dynamic.
- You can also wrap plugin paths in variables to create multiple conditions or behaviours.

This approach enables **highly responsive plugin calls** with minimal overhead.

**Example XML**
```xml
<control type="list" id="9000">
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=artwork&amp;background_url=$INFO[ListItem.Art(fanart)]&amp;background_blur=true</content>
</control>
```

### Available plugin paths

| `info=` | What it does | Page |
|--------|--------------|------|
| `artwork` | Crops clearlogos, blurs backgrounds, analyses colours, works out darken values, collects multiart and can fill a FadeLabel with it. | [Artwork](artwork.md) |
| `metadata` | Returns tidied details of the focused item, with optional TMDb details. | [Metadata](metadata.md) |
| `tmdb_details` | Returns the focused item's details and artwork from TMDb. | [Metadata](metadata.md#tmdb_details) |
| `progressbar` | Works out watched progress and places a progress bar. | [Progress Bar](progressbar.md) |
| `typewriter` | Types a label into a textbox one character at a time. | [Typewriter](typewriter.md) |
| `jumpbutton` | Moves a button along a scrollbar and labels it with the sort letter. | [Jump Button](jumpbutton.md) |
| `text` | Draws text into a PNG image. | [Text Image](text.md) |
| `reposition` | Sets the position or size of controls. | [Reposition](reposition.md) |
| `in_progress`, `next_up`, `random_movies`, `random_tvshows`, `actor_credits`, `director_credits`, `writer_credits` | Fill a container with library items. | [Library Listings](library.md) |
| `speed_dial` | Fills a container with pinned and recently played music. | [Speed Dial](speed_dial.md) |

`jumpbutton`, `progressbar` and `typewriter` share the [placement options](placement.md).

An unknown `info=` value returns an empty list. With no `info=` at all, the add-on
lists its own folders (see [Library Listings](library.md#the-add-ons-own-directory)).

---

## 2) The plugin path

A minimal static path:

```xml
<content>plugin://script.copacetic.helper/?info=artwork</content>
```

This will fire only once, because it never changes.

To make it dynamic, add a parameter that updates as the user scrolls:

```xml
<content>plugin://script.copacetic.helper/?info=artwork&amp;current=$INFO[Container.CurrentItem]</content>
```

Now, because `Container.CurrentItem` changes whenever the user scrolls, the artwork helper re-fires automatically for each focused item.

> Use `$INFO[...]` or `$VAR[...]` expressions in your path parameters to tie plugin updates to focus, content type, or visibility conditions.

The helper ignores parameters it does not read, so a parameter like `current=` above
can be added just to make the path change.

Parameter values are URL-decoded (`%20` becomes a space). A value may contain a plain
`&`: the path is only split where `&` is followed by `name=`. In XML, write `&amp;`
between parameters.

**Important:** infolabels and variables in parameters are **resolved at dispatch time**. The helper receives plain values (`focus_guard=5`), never live references. Anything the helper must re-check *during* its run has to be reconstructible plugin-side — this is what the guard parameters below are for.

---

## 3) Guarding against fast scrolls and container moves

> **Problem:** scrolling quickly — or moving focus to a different container — can leave earlier plugin invocations still in flight. Without protection, a slow invocation can deliver its results *after* the UI has moved on, overwriting fresh state with stale data.

There are two complementary safeguards: **debouncing** (don't fire calls that will be wasted) and **focus guards** (calls that did fire refuse to deliver into a world that has moved on).

### Division of responsibility

A guard prevents stale data **arriving late**; it cannot make old data **disappear early**. Plugin round-trips take anywhere from ~15 ms (cache hit) to seconds (fresh network fetch), so anything that must vanish instantly on a focus change — hiding a label, clearing a FadeLabel, stopping playback — belongs in skin XML (`onfocus` actions, visibility conditions), on the skin's clock. The guards below are the other half of the contract: they make sure a slow invocation can never repopulate what the skin just cleared.

---

### Debouncing on the plugin container

Containers only refire content while they're visible. Exploit that to create a small **invisibility window** during rapid scrolling, so intermediate items never spawn invocations at all.

**Example XML**
```xml
<control type="list" id="9000">
  <visible>!Control.IsVisible(5900)</visible>
  <itemlayout />
  <focusedlayout />
  <content>$VAR[artwork_helper]</content>
</control>

<control type="group" id="5900"><!-- debouncer for plugin calls -->
  <visible>Container.OnPrevious | Container.OnNext</visible>
  <animation effect="slide" end="0,0" time="128" reversible="false">Hidden</animation>
</control>
```

**How it works**
- Group `5900` becomes visible for 128 ms after a scroll event.
- While visible, container `9000` is hidden → the plugin path cannot refire.
- Once scrolling stops, the group hides again and the plugin updates exactly once.

Debouncing is **economics, not correctness**: it prevents wasted invocations, but offers no protection against the ones that do fire. That is the guards' job.

---

### The focus guard

Every guarded helper builds a guard object at startup and re-checks it at key points throughout its run (`guard.alive()`). The guard enforces up to **two independent checks**, both declared by the skinner through URL parameters:

| Parameter | What it declares | Check performed |
|-----------|------------------|-----------------|
| `focus_ids` | Comma-separated control ids forming one perceptual unit | **Focus check** — at least one of the listed controls must currently hold focus. |
| `focus_guard` | Snapshot of the focused item's identity, resolved at dispatch | **Identity check** — the live identity must still equal the snapshot exactly. |
| `identity_labels` | *(optional)* Comma-separated infolabel paths defining the live side of the identity | Overrides the default live identity source. |
| `identity_container` | *(optional)* Container id | The container whose `CurrentItem` is the default live identity. Defaults to `target`. |

`target` (a container id) is read by most paths. It sets which container's focused
item the path works on. Without it, `Container` (the current container) is used.
`target=item` reads the window's own item instead (bare `ListItem.*`), which in an
info dialog is the item the dialog shows; a `Container` read there lands on the
focused list (the cast list 50 or a rail). The item never scrolls, so it takes no
`focus_guard`; `focus_ids` still works, and artwork returns no position properties.

Two cases always pass: when no control has focus at all, and when the live identity
reads as empty.

Either check can be disabled by omission: no `focus_ids` skips the focus check; an absent or empty `focus_guard` skips the identity check. A handler with neither runs unguarded.

The addon imposes **no skin topology**. Which controls form a unit, and what constitutes an item's identity, are entirely skinner-declared. The addon only implements the semantics: *any-of-these-has-focus* and *snapshot-equals-live*.

#### Identity check — `focus_guard`

```xml
<content>
  plugin://script.copacetic.helper/?info=artwork&amp;target=3100&amp;focus_guard=$INFO[Container(3100).CurrentItem]
</content>
```

- Kodi resolves the snapshot at dispatch: if item 5 is focused, the helper receives `focus_guard=5`.
- By default, the live side is derived as `Container(<identity_container>).CurrentItem` (`identity_container` defaults to `target`; with neither, `Container.CurrentItem`) — so only the snapshot needs passing.
- At every checkpoint, the helper compares snapshot to live. Any mismatch aborts.

`CurrentItem` is the right default identity for **scrolling within one container** — it changes on every item move. It is **not** sufficient across containers: `Container(3202).CurrentItem` and `Container(3206).CurrentItem` can both be `1`. That is what the focus check is for.

#### Focus check — `focus_ids`

```xml
<content>
  plugin://script.copacetic.helper/?info=artwork&amp;target=3202&amp;focus_guard=$INFO[Container(3202).CurrentItem]&amp;focus_ids=3202
</content>
```

At every checkpoint, the helper verifies that at least one control in `focus_ids` holds focus (`Control.HasFocus`). The moment focus leaves the declared set — to another widget, a list, a menu — every in-flight invocation for this unit aborts at its next checkpoint, even if its identity snapshot still happens to match.

#### Custom identities — `identity_labels`

When `CurrentItem` of one container isn't discriminating enough, declare the identity explicitly. `identity_labels` takes literal infolabel paths (no `$INFO[...]` wrapper — they must reach the helper unresolved); the helper reads each live and joins the values with `,`. The matching snapshot is built by joining the corresponding `$INFO[...]` expressions with `,` in `focus_guard`. The two sides never need parsing — they only need to be constructed the same way.

#### Recipe: treating two containers as one

A paired tab list (`32020`) and content list (`3202`) should behave as a single unit: moving between them must not abort or refire anything, but leaving the pair — or scrolling the tab, which swaps the content underneath — must invalidate in-flight calls. Both requirements are declared in one value:

```xml
<value>target=3202&amp;focus_guard=$INFO[Container(32020).CurrentItem],$INFO[Container(3202).CurrentItem]&amp;identity_labels=Container(32020).CurrentItem,Container(3202).CurrentItem&amp;focus_ids=3202,32020</value>
```

- `focus_ids=3202,32020` — focus anywhere in the couple keeps calls alive; focus elsewhere kills them.
- The composite identity includes the **tab's** position, so a tab scroll changes the identity even when the new content lands back on item 1.

### How guards are enforced inside handlers

Guarded handlers don't check once at startup — they re-check before every stage that is expensive or has visible side effects:

- **`artwork`** checks at the start, after image processing, after multiart resolution, and immediately **before filling the multiart FadeLabel** — so a stale invocation can never refill a FadeLabel the skin has just cleared. A guard that still passes at the end also lets the helper write `artwork_cursor_<cursor_key>` itself when the property does not match the item it ran for (see [Is this result for the focused item?](artwork.md#is-this-result-for-the-focused-item)).
- **`metadata`** checks before reading the item, after the TMDb lookup, and before returning the item.
- **`tmdb_details`** checks before and after the TMDb lookup.
- **`text`** checks before and after drawing the image.
- **`typewriter`** receives the guard's `alive` callable and checks it **per character**, alongside a supersession lease (`typewriter_current_<id>` window property): each run claims the property with a unique token, and any later writer — a newer run, or the skin writing `scroll` into it on a reset — aborts the older one. The skin-side reset lines are therefore part of the contract, not just visual plumbing.
- **`progressbar`** checks before calculating and again before moving UI controls (the data result is still returned; only the UI update is skipped).
- **`jumpbutton`** is deliberately **unguarded** — it must stay responsive during scroll.
- **`reposition`**, the library listings and `speed_dial` are unguarded.

---

## 4) Wrapping plugin paths in variables

Wrapping your plugin paths inside a **variable** gives you more control and flexibility than a single static `<content>` call. A variable can contain **multiple values**, each with its own condition, so the helper switches behaviour automatically with the active layout, focused container, or skin setting.

It also keeps guard parameters in one place. Define the focus/identity declaration once per group of containers and compose it into every consumer:

```xml
<variable name="params_focus_secondary">
  <value>target=3100&amp;focus_guard=$INFO[Container(3100).CurrentItem]&amp;focus_ids=3100</value>
</variable>

<variable name="artwork_helper">
  <value condition="$EXP[layouts_fanart_visible]">
    plugin://script.copacetic.helper/?info=artwork&amp;$VAR[params_focus_secondary]&amp;background_url=$INFO[Container(3100).ListItem.Art(fanart)]&amp;background_blur=true
  </value>
  <value condition="$EXP[layouts_poster_visible]">
    plugin://script.copacetic.helper/?info=artwork&amp;$VAR[params_focus_secondary]&amp;clearlogo_url=$INFO[Container(3100).ListItem.Art(clearlogo)]&amp;clearlogo_crop=true&amp;multiart=poster&amp;multiart_max=10
  </value>
  <value>plugin://script.copacetic.helper/?info=artwork&amp;$VAR[params_focus_secondary]&amp;background_url=$INFO[Container(3100).ListItem.Art(fanart)]&amp;background_analyze=true</value>
</variable>
```

Then reference the variable in your container:

```xml
<control type="list" id="9300">
  <visible>!Control.IsVisible(5900)</visible>
  <itemlayout />
  <focusedlayout />
  <content>$VAR[artwork_helper]</content>
</control>
```

> **Caution:** every `$VAR`/`$INFO` nested in the path is part of the invocation's identity — if any of them resolves differently between two states the skin considers equivalent (e.g. focus moving within a paired unit), the path changes and the helper refires. Keep every nested reference **focus-stable across the unit** the path serves.

---

## 5) See also

- [Artwork](artwork.md)
- [Metadata and TMDb details](metadata.md)
- [Progress Bar](progressbar.md)
- [Typewriter](typewriter.md)
- [Jump Button](jumpbutton.md)
- [Text Image](text.md)
- [Reposition](reposition.md)
- [Library Listings](library.md)
- [Speed Dial](speed_dial.md)
- [Placement Options](placement.md)