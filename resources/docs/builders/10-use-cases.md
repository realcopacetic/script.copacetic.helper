# Chaining Builders — Use Cases

Each builder is useful on its own; the system gets interesting when you chain them. The three examples below show how Copacetic 2 uses the builders in combination — they're worked examples, not prescriptions. Use whichever pieces fit your skin.

---

## 1. Standalone variables

**Builders:** Variables only.
**Mapping:** `"none"`.

The simplest use case — generate many similar `<variable>` elements from one template plus an index range.

```json
{
  "mapping": "none",
  "variables": {
    "texture_primary_poster{index}": {
      "index": { "start": -3, "end": 6 },
      "values": [
        {
          "condition": "!String.IsEmpty(ListItemNoWrap({index}).Art(keyart)) + $EXP[art_keyart_visible]",
          "value": "$INFO[ListItem({index}).Art(keyart)]"
        },
        {
          "condition": "!String.IsEmpty(ListItemNoWrap({index}).Art(poster))",
          "value": "$INFO[ListItem({index}).Art(poster)]"
        }
      ]
    }
  }
}
```

Output: 10 `<variable>` elements (`texture_primary_poster-3` through `texture_primary_poster6`), each with the condition/value pairs substituted.

No configs, controls, expressions, or runtime state involved. Reference the variables in your skin XML with `$VAR[texture_primary_poster1]`.

---

## 2. Views — static, skin-string-driven

**Builders:** Configs → Controls → Expressions.
**Mapping:** `content_types` (built-in, dict-of-lists).

Per-content-type view settings. The user picks a layout for each content type through a Dynamic Editor window; the skin shows the matching view based on what's currently displayed.

The built-in `content_types` mapping pairs windows with their content types:

```json
{
  "items": {
    "videos": ["movies", "sets", "tvshows", "seasons", "episodes", "videos", "musicvideos"],
    "music": ["artists", "albums", "songs"],
    "pictures": ["images"],
    "addons": ["addons"],
    "favourites": ["favourites"]
  },
  "placeholders": { "key": "window", "value": "content_type" }
}
```

### Step 1: Configs

```json
{
  "mapping": "content_types",
  "configs": {
    "{content_type}_layout": {
      "mode": "static",
      "items": ["list", "showcase", "strip", "grid"],
      "filter_mode": "exclude",
      "rules": [
        { "condition": "In({content_type}, [songs])",
          "value": ["showcase", "strip", "grid"] }
      ],
      "default_key": "window",
      "defaults": { "*": "list" }
    }
  }
}
```

The Dynamic Editor resolves this template per content type when the viewsettings window opens: `movies_layout` exposes all four layouts; `songs_layout` exposes only `list` (the others are excluded by the rule). Defaults per `defaults: {"*": "list"}`.

### Step 2: Controls

```json
{
  "mapping": "content_types",
  "controls": {
    "{content_type}_item": {
      "control_type": "listitem",
      "label": "{content_type}",
      "icon": "icons/{content_type}.png"
    },
    "layout": {
      "id": 200,
      "control_type": "sliderex",
      "contextual_bindings": {
        "linked_config": "{content_type}_layout",
        "update_trigger": "focused({content_type}_item)"
      },
      "label": "Layout"
    }
  }
}
```

The listitem expands to one row per content type. The single `layout` slider gets bindings for each. The user scrolls the list, the slider follows.

### Step 3: Expressions

```json
{
  "mapping": "content_types",
  "expressions": {
    "{window}_views_visible_{item}": {
      "items": ["list", "showcase", "strip", "grid"],
      "rules": [
        { "condition": "xml(Skin.String({content_type}_layout,{item}))",
          "type": "append",
          "value": "Container.Content({content_type})" }
      ],
      "fallback_key": "window",
      "fallbacks": {
        "*": { "target_item": "list", "value": "invert()" }
      }
    }
  }
}
```

Output: `videos_views_visible_showcase` becomes `Container.Content(movies) | Container.Content(tvshows)` (assuming those content types are set to showcase). Reference in your skin XML with `$EXP[videos_views_visible_showcase]`.

Everything is stored as Kodi skin strings. No runtime state.

---

## 3. Widgets — dynamic, runtime-state-driven

**Builders:** Configs → Controls → Includes (+ runtime state).
**Mapping:** `widgets` (custom, flat list with `config_fields` and `metadata`).

Multi-instance, user-managed widget slots. The user adds, deletes, reorders, and configures slots through a Dynamic Editor window. Each slot has a preset (built-in or custom), a layout, and an art type. The builder generates one `<include>` call per slot.

### The mapping

A few representative presets from `extras/templates/mappings/mappings_widgets.json`:

```json
{
  "widgets": {
    "mode": "dynamic",
    "items": ["next_up", "latest_movies", "random_movies", "favourites", "custom"],
    "placeholders": { "key": "widget_preset" },
    "default_order": ["random_movies", "latest_movies", "random_tvshows", "latest_tvshows"],
    "config_fields": {
      "global": {
        "layout": "widget_{widget_preset}_layout",
        "art": "widget_{widget_preset}_art"
      },
      "custom": {
        "sortby": "widget_custom_sortby",
        "sortorder": "widget_custom_sortorder",
        "limit": "widget_custom_limit"
      }
    },
    "metadata": {
      "next_up": {
        "label": "$LOCALIZE[31201]",
        "target": "videos",
        "content": "plugin://script.copacetic.helper/?info=next_up",
        "limit": "20",
        "parent": "tvshows"
      },
      "latest_movies": {
        "label": "$LOCALIZE[31202]",
        "target": "videos",
        "content": "videodb://movies/titles/",
        "xsp": {
          "rules": { "and": [
            { "field": "playcount", "operator": "lessthan", "value": ["1"] }
          ]},
          "type": "movies"
        },
        "sortby": "dateadded",
        "sortorder": "descending",
        "limit": "20",
        "parent": "movies"
      },
      "custom": {
        "label": "$LOCALIZE[31210]",
        "content": "",
        "use_custom_click": "true"
      }
    }
  }
}
```

Built-in presets carry a complete picture of the widget — label, content path, sort order, target, optional smart-playlist filter, the parent menu item. The `custom` preset is mostly empty; the user fills it through the editor.

`parent` references an item in another mapping (here, `movies` and `tvshows` from the `mainmenu` mapping). At initialisation, parent values get replaced with the corresponding entry's `runtime_id`. This is what links widgets to menu items and keeps them attached across reorders. See [Runtime State & Dynamic Editor](09-runtime-state.md#parent-references).

### Step 1: Configs

```json
{
  "mapping": "widgets",
  "configs": {
    "widget_{widget_preset}_layout": {
      "mode": "dynamic",
      "items": {
        "list": "$LOCALIZE[535]",
        "showcase": "$LOCALIZE[31002]",
        "strip": "$LOCALIZE[31003]",
        "grid": "$LOCALIZE[31004]"
      },
      "defaults": { "*": "strip" }
    },
    "widget_{widget_preset}_art": {
      "mode": "dynamic",
      "items": {
        "fanart": "$LOCALIZE[31007]",
        "poster": "$LOCALIZE[31006]",
        "square": "$LOCALIZE[31008]"
      },
      "filter_mode": "exclude",
      "rules": [
        { "condition": "In({widget_preset}, [latest_albums, recent_albums, random_albums, liked_songs, favourites])",
          "value": ["fanart", "poster"] }
      ],
      "defaults": { "next_up": "fanart", "*": "poster" }
    }
  }
}
```

`mode: "dynamic"` means values go to runtime state, not skin strings. The Dynamic Editor resolves these templates per widget preset when the widgetsettings window opens.

### Step 2: Controls

```json
{
  "mapping": "widgets",
  "controls": {
    "widget_{index}": {
      "mode": "dynamic",
      "control_type": "listitem",
      "label": "{label}",
      "description": "Select widget to configure."
    },
    "widget_preset": {
      "mode": "dynamic",
      "role": "item_picker",
      "id": 200,
      "control_type": "button",
      "onclick": {
        "type": "select",
        "heading": "Choose widget",
        "then": { "custom": "widget_content" }
      },
      "label": "Change type""
    },
    "widget_layout": {
      "mode": "dynamic",
      "field": "layout",
      "id": 201,
      "control_type": "sliderex",
      "label": "Layout"
    },
    "widget_content": {
      "mode": "dynamic",
      "field": "content",
      "id": 203,
      "control_type": "button",
      "visible": "In({widget_preset}, [custom])",
      "onclick": {
        "type": "browse_content",
        "heading": "Select content path",
        "mode": "widget",
        "sibling_fields": { "label": "widget_label" }
      }
    },
    "widget_label": {
      "mode": "dynamic",
      "field": "label",
      "id": 204,
      "control_type": "edit",
      "visible": "In({widget_preset}, [custom])",
      "label": "Widget name"
    }
  }
}
```

The `then` map on the picker means picking `custom` while adding a new entry runs the `widget_content` browse dialog as a chained step before the entry is inserted. A new custom widget never lands with an empty content path. See [Controls Builder](06-controls.md).

### Step 3: Runtime state

Initialised on first install from `default_order`. From there, the user adds, deletes, reorders, and edits slots through the Dynamic Editor — all writes happen in real time. See [Runtime State & Dynamic Editor](09-runtime-state.md).

### Step 4: Includes

A single dynamic template assembles the widget list from runtime state:

```xml
<template>
  <mode>dynamic</mode>
  <index start="3200" />
  <include name="widget_containers">
    <include content="lst_{layout}">
      <param name="id" value="{index}" />
      <param name="visible" value="..." />
      <param name="target" value="{target}" />
      <param name="sortby" value="{sortby}" />
      <param name="content" value="{content}{xsp}" />
      <param name="label" value="{label}" />
    </include>
  </include>
</template>
```

The outer `<include name="widget_containers">` is fixed, so it appears once. The inner `<include content="lst_{layout}">` multiplies — one call per runtime entry, each routing to the matching skin-defined layout include (`lst_strip`, `lst_grid`, `lst_showcase`). On editor close, the includes builder re-runs and the skin reloads. See [Includes Builder](07-includes.md).