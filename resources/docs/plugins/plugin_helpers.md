# Copacetic Plugin Helpers — Architecture

This page explains how Copacetic’s plugin helpers work and how to use them effectively in your skin.

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
<control type="list" id="9999">
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=artwork</content>
</control>
```

### Available Copacetic helpers
| Helper | Description |
|--------|--------------|
| `metadata` | Fetches and formats item metadata. |
| `artwork` | Crops clearlogos, blurs fanart, extracts colour palette, optional darken for overlays, standardises multiart. |
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

---

## 3) Debouncing during fast scrolls

> **Problem:** In Kodi, scrolling quickly can trigger many plugin calls in rapid succession.  
> Each new item creates a new plugin instance — potentially causing race conditions or leftover data from earlier items.

There are two safeguards: **debouncing** and **focus guards**.

---

### Using a debouncer on the plugin container

Containers can only refire content when they’re visible.  
We exploit that to create a small **invisibility window** where the list is hidden, pausing plugin refreshes during rapid scrolling.

**Example XML**
```xml
<include name="metadata_helper">
  <control type="list" id="9999">
    <visible>!Control.IsVisible(5007)</visible>
    <itemlayout />
    <focusedlayout />
    <content>$VAR[metadata_helper_path]</content>
  </control>
</include>

<control type="group" id="5007"><!-- debouncer for plugin calls -->
  <visible>Container.OnPrevious | Container.OnNext</visible>
  <animation effect="slide" end="0,0" time="128" reversible="false">Hidden</animation>
</control>
```

**How it works**
- Group `5007` becomes visible for 128 ms after a scroll event.
- While visible, container `9999` is hidden → the plugin path cannot refire.
- Once scrolling stops, the group hides again and the plugin updates exactly once.
- Use this for helpers that refresh during scroll (e.g. `artwork`, `metadata`, `typewriter`).

---

### Adding a focus safety — `focus_guard`

**What it is:**  
A simple “expected identity” check (`Container(id).CurrentItem`).  
If focus changes mid-run, the helper **aborts early** to prevent flicker or stale data.

**Example**
```xml
<content>
  plugin://script.copacetic.helper/?info=artwork&amp;focus_guard=$INFO[Container.CurrentItem]
</content>
```

**How it works**
- Parameters are evaluated at execution time.  
  If the 5th item is focused, the helper sees `focus_guard=5`.
- During processing, the plugin keeps checking `Container.CurrentItem`.
- If focus moves (to item 6 or another container), the helper aborts immediately.
- You can also specify a **target container** explicitly:

```xml
<content>
  plugin://script.copacetic.helper/?info=artwork&amp;target=3100&amp;focus_guard=$INFO[Container(3100).CurrentItem]
</content>
```

This ensures the guard tracks the correct container when multiple lists are visible.

---

## 4) Wrapping plugin paths in variables

Wrapping your plugin paths inside a **variable** gives you more control and flexibility than a single static `<content>` call.  
A variable can contain **multiple values**, each with its own condition. This allows your helper to switch behaviour automatically depending on the active layout, focused container, or even skin setting.

In other words — instead of editing the plugin path itself, you **switch which plugin path is active** based on runtime conditions.

**Example:**
```xml
<variable name="artwork_helper">
  <value condition="$EXP[layouts_fanart_visible]">
    plugin://script.copacetic.helper/?info=artwork&amp;bg_blur=true&amp;overlay_enable=true
  </value>
  <value condition="$EXP[layouts_poster_visible]">
    plugin://script.copacetic.helper/?info=artwork&amp;crop_clearlogo=true&amp;multiart_max=10
  </value>
  <value condition="$EXP[layouts_square_visible]">
    plugin://script.copacetic.helper/?info=artwork&amp;multiart=square&amp;multiart_max=5
  </value>
  <value>plugin://script.copacetic.helper/?info=artwork</value>
</variable>
```

Then reference the variable in your container:

```xml
<control type="list" id="9999">
  <visible>!Control.IsVisible(5007)</visible>
  <itemlayout />
  <focusedlayout />
  <content>$VAR[artwork_helper]</content>
</control>
```

---

## 5) See also

- [Artwork Plugin Handler](Artwork-Plugin-Handler)
- [Typewriter Plugin Handler](Typewriter-Plugin-Handler)
- [Progress Bar Plugin Handler](Progressbar-Plugin-Handler)
- [Jump Button Plugin Handler](Jumpbutton-Plugin-Handler)
- [Metadata Plugin Handler](Metadata-Plugin-Handler)
