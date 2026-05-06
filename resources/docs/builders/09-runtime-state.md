# Runtime State & the Dynamic Editor

Runtime state powers the multi-instance features: widgets, menus, and anything else where the user adds, removes, reorders, and configures entries. Each entry is stored in `runtime_state.json` with a stable UUID and a set of fields. The Dynamic Editor reads and writes that file through the controls you've defined.

---

## runtime_state.json

One list per mapping. Each entry is a flat dictionary of string fields. Two entries from a real widget list:

```json
{
  "widgets": [
    {
      "runtime_id": "f6698793-c695-4325-8fe1-978def805d65",
      "mapping_item": "latest_movies",
      "label": "$LOCALIZE[31202]",
      "target": "videos",
      "content": "videodb://movies/titles/",
      "sortby": "dateadded",
      "sortorder": "descending",
      "limit": "20",
      "parent": "bf340cc1-17c5-437f-8f84-76d6676601c6",
      "layout": "strip",
      "art": "fanart"
    },
    {
      "runtime_id": "a956c4b6-d6b3-4754-957e-d5993786a8b9",
      "mapping_item": "custom",
      "label": "In-progress movies",
      "content": "special://skin/extras/playlists/inprogress_movies.xsp",
      "layout": "strip",
      "art": "poster",
      "sortby": "title",
      "sortorder": "ascending",
      "limit": "20",
      "parent": "bf340cc1-17c5-437f-8f84-76d6676601c6"
    }
  ]
}
```

Fields on each entry:

| Field | Source |
|---|---|
| `runtime_id` | UUID — assigned on insert, stable across reorder, rename, and preset changes |
| `mapping_item` | Which preset this entry uses |
| Metadata fields | All string-valued metadata for this `mapping_item`, copied onto the entry at insert |
| `config_field` values | One per entry in the mapping's `config_fields`, initialised from the resolved default |
| `parent` | Optional — runtime_id of an entry in another mapping group |
| User edits | Anything edited through the editor overwrites the corresponding field |

The same `mapping_item` can appear multiple times — runtime_id keeps them distinct. Non-string metadata (e.g. an `xsp` smart-playlist dict) is intentionally not copied onto the entry; it stays metadata-only and gets merged in by the includes builder at substitution time.

---

## Initialisation

When `runtime_state.json` doesn't exist yet (first skin install), one entry is created for each item in the mapping's `default_order` (or `items` if no `default_order` is set). New entries get a fresh UUID, the `mapping_item` name, all string metadata for that item, and resolved default values for each `config_field`. Metadata wins over config defaults — if metadata defines `sortby`, the config default doesn't get applied.

---

## Parent references

When a mapping item's metadata sets `parent` to the name of an item in another mapping, that name is replaced with the matching entry's runtime_id at initialisation.

For example, the widget preset `latest_movies` has `"parent": "movies"`. The `movies` item lives in the `mainmenu` mapping. After initialisation:

```json
{
  "mainmenu": [
    { "runtime_id": "bf340cc1-...", "mapping_item": "movies", "..." }
  ],
  "widgets": [
    { "runtime_id": "f6698793-...", "mapping_item": "latest_movies",
      "parent": "bf340cc1-...", "..." }
  ]
}
```

The widget now points at the menu item by ID. This is what lets includes templates filter widgets to the focused menu item via `{parent}`. If the menu item is later deleted, the orphaned widget is cleaned up automatically.

---

## The Dynamic Editor

A two-panel Kodi dialog window: a scrollable list on the left (control ID 100), contextual controls on the right.

### Opening the editor

```xml
RunScript(script.copacetic.helper,action=dynamic_settings_window,name=widgetsettings)
```

The `name` parameter matches the window XML filename. The editor loads `controls.json`, filters for controls tagged with that window name, and builds the UI.

Optional: pass `parent=<runtime_id>` to restrict the list to entries whose `parent` matches — used for the "configure widgets for this menu item" flow, where only widgets attached to one menu item should appear.

### What you provide in the window XML

| Control | ID | Purpose |
|---|---|---|
| List container | 100 | Left-hand list. Populated automatically. |
| Description label | 6 | Bottom of the window. The editor sets it to the focused control's `description`. |
| Right-hand controls | as declared | Sliders, buttons, radios, edit fields. IDs must match those in `controls.json`. |
| Management buttons | 410–415 | See below. Hidden by default; the editor shows them when the controls include an `item_picker` role. |

### List rows

The left list is populated from controls with `"control_type": "listitem"` in `controls.json`.

**Static window** (e.g. view settings) — one listitem per loop value in the mapping. With the `content_types` mapping, the `{content_type}_item` template produces `movies_item`, `tvshows_item`, `albums_item`, etc.

**Dynamic window** (e.g. widget settings) — list rows come from `runtime_state.json`. The listitem template defines how rows look; one row per runtime entry, in storage order.

```json
"widget_{index}": {
  "mode": "dynamic",
  "control_type": "listitem",
  "window": ["widgetsettings"],
  "label": "{label}",
  "description": "Select widget to configure."
}
```

The user reorders, adds, and deletes rows with the management buttons.

### Linking controls to data

The right-hand controls connect to data in one of two ways. See [Controls Builder](06-controls.md) for full details.

**Contextual bindings** (static) — one control shared across all listitems, with a different config key bound for each. Used for view settings: a single layout slider that follows the focused content type.

**Field bindings** (dynamic) — one control per runtime field, shared across all entries. The control reads and writes the same field on whichever entry is selected. Used for widget settings: a layout slider that reads the focused widget's `layout` field.

### Management buttons

Provide controls 410–415 in your window XML. The editor enables and labels them automatically when a control with `role: "item_picker"` is present.

| Button | ID | Action |
|---|---|---|
| Add | 410 | Pick a preset, then insert a new entry after the current position |
| Delete | 411 | Remove the current entry (disabled when only one entry remains) |
| Move Up | 412 | Swap the current entry with the one above |
| Move Down | 413 | Swap the current entry with the one below |
| Reset | 414 | Reset the mapping group to `default_order` (with confirmation) |
| Close | 415 | Save and close |

### On close

If the runtime state changed while the editor was open, the includes and expressions builders re-run for the `runtime` context, and `ReloadSkin()` is called. Changes to widget order, presets, layouts, or art types appear in the skin immediately.

---

## Next

- [Chaining Builders](10-use-cases.md) — Real-world examples combining multiple builders