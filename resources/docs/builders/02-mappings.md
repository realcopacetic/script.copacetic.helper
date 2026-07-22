# Mappings

A mapping is a named list plus what each item on it knows about itself. Every builder input names the mapping it loops over.

> Reference doc. For a worked example, start with the [Quickstart](00-quickstart.md).

---

## Where they live

The addon ships one built-in mapping (`content_types`). Your own go in `extras/templates/mappings/` — each file an object of mapping name → definition. Reusing a built-in's name replaces it.

```json
{
  "widgets": {
    "mode": "dynamic",
    "parent_mapping": "mainmenu",
    "items": ["next_up", "in_progress", "latest_movies", "custom", "..."],
    "placeholders": { "key": "widget_preset" },
    "default_order": ["random_movies", "latest_movies", "random_tvshows", "latest_tvshows"],
    "config_fields": { "..." },
    "metadata": { "..." }
  }
}
```

| Field | Required | What it does |
|---|---|---|
| `items` | Yes | The values to loop over |
| `placeholders` | Yes | What to call the `{token}` for each value |
| `mode` | No | `"dynamic"` = this mapping gets entries in the settings file. Default `"static"` = loop values only. See [Overview](01-overview.md#the-three-kinds-of-mapping). |
| `default_order` | No | Which items get entries when the settings file is first created, in order. Defaults to all of `items`. |
| `config_fields` | No | Which settings entries have, and which config governs each — see below |
| `metadata` | No | Facts about each item, usable as `{tokens}` |
| `parent_mapping` | No | Which mapping's entries own this one's (the hub pattern — [Includes → Hubs](07-includes.md#hubs-each-parent-owns-its-own-children)) |
| `skin_mirrors` | No | Field → skin-setting pairs kept in sync so skin XML can read a runtime value — see below |

---

## `items`

**Flat list** — one loop pass per item:

```json
"items": ["next_up", "in_progress"],
"placeholders": { "key": "widget_preset" }
```

Each pass gets `{widget_preset}` set to the item name.

**Dict of lists** — a two-level loop:

```json
"items": { "videos": ["movies", "tvshows"], "music": ["albums"] },
"placeholders": { "key": "window", "value": "content_type" }
```

Each pass gets both `{window}` and `{content_type}`. For dynamic mappings, prefer a flat list and put the grouping in metadata — that's how `content_types` tags each type with its `window`.

Every pass also gets `{count}`, `{is_first}`, `{is_last}` — see [Overview → Placeholders](01-overview.md#placeholders).

---

## `metadata` — what each item knows

Facts attached to specific items. During that item's loop pass, they're all available as `{tokens}`:

```json
"metadata": {
  "next_up": {
    "label": "$LOCALIZE[31201]",
    "target": "videos",
    "content": "plugin://script.copacetic.helper/?info=next_up&limit=20",
    "icon": "icons/FastForward.png",
    "parent": "tvshows"
  },
  "custom": { "label": "$LOCALIZE[31210]", "content": "" }
}
```

This is what lets one includes template produce different output per item — each widget preset brings its own content path, label, and icon.

The `custom` preset is nearly empty on purpose. The user fills in `content` and `label` through the editor.

**Strings vs everything else.** Only string values can end up on settings-file entries and be edited. Dicts, lists, and numbers stay in the mapping — the builders can still use them (an `xsp` smart-playlist dict becomes the `{xsp}` token, for example), but they never appear in the settings file. So: user-editable → make it a string, even if just `""`.

---

## `config_fields` — the settings each entry has

Names the settings, and points each at the config that decides its allowed values:

```json
"config_fields": {
  "global": {
    "layout": "{widget_preset}_layout",
    "art": "{widget_preset}_art"
  },
  "custom": {
    "sortby": "sortby",
    "sortorder": "sortorder"
  }
}
```

`global` = every entry has these. A per-item section = only that item has these. So a `next_up` entry has layout and art; a `custom` entry has all four. Anything not listed doesn't exist as a setting.

The `{widget_preset}` token in a config name is filled with the entry's item name — so `layout` on a `next_up` entry uses config `next_up_layout`.

**Placeholder in the name, or not?** A config name containing the token gets resolved separately per item (each preset filters its layouts differently). A plain name is one shared config (there's only one `sortorder`). More in [Configs](05-configs.md#one-config-per-item-or-one-shared).

### The three kinds of setting

- **Fixed by you** — plain metadata (`target`, `content`, `icon` on the built-in presets). Copied to the entry; the editor leaves them alone unless you bind a control to them.
- **Picked from a list** — declared in `config_fields`, the user chooses from the config's allowed values (`layout`, `art`).
- **Typed or browsed** — bound to a control but with no config: the user enters whatever they want (`content` and `label` on the custom widget).

The same name can be different kinds per item: `label` is fixed for built-in presets and typed for `custom`, just because the edit control is only visible there.

---

## `skin_mirrors` — let skin XML read a runtime value

Runtime values live in the settings file, which skin XML can't read. When a visibility condition outside the editor needs one — a mapping-wide flag like `widgets_per_menu` gating which widget includes show — declare a mirror:

```json
"skin_mirrors": { "widgets_per_menu": "widgets_per_menu" }
```

Field name on the left, Kodi skin-setting name on the right. The addon keeps the skin setting matched to the runtime value:

- **On every write** to the settings file, all declared mirrors re-sync.
- **On boot**, mirrors are reconciled against the file — this covers edits the live sync never saw (restored backups, wiped settings).
- Writes are idempotent: nothing touches Kodi unless the value actually changed.

The value is read *resolved* — the stored value, or the config default when the user hasn't touched it. The first entry carrying the field wins, so declare mirrors for single-entry semantics (mapping-wide flags), not per-entry values.

**How to read it from XML** depends on the value's shape:

| Runtime value | Written via | Read with |
|---|---|---|
| `"true"` / `"false"` (or bool) | `Skin.SetBool` / `Skin.Reset` | `Skin.HasSetting(name)` |
| anything else | `Skin.SetString` | `Skin.String(name,value)` / `Skin.String(name)` |

**One direction only.** The runtime value is the source of truth and the mirror is a projection of it. Never write the skin setting from XML — `Skin.ToggleSetting` on a mirrored name will be silently overwritten on the next sync. If the user should change the value, give them an editor control for the field; the mirror follows.

---

## `default_order`

Which items get entries when the settings file is first created, and in what order. Entries store only their identity at that point — every setting shows its config default until the user changes it. Which means: change a default in your templates, and every entry the user never touched picks it up.

---

## Pointing inputs at a mapping

Every builder input file names its mapping at the top:

```json
{ "mapping": "widgets", "configs": { "..." } }
```

Spread one mapping's inputs across as many files as you like — they all share the same loop values.

`"mapping": "none"` (or leaving it out) means no loop values — for templates that only need an `{index}` range.

---

## Next

- [Variables](03-variables.md) — mappings in action with the simplest builder