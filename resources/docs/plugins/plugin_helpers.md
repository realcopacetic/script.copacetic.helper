# Copacetic Plugin Helpers — Architecture

This page explains how Copacetic's plugin helpers work and how to use them effectively in your skin.

> A plugin helper is a **dynamic data source** you call from skin XML via a `plugin://` path.
> It runs **on demand**, returns data tailored to the current item or view, and **re-fires whenever its parameters change**.

---

## 1) What is a plugin helper?

- A lightweight helper invoked from skin XML (`<content>plugin://…</content>`).
- The `<content>` tag must belong to a **container with a defined ID**.
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
  <content>plugin://script.copacetic.helper/?info=artwork</content>
</control>
```

### Available Copacetic helpers
| Helper | Description |
|--------|--------------|
| `metadata` | Fetches and formats item metadata, with optional TMDb enrichment. |
| `artwork` | Crops clearlogos, blurs fanart, extracts colour palette, optional darken regions, standardises multiart and can seed a FadeLabel with the sequence. |
| `typewriter` | Progressive label-rendering animation. |
| `progressbar` | Displays resume/unwatched progress bars for supported types (movies, sets, tvshows, seasons, episodes). |
| `jumpbutton` | Context-aware alphabet/section jump navigation. |

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

Either check can be disabled by omission: no `focus_ids` skips the focus check; an absent or empty `focus_guard` skips the identity check. A handler with neither runs unguarded.

The addon imposes **no skin topology**. Which controls form a unit, and what constitutes an item's identity, are entirely skinner-declared. The addon only implements the semantics: *any-of-these-has-focus* and *snapshot-equals-live*.

#### Identity check — `focus_guard`

```xml
<content>
  plugin://script.copacetic.helper/?info=artwork&amp;target=3100&amp;focus_guard=$INFO[Container(3100).CurrentItem]
</content>
```

- Kodi resolves the snapshot at dispatch: if item 5 is focused, the helper receives `focus_guard=5`.
- By default, the live side is derived as `Container(<target>).CurrentItem` (or the focused container's `CurrentItem` when no `target` is given) — so only the snapshot needs passing.
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

- **`artwork`** checks after image processing, after multiart resolution, and immediately **before seeding the multiart FadeLabel** — so a stale invocation can never repopulate a FadeLabel the skin has just cleared.
- **`metadata`** checks before the JSON-RPC fetch, after TMDb enrichment, and before setting items.
- **`typewriter`** receives the guard's `alive` callable and checks it **per character**, alongside a supersession lease (`typewriter_current_<id>` window property): each run claims the property with a unique token, and any later writer — a newer run, or the skin writing `scroll` into it on a reset — aborts the older one. The skin-side reset lines are therefore part of the contract, not just visual plumbing.
- **`progressbar`** checks before calculating and again before moving UI controls (the data result is still returned; only the UI update is skipped).
- **`jumpbutton`** is deliberately **unguarded** — it must stay responsive during scroll.

---

## 4) Wrapping plugin paths in variables

Wrapping your plugin paths inside a **variable** gives you more control and flexibility than a single static `<content>` call. A variable can contain **multiple values**, each with its own condition, so the helper switches behaviour automatically with the active layout, focused container, or skin setting.

It also keeps guard parameters in one place. Define the focus/identity declaration once per region and compose it into every consumer:

```xml
<variable name="params_focus_secondary">
  <value>target=3100&amp;focus_guard=$INFO[Container(3100).CurrentItem]&amp;focus_ids=3100</value>
</variable>

<variable name="artwork_helper">
  <value condition="$EXP[layouts_fanart_visible]">
    plugin://script.copacetic.helper/?info=artwork&amp;$VAR[params_focus_secondary]&amp;background_blur=true
  </value>
  <value condition="$EXP[layouts_poster_visible]">
    plugin://script.copacetic.helper/?info=artwork&amp;$VAR[params_focus_secondary]&amp;clearlogo_crop=true&amp;multiart_max=10
  </value>
  <value>plugin://script.copacetic.helper/?info=artwork&amp;$VAR[params_focus_secondary]</value>
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

- [Artwork Plugin Handler](Artwork-Plugin-Handler)
- [Typewriter Plugin Handler](Typewriter-Plugin-Handler)
- [Progress Bar Plugin Handler](Progressbar-Plugin-Handler)
- [Jump Button Plugin Handler](Jumpbutton-Plugin-Handler)
- [Metadata Plugin Handler](Metadata-Plugin-Handler)