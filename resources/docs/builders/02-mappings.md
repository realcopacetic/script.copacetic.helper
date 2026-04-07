# Mappings

A mapping is the loop definition that drives every builder. It declares what to iterate over, how to name the placeholders, and optionally attaches metadata and config field templates. Every builder input file references a mapping by name, and the builder uses that mapping's structure to generate substitutions.

---

## Anatomy of a mapping

A mapping is a JSON object with the following fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `items` | list or dict | Yes | The values to loop over |
| `placeholders` | object | Yes | Names for substitution tokens |
| `default_order` | list | No | Initial ordering for runtime state entries |
| `config_fields` | object | No | Templates that link runtime fields to config keys |
| `metadata` | object | No | Per-item key-value data injected into substitutions |

---

## `items` — what to loop over

The `items` field can be either a flat list or a dict of lists.

**Flat list** — each item becomes a single substitution using the `key` placeholder:

```json
{
  "items": ["next_up", "in_progress", "latest_movies", "latest_tvshows"],
  "placeholders": { "key": "widget_preset" }
}
```

This produces four substitutions:
- `{ "widget_preset": "next_up" }`
- `{ "widget_preset": "in_progress" }`
- `{ "widget_preset": "latest_movies" }`
- `{ "widget_preset": "latest_tvshows" }`

**Dict of lists** — creates a two-level loop using both `key` and `value` placeholders:

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

This produces a substitution for every inner value, with its parent key available too:
- `{ "window": "videos", "content_type": "movies" }`
- `{ "window": "videos", "content_type": "sets" }`
- `{ "window": "music", "content_type": "artists" }`
- ...and so on for all combinations.

---

## `placeholders` — naming the tokens

The `placeholders` object defines which substitution keys are available in your templates:

| Key | Description |
|---|---|
| `key` | The primary loop variable name. Always required. |
| `value` | The secondary loop variable name. Required when `items` is a dict. |

These names are what you use inside `{curly braces}` in template strings. For example, with `"placeholders": { "key": "window", "value": "content_type" }`, you can write template names like `{content_type}_view` or conditions like `In({content_type}, [songs])`.

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
      "content_path": "plugin://script.copacetic.helper/?info=next_up"
    },
    "in_progress": {
      "label": "$LOCALIZE[31200]",
      "target": "videos",
      "content_path": "plugin://script.copacetic.helper/?info=in_progress",
      "sortby": "lastplayed",
      "sortorder": "descending"
    },
    "custom": {
      "label": "$LOCALIZE[31210]",
      "content_path": "$PARAM[content]"
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
  "content_path": "plugin://script.copacetic.helper/?info=next_up"
}
```

All of these are available in template strings: `{label}`, `{target}`, `{content_path}`, etc.

Metadata is particularly powerful for the includes builder, where it enables a single XML template to produce different output for each item — different content paths, sort orders, art types, and so on.

### XSP metadata

The includes builder has special handling for XSP (smart playlist) metadata. As a convenience, you write the smart playlist filter as a nested JSON dictionary in your metadata, and the builder automatically encodes it into a URL query string that Kodi can parse.

In the mapping metadata, you write it as structured JSON:

```json
"latest_movies": {
  "label": "$LOCALIZE[31202]",
  "content_path": "videodb://movies/titles/",
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

Before template expansion, the builder JSON-encodes and URL-encodes the `xsp` dict into a single string:

```
?xsp=%7B%22group%22%3A%7B%22mixed%22%3A%22false%22%2C%22type%22%3A%22none%22%7D%2C%22rules%22%3A...%7D
```

Any `$ESCINFO[]` references within the XSP values are preserved unquoted so Kodi can resolve them at runtime. The result is stored back into the metadata as a plain string, so when an include template uses `{content_path}{xsp}`, it produces a complete widget path with an inline smart playlist filter — e.g. only unwatched movies, sorted by date added.

---

## `config_fields` — linking runtime fields to configs

The `config_fields` object is used by mappings that support dynamic (runtime state) mode. It defines a template for resolving the config key associated with each field in a runtime state entry.

```json
{
  "config_fields": {
    "view": "widget_{widget_preset}_view",
    "layout": "widget_{widget_preset}_layout"
  }
}
```

When a runtime state entry has `"mapping_item": "next_up"`, the `view` field's config key resolves to `widget_next_up_view`. This is how the Dynamic Editor knows which config to look up to determine the allowed values for that field.

The `{widget_preset}` placeholder here refers to the mapping's `key` placeholder name, which at runtime is substituted with the entry's `mapping_item` value.

---

## `default_order` — initial runtime state

When `runtime_state.json` is first created (on skin install or build), the `default_order` list determines which items appear and in what order:

```json
{
  "default_order": ["next_up", "in_progress", "latest_movies", "latest_tvshows"]
}
```

Each item in the list gets a runtime state entry with a UUID, the `mapping_item` name, and default values for each `config_field` (resolved from `configs.json`).

The UUID is a unique identifier assigned to each entry. It allows the same `mapping_item` to appear multiple times in the list — for example, a user could add several "custom" widget slots, each with a different content path and label. The UUID is what distinguishes them, so that reordering, deleting, or editing one doesn't affect the others.

---

## Built-in vs custom mappings

### Built-in mapping: `content_types`

The addon ships with one built-in mapping defined in `builder_config.py`:

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

This is a dict-of-lists mapping that models the relationship between Kodi windows and their content types. It drives the views system — generating per-content-type configs, controls, and expressions.

### Custom mappings

Skinners can define additional mappings by placing JSON files in `extras/builders/mappings/`. Each file is a top-level object where keys are mapping names and values are mapping definitions:

```json
{
  "widgets": {
    "items": ["next_up", "in_progress", "latest_movies", "..."],
    "placeholders": { "key": "widget_preset" },
    "default_order": ["next_up", "in_progress", "latest_movies", "latest_tvshows"],
    "config_fields": {
      "view": "widget_{widget_preset}_view",
      "layout": "widget_{widget_preset}_layout"
    },
    "metadata": { "..." }
  }
}
```

Custom mappings are merged with built-in mappings at startup. If a custom mapping has the same name as a built-in one, the custom version takes precedence.

---

## How mappings connect to builder inputs

Every builder input file (JSON or XML) declares which mapping it uses via a `"mapping"` field at the top level:

```json
{
  "mapping": "widgets",
  "configs": { "..." },
  "controls": { "..." }
}
```

The builder system groups all inputs by mapping name, then processes each group using the corresponding mapping definition. This means you can spread a mapping's builder inputs across multiple files — configs in one, expressions in another — and they'll all use the same loop values and placeholders.

If a builder input uses `"mapping": "none"`, or omits the `"mapping"` key entirely, it runs without any mapping loop values. This is useful for templates that only use an `index` range (like variables that just need to expand over a numeric range).

---

## Next

- [Variables Builder](03-variables.md) — See mappings in action with the simplest builder
