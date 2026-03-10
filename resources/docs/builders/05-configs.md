# Configs Builder

The configs builder determines which options are valid for each setting in your skin. It takes a master list of items, applies filter rules to exclude (or include) options based on conditions, and resolves defaults. The output is `configs.json`, which the Dynamic Editor and other builders reference to know what choices to present.

---

## When to use it

Use the configs builder whenever you have settings where the available options vary depending on context. For example, a "layout" setting might offer `fanart`, `poster`, and `square` in general — but for albums, `fanart` and `poster` should be excluded because albums only look right in the square layout.

---

## Input format

Config inputs are JSON files placed in `extras/builders/configs/`. Each file declares a mapping and a `configs` object:

```json
{
  "mapping": "content_types",
  "configs": {
    "{content_type}_layout": {
      "mode": "static",
      "items": ["fanart", "poster", "square"],
      "filter_mode": "exclude",
      "rules": [
        {
          "condition": "In({content_type}, [addons, favourites, albums, songs, images])",
          "value": ["fanart", "poster"]
        }
      ],
      "default_key": "window",
      "defaults": {
        "videos": "fanart",
        "*": "square"
      }
    }
  }
}
```

### Template fields

| Field | Type | Default | Description |
|---|---|---|---|
| `items` | list | `[]` | Master list of all possible values |
| `mode` | string | `"static"` | `"static"` (skin strings) or `"dynamic"` (runtime state) |
| `filter_mode` | string | `"exclude"` | `"exclude"` removes matched items; `"include"` keeps only matched items |
| `rules` | list | `[]` | Filter rules with conditions and value lists |
| `default_key` | string | — | Placeholder name to look up in `defaults` |
| `defaults` | object | — | Per-group default values, with `"*"` as wildcard |

---

## Filter rules

Each rule in the `rules` array has:

| Field | Type | Description |
|---|---|---|
| `condition` | string | A condition evaluated by the [Rule Engine](08-rule-engine.md). Supports `{placeholder}` substitution. |
| `value` | list | Items to add to the excluded (or included) set when the condition is true |

### How filtering works

1. The builder evaluates every rule's condition for each substitution in the current group.
2. Any rule whose condition is true contributes its `value` list to the "excluded" set.
3. The final items list is filtered:
   - **`filter_mode: "exclude"`** (default) — keep items that are NOT in the excluded set
   - **`filter_mode: "include"`** — keep items that ARE in the excluded set

This gives you two ways to think about it: "start with everything and remove what doesn't apply" (exclude mode) or "start with nothing and add what does apply" (include mode).

---

## Example walkthrough

Given this config template with the `content_types` mapping:

```json
"{content_type}_layout": {
  "items": ["fanart", "poster", "square"],
  "filter_mode": "exclude",
  "rules": [
    {
      "condition": "In({content_type}, [addons, favourites, albums, songs, images])",
      "value": ["fanart", "poster"]
    },
    {
      "condition": "In({content_type}, [episodes, videos, musicvideos])",
      "value": ["poster", "square"]
    }
  ]
}
```

For `{content_type} = "albums"`:
- Rule 1 condition: `In({content_type}, [addons, favourites, albums, songs, images])` → **true**
- Excluded set: `{"fanart", "poster"}`
- Result: `["square"]` — albums can only use the square layout

For `{content_type} = "movies"`:
- Rule 1 condition: `In({content_type}, [addons, favourites, albums, songs, images])` → **false**
- Rule 2 condition: `In({content_type}, [episodes, videos, musicvideos])` → **false**
- Excluded set: `{}` (empty)
- Result: `["fanart", "poster", "square"]` — movies get all three options

For `{content_type} = "episodes"`:
- Rule 1: **false**
- Rule 2: `In({content_type}, [episodes, videos, musicvideos])` → **true**
- Excluded set: `{"poster", "square"}`
- Result: `["fanart"]` — episodes can only use fanart layout

---

## Defaults

The defaults system assigns a preferred value to each expanded config. It uses two fields:

- **`default_key`** — Which placeholder to use as the lookup key into the `defaults` dict
- **`defaults`** — A dict mapping group values to default item values, with `"*"` as a catch-all

```json
"default_key": "window",
"defaults": {
  "videos": "fanart",
  "*": "square"
}
```

For a config expanded under the `videos` window group, the default is `"fanart"`. For all other windows, the default is `"square"`.

### Default validation

The builder validates that each resolved default is actually in the allowed items list for that config. If the default isn't allowed (because rules filtered it out), the builder falls back to the first remaining item:

```
ConfigsBuilder: [Default override] albums_layout default not in allowed items; using 'square'
```

If only one item remains after filtering, that item becomes both the only option and the default — the setting is effectively locked.

---

## Static vs dynamic mode

The `mode` field determines how the setting value is stored:

- **`"static"`** — The value is stored as a Kodi skin string. At build time, `BuildElements.initialize_skinstrings()` sets any unset skin strings to their default values. The Dynamic Editor reads and writes these using `Skin.SetString()` and `Skin.String()`.

- **`"dynamic"`** — The value is stored in `runtime_state.json` as a field on each entry. The Dynamic Editor reads and writes these through the `RuntimeStateManager`. This is used when the same setting needs different values per instance (e.g. each widget slot has its own view and layout).

---

## Output format

The configs builder writes `configs.json`. Each entry is keyed by the fully expanded setting name:

```json
{
  "movies_layout": {
    "items": ["fanart", "poster", "square"],
    "mode": "static",
    "default": "fanart"
  },
  "albums_layout": {
    "items": ["square"],
    "mode": "static",
    "default": "square"
  },
  "songs_view": {
    "items": ["list"],
    "mode": "static",
    "default": "list"
  },
  "widget_next_up_view": {
    "items": ["list", "showcase", "strip", "grid"],
    "mode": "dynamic",
    "default": "strip"
  }
}
```

This file is consumed by:
- The **Dynamic Editor** — to populate sliders and validate user selections
- The **RuntimeStateManager** — to resolve default values when initialising runtime state
- The **expressions builder** — indirectly, through skin strings that configs initialises

---

## Next

- [Controls Builder](06-controls.md) — How UI control definitions are expanded
