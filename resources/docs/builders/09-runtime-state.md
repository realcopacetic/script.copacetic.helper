# Runtime State & the Dynamic Editor

Runtime state powers the multi-instance features: widgets, menus, and anything else where the user adds, removes, reorders, and configures entries. Each entry is stored in `runtime_state.json` with a stable UUID and a set of fields. The Dynamic Editor reads and writes that file through the controls you've defined.

---

## runtime_state.json

One list per mapping. Each entry is a flat dictionary of string fields. Two entries from a real widget list.
An entry only carries fields it needs to: identity, copied metadata strings, and any fields the user has set. Anything the user hasn't touched is absent on disk and resolves to its config default on read. Two entries from a real widget list:

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
      "parent": "bf340cc1-17c5-437f-8f84-76d6676601c6",
      "layout": "showcase",
    },
    {
      "runtime_id": "a956c4b6-d6b3-4754-957e-d5993786a8b9",
      "mapping_item": "custom",
      "label": "In-progress movies",
      "content": "special://skin/extras/playlists/inprogress_movies.xsp",
      "parent": "bf340cc1-17c5-437f-8f84-76d6676601c6"
    }
  ]
}
```

The first entry has been touched by the user — `layout` is set to `showcase`. The second is untouched; layout, art, sortby, sortorder, limit will all resolve to their config defaults when read.

Fields on each entry:

| Field | Source |
|---|---|
| `runtime_id` | UUID — assigned on insert, stable across reorder, rename, and preset changes |
| `mapping_item` | Which preset this entry uses |
| Metadata fields | All string-valued metadata for this `mapping_item`, copied onto the entry at insert |
| `config_field` values | Absent unless the user has set them. Reads fall back to the field's config default. |
| `parent` | Optional — runtime_id of an entry in another mapping group |
| User edits | Anything edited through the editor overwrites the corresponding field |

The same `mapping_item` can appear multiple times — runtime_id keeps them distinct. Non-string metadata (e.g. an `xsp` smart-playlist dict) is intentionally not copied onto the entry; it stays metadata-only and gets merged in by the includes builder at substitution time.

---

## Initialisation

When `runtime_state.json` doesn't exist yet (first skin install), one entry is created for each item in the mapping's `default_order` (or `items` if no `default_order` is set). New entries get a fresh UUID, the `mapping_item` name, and all string metadata for that item. `config_field` values are not seeded; they resolve to their config defaults on read until the user sets them. Metadata still wins over config defaults — if metadata defines `sortby`, the field is on the entry and the config default never applies.

---

## Parent references

Dynamic mappings can reference each other via `parent`. The canonical use is **hubs**: each menu item owns its own set of widgets, the user configures them through a child editor scoped to whichever menu item they were on, and the skin shows the right widgets when each menu item is focused.

The full pattern spans three places — metadata, includes template, and the dialog that opens the child editor scoped to one parent. The metadata side lives here; the other two pieces are covered in [Includes Builder → Hubs](07-includes.md#hubs-filtering-child-entries-by-parent), and you'll usually want to read both pages once when you're wiring up a hub for the first time.

### Tagging an entry to a parent

In the child mapping's metadata, set `parent` to the `mapping_item` name of an entry in another mapping. The `widgets` mapping uses this to attach each widget preset to a menu item:

```json
"latest_movies": {
  "label": "$LOCALIZE[31202]",
  "target": "videos",
  "content": "videodb://movies/titles/",
  "sortby": "dateadded",
  "parent": "movies"
}
```

The `movies` item lives in the `mainmenu` mapping. After `runtime_state.json` is initialised, the parent reference is resolved to the corresponding entry's `runtime_id`:

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

The widget now points at the menu item by ID. This survives reorder and rename of the menu item — the runtime_id is stable. If the menu item is later deleted, the orphaned widget is cleaned up automatically.

### What the parent buys you

Once entries are tagged, the `{parent}` placeholder is available wherever the child mapping is iterated:

- In the **includes builder**, `{parent}` substitutes into the generated XML, where you typically use it to gate visibility on the matching menu item being focused. See [Includes Builder → Hubs](07-includes.md#hubs-filtering-child-entries-by-parent) for the worked include and the visibility expression.
- In the **Dynamic Editor**, passing `parent=<runtime_id>` when opening the editor filters the entry list to that single hub. See [Opening the editor](#opening-the-editor) below.

---

## The Dynamic Editor

A two-panel Kodi dialog window: a scrollable list on the left (control ID 100), contextual controls on the right.

### Opening the editor

```xml
RunScript(script.copacetic.helper,action=dynamic_settings_window,name=widgetsettings,mapping=widgets)
```

The `name` parameter matches the window XML filename. The editor filters for controls tagged with that window name, and builds the UI.

To open the editor scoped to a single parent, pass `parent=<runtime_id>`. Only entries whose `parent` field matches appear in the list, and entries inserted from the filtered editor have their `parent` set automatically. See [Includes Builder → Hubs](07-includes.md#hubs-filtering-child-entries-by-parent) for the full hub recipe.

### Reusing one window for multiple mappings

If two mappings share the same control shape — same fields, same control types, same window layout — one window XML and one set of `controls/` templates can serve both. The `mapping` kwarg names the mapping this session edits; the optional `controls_from` kwarg names additional mappings whose controls should also be loaded into the window.

The mainmenu and shutdownmenu mappings illustrate this. Both have `label`, `icon`, and `action` fields per entry; both want the same edit/browse/icon-picker controls. `controls_menus.json` declares `mapping: "mainmenu"` — and the same window opens against shutdownmenu by passing it as the session mapping and borrowing the mainmenu controls:

```xml
RunScript(script.copacetic.helper,action=dynamic_settings_window,name=menusettings,mapping=shutdownmenu,controls_from=mainmenu)
```

The list shows shutdownmenu entries; adds, deletes, and field edits all write to the shutdownmenu mapping. No second `controls_shutdownmenu.json` needed.

`controls_from` accepts a comma-separated list, so a window can borrow controls from several mappings at once. The session's own mapping is always loaded; `controls_from` is purely additive.

**Constraint.** Every control loaded into the session edits the session's mapping. This works when the borrowed controls' fields match the session mapping's shape (as mainmenu and shutdownmenu do). If a borrowed control references a field the session mapping doesn't have, the field will be created on first write — usually not what you want. Borrow only when the shapes genuinely match.

### Querying editor state from skin XML

While an editor is open it sets two window properties on `Window(home)`:

| Property | Value | When set |
|---|---|---|
| `<name>` | `"true"` | Always, while the editor is open |
| `current_mapping` | The session's `mapping` value | Always, while the editor is open |

Skin conditions branch on either:

```
!String.IsEmpty(Window(home).Property(menusettings))                  # editor open
String.IsEmpty(Window(home).Property(current_mapping))                # default (no override)
String.IsEqual(Window(home).Property(current_mapping),shutdownmenu)   # editing shutdownmenu
```

Controls that should only appear for a specific session mapping check it explicitly — for example, `menu_configure_widgets` is mainmenu-specific:

```json
"visible": "xml(String.IsEqual(Window(home).Property(current_mapping),mainmenu) + Skin.HasSetting(widgets_per_menu))"
```

Both properties are cleared when the editor closes.

**Nested editors.** When an editor is opened with `parent=<uuid>` (the hub pattern — opening a child editor scoped to one parent), the `current_mapping` slot is suffixed with the parent uuid: `current_mapping_<uuid>`. This keeps outer and inner editors from colliding on the property when the same window XML is reused at both levels. The window flag stays unsuffixed so skin-level "is this window open" conditions work uniformly across top-level and nested invocations. Conditions inside a control template that already has `{runtime_id}` available (controls iterating a parent mapping) can target the nested slot directly:

```
String.IsEqual(Window(home).Property(current_mapping_{runtime_id}),submenu)
```

For top-level conditions, query the unsuffixed slots.

### What you provide in the window XML

| Control | ID | Purpose |
|---|---|---|
| List container | 100 | Left-hand list. Populated automatically. |
| Description label | 6 | Bottom of the window. The editor sets it to the focused control's `description`. |
| Right-hand controls | as declared | Sliders, buttons, radios, edit fields. IDs must match the `id` declared on each control template. |
| Management buttons | 410–415 | See below. Hidden by default; the editor shows them when the controls include an `item_picker` or `add_action` role. |

### List rows

The left list is populated from controls with `"control_type": "listitem"` declared for the session's mapping.

**Static window** (e.g. view settings) — one listitem per loop value in the mapping. With the `content_types` mapping, the `{content_type}_item` template produces `movies_item`, `tvshows_item`, `albums_item`, etc.

**Dynamic window** (e.g. widget settings) — list rows come from `runtime_state.json`. The listitem template defines how rows look; one row per runtime entry, in storage order.

```json
"widget_{index}": {
  "mode": "dynamic",
  "control_type": "listitem",
  "label": "{label}",
  "icon": "{icon}",
  "description": "Select widget to configure."
}
```

The user reorders, adds, and deletes rows with the management buttons.

### Linking controls to data

The right-hand controls connect to data in one of two ways. See [Controls Builder](06-controls.md) for full details.

**Contextual bindings** (static) — one control shared across all listitems, with a different config key bound for each. Used for view settings: a single layout slider that follows the focused content type.

**Field bindings** (dynamic) — one control per runtime field, shared across all entries. The control reads and writes the same field on whichever entry is selected. Used for widget settings: a layout slider that reads the focused widget's `layout` field.

### Management buttons

Provide controls 410–415 in your window XML. The editor enables and labels them automatically when a control with `role: "item_picker"` or `role: "add_action"` is present.

| Button | ID | Action |
|---|---|---|
| Add | 410 | Run the governing handler's dialog (preset picker or add-action), then insert a new entry |
| Delete | 411 | Remove the current entry (disabled when only one entry remains) |
| Move Up | 412 | Swap the current entry with the one above |
| Move Down | 413 | Swap the current entry with the one below |
| Reset | 414 | Reset the mapping group to `default_order` (with confirmation) |
| Close | 415 | Save and close |

When the editor is opened with a `parent` filter, the management buttons stay scoped to the filtered set — Add inserts as a child of the same parent, Move keeps the new ordering within the filtered view, and Delete only removes from the visible entries.

### On close

If the runtime state changed while the editor was open, the includes and expressions builders re-run for the `runtime` context, and `ReloadSkin()` is called. Changes to widget order, presets, layouts, or art types appear in the skin immediately.

---

## Next

- [Chaining Builders](10-use-cases.md) — Real-world examples combining multiple builders