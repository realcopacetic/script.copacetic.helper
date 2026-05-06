# Configs Builder

The configs builder determines which options are valid for each setting in your skin. It takes a master list of items, applies filter rules to exclude (or include) options based on conditions, and resolves defaults. The output is `configs.json`, which the Dynamic Editor and other builders reference to know what choices to present.

The classic case: a "layout" setting that offers `fanart`, `poster`, and `square` in general — but for albums, `fanart` and `poster` are excluded because albums only look right in `square`.

---

## Input format

JSON files placed in `extras/builders/configs/`. Each file declares a mapping and a `configs` object:

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

| Field | Type | Default | Description |
|---|---|---|---|
| `mapping` | string | — | Mapping name. Either built-in (`content_types`), a custom one in `extras/builders/mappings/`, or `"none"` — see [Mappings](02-mappings.md). |
| `items` | list | `[]` | Master list of all possible values |
| `mode` | string | `"static"` | `"dynamic"` to store values in `runtime_state.json`. Default is static, which stores values as Kodi skin strings — one per item in the mapping. |
| `filter_mode` | string | `"exclude"` | `"exclude"` removes matched items; `"include"` keeps only matched items |
| `rules` | list | `[]` | Filter rules with conditions and value lists |
| `default_key` | string | — | Placeholder name to look up in `defaults` |
| `defaults` | object | — | Per-group default values, with `"*"` as wildcard |

---

## Filter rules

Each rule has two fields:

| Field | Description |
|---|---|
| `condition` | Evaluated by the [Rule Engine](08-rule-engine.md). Supports `{placeholder}` substitution. |
| `value` | Items to add to the matched set when the condition is true |

The builder evaluates every rule's condition for each substitution, collects matched items into a set, then filters the master `items` list:

- **`filter_mode: "exclude"`** (default) — keep items that are NOT in the matched set
- **`filter_mode: "include"`** — keep items that ARE in the matched set

Two ways to think about it: "start with everything and remove what doesn't apply" (exclude), or "start with nothing and add what does apply" (include).

---

## Example walkthrough

Given this template with the `content_types` mapping:

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
- Rule 1: `In(albums, [addons, favourites, albums, songs, images])` → **true**. Excluded set: `{fanart, poster}`.
- Result: `["square"]` — albums can only use the square layout.

For `{content_type} = "movies"`:
- Rule 1: false. Rule 2: false. Excluded set: empty.
- Result: `["fanart", "poster", "square"]` — movies get all three options.

For `{content_type} = "episodes"`:
- Rule 1: false. Rule 2: `In(episodes, [episodes, videos, musicvideos])` → **true**. Excluded set: `{poster, square}`.
- Result: `["fanart"]` — episodes can only use fanart.

---

## Defaults

The `defaults` system assigns a preferred value to each expanded config:

| Field | Description |
|---|---|
| `default_key` | Which placeholder to use as the lookup key into `defaults` |
| `defaults` | Map of group values to default item values, with `"*"` as catch-all |

```json
"default_key": "window",
"defaults": {
  "videos": "fanart",
  "*": "square"
}
```

For configs expanded under the `videos` window group, the default is `"fanart"`. For all other windows, `"square"`.

If the resolved default isn't in the allowed items (because rules filtered it out), the builder falls back to the first remaining item and logs a notice. When only one item remains after filtering, it becomes both the only option and the default — the setting is effectively locked.

---

## Output format

The builder writes `configs.json`. Each entry is keyed by the fully expanded setting name:

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
  "songs_layout": {
    "items": ["square"],
    "mode": "static",
    "default": "square"
  },
  "widget_next_up_layout": {
    "items": ["list", "showcase", "strip", "grid"],
    "mode": "dynamic",
    "default": "strip"
  }
}
```

This file is consumed by:
- The **Dynamic Editor** — to populate sliders and validate user selections
- The **runtime state initialiser** — to resolve defaults when seeding `runtime_state.json`
- The **expressions builder** — indirectly, through skin strings that configs initialises at build time

---

## Next

- [Controls Builder](06-controls.md) — How UI control definitions are expanded