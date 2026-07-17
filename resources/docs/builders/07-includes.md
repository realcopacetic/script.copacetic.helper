# Includes Builder

Generates repeated XML into your skin. Despite the name, the body of a template can be **any XML** — include calls, `<item>` lists for menus, whole `<control>` trees. You write the shape once; the builder emits one filled-in copy per loop pass.

The two classic cases: a widget container include called once per configured widget, and a main-menu `<item>` list built once per menu entry.

---

## Input

XML files in `extras/templates/includes/`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<xml>
  <mapping>widgets</mapping>
  <includes>
    <template>
      <mode>dynamic</mode>
      <index start="3200" />
      <include name="widget_containers">
        <include content="ctn_{layout}">
          <param name="id" value="{index}" />
          <param name="content" value="{content}{xsp}" />
          <param name="label" value="{label}" />
          <param name="target" value="{target}" />
        </include>
      </include>
    </template>
  </includes>
</xml>
```

| Element | What it does |
|---|---|
| `<mapping>` | Mapping name |
| `<template>` | One unit to expand (several per file is fine) |
| `<mode>` | `dynamic` = one copy per settings-file entry. Default = one per mapping item. |
| `<index>` | Start number (or range) for `{index}` |
| `<items>` | An extra comma-separated loop on the template itself |
| `<filter>` | Skip some loop passes — see below |
| `<include name="...">` | The **outer** include — the name your skin references. Appears once. |

Everything *inside* the outer include is the body, and the body multiplies: one copy per pass, tokens filled per pass. Tokens work anywhere — element text, attributes, even the `content` name (`ctn_{layout}` routes each entry to your matching layout include: `ctn_strip`, `ctn_grid`, …).

---

## Body shapes

**Include calls with params** — the widget case above.

**Any other XML.** The main menu emits `<item>` elements, not includes:

```xml
<template>
  <mode>dynamic</mode>
  <index start="1" />
  <include name="mainmenu_items">
    <item id="{index}">
      <label>{label}</label>
      <icon>{icon}</icon>
      <onclick condition="Window.IsActive({window})">{update}</onclick>
      <onclick condition="!Window.IsActive({window})">{action}</onclick>
      <visible>{visible}</visible>
      <property name="runtime_id">{runtime_id}</property>
    </item>
  </include>
</template>
```

One `<item>` per menu entry, straight into a container's content block. Attributes (`condition`, `id`), text, nested elements — all substituted. Widget templates go further and emit full `<control>` trees with animations. If you can write it as XML, the builder can repeat it.

**Conditional include calls.** An inner `<include>` can carry a `condition` attribute; it lands in the output for Kodi to evaluate. The views template composes it from tokens *and* `$PARAM[...]` — the token fills at build time, the `$PARAM` when your skin later calls the outer include:

```xml
<include content="tpl_vues" condition="$EXP[layout_{layout}_include_$PARAM[window]]">
```

---

## Empty means gone (and one exception)

A param, attribute, or element whose value fills in to nothing is dropped from that copy — so your include's `$PARAM` defaults take over, and `<onclick>{update}</onclick>` simply isn't there for entries with no update action.

The exception is the outer include itself: if a filter removes *every* pass, the named include is still written as an empty shell. Your skin XML can reference `<include>widget_containers</include>` unconditionally without breaking when the user has nothing configured.

---

## What the tokens are

**Default (per mapping item):** the mapping's loop names, the template's own `<items>`, `{index}`, and the item's string metadata.

**Dynamic (per settings entry):** all of the above, plus everything stored on the entry (`{layout}`, `{content}`, `{label}`, `{runtime_id}`, `{parent}`, …) — stored values win over metadata. `{index}` counts up from the start number, so containers get sequential IDs (3200, 3201, …). Maths works too: `{index}0` by concatenation, `{index+2002}` by arithmetic.

**`{xsp}`:** if an item's metadata has an `xsp` smart-playlist dict, the builder URL-encodes it and hands it to you as `{xsp}` — stick it on the end of a path: `value="{content}{xsp}"`. Items without one get nothing there, and the param prunes away. `$ESCINFO[]` inside the playlist stays live for Kodi to resolve.

---

## Filtering: skipping loop passes

`<filter>` is a condition checked once per loop pass, before anything is written ([Rule Engine](08-rule-engine.md)). Fail it and that pass doesn't exist in the output.

That's different from a `condition` in the body: **filter decides whether a thing exists; conditions decide what an existing thing does at runtime.**

Its best trick is letting different loop values cover different ranges from one template. The texture variables loop a two-item mapping (`nowrap`, `wrap`) across index −3..6 — but the two variants need different ranges: views draw ten fixed slots, while the wrap-around transition machinery only ever looks one step each way:

```json
"filter": "equals({wrapness}, nowrap) | In({index}, [-1, 0, 1])"
```

Read it as two ways to survive, OR'd: `nowrap` always passes (all ten indices emit); `wrap` only passes at −1, 0, 1. One template instead of two per family, and no `_wrap-3` outputs that nothing uses.

---

## Hubs: each parent owns its own children

**The problem this solves.** By default the widgets are one flat list — the same row of widgets whatever menu item is focused. The hub pattern gives each menu item its *own* set: focus Movies, see the movie widgets; focus Music, see the music widgets. Copacetic exposes it as the `widgets_per_menu` skin setting, and the whole thing is wiring between two mappings — no special container tricks.

Four pieces. The first three you write; the fourth is what comes out.

### 1. Tag the child to a parent in metadata

In the child mapping (`widgets`), give an item a `parent` naming an item in the parent mapping (`mainmenu`):

```json
"latest_movies": { "label": "$LOCALIZE[31202]", "content": "videodb://movies/titles/", "parent": "movies" }
```

When the settings file is created, that name is swapped for the movies menu entry's permanent id. From then on the link is by id — reorder either list, rename labels, nothing breaks. `{parent}` is now a token in any dynamic template for the widgets mapping.

### 2. The parent announces itself; the child checks

Two halves of one handshake. The menu template writes each row's id onto its listitem (that's the `<property>` line in the menu example above):

```xml
<property name="runtime_id">{runtime_id}</property>
```

And the widget template's visible param compares the focused menu row against its own `{parent}` — letting everything through when hub mode is off:

```xml
<param name="visible" value="[!Skin.HasSetting(widgets_per_menu) | String.IsEqual(Container(3000).ListItem.Property(runtime_id),{parent})] + [Control.HasFocus({index}) | Control.HasFocus({index}0)]" />
```

### 3. What the output looks like

This is the part worth staring at once. From the generated `script-copacetic-helper_includes.xml`, the movies menu item:

```xml
<item id="1">
  <label>$LOCALIZE[342]</label>
  <icon>DefaultMovies.png</icon>
  <onclick condition="Window.IsActive(Videos)">Container.Update("videodb://movies/titles/")</onclick>
  <onclick condition="!Window.IsActive(Videos)">ActivateWindow(Videos,"videodb://movies/titles/",return)</onclick>
  <property name="runtime_id">3ad35bab-f50e-5752-be73-c515e4f6b555</property>
</item>
```

…and a widget whose entry carries `"parent": "3ad35bab-..."`:

```xml
<include content="ctn_strip">
  <param name="id" value="3200" />
  <param name="visible" value="[!Skin.HasSetting(widgets_per_menu) | String.IsEqual(Container(3000).ListItem.Property(runtime_id),3ad35bab-f50e-5752-be73-c515e4f6b555)] + [Control.HasFocus(3200) | Control.HasFocus(32000)]" />
  ...
</include>
```

The same id appears in both files: the menu item wears it as a property, the widget checks for it in its visible condition. When the Movies row is focused, `Container(3000).ListItem.Property(runtime_id)` is that id, the comparison is true, and this widget shows. Focus another menu item and it doesn't. That's the entire runtime mechanism — one string equality Kodi evaluates like any other.

### 4. Open the child editor stamped to one parent

The last piece is how the user *builds* each menu item's set. Open the widget editor with `parent=` and the session is stamped to that hub. On the menu editor, this is a button whose action fills `{runtime_id}` from the highlighted menu row:

```json
"menu_configure_widgets": {
  "id": 205,
  "control_type": "button",
  "label": "Configure widgets",
  "onclick": {
    "type": "custom",
    "action": "RunScript(script.copacetic.helper,action=dynamic_settings_window,name=widgetsettings,mapping=widgets,parent={runtime_id})"
  }
}
```

Highlight Movies, press the button, and the widget editor opens showing *only* the movie widgets. Stamping means:

- **Adds inherit the parent.** A new entry arrives with `parent` already set to this hub's id and is inserted next to its siblings in the file — you never see, or set, the link by hand.
- **Everything stays inside the hub.** Move up/down reorders within this hub's entries; Delete and Reset touch only them. Other hubs' widgets are invisible and untouchable.
- **The link is maintained for you.** Delete the menu item later and its widgets go with it; reset the menu and surviving links are re-pointed at the fresh entries — see [Runtime State → Parent links](09-runtime-state.md#parent-links).

Tag in metadata, handshake in the templates, stamp in the dialog. Same recipe wherever one editable list should own another — menu → widgets is just the built-in example.

---

## Where it goes

The builder writes `script-copacetic-helper_includes.xml`. Include it once from your skin, then call the generated names (`widget_containers`, `mainmenu_items`, …) like any other include.

---

## Next

- [Rule Engine](08-rule-engine.md) — the condition language filters and rules use