# Includes Builder

The includes builder expands Kodi `<include>` templates using recursive placeholder substitution. It takes a compact template and generates multiple parameterised instances of a skin include — each populated with different metadata, user settings, and runtime state values. The real value is in recursively creating multiple instances of an include you have defined in your skin XML.

---

## When to use it

Use the includes builder when you need to generate multiple instances of the same include with different parameters. For example, a single widget container include defined in your skin XML can be instantiated N times — once per widget the user has configured — each with its own content path, label, sort order, and layout. The builder handles the expansion and the metadata injection.

---

## Input format

Include inputs are **XML** files (not JSON) placed in `extras/builders/includes/`. The format uses a wrapper structure:

```xml
<?xml version="1.0" encoding="utf-8"?>
<xml>
  <mapping>widgets</mapping>
  <includes>
    <template>
      <mode>dynamic</mode>
      <index start="1" />
      <include name="WidgetContainer">
        <param name="id" value="{index}" />
        <param name="content" value="{content_path}{xsp}" />
        <param name="label" value="{label}" />
        <param name="target" value="{target}" />
      </include>
    </template>
  </includes>
</xml>
```

### Structure

| Element | Description |
|---|---|
| `<mapping>` | Name of the mapping to use for substitution |
| `<includes>` | Container for all templates in this file |
| `<template>` | A single include template to expand |
| `<mode>` | Optional: `"dynamic"` to expand from runtime_state |
| `<index>` | Optional: start attribute for index numbering |
| `<items>` | Optional: comma-separated list of items to loop over |
| `<include>` | The include to instantiate, with `name` matching a skin-defined include |

The `name` attribute on `<include>` refers to an include you have already defined in your skin XML using `$PARAM[...]` placeholders. The builder generates multiple parameterised instances of that include — one per loop iteration or runtime state entry. You define the include template once in your skin; the builder creates the instances.

---

## Recursive expansion

The includes builder's key feature is recursive template expansion. When processing a list within the template (like multiple `<param>` elements), the builder checks whether each item contains any placeholders from the current substitutions:

- **If it contains placeholders** — the item is multiplied across all substitutions, producing one copy per substitution with tokens replaced.
- **If it doesn't contain placeholders** — the item is included once, unchanged.

This means a single template can contain both static elements (that appear once) and dynamic elements (that repeat per loop iteration).

### Pruning

After substitution, any element where the `value` attribute or text content resolves to an empty string is removed entirely. This means you can include conditional parameters that only appear when the metadata has a value for them:

```xml
<param name="sortby" value="{sortby}" />
<param name="sortorder" value="{sortorder}" />
```

If a preset's metadata doesn't define `sortby`, the parameter is omitted from the output rather than appearing as an empty `value=""`.

---

## Static vs dynamic mode

### Static mode (default)

In static mode, the builder loops over the mapping's `items` list (or dict) combined with any `<items>` declared in the template. The template name itself can contain placeholders, producing one output include per loop value.

### Dynamic mode

In dynamic mode (`<mode>dynamic</mode>`), the builder reads entries from `runtime_state.json` for the template's mapping. You don't interact with the runtime state file directly — it captures user preferences from a Dynamic Editor screen. Each entry provides a substitution dictionary containing:

- The `mapping_item` field, which ties the entry to a specific item in the custom mapping. This is what connects the entry to its preset-specific metadata — labels, content paths, sort orders, and anything else the skinner has defined for that item.
- All other stored fields: `view`, `layout`, `label`, `content_path`, etc. — values the user has configured through the Dynamic Editor.
- A numeric `index` (starting from the `<index start="N">` value).
- The mapping's key placeholder set to the `mapping_item` value.
- All metadata for the entry's `mapping_item`, merged in from the mapping definition.
- `runtime|field` prefixed copies of each stored field.

The `runtime|field` prefix is important for templates that need to distinguish between metadata values and user-configured values. For example, a mapping's metadata might define a default `label` for each preset (like "$LOCALIZE[31201]" for "Next Up"), but a user might override the label for a "custom" widget through an edit field. The template can use `{runtime|label}` to access specifically the user-entered value, or `{label}` which resolves from the combined substitution dictionary (where user values take precedence over metadata).

---

## XSP URL encoding

For presets that use smart playlists, the mapping metadata can include an `xsp` key containing a structured dict:

```json
"latest_movies": {
  "content_path": "videodb://movies/titles/",
  "xsp": {
    "group": { "mixed": "false", "type": "none" },
    "rules": {
      "and": [
        { "field": "playcount", "operator": "lessthan", "value": ["1"] }
      ]
    },
    "type": "movies"
  }
}
```

During builder initialisation, `_prepare_xsp_urls()` converts this to a URL-encoded query string:

```
?xsp=%7B%22group%22%3A%7B%22mixed%22%3A%22false%22%2C%22type%22%3A%22none%22%7D%2C...%7D
```

Any `$ESCINFO[]` references within the XSP are preserved unquoted. The result is stored back in metadata as a string, so when a template uses `{content_path}{xsp}`, it produces a complete widget path with an inline smart playlist filter.

---

## Example walkthrough

In practice, widget includes use two templates working together — one to create the per-preset definitions, and one to assemble the user's widget list from runtime state.

### Template 1: Per-preset definitions (static)

This template has a placeholder in its `name`, so it expands into multiple *named include definitions* — one per mapping item:

```xml
<template>
  <include name="widget_{widget_preset}">
    <include content="widget_template">
      <param name="widget_header" value="{label}" />
      <param name="id" value="$PARAM[id]" />
      <param name="target" value="{target}" />
      <param name="sortby" value="{sortby}" />
      <param name="sortorder" value="{sortorder}" />
      <param name="content" value="{content_path}{xsp}" />
      <param name="view" value="$PARAM[view]" />
      <param name="layout" value="$PARAM[layout]" />
      <param name="label" value="{label}" />
    </include>
  </include>
</template>
```

The builder loops over the mapping's items and substitutes metadata into each one. `{label}`, `{target}`, `{content_path}`, `{sortby}`, `{sortorder}`, and `{xsp}` all come from the mapping's metadata for that item. Params that resolve to empty (e.g. `{sortby}` for presets with no sort order) are pruned automatically.

Notice that some params use `$PARAM[...]` instead of `{...}`. These are Kodi include parameters — they're *not* substituted by the builder. They're left as-is so that when the include is *called* in Template 2, the caller can pass values through.

This produces one named include definition per mapping item:

```xml
<include name="widget_next_up">
  <include content="widget_template">
    <param name="widget_header" value="$LOCALIZE[31201]" />
    <param name="id" value="$PARAM[id]" />
    <param name="target" value="videos" />
    <param name="content" value="plugin://script.copacetic.helper/?info=next_up" />
    <param name="view" value="$PARAM[view]" />
    <param name="layout" value="$PARAM[layout]" />
    <param name="label" value="$LOCALIZE[31201]" />
  </include>
</include>
<include name="widget_latest_movies">
  <include content="widget_template">
    <param name="widget_header" value="$LOCALIZE[31202]" />
    <param name="id" value="$PARAM[id]" />
    <param name="target" value="videos" />
    <param name="sortby" value="dateadded" />
    <param name="sortorder" value="descending" />
    <param name="content" value="videodb://movies/titles/?xsp=%7B%22group%22%3A..." />
    <param name="view" value="$PARAM[view]" />
    <param name="layout" value="$PARAM[layout]" />
    <param name="label" value="$LOCALIZE[31202]" />
  </include>
</include>
<!-- ... one for each mapping item -->
```

Each definition wraps `widget_template` (a skin-defined include containing the actual container XML) with all the preset-specific metadata baked in, while leaving `$PARAM[id]`, `$PARAM[view]`, and `$PARAM[layout]` as pass-through parameters for the caller to fill.

### Template 2: The widget list (dynamic)

This template has a fixed `name` (`widgets`) but its inner `<include content="...">` contains placeholders that multiply per runtime state entry:

```xml
<template>
  <mode>dynamic</mode>
  <index start="3200" />
  <include name="widgets">
    <include content="widget_{widget_preset}">
      <param name="id" value="{index}" />
      <param name="content" value="{runtime|content_path}" />
      <param name="view" value="{view}" />
      <param name="layout" value="{layout}" />
      <param name="label" value="{runtime|label}" />
    </include>
  </include>
</template>
```

The builder reads entries from `runtime_state.json`. Each entry provides its `mapping_item` (which resolves `{widget_preset}`), its stored fields (`{view}`, `{layout}`), and `runtime|` prefixed fields for user-entered values. The inner `<include content="...">` is multiplied once per entry, while the outer `<include name="widgets">` stays singular.

Given this runtime state:

```json
{
  "widgets": [
    { "runtime_id": "912e...", "mapping_item": "next_up", "view": "strip", "layout": "poster" },
    { "runtime_id": "ede8...", "mapping_item": "custom", "view": "grid", "layout": "poster",
      "label": "Comedy", "content_path": "videodb://movies/genres/4/" },
    { "runtime_id": "3efd...", "mapping_item": "latest_movies", "view": "strip", "layout": "poster" }
  ]
}
```

The output is:

```xml
<include name="widgets">
  <include content="widget_next_up">
    <param name="id" value="3200" />
    <param name="view" value="strip" />
    <param name="layout" value="poster" />
  </include>
  <include content="widget_custom">
    <param name="id" value="3201" />
    <param name="content" value="videodb://movies/genres/4/" />
    <param name="view" value="grid" />
    <param name="layout" value="poster" />
    <param name="label" value="Comedy" />
  </include>
  <include content="widget_latest_movies">
    <param name="id" value="3202" />
    <param name="view" value="strip" />
    <param name="layout" value="poster" />
  </include>
</include>
```

Notice how:
- The outer `<include name="widgets">` is a single definition. The inner `<include content="...">` calls multiplied — one per runtime state entry.
- `{widget_preset}` resolved to each entry's `mapping_item`, creating calls to the preset definitions from Template 1 (`widget_next_up`, `widget_custom`, `widget_latest_movies`).
- `{index}` incremented from 3200, giving each widget a unique ID.
- `{runtime|content_path}` and `{runtime|label}` pulled user-entered values — these only have values for the "custom" entry, so they were pruned from the other two.
- `{view}` and `{layout}` came from the runtime state fields the user configured in the Dynamic Editor.

The skin references the final include with `<include>widgets</include>` on the home screen. All the per-preset metadata, user settings, and instance ordering are resolved by the builder.

---

## Grouped template names

When the template name contains placeholders, the builder groups substitutions by the expanded name. All substitutions that produce the same template name are collected and used together during recursive expansion.

When the template name has no placeholders (the common case for dynamic mode), all substitutions are grouped under the same name, and the include is expanded with all of them collectively — this is what produces the multiple instances shown in the example above.

---

## Output format

The includes builder writes `script-copacetic-helper_includes.xml`. To make the generated instances available, add the file to your skin's `Includes.xml`:

```xml
<include file="script-copacetic-helper_includes.xml" />
```

The generated file contains parameterised include calls that reference includes defined in your skin XML. The skinner defines the include template (with `$PARAM[...]` placeholders), and the builder populates instances of it.

---

## Next

- [Rule Engine](08-rule-engine.md) — The condition evaluator used by configs, expressions, and controls