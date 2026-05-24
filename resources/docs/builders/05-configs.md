# Configs Builder

The configs builder determines which options are valid for each setting in your skin. It takes a master list of items, applies filter rules to exclude (or include) options based on conditions, and resolves defaults. Templates are resolved on demand by the Dynamic Editor when a settings window opens.

The classic case: a "layout" setting that offers `fanart`, `poster`, and `square` in general — but for albums, `fanart` and `poster` are excluded because albums only look right in `square`.

---

## Input format

JSON files placed in `extras/templates/configs/`. Each file declares a mapping and a `configs` object:

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
| `mapping` | string | — | Mapping name. Either built-in (`content_types`), a custom one in `extras/templates/mappings/`, or `"none"` — see [Mappings](02-mappings.md). |
| `items` | list or object | `[]` | Master list of all possible values. Use a list for raw values, or an object mapping value → display label — see [Items with display labels](#items-with-display-labels) below. |
| `mode` | string | `"static"` | `"dynamic"` to store values in `runtime_state.json`. Default is static, which stores values as Kodi skin strings — one per item in the mapping. |
| `filter_mode` | string | `"exclude"` | `"exclude"` removes matched items; `"include"` keeps only matched items |
| `rules` | list | `[]` | Filter rules with conditions and value lists |
| `default_key` | string | — | Placeholder name to look up in `defaults` |
| `defaults` | object | — | Per-group default values, with `"*"` as wildcard |

---

## Items with display labels

`items` accepts two shapes. Use whichever fits.

**List form** — when the raw values are already what you want shown to the user:

```json
"items": ["list", "showcase", "strip", "grid"]
```

**Object form** — when the stored value and the displayed label should differ. Keys are the values that get stored and matched against; values are the display labels (typically `$LOCALIZE[]` references for translation):

```json
"items": {
  "true": "$LOCALIZE[186]",
  "false": "$LOCALIZE[106]"
}
```

In production, every boolean toggle uses the object form so the user sees "Enabled / Disabled" rather than "true / false". Sortby fields use it to show "Date added" rather than `dateadded`. Layout and art configs typically use it for the same reason — `$LOCALIZE[535]` for "List", `$LOCALIZE[31002]` for "Showcase".

The configs builder normalises this internally: keys become the items array (and what filter rules match against — write rule `value`s with the keys, not the labels), and a parallel `labels` map is attached to the resolved entry. The Dynamic Editor uses `labels` to render slider, button, and select dialog text. If `items` is given as a list, no `labels` field is attached.

```json
"widget_{widget_preset}_layout": {
  "mode": "dynamic",
  "items": {
    "list": "$LOCALIZE[535]",
    "showcase": "$LOCALIZE[31002]",
    "strip": "$LOCALIZE[31003]",
    "grid": "$LOCALIZE[31004]"
  },
  "filter_mode": "exclude",
  "rules": [],
  "defaults": { "*": "strip" }
}
```

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

> [!IMPORTANT]
> `items` is the authoritative set of values a config can ever resolve to. Every value a rule's `value` adds, and every value a `defaults` entry names, must appear in `items`. The resolver filters `items` against the matched set — so a rule value that isn't in `items` is silently dropped, and a default that isn't in `items` falls back to the first surviving item. The resolved value is always a member of `items`: the default if it survives filtering, otherwise the first remaining item, otherwise `None`. An empty `items` always resolves to `None`, whatever the rules or defaults say.


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

## Per-loop variation requires a placeholder in the name

Configs are resolved on demand against the calling context. A template name with a placeholder produces one resolved entry per substitution value; a constant name produces one. The resolver tries the substituted name first (e.g. `widget_limit_showcase`), then falls back to the raw template name (e.g. `widget_{widget_preset}_layout`) — so both flavours work and a constant-named entry takes precedence when both exist.

If you want a config to vary across the loop, put the placeholder in the template name:

```json
"widget_{widget_preset}_layout": {
  "items": ["list", "showcase", "strip", "grid"],
  "rules": [
    { "condition": "In({widget_preset}, [latest_albums])", "value": ["list", "strip"] }
  ]
}
```

Twelve presets, twelve resolved cfg_keys, twelve cached resolutions. The `{widget_preset}` placeholder in `rules` resolves correctly because each cfg_key has its own sub.

A constant template name resolves to one cfg_key:

```json
"widget_custom_sortby": {
  "items": ["title", "dateadded", "lastplayed", "..."]
}
```

One name, one slot. Don't reference the loop placeholder in `rules` here — the rule would need to resolve differently per loop value, but only one resolution is reachable. The resolver raises `KeyError` to flag the mistake.

The same shape applies to `defaults`: per-key defaults work because they're looked up against the surviving sub at resolve time. With a constant template name only one sub survives, so use `"*"` and skip per-key overrides — anything else is silently a no-op for all but one loop value.

---

## Cross-field config dependencies

A config's allowed values or default sometimes depend on *another field's* resolved value, not just the loop key. Widget `limit` depends on the chosen `layout` — a showcase shows fewer items than a strip; `blk_tab_left` depends on both `layout` and `art`. Fields resolve in dependency order per entry, but only if you declare the dependency, and the only way to declare it is to put that field's placeholder in the config-key name.

> [!WARNING]
> If a config's `rules` reference a sibling field (`{layout}`, `{art}`, …), that field's placeholder **must** also appear in the config-key name. A constant-named config whose rules reference a sibling field resolves before the sibling is ready and raises `KeyError` — it does not silently fall back.

A placeholder in the name is what tells the resolver to wait. It resolves the field's name against the entry's other resolved fields first; while the name still contains an unresolved placeholder the field is deferred, and it's retried once that placeholder is available. A constant name has nothing to defer on, so it resolves immediately — before `layout`/`art` exist — and the rule conditions that reference them blow up.

Correct — every depended-on field is named:

```json
// in the mapping's config_fields
"tab_left": "tab_left_{layout}_{art}"
```

```json
// the config — defined once under the placeholdered key
"tab_left_{layout}_{art}": {
  "mode": "dynamic",
  "items": ["540", "600", "840"],
  "filter_mode": "include",
  "rules": [
    { "condition": "equals({layout}, strip) + equals({art}, square)", "value": ["540"] },
    { "condition": "equals({layout}, strip) + equals({art}, poster)", "value": ["600"] },
    { "condition": "true", "value": ["840"] }
  ]
}
```

The resolver formats `blk_tab_left_{layout}_{art}` against the entry, finds `layout` and `art` unresolved on the first pass, defers, and comes back once both are filled — so by the time the rules run, `{layout}` and `{art}` carry real values. Every placeholder in the name must be satisfied before the field resolves, so list all the fields you depend on.

Broken — the dependency lives only in the rules:

```json
"blk_tab_left": {
  "rules": [
    { "condition": "equals({layout}, strip)  equals({art}, square)", "value": ["540"] }
  ]
}
```

The name has nothing to defer on, so this resolves ahead of `layout`/`art` and raises `KeyError` on the rule condition.

This is the same placeholder-in-name mechanism as [Per-loop variation](#per-loop-variation-requires-a-placeholder-in-the-name), used for a different reason: there the placeholder is the loop key (`{widget_preset}`) and produces one config per loop value; here it's a sibling field (`{layout}`) and sequences resolution order.

---

## How the values are used

When the Dynamic Editor opens a settings window, it asks each control what config it's bound to (e.g. `widget_next_up_layout`), then resolves the template against the entry's current state: filter rules run, defaults are picked. Resolution is fresh each time — there's no cache — so configs that depend on the entry's other fields (e.g. `widget_limit_{layout}`) re-evaluate when the user changes those fields.

Static-mode configs additionally seed Kodi skin string defaults at build time — so on first install, every `<content_type>_layout` skin string already has a sensible default before the user opens any editor.

---

## Next

- [Controls Builder](06-controls.md) — How UI control definitions are expanded