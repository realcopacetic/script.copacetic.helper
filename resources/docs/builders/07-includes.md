# Includes Builder

The includes builder generates `<include>` calls into your skin XML — typically multiple parameterised instances of an include you've defined yourself. You write one compact template; the builder produces N instances populated with metadata, user settings, or runtime state values.

The classic case: a widget container include in your skin XML, instantiated once per widget the user has configured, each with its own content path, label, sort order, and layout.

---

## Input format

Place XML files in `extras/templates/includes/`:

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
| `<mapping>` | Mapping name. Either a built-in mapping (`content_types`) or a custom one defined in `extras/templates/mappings/` — see [Mappings](02-mappings.md). |
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

## Template body shape

The example above uses `<param>` elements inside the include because that's how Kodi's `<include name="...">` system passes parameters. But the builder doesn't enforce that shape — it walks whatever XML you put inside the outer `<include>` and substitutes placeholders in attributes and text content.

When the include you're targeting takes a different shape, write that shape directly. The mainmenu builder calls a skin include named `mainmenu_items` whose body is a list of `<item>` elements with child elements rather than param attributes:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<xml>
  <mapping>mainmenu</mapping>
  <includes>
    <template>
      <mode>dynamic</mode>
      <index start="1" />
      <include name="mainmenu_items">
        <item id="{index}">
          <label>{label}</label>
          <icon>{icon}</icon>
          <onclick>{action}</onclick>
          <visible>{visible}</visible>
          <property name="runtime_id">{runtime_id}</property>
        </item>
      </include>
    </template>
  </includes>
</xml>
```

This produces one `<item>` per runtime entry, each with its label, icon, onclick action, and a `runtime_id` property the skin can read with `Container.ListItem.Property(runtime_id)`. That property is what the menu uses to filter widgets to the focused menu item — see [Hubs: filtering child entries by parent](#hubs-filtering-child-entries-by-parent) below.

The substitution rules are the same regardless of the body shape: any `{placeholder}` in an attribute value or element text is replaced; non-string metadata fields (like an `xsp` dict) aren't surfaced as text but are available to special handling like the `{xsp}` token.

---

## Pruning

After substitution, any element whose `value` attribute or text content resolves to an empty string is removed entirely. So you can include parameters that only appear when the data has a value for them:

```xml
<param name="sortby" value="{sortby}" />
<param name="sortorder" value="{sortorder}" />
```

If an entry has no `sortby`, the param is omitted instead of becoming `value=""`.

The same applies to non-`<param>` element shapes — `<onclick>{action}</onclick>` is dropped entirely if `{action}` resolves to an empty string.

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

## Hubs: filtering child entries by parent

Dynamic mappings can reference each other via `parent` — letting you build hub structures where each menu item owns its own set of widgets. The wiring spans three places: the child mapping's metadata, the includes template, and the dialog that opens the child editor scoped to one parent.

### 1. Tag the child to a parent in metadata

In the child mapping's metadata, set `parent` to the `mapping_item` name of an entry in another mapping. At runtime-state initialisation, that name is replaced with the matching entry's `runtime_id`. This is described in [Runtime State → Parent references](09-runtime-state.md#parent-references).

```json
"latest_movies": {
  "label": "$LOCALIZE[31202]",
  "target": "videos",
  "content": "videodb://movies/titles/",
  "parent": "movies"
}
```

After initialisation, the `latest_movies` widget entry has `"parent": "<runtime_id of the movies menu item>"`. Once tagged, `{parent}` becomes available as a placeholder for any dynamic includes template iterating that mapping.

### 2. Filter visibility in the child include

In the includes template that emits the child entries, gate visibility on the parent matching whatever the skin currently considers focused. The widgets template uses a Kodi property on the menu container:

```xml
<param name="visible" value="String.IsEqual(Container(3000).ListItem.Property(runtime_id),{parent})" />
```

`Container(3000)` here is the menu container. Its listitems have a `runtime_id` property because the mainmenu template wrote one (`<property name="runtime_id">{runtime_id}</property>` — see the body-shape example earlier on this page). The widget is visible only when its `{parent}` matches the focused menu item's `runtime_id`.

The full visibility expression in production also handles the case where the user has hub mode disabled, allowing every widget through:

```xml
<param name="visible" value="[Integer.IsGreater(Container({index}).NumItems,0) | Container({index}).IsUpdating] + [!Skin.HasSetting(widgets_per_menu) | String.IsEqual(Container(3000).ListItem.Property(runtime_id),{parent})]" />
```

The first bracketed group keeps empty widgets hidden; the second bracketed group is the hub gate.

### 3. Open the child editor scoped to one parent

The Dynamic Editor accepts a `parent` URL parameter that filters the list to entries with a matching `parent` value. Wire this to a button on the parent's editor — the menu editor uses a control on each menu listitem that opens the widget editor pre-filtered to widgets owned by that menu item:

```json
"menu_configure_widgets": {
  "mode": "dynamic",
  "id": 204,
  "control_type": "button",
  "label": "Configure widgets for this menu item",
  "visible": "xml(String.IsEqual(Window(home).Property(current_mapping),mainmenu) + Skin.HasSetting(widgets_per_menu))",
  "onclick": {
    "type": "custom",
    "action": "RunScript(script.copacetic.helper,action=dynamic_settings_window,name=widgetsettings,mapping=widgets,parent={runtime_id})"
  }
}
```

`{runtime_id}` is the focused menu item's runtime_id, substituted at the moment the button is pressed. The opened editor only shows entries whose `parent` matches; adds, deletes, and reorders inside the filtered editor stay scoped, and new entries are inserted with `parent` already set so they appear adjacent to existing siblings.

This three-step pattern — tag in metadata, filter in include, scope in dialog — is the whole hub recipe. Same pieces wherever you want one dynamic mapping to own a per-entry set of children.

---

## Example

Single template in `extras/templates/includes/includes_widgets.xml`:

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