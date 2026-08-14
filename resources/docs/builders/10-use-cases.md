# Use Cases — Chaining the Builders

Three worked examples from Copacetic 2. Patterns to borrow, not rules.

---

## 1. Standalone variables

**Builders:** variables only. **Mapping:** `"none"`.

Lots of similar `<variable>` elements from one template and a number range:

```json
{
  "mapping": "none",
  "variables": {
    "texture_primary_poster{range}": {
      "range": { "start": -3, "end": 6 },
      "values": [
        { "condition": "!String.IsEmpty(ListItemNoWrap({range}).Art(keyart)) + $EXP[art_keyart_visible]",
          "value": "$INFO[ListItem({range}).Art(keyart)]" },
        { "condition": "!String.IsEmpty(ListItemNoWrap({range}).Art(poster))",
          "value": "$INFO[ListItem({range}).Art(poster)]" }
      ]
    }
  }
}
```

Ten variables out. Use with `$VAR[texture_primary_poster1]` etc. No configs, controls, or settings involved.

---

## 2. Views — a fixed list

**Builders:** configs → controls → expressions. **Mapping:** `content_types` (built-in).

The user picks a layout per content type; the skin shows the matching view. The list of content types is fixed — the user only edits each one's settings.

### Configs

```json
{
  "mapping": "content_types",
  "configs": {
    "{content_type}_layout": {
      "items": { "list": "Catalogue", "showcase": "Showcase", "strip": "Strip", "grid": "Grid" },
      "filter_mode": "exclude",
      "rules": [
        { "condition": "In({content_type}, [songs])", "value": ["showcase", "strip", "grid"] }
      ],
      "default_key": "window",
      "defaults": { "*": "list" }
    }
  }
}
```

Movies get all four; songs only `list`. Registered on the mapping with `"layout": "{content_type}_layout"` under `config_fields.global`.

### Controls

```json
{
  "mapping": "content_types",
  "controls": {
    "content_type_item": {
      "control_type": "listitem",
      "label": "{content_type}",
      "icon": "icons/{content_type}.png"
    },
    "layout": {
      "field": "layout",
      "id": 200,
      "control_type": "sliderex",
      "label": "Layout"
    }
  }
}
```

One row per content type; one slider that follows the highlighted row.

### Expressions

```json
{
  "mapping": "content_types",
  "expressions": {
    "layout_{item}_visible_{window}": {
      "items": ["list", "showcase", "strip", "grid"],
      "rules": [
        { "condition": "equals({layout}, {item})",
          "type": "append",
          "value": "Container.Content({content_type})" }
      ],
      "fallback_key": "window",
      "fallbacks": { "*": { "target_item": "list", "value": "invert()" } }
    }
  }
}
```

One expression per layout per window — `layout_showcase_visible_videos` becomes `Container.Content(movies) | Container.Content(tvshows)` when both use showcase, and `list` catches everything else via `invert()`. Use with `$EXP[layout_showcase_visible_videos]`.

All choices live as fields on the content-type entries in the settings file.

---

## 3. Widgets — editable lists

**Builders:** configs → controls → includes. **Mapping:** `widgets` (custom).

Widget slots the user adds, deletes, reorders, and configures. One `<include>` call per slot.

### The mapping

```json
{
  "widgets": {
    "mode": "dynamic",
    "parent_mapping": "mainmenu",
    "items": ["next_up", "latest_movies", "custom", "..."],
    "placeholders": { "key": "widget_preset" },
    "default_order": ["random_movies", "latest_movies", "random_tvshows", "latest_tvshows"],
    "config_fields": {
      "global": { "layout": "{widget_preset}_layout", "art": "{widget_preset}_art" },
      "custom": { "sortby": "sortby", "sortorder": "sortorder" }
    },
    "metadata": {
      "latest_movies": {
        "label": "$LOCALIZE[31202]",
        "target": "videos",
        "content": "videodb://movies/titles/",
        "parent": "movies"
      },
      "custom": { "label": "$LOCALIZE[31210]", "content": "" }
    }
  }
}
```

`parent` names a main-menu item — swapped for that entry's permanent id when the settings file is created, which is what keeps widgets attached to their menu item across reorders ([hubs](07-includes.md#hubs-each-parent-owns-its-own-children)). The `custom` preset is nearly empty; the user fills it in.

### Configs

```json
{
  "mapping": "widgets",
  "configs": {
    "{widget_preset}_layout": {
      "items": { "strip": "Strip", "grid": "Grid", "showcase": "Showcase", "marquee": "Marquee" },
      "rules": [
        { "condition": "In({widget_preset}, [drilldown, group])", "value": ["marquee"] }
      ],
      "defaults": { "*": "strip" }
    },
    "{widget_preset}_art": {
      "dependent_fields": ["layout"],
      "items": { "fanart": "$LOCALIZE[31007]", "poster": "$LOCALIZE[31006]", "square": "$LOCALIZE[31008]" },
      "rules": [
        { "condition": "In({widget_preset}, [latest_albums, liked_songs, favourites])", "value": ["fanart", "poster"] },
        { "condition": "equals({layout}, showcase)", "value": ["fanart", "poster"] }
      ],
      "defaults": { "next_up": "fanart", "*": "poster" }
    }
  }
}
```

Note `dependent_fields`: the art options react to the chosen layout ([Configs → rules that read another setting](05-configs.md#rules-that-read-another-setting)).

### Controls

```json
{
  "mapping": "widgets",
  "controls": {
    "widget_{index}": {
      "control_type": "listitem",
      "label": "{label}",
      "icon": "{icon}",
      "description": "Select widget to configure."
    },
    "widget_preset": {
      "role": "item_picker",
      "id": 200,
      "control_type": "button",
      "onclick": {
        "type": "select",
        "heading": "Choose widget",
        "then": { "custom": "widget_content", "drilldown": "widget_content" }
      },
      "label": "Change type"
    },
    "widget_layout": {
      "field": "layout",
      "id": 202,
      "control_type": "sliderex",
      "label": "Layout"
    },
    "widget_content": {
      "field": "content",
      "id": 205,
      "control_type": "button",
      "visible": "In({widget_preset}, [custom, drilldown])",
      "onclick": {
        "type": "browse_content",
        "heading": "Select content path",
        "mode": "widget",
        "sibling_fields": { "label": "widget_label", "target": "target" }
      }
    },
    "widget_label": {
      "field": "label",
      "id": 206,
      "control_type": "edit",
      "label": "Widget name",
      "visible": "In({widget_preset}, [custom, drilldown, group])"
    }
  }
}
```

`widget_preset` has the role, so this window is an editable list. Its `then` map means picking `custom` while adding runs the content browser first — a new custom widget never arrives with an empty path ([Controls → Onclick](06-controls.md#onclick)).

### Includes

```xml
<template>
  <mode>dynamic</mode>
  <index start="3200" />
  <include name="widget_containers">
    <include content="ctn_{layout}">
      <param name="id" value="{index}" />
      <param name="target" value="{target}" />
      <param name="sortby" value="{sortby}" />
      <param name="content" value="{content}{xsp}" />
      <param name="label" value="{label}" />
    </include>
  </include>
</template>
```

The outer include appears once; the inner call multiplies — one per widget, each routed to your matching layout include (`ctn_strip`, `ctn_grid`, …). When the user closes the editor, this rebuilds and the skin reloads.

---

## 4. Regions — one cascade, per-item deltas

**Builders:** variables + expressions. **Mappings:** `regions` (static), borrowed alongside `widgets`, `search`, `views`.

The skin has several places that show "the current item": the media view (**primary**), the secondary strip (**secondary**), the home hub's widgets, and the search rails. They need the same cascades — which clearlogo, is the container updating, is the typewriter ready — but each one addresses its list differently. Writing four copies of every cascade is the maintenance trap `templates_from` exists for; the regions mapping is where the per-place differences live.

### The mapping

```json
"regions": {
  "mode": "static",
  "items": [ "hub", "primary", "secondary" ],
  "placeholders": { "key": "region" },
  "tokens": {
    "guard": "true",
    "id_filter": "equals({region}, secondary)",
    "texture_prefix": "{region}"
  },
  "metadata": {
    "primary":   { "listitem": "ListItem",                 "onnext": "[Container.OnNext + Integer.IsGreater(Container.NumItems,1)] | $EXP[container_onnext_widgets]", "window": "videos" },
    "secondary": { "listitem": "Container(3100).ListItem", "onnext": "Container(3100).OnNext + Integer.IsGreater(Container(3100).NumItems,1)", "hasfocus": "Control.HasFocus(3100) | Control.HasFocus(4100)", "updating": "Container(3100).IsUpdating" }
  }
}
```

Static: nothing stored, no editor. `tokens` are the mapping-wide defaults; `metadata` is what differs per region. The widgets and search mappings declare the *same token names* (`guard`, `listitem`, `onnext`, `updating`, …) with their own grammar — `Container({index}).ListItem`, `Control.HasFocus({index}) | $EXP[search_preview_{index}]` — so a template written against those names works for all of them.

### One template, four families

```json
"container_updating_{region}": {
  "templates_from": [ "regions", "widgets", "search", "views" ],
  "index": { "start": 3200 },
  "filter": "{id_filter}",
  "rules": [ { "type": "append", "value": "{updating}" } ]
}
```

What comes out:

| Borrowed from | `{region}` is | Output |
|---|---|---|
| regions (secondary only, via `id_filter`) | the item name | `container_updating_secondary` = `Container(3100).IsUpdating` |
| widgets | the token `"widgets"` | `container_updating_widgets` = one `[…]` per configured widget, ORed |
| search | the token `"search"` | `container_updating_search` = one per rail, ORed |
| views | the token `"primary"` | `container_updating_primary` = `Container(50).IsUpdating | … | Container(57).IsUpdating` |

The last row is the trick worth learning: `views` sets `"region": "primary"` as a *token*, so all eight view containers land under one name and `append` rolls them up. Primary's rollup falls out of the same rule as everyone else's — no separate template.

### The same for variables

```json
"art_clearlogo_{region}": {
  "templates_from": [ "regions", "widgets", "search" ],
  "index": { "start": 3200 },
  "filter": "{region_filter}",
  "values": [ [
    { "condition": "{guard} + !String.IsEmpty({listitem}.Art(clearlogo))", "value": "$INFO[{listitem}.Art(clearlogo)]" },
    { "condition": "{guard} + !String.IsEmpty({listitem}.Art(tvshow.clearlogo))", "value": "$INFO[{listitem}.Art(tvshow.clearlogo)]" }
  ] ]
}
```

For primary, `{guard}` is `true` and gets elided; for a widget it's the focus test, so each widget's rows only match while that widget has focus. `{listitem}` is bare `ListItem` for primary and `Container(3200).ListItem` for the first widget. One cascade, no copies.

### When to use it

Reach for a static mapping with `tokens` + `metadata` when the *deltas are per item* and the cascade is shared. If two places differ in **structure** — different rows, not different snippets — they're two templates. And keep the token vocabulary small and consistent across the borrowed mappings: a template only works where every name it uses is defined.
