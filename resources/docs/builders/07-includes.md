# Includes Builder

The includes builder generates `<include>` calls into your skin XML — typically multiple parameterised instances of an include you've defined yourself. You write one compact template; the builder produces N instances populated with metadata, user settings, or runtime state values.

The classic case: a widget container include in your skin XML, instantiated once per widget the user has configured, each with its own content path, label, sort order, and layout.

---

## Input format

Place XML files in `extras/builders/includes/`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<xml>
  <mapping>widgets</mapping>
  <includes>
    <template>
      <mode>dynamic</mode>
      <index start="3200" />
      <include name="widget_containers">
        <include content="lst_{layout}">
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

| Element | Description |
|---|---|
| `<mapping>` | Mapping name. Either a built-in mapping (`content_types`) or a custom one defined in `extras/builders/mappings/` — see [Mappings](02-mappings.md). |
| `<template>` | One include to expand (multiple per file allowed) |
| `<mode>` | `"dynamic"` to iterate once per runtime entry (a list the user grows and shrinks — widgets, menus). Default is static, which iterates once per item in the mapping's `items` list or dict — fixed at build time. |
| `<index>` | Optional `start` attribute for index numbering |
| `<items>` | Optional comma-separated list to loop over |
| `<include>` | The include to instantiate, with `name` matching one defined in your skin XML |

The `name` attribute on the outer `<include>` is the include you've already defined in your skin — typically with `$PARAM[...]` placeholders for the values that vary between instances. The builder fills those `$PARAM[...]` placeholders from your template, one call per loop iteration or runtime entry.

---

## Available placeholders

Inside the template, `{placeholder}` tokens are substituted before output. What's available depends on mode:

**Static mode (default)** — the template iterates once per item in the mapping's `items` list (or dict). Each iteration gets the mapping's loop values, anything declared in `<items>` on the template itself, and all string-valued metadata for the current item. Use this when the set of outputs is known at build time — for example, one config per content type.

**Dynamic mode** — the template iterates once per entry in `runtime_state.json` for this mapping. The number of iterations grows and shrinks with what the user has configured (widgets, menu items, etc.). Each entry provides:

- The mapping's key placeholder (e.g. `{widget_preset}`) set to the entry's `mapping_item`
- All string-valued fields stored on the entry (the user's chosen `layout`, `art`, `sortby`, custom `label`, resolved `parent` runtime_id, etc.)
- A numeric `{index}`, starting from `<index start="N">` and incrementing once per entry
- All string-valued metadata for the entry's `mapping_item`

When the same key appears in both stored fields and metadata, the stored field wins — so a user-edited label overrides the preset's default.

---

## Pruning

After substitution, any element whose `value` attribute or text content resolves to an empty string is removed entirely. So you can include parameters that only appear when the data has a value for them:

```xml
<param name="sortby" value="{sortby}" />
<param name="sortorder" value="{sortorder}" />
```

If an entry has no `sortby`, the param is omitted instead of becoming `value=""`.

---

## XSP smart playlists

If a mapping item's metadata contains an `xsp` key with a structured smart-playlist dict, the builder URL-encodes it into a query string at startup and exposes it as a `{xsp}` placeholder. Concatenate it with the content path:

```json
"latest_movies": {
  "content": "videodb://movies/titles/",
  "xsp": {
    "rules": { "and": [
      { "field": "playcount", "operator": "lessthan", "value": ["1"] }
    ]},
    "type": "movies"
  }
}
```

```xml
<param name="content" value="{content}{xsp}" />
```

Items without an `xsp` get an empty string here, and the param is pruned. `$ESCINFO[]` references inside the XSP are kept unquoted so Kodi resolves them at runtime.

---

## Example

Single template in `extras/builders/includes/includes_widgets.xml`:

```xml
<template>
  <mode>dynamic</mode>
  <index start="3200" />
  <include name="widget_containers">
    <include content="lst_{layout}">
      <param name="id" value="{index}" />
      <param name="visible" value="[Integer.IsGreater(Container({index}).NumItems,0) | Container({index}).IsUpdating] + [!Skin.HasSetting(widgets_per_menu) | String.IsEqual(Container(3000).ListItem.Property(runtime_id),{parent})]" />
      <param name="target" value="{target}" />
      <param name="sortby" value="{sortby}" />
      <param name="content" value="{content}{xsp}" />
      <param name="label" value="{label}" />
    </include>
  </include>
</template>
```

The outer `<include name="widget_containers">` has a fixed name, so it appears once in the output. The inner `<include content="lst_{layout}">` contains placeholders, so it multiplies — one call per runtime entry. Each entry's stored `layout` value picks the skin-defined include to call: `lst_strip`, `lst_grid`, `lst_showcase`.

With three configured widgets, the output looks like:

```xml
<include name="widget_containers">
  <include content="lst_strip">
    <param name="id" value="3200" />
    <param name="visible" value="..." />
    <param name="sortby" value="title" />
    <param name="content" value="special://skin/extras/playlists/inprogress_movies.xsp" />
    <param name="label" value="In-progress movies" />
  </include>
  <include content="lst_strip">
    <param name="id" value="3201" />
    <param name="visible" value="..." />
    <param name="target" value="videos" />
    <param name="sortby" value="random" />
    <param name="content" value="videodb://movies/titles/" />
    <param name="label" value="$LOCALIZE[31204]" />
  </include>
  <include content="lst_strip">
    <param name="id" value="3202" />
    <param name="visible" value="..." />
    <param name="target" value="videos" />
    <param name="sortby" value="dateadded" />
    <param name="content" value="videodb://movies/titles/?xsp=%7B%22rules%22%3A...%7D" />
    <param name="label" value="$LOCALIZE[31202]" />
  </include>
</include>
```

`{layout}` resolved to `strip` for all three. `{index}` incremented from 3200. The custom widget has no `target`, so that param was pruned. The `latest_movies` widget got its xsp encoded onto the content URL.

---

## Output

The builder writes `script-copacetic-helper_includes.xml`. To use the generated includes, reference the file in your skin's `Includes.xml`:

```xml
<include file="script-copacetic-helper_includes.xml" />
```

Then call the generated includes from your skin XML — `<include>widget_containers</include>` for the example above.

---

## Next

- [Rule Engine](08-rule-engine.md) — Condition evaluator used by configs, expressions, and controls