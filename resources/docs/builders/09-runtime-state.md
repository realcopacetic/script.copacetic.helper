# Runtime State & the Dynamic Editor

The runtime state system enables user-configurable, multi-instance features like widgets. It stores per-entry settings in a JSON file and provides a visual editor where users can add, remove, reorder, and configure entries. When the user closes the editor, changed outputs are rebuilt and the skin reloads.

---

## runtime_state.json

The runtime state file stores one list per mapping group. Each entry in a list represents a single instance (e.g. one widget slot) with a stable UUID, a mapping item identifier, and values for each configured field.

```json
{
  "widgets": [
    {
      "runtime_id": "912e32e9-fcde-4f49-8914-62ec8d23c25a",
      "mapping_item": "next_up",
      "view": "strip",
      "layout": "poster"
    },
    {
      "runtime_id": "ede86898-9c53-418c-9351-c24632e99f08",
      "mapping_item": "in_progress",
      "view": "showcase",
      "layout": "square"
    },
    {
      "runtime_id": "c889b495-1fa9-45f8-8e17-28e1adf03e94",
      "mapping_item": "custom",
      "view": "grid",
      "layout": "poster",
      "label": "Comedy",
      "content_path": "videodb://movies/genres/4/"
    }
  ]
}
```

### Entry fields

| Field | Description |
|---|---|
| `runtime_id` | UUID — stable identifier that survives reordering |
| `mapping_item` | Which item this entry uses (from the mapping's `items` list) |
| Field names from `config_fields` | e.g. `view`, `layout` — values chosen by the user |
| Additional fields | e.g. `label`, `content_path` — set by controls like edit fields or browse dialogs |

### Initialisation

When `runtime_state.json` doesn't exist (first skin install), it is automatically created from the mapping's `default_order` list. For each item in the default order, an entry is built with a fresh UUID and default values for each `config_field` resolved from `configs.json`.

---

## The Dynamic Editor

The Dynamic Editor is a Kodi dialog window that provides the UI for editing runtime state and static skin settings. It has a two-panel layout: a scrollable list on the left (control ID 100) and contextual controls on the right.

### Opening the editor

The editor is launched from a skin XML button via a script action:

```xml
RunScript(script.copacetic.helper,action=dynamic_settings_window,name=widgetsettings)
```

The `name` parameter matches the window XML filename. The editor loads `controls.json`, filters for controls tagged with that window name, and builds the UI.

### The left-hand list (ID 100)

The list container (control ID 100) is populated from controls with `"control_type": "listitem"` in `controls.json`. These are defined in the controls input JSON like any other control, but instead of appearing in the right-hand panel, they become rows in the list.

For example, this template defines one listitem per content type:

```json
"{content_type}_item": {
  "control_type": "listitem",
  "window": ["viewsettings"],
  "visible": "true",
  "label": "{content_type}",
  "description": "Configure view settings for {content_type}.",
  "icon": "icons/{content_type}.png"
}
```

**For static windows** (e.g. view settings), the controls builder expands this template across the mapping's loop values — so with the `content_types` mapping, you get one entry per content type (movies, tvshows, albums, etc.), each with its own label and icon.

**For dynamic windows** (e.g. widget settings), the listitem uses `"mode": "dynamic"` and the list entries come from `runtime_state.json` instead:

```json
"widget_{index}": {
  "mode": "dynamic",
  "control_type": "listitem",
  "window": ["widgetsettings"],
  "visible": "true",
  "label": "{label}",
  "description": "Select widget to configure."
}
```

This template acts as a stand-in — it defines how each list row should look, but the actual entries come from the runtime state. On first install, the list is populated from the mapping's `default_order`. From there, the user can add more entries, remove existing ones, or reorder them using the management buttons. Each entry's label is resolved from its metadata (e.g. "$LOCALIZE[31201]" for "Next Up") or from user-entered values (e.g. "Comedy" for a custom widget). The template name (`widget_{index}`) doesn't matter for identification — each entry is tracked by its UUID in the runtime state.

### The two linking modes

The editor supports two fundamentally different ways of connecting controls to data:

**Static mode (contextual bindings)** — Used for view settings. A single control is shared across all listitems. In the controls JSON input, the skinner writes the binding as a template:

```json
"view": {
  "id": 200,
  "control_type": "sliderex",
  "contextual_bindings": {
    "linked_config": "{content_type}_view",
    "update_trigger": "focused({content_type}_item)"
  },
  "label": "View"
}
```

The controls builder expands this across all content types, producing the resolved bindings array in `controls.json`:

```json
"contextual_bindings": [
  { "linked_config": "movies_view", "update_trigger": "focused(movies_item)" },
  { "linked_config": "tvshows_view", "update_trigger": "focused(tvshows_item)" },
  { "linked_config": "albums_view", "update_trigger": "focused(albums_item)" }
]
```

At runtime, when the user scrolls the list to "movies", the slider reads from the `movies_view` skin string. Scroll to "albums", and the same slider reads from `albums_view`. One control, many config bindings.

**Dynamic mode (field bindings)** — Used for widget settings. Each control has a `field` that maps to a column in the runtime state:

```json
"widget_view": {
  "mode": "dynamic",
  "field": "view",
  "id": 201,
  "control_type": "sliderex",
  "label": "View"
}
```

Every entry in the runtime state shares the same set of controls. When the user scrolls the list, the controls read and write values from the selected entry. For example, with this runtime state:

```json
[
  { "runtime_id": "912e...", "mapping_item": "next_up", "view": "strip", "layout": "poster" },
  { "runtime_id": "ede8...", "mapping_item": "in_progress", "view": "showcase", "layout": "square" }
]
```

Selecting the first entry shows "strip" on the View slider. Selecting the second shows "showcase". The same slider control, reading a different entry's `view` field each time.

### How the editor responds to user actions

When the user scrolls the list or interacts with a control, the editor refreshes all controls for the current selection. For each control it reads the current value (from the relevant skin string or runtime state entry), evaluates the visibility condition, and updates the display. When the user changes a value (moving a slider, pressing a button, toggling a radio), the new value is written back to the skin string or runtime state and the UI refreshes.

When the user changes which item a slot uses (via the item picker button), the editor refreshes all controls, resets any field values that are no longer valid for the new item (falling back to the config's default), and updates the list label.

### The editor layout

The editor window XML needs to provide the following controls:

**List container** (ID 100) — the scrollable left-hand list. Populated automatically by the editor from listitems in `controls.json` or entries in `runtime_state.json`.

**Description label** (ID 6) — a text area at the bottom of the window. The editor sets this to the `description` field of whichever listitem or control currently has focus.

**Right-hand controls** — sliders, buttons, radio buttons, and edit fields defined in `controls.json` for this window. These are placed in the window XML by the skinner with the IDs matching those declared in the controls JSON. See [Controls Builder](06-controls.md) for details on defining controls and setting them up in XML.

**Management buttons** (IDs 410–415) — only needed for dynamic windows. These should be present in the window XML but hidden by default; the editor shows them when it detects a control with `role: "item_picker"`.

| Button | ID | Action |
|---|---|---|
| Add | 410 | Shows the item picker dialog (from the mapping's `items` list), then inserts a new entry after the current position |
| Delete | 411 | Removes the current entry (disabled when only one entry remains) |
| Move Up | 412 | Swaps the current entry with the one above |
| Move Down | 413 | Swaps the current entry with the one below |
| Reset | 414 | Resets the entire mapping group to `default_order` (with confirmation dialog) |
| Close | 415 | Saves and closes (triggers rebuild if state changed) |

### On close

When the editor closes, the current runtime state is compared to a snapshot taken when the window opened. If anything changed, the includes and expressions builders are re-run for the `runtime` context, and `ReloadSkin()` is called so Kodi picks up the new XML. This ensures that changes to widget order, presets, views, or layouts are immediately reflected in the skin.

---

## Next

- [Chaining Builders](10-use-cases.md) — Real-world examples combining multiple builders