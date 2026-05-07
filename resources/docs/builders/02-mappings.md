# Mappings
 
A mapping is the loop definition that drives every builder. It declares what to iterate over, how to name the placeholders, and optionally attaches metadata and config field templates. Every builder input file references a mapping by name.
 
> Reference doc — fields and behaviours. If you arrived here cold and want a worked example, start with the [Quickstart](00-quickstart.md) or [Use case 3: Widgets](10-use-cases.md#3-widgets--dynamic-runtime-state-driven).
 
---

## Built-in vs custom mappings

There's one built-in mapping (`content_types`) provided by the addon. Custom mappings are defined in `extras/builders/mappings/`. Custom mappings with the same name as a built-in override it.

### Built-in: `content_types`

This is the dict-of-lists mapping that models Kodi's content windows. It drives the views system — generating per-content-type configs, controls, and expressions.

```json
{
  "content_types": {
    "items": {
      "addons": ["addons"],
      "favourites": ["favourites"],
      "music": ["artists", "albums", "songs"],
      "pictures": ["images"],
      "videos": ["movies", "sets", "tvshows", "seasons", "episodes", "videos", "musicvideos"]
    },
    "placeholders": { "key": "window", "value": "content_type" }
  }
}
```

You don't define this; reference it with `"mapping": "content_types"` in any builder input.

### Custom mappings

Place JSON files in `extras/builders/mappings/`. Each file is a top-level object where keys are mapping names and values are mapping definitions:

```json
{
  "widgets": {
    "items": ["next_up", "in_progress", "latest_movies", "..."],
    "placeholders": { "key": "widget_preset" },
    "default_order": ["next_up", "in_progress", "latest_movies", "latest_tvshows"],
    "config_fields": {
      "layout": "widget_{widget_preset}_layout",
      "art": "widget_{widget_preset}_art"
    },
    "metadata": { "..." }
  }
}
```

The `widgets`, `mainmenu`, and `shutdownmenu` mappings in Copacetic are all custom mappings defined this way.

---

## Anatomy of a mapping

| Field | Type | Required | Description |
|---|---|---|---|
| `items` | list or dict | Yes | The values to loop over |
| `placeholders` | object | Yes | Names for substitution tokens |
| `mode` | string | No | `"dynamic"` if this mapping should be backed by `runtime_state.json` |
| `default_order` | list | No | Initial ordering for runtime state entries |
| `config_fields` | object | No | Templates that link runtime fields to config keys |
| `metadata` | object | No | Per-item key-value data injected into substitutions |

---

## `items` — what to loop over

**Flat list** — each item becomes a single substitution using the `key` placeholder:

```json
{
  "items": ["next_up", "in_progress", "latest_movies", "latest_tvshows"],
  "placeholders": { "key": "widget_preset" }
}
```

Produces four substitutions:
- `{ "widget_preset": "next_up" }`
- `{ "widget_preset": "in_progress" }`
- `{ "widget_preset": "latest_movies" }`
- `{ "widget_preset": "latest_tvshows" }`

**Dict of lists** — creates a two-level loop using both `key` and `value` placeholders:

```json
{
  "items": {
    "videos": ["movies", "sets", "tvshows"],
    "music": ["artists", "albums", "songs"]
  },
  "placeholders": { "key": "window", "value": "content_type" }
}
```

Produces a substitution for every inner value, with its parent key available too:
- `{ "window": "videos", "content_type": "movies" }`
- `{ "window": "videos", "content_type": "sets" }`
- `{ "window": "music", "content_type": "artists" }`
- ...and so on.

---

## `placeholders` — naming the tokens

| Key | Description |
|---|---|
| `key` | The primary loop variable name. Always required. |
| `value` | The secondary loop variable name. Required when `items` is a dict. |

These names are what you use inside `{curly braces}` in template strings. With `"placeholders": { "key": "window", "value": "content_type" }`, you can write template names like `{content_type}_layout` or conditions like `In({content_type}, [songs])`.

In addition to the names you declare here, every substitution also includes `{count}`, `{is_first}`, and `{is_last}` for loop-position-aware templates. See [Builder System Overview](01-overview.md#auto-injected-placeholders).

---

## `metadata` — per-item data injection

The `metadata` object attaches arbitrary key-value pairs to specific item names. When a substitution is generated for that item, all its metadata fields are merged into the substitution dictionary, making them available as additional `{placeholder}` tokens.

```json
{
  "items": ["next_up", "in_progress", "custom"],
  "placeholders": { "key": "widget_preset" },
  "metadata": {
    "next_up": {
      "label": "$LOCALIZE[31201]",
      "target": "videos",
      "content": "plugin://script.copacetic.helper/?info=next_up",
      "limit": "20",
      "parent": "tvshows"
    },
    "in_progress": {
      "label": "$LOCALIZE[31200]",
      "target": "videos",
      "content": "plugin://script.copacetic.helper/?info=in_progress",
      "sortby": "lastplayed",
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
```

When the builder processes `next_up`, the substitution dictionary becomes:

```
{
  "widget_preset": "next_up",
  "label": "$LOCALIZE[31201]",
  "target": "videos",
  "content": "plugin://script.copacetic.helper/?info=next_up",
  "limit": "20",
  "parent": "tvshows"
}
```

All of these are available in template strings: `{label}`, `{target}`, `{content}`, etc.

Metadata is particularly powerful for the includes builder, where it lets a single XML template produce different output for each item — different content paths, sort orders, art types, and so on.

The `custom` preset is intentionally sparse: empty `content`, no `target`, no sort order. The user fills these in through the Dynamic Editor; the empty fields remain on the entry as overridable slots.

### XSP metadata

The includes builder has special handling for XSP (smart playlist) metadata. Write the smart playlist as a structured dict; the builder URL-encodes it to a query string at startup.

```json
"latest_movies": {
  "label": "$LOCALIZE[31202]",
  "content": "videodb://movies/titles/",
  "xsp": {
    "group": { "mixed": "false", "type": "none" },
    "rules": {
      "and": [
        { "field": "playcount", "operator": "lessthan", "value": ["1"] }
      ]
    },
    "type": "movies"
  },
  "sortby": "dateadded",
  "sortorder": "descending"
}
```

Becomes:

```
?xsp=%7B%22group%22%3A%7B%22mixed%22%3A%22false%22%2C%22type%22%3A%22none%22%7D%2C...%7D
```

`$ESCINFO[]` references inside the XSP are kept unquoted so Kodi resolves them at runtime. The encoded result is exposed as `{xsp}` — concatenate with the content path: `<param name="content" value="{content}{xsp}" />`.

---

## `config_fields` — linking runtime fields to configs

For mappings with `mode: "dynamic"`, this object defines a template for resolving the config key associated with each runtime field.

```json
{
  "config_fields": {
    "layout": "widget_{widget_preset}_layout",
    "art": "widget_{widget_preset}_art"
  }
}
```

When a runtime entry has `"mapping_item": "next_up"`, the `layout` field's config key resolves to `widget_next_up_layout`. This is how the Dynamic Editor knows which config to look up for the allowed values.

The `{widget_preset}` placeholder here is the mapping's `key` placeholder name, substituted with the entry's `mapping_item` at runtime.

---

## `default_order` — initial runtime state

When `runtime_state.json` is first created, the `default_order` list determines which items appear and in what order:

```json
{
  "default_order": ["random_movies", "latest_movies", "random_tvshows", "latest_tvshows"]
}
```

Each item gets a runtime entry with a fresh UUID, the `mapping_item` name, all string-valued metadata for that item, and resolved default values for each `config_field`. See [Runtime State & Dynamic Editor](09-runtime-state.md) for the entry shape.

If `default_order` isn't set, the full `items` list is used.

---

## How mappings connect to builder inputs

Every builder input file (JSON or XML) declares which mapping it uses via a `"mapping"` field at the top level:

```json
{
  "mapping": "widgets",
  "configs": { "..." }
}
```

The system groups all inputs by mapping name and processes each group using the corresponding mapping definition. You can spread a mapping's builder inputs across multiple files — configs in one, expressions in another — and they'll all use the same loop values and placeholders.

If a builder input uses `"mapping": "none"`, or omits the key entirely, it runs without any mapping loop values. Useful for templates that only use an `index` range, like variables that just need to expand over a numeric range.

---

## Next

- [Variables Builder](03-variables.md) — See mappings in action with the simplest builder