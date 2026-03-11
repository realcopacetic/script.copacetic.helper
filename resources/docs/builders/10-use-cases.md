# Chaining Builders — Use Cases

The real power of the builder system emerges when you chain multiple builders together. Each builder produces output that feeds into the next, creating complete features from a small set of input definitions.

The examples below are just that — examples. They show how Copacetic 2 uses the system, but they're not the only way to do things. You don't have to use skin strings for views, or runtime state for widgets, or any particular combination of builders. The system is general-purpose — use whichever pieces make sense for your skin.

---

## 1. Standalone variables

**Builders used:** Variables only

**Mapping:** `"none"` (no mapping loop)

This is the simplest use case. You just want to eliminate repetitive XML by generating many similar `<variable>` elements from a template with an index range.

### Input

A single JSON file in `extras/builders/variables/`:

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

### What happens

1. The variables builder expands the index range (-3 to 6).
2. For each index, it formats the template name and all condition/value pairs.
3. Output: 10 `<variable>` elements in `script-copacetic-helper_variables.xml`.

### No other builders needed

There's no configs, controls, expressions, or runtime state involved. The variables builder runs at `build` context and writes its XML directly.

---

## 2. Views — static, skin-string-driven

**Builders used:** Configs → Controls → Expressions

**Mapping:** `content_types` (built-in, dict-of-lists)

Views are the canonical example of chaining builders with static (skin string) storage. The user configures per-content-type settings (view, layout, size, clearlogo, etc.) through a Dynamic Editor window. The system generates the correct expressions so that the right view is activated for whatever content type is currently displayed.

### The mapping

The built-in `content_types` mapping defines windows as keys and content types as values:

```json
{
  "content_types": {
    "items": {
      "videos": ["movies", "sets", "tvshows", "seasons", "episodes", "videos", "musicvideos"],
      "music": ["artists", "albums", "songs"],
      "pictures": ["images"],
      "addons": ["addons"],
      "favourites": ["favourites"]
    },
    "placeholders": { "key": "window", "value": "content_type" }
  }
}
```

### Step 1: Configs

Input (`extras/builders/configs/configs-views.json`):

```json
{
  "mapping": "content_types",
  "configs": {
    "{content_type}_view": {
      "mode": "static",
      "items": ["list", "showcase", "strip", "grid"],
      "filter_mode": "exclude",
      "rules": [
        {
          "condition": "In({content_type}, [songs])",
          "value": ["showcase", "strip", "grid"]
        }
      ],
      "default_key": "window",
      "defaults": { "*": "list" }
    }
  }
}
```

Output in `configs.json`:
- `movies_view` → items: `[list, showcase, strip, grid]`, default: `list`
- `songs_view` → items: `[list]`, default: `list` (other views excluded)
- ...one entry per content type

### Step 2: Controls

Input (`extras/builders/controls/controls-views.json`):

```json
{
  "mapping": "content_types",
  "controls": {
    "{content_type}_item": {
      "control_type": "listitem",
      "window": ["viewsettings"],
      "label": "{content_type}",
      "icon": "icons/{content_type}.png"
    },
    "view": {
      "id": 200,
      "control_type": "sliderex",
      "window": ["viewsettings"],
      "contextual_bindings": {
        "linked_config": "{content_type}_view",
        "update_trigger": "focused({content_type}_item)"
      },
      "label": "View"
    }
  }
}
```

Output in `controls.json`:
- 15+ listitem entries (one per content type): `movies_item`, `tvshows_item`, `albums_item`, ...
- One `view` control with expanded `contextual_bindings` array linking to each content type's config

### Step 3: Expressions

Input (`extras/builders/expressions/expressions-views.json`):

```json
{
  "mapping": "content_types",
  "expressions": {
    "{window}_views_include_{item}": {
      "items": ["list", "showcase", "strip", "grid"],
      "rules": [
        {
          "condition": "xml(Skin.String({content_type}_view,{item}))",
          "type": "assign",
          "value": "true"
        }
      ],
      "fallback_key": "window",
      "fallbacks": {
        "*": { "target_item": "list", "value": "true" }
      }
    },
    "{window}_views_visible_{item}": {
      "items": ["list", "showcase", "strip", "grid"],
      "rules": [
        {
          "condition": "xml(Skin.String({content_type}_view,{item}))",
          "type": "append",
          "value": "Container.Content({content_type})"
        }
      ],
      "fallback_key": "window",
      "fallbacks": {
        "*": { "target_item": "list", "value": "invert()" }
      }
    }
  }
}
```

Output in `script-copacetic-helper_expressions.xml`:
- `videos_views_include_list` → `true` (fallback, since no content type explicitly selected list)
- `videos_views_visible_showcase` → `Container.Content(movies)` (if movies has showcase set)
- `videos_views_visible_list` → `![Container.Content(movies)]` (inverted fallback)

### How it all connects

1. **Configs** determine what options exist per content type and initialise skin strings with defaults.
2. **Controls** create the Dynamic Editor UI where the user changes these skin strings.
3. **Expressions** read the skin strings at build time and generate boolean conditions.
4. **Skin XML** references expressions via `$EXP[videos_views_include_list]` to control which view include is active.

No runtime state is involved — everything is stored as Kodi skin strings.

---

## 3. Widgets — dynamic, runtime-state-driven

**Builders used:** Configs → Controls → Includes (+ runtime state)

**Mapping:** `widgets` (custom, flat list with `config_fields` and `metadata`)

Widgets are the most complex use case. The user can add, remove, reorder, and individually configure widget slots. Each slot has a preset (determining the content source), a view, and a layout. The system generates personalised `<include>` elements from the user's runtime state.

### The mapping

Custom mapping in `extras/builders/custom_mappings/mapping_widgets.json`:

```json
{
  "widgets": {
    "items": ["next_up", "in_progress", "latest_movies", "custom", "..."],
    "placeholders": { "key": "widget_preset" },
    "default_order": ["next_up", "in_progress", "latest_movies", "latest_tvshows"],
    "config_fields": {
      "view": "widget_{widget_preset}_view",
      "layout": "widget_{widget_preset}_layout"
    },
    "metadata": {
      "next_up": {
        "label": "$LOCALIZE[31201]",
        "target": "videos",
        "content_path": "plugin://script.copacetic.helper/?info=next_up"
      },
      "latest_movies": {
        "label": "$LOCALIZE[31202]",
        "content_path": "videodb://movies/titles/",
        "xsp": { "...smart playlist filter..." },
        "sortby": "dateadded",
        "sortorder": "descending"
      },
      "custom": {
        "label": "$LOCALIZE[31210]",
        "content_path": "$PARAM[content]"
      }
    }
  }
}
```

### Step 1: Configs

Input defines per-preset option filtering:

```json
{
  "mapping": "widgets",
  "configs": {
    "widget_{widget_preset}_view": {
      "mode": "dynamic",
      "items": ["list", "showcase", "strip", "grid"],
      "default_key": "widget_preset",
      "defaults": {
        "next_up": "strip",
        "in_progress": "strip",
        "*": "grid"
      }
    },
    "widget_{widget_preset}_layout": {
      "mode": "dynamic",
      "items": ["fanart", "poster", "square"],
      "rules": [
        {
          "condition": "In({widget_preset}, [latest_albums, random_albums, liked_songs, favourites])",
          "value": ["fanart", "poster"]
        }
      ],
      "default_key": "widget_preset",
      "defaults": {
        "next_up": "fanart",
        "*": "poster"
      }
    }
  }
}
```

Output: `configs.json` entries like `widget_next_up_view`, `widget_latest_albums_layout`, etc. — each with filtered items and resolved defaults. Mode is `"dynamic"` so values go to runtime state, not skin strings.

### Step 2: Controls

Input defines the Dynamic Editor UI:

```json
{
  "mapping": "widgets",
  "controls": {
    "widget_{index}": {
      "mode": "dynamic",
      "control_type": "listitem",
      "window": ["widgetsettings"],
      "label": "{label}",
      "description": "Select widget to configure."
    },
    "widget_preset": {
      "mode": "dynamic",
      "role": "item_picker",
      "id": 200,
      "control_type": "button",
      "window": ["widgetsettings"],
      "onclick": { "type": "select", "heading": "Choose widget" },
      "label": "Choose type"
    },
    "widget_view": {
      "mode": "dynamic",
      "field": "view",
      "id": 201,
      "control_type": "sliderex",
      "window": ["widgetsettings"],
      "label": "View"
    },
    "widget_content_path": {
      "mode": "dynamic",
      "field": "content_path",
      "id": 203,
      "control_type": "button",
      "window": ["widgetsettings"],
      "visible": "In({widget_preset}, [custom])",
      "onclick": {
        "type": "browse_content",
        "heading": "Select content path",
        "sibling_fields": { "label": "widget_label" }
      }
    }
  }
}
```

Output: `controls.json` with dynamic controls. The editor reads runtime state to populate the left list and uses `config_fields` to resolve which config applies to each field.

### Step 3: Runtime state

When the user opens the editor, they see their widget slots in the left list. They can:
- Change a widget's preset (e.g. "Next Up" → "Random Movies")
- Adjust view and layout via sliders
- For "Custom" presets, browse for a content path and set a label
- Add new slots, delete existing ones, reorder them

All changes are written to `runtime_state.json` in real time.

### Step 4: Includes

XML templates in `extras/builders/includes/` work in two stages. A static template expands per-preset definitions with metadata baked in, while a dynamic template assembles the user's widget list from runtime state:

```xml
<!-- Template 1: one named definition per preset (static) -->
<template>
  <include name="widget_{widget_preset}">
    <include content="widget_template">
      <param name="widget_header" value="{label}" />
      <param name="id" value="$PARAM[id]" />
      <param name="target" value="{target}" />
      <param name="sortby" value="{sortby}" />
      <param name="content" value="{content_path}{xsp}" />
      <param name="view" value="$PARAM[view]" />
      <param name="layout" value="$PARAM[layout]" />
    </include>
  </include>
</template>

<!-- Template 2: the widget list from runtime state (dynamic) -->
<template>
  <mode>dynamic</mode>
  <index start="3200" />
  <include name="widgets">
    <include content="widget_{widget_preset}">
      <param name="id" value="{index}" />
      <param name="content" value="{runtime|content_path}" />
      <param name="view" value="{view}" />
      <param name="layout" value="{layout}" />
    </include>
  </include>
</template>
```

On close, the builder generates a single `<include name="widgets">` containing one `<include content="...">` call per runtime state entry, referencing the preset definitions from Template 1. The skin reloads and the widgets update. See [Includes Builder](07-includes.md) for a full walkthrough with output.

### How it all connects

1. **Configs** define what options each preset supports and provide defaults.
2. **Controls** create the Dynamic Editor UI for managing widget slots.
3. **Runtime state** stores the user's choices persistently.
4. **Includes** generate the actual skin XML from runtime state + metadata.
5. **On close**, includes are rebuilt and the skin reloads.
