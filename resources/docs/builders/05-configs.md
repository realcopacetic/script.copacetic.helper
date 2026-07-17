# Configs Builder

A config decides which values a setting is allowed to have: a master list, rules that trim it, and a default. The editor reads configs when a settings window opens.

The classic case: an "art" setting offering fanart, poster, and square — except albums only look right in square, so the other two are removed for albums.

---

## Input

JSON files in `extras/templates/configs/`:

```json
{
  "mapping": "content_types",
  "configs": {
    "{content_type}_art": {
      "items": {
        "fanart": "$LOCALIZE[31007]",
        "poster": "$LOCALIZE[31006]",
        "square": "$LOCALIZE[31008]"
      },
      "filter_mode": "exclude",
      "rules": [
        {
          "condition": "In({content_type}, [addons, favourites, albums, songs, images])",
          "value": ["fanart", "poster"]
        }
      ],
      "default_key": "window",
      "defaults": { "videos": "fanart", "*": "square" }
    }
  }
}
```

| Field | Default | What it does |
|---|---|---|
| `items` | `[]` | The master list — plain list, or object of value → display label |
| `filter_mode` | `"exclude"` | `"exclude"` removes what rules match; `"include"` keeps only what rules match |
| `rules` | `[]` | Conditions plus the values they match |
| `default_key` | — | Which token picks the row in `defaults` |
| `defaults` | — | Default per group, `"*"` as wildcard |
| `dependent_fields` | — | Other settings this config's rules read — see below |

---

## Values vs labels

**Plain list** when the value is fine to show as-is:

```json
"items": ["thumbnail", "fullscreen"]
```

**Object** when the stored value and the shown label differ. Keys are stored and matched; values are what the user sees:

```json
"items": { "true": "$LOCALIZE[186]", "false": "$LOCALIZE[106]" }
```

Every boolean toggle uses this so users see "Enabled / Disabled". Rules and defaults always use the **keys**, never the labels.

---

## Rules

Each rule: a `condition` ([Rule Engine](08-rule-engine.md), tokens filled in first) plus the `value` items it matches. All rules run; the matches pool together; then:

- **exclude** — keep everything NOT matched ("start full, remove what doesn't apply")
- **include** — keep only what matched ("start empty, add what does")

For the art config above: albums match the rule, so fanart and poster go — only square is left. Movies match nothing — all three stay.

> [!IMPORTANT]
> `items` is the whole universe. A rule value that isn't in `items` does nothing, silently. A default that isn't in `items` falls back to the first surviving value. If filtering leaves nothing, the config resolves to nothing at all — with `include` mode especially, add a `"condition": "true"` catch-all rule for values that should always survive.

---

## Defaults

`default_key` picks which token looks up the row in `defaults`:

```json
"default_key": "window",
"defaults": { "videos": "fanart", "*": "square" }
```

Videos-window content types default to fanart; everything else to square. If rules removed the default, the first surviving value is used instead. If only one value survives, it's the default *and* the only option — the editor disables the control.

---

## One config per item, or one shared

A config name containing the mapping's token — `{widget_preset}_layout` — resolves separately for each item, so each preset can filter differently and its rules can use `{widget_preset}`.

A plain name — `sortorder` — resolves once, shared by every item that points at it. Don't use the loop token in a shared config's rules: there's nothing per-item to fill it with, and the resolver errors to flag it. Same for `defaults` — with a plain name, use only `"*"`.

---

## Rules that read another setting

Allowed values can depend on a *different setting's* current value, not just which item this is. Widget `art` depends on `layout` — a reel only takes fanart:

```json
"{widget_preset}_art": {
  "dependent_fields": ["layout"],
  "items": { "fanart": "...", "poster": "...", "square": "..." },
  "rules": [
    { "condition": "equals({layout}, reel)", "value": ["fanart"] },
    { "condition": "equals({layout}, showcase)", "value": ["fanart", "poster"] }
  ]
}
```

`dependent_fields` makes `layout` resolve first, so `{layout}` in the rules is always a real value. When the user changes the layout, the art options refilter on the spot, and a now-invalid stored value snaps to the default.

> [!WARNING]
> If a rule reads another setting's token (`{layout}`, `{art}`, `{autoplay}`, …), list that setting in `dependent_fields`. Otherwise the config can resolve before the other setting exists, and the rule fails instead of waiting.

---

## Next

- [Controls](06-controls.md) — the UI that presents these options
