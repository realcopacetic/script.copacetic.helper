# Controls Builder

The controls builder generates `controls.json`, which defines every interactive control that appears in a Dynamic Editor window. It handles three distinct patterns: static controls that expand per-mapping-item, shared controls that bind to different configs based on list focus, and dynamic controls that read/write runtime state fields.

---

## When to use it

Use the controls builder whenever you need a Dynamic Editor window — a skin settings panel where the user can configure options via sliders, buttons, radio buttons, or text fields. The builder expands your compact control templates into the full set of control definitions that the editor needs at runtime.

---

## Input format

Control inputs are JSON files placed in `extras/builders/controls/`. Each file declares a mapping and a `controls` object:

```json
{
  "mapping": "content_types",
  "controls": {
    "template_name": {
      "control_type": "sliderex",
      "id": 200,
      "window": ["viewsettings"],
      "label": "View",
      "description": "Choose from available views.",
      "contextual_bindings": { "..." }
    }
  }
}
```

### Template fields

| Field | Type | Required | Description |
|---|---|---|---|
| `control_type` | string | Yes | One of: `listitem`, `button`, `sliderex`, `slider`, `radiobutton`, `edit` |
| `id` | integer | Yes* | Kodi control ID in the XML layout (*not required for listitems) |
| `id_start` | integer | No | Starting ID for auto-incrementing across expanded controls |
| `window` | list | Yes | Window XML filenames this control belongs to |
| `mode` | string | No | `"dynamic"` for runtime-state-linked controls |
| `field` | string | No | Runtime state field name (for dynamic mode) |
| `role` | string | No | Special role identifier (e.g. `"item_picker"`) |
| `label` | string | No | Display label (supports `{placeholder}` tokens and `$LOCALIZE[]`) |
| `label2` | string | No | Secondary label |
| `description` | string | No | Help text shown at bottom of editor |
| `visible` | string | No | Visibility condition (supports `{placeholder}` tokens) |
| `onclick` | object | No | Action configuration for button controls |
| `contextual_bindings` | object | No | Dynamic config binding (for static/shared controls) |
| `textcolor` | string | No | Text colour value or `$INFO[]` reference |
| `focusedcolor` | string | No | Focused state colour |
| `disabledcolor` | string | No | Disabled state colour |
| `shadowcolor` | string | No | Shadow colour |

---

## Control types

### `listitem`

Listitems define entries in the left-hand list panel. They aren't interactive controls themselves — they represent the items the user scrolls through. When a listitem is focused, the right-hand controls update to show that item's settings.

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

With the `content_types` mapping, this expands to `movies_item`, `tvshows_item`, `albums_item`, etc. — one list entry per content type.

Dynamic listitems use `"mode": "dynamic"` and get their entries from `runtime_state.json` instead:

```json
"widget_{index}": {
  "mode": "dynamic",
  "control_type": "listitem",
  "window": ["widgetsettings"],
  "label": "{label}",
  "description": "Select widget to configure."
}
```

The `{label}` token is resolved from metadata at runtime — it might be "$LOCALIZE[31201]" for "Next Up" or the user's custom label.

### `button`

Buttons trigger an action when pressed. The `onclick` field defines what happens:

```json
"widget_preset": {
  "mode": "dynamic",
  "role": "item_picker",
  "id": 200,
  "control_type": "button",
  "window": ["widgetsettings"],
  "onclick": {
    "type": "select",
    "heading": "Choose widget"
  },
  "label": "Choose type",
  "description": "Configure settings for '{label}' widget."
}
```

See the [onclick configuration](#onclick-configuration) section below for all action types.

### `sliderex`

A composite control pairing a slider with a label button. On its own, a Kodi slider control is just a draggable bar with no text — it can't display a label or show the current value. The `sliderex` type solves this by associating a button control with the slider. The button shows `label` (the setting name) and `label2` (the current value), while the slider handles left/right input. Pressing select toggles focus between the two, so the user can read the label, then switch to the slider to change the value.

```json
"view": {
  "id": 200,
  "control_type": "sliderex",
  "window": ["viewsettings"],
  "contextual_bindings": {
    "linked_config": "{content_type}_view",
    "update_trigger": "focused({content_type}_item)"
  },
  "label": "View",
  "description": "Choose from available views."
}
```

The button companion control ID is derived by appending `0` to the slider ID (e.g. slider 200 → button 2000). This convention must be followed in the Kodi XML layout.

#### XML template for sliderex

Because Kodi doesn't have a native composite slider+button control, you need to build one in your window XML using a parameterised include. Here's an example template that wraps a button and slider together in a grouplist:

```xml
<include name="settings_slider">
  <control type="grouplist" id="$PARAM[id]1">
    <visible>Control.IsVisible($PARAM[id])</visible>
    <defaultcontrol always="true">$PARAM[id]0</defaultcontrol>
    <height>120</height>
    <width>1119</width>
    <orientation>horizontal</orientation>
    <itemgap>0</itemgap>
    <usecontrolcoords>true</usecontrolcoords>
    <control type="button" id="$PARAM[id]0">
      <visible>Control.IsVisible($PARAM[id])</visible>
      <width>1119</width>
      <right>0</right>
      <textoffsetx>150</textoffsetx>
      <textcolor>pearl</textcolor>
      <focusedcolor>gunmetal</focusedcolor>
      <onup>$PARAM[onup]</onup>
      <ondown>$PARAM[ondown]</ondown>
    </control>
    <control type="slider" id="$PARAM[id]">
      <right>30</right>
      <onup>$PARAM[onup]</onup>
      <ondown>$PARAM[ondown]</ondown>
    </control>
  </control>
</include>
```

The key points:

- You pass the slider's `id` as a parameter. The button ID is `$PARAM[id]0` — matching the convention the Python handler expects (slider 200 → button 2000).
- The grouplist visibility is tied to the slider's visibility (`Control.IsVisible($PARAM[id])`), which the Dynamic Editor controls programmatically.
- `defaultcontrol` is set to the button ID so the user lands on the labelled button first, then can press select to switch to the slider.
- The slider itself is hidden behind the button visually — the user interacts with it via left/right after toggling focus.

### `radiobutton`

A toggle control for boolean settings (true/false):

```json
"clearlogo": {
  "id": 203,
  "control_type": "radiobutton",
  "window": ["viewsettings"],
  "contextual_bindings": {
    "linked_config": "{content_type}_clearlogo",
    "update_trigger": "focused({content_type}_item)",
    "visible": "In({content_type}, [movies, sets, tvshows, artists])"
  },
  "label": "$LOCALIZE[31443]"
}
```

### `slider`

A standalone slider without the companion button. Works the same as `sliderex` but without the focus-toggle behaviour.

### `edit`

An inline text input field. The user types a value via Kodi's keyboard, and it's saved when they navigate away or press select:

```json
"widget_label": {
  "mode": "dynamic",
  "field": "label",
  "id": 204,
  "control_type": "edit",
  "window": ["widgetsettings"],
  "label": "Widget name",
  "description": "Choose a custom label.",
  "visible": "In({widget_preset}, [custom])"
}
```

---

## Contextual bindings (static controls)

In a static editor window, the left-hand list contains one listitem per loop item from the mapping (e.g. one per content type). The right-hand panel has a fixed set of controls — but each control needs to read/write a different config key depending on which listitem is focused. Contextual bindings are how this link is established.

A single control definition in the JSON produces one control instance in the window, but with an expanded array of bindings — one per listitem. At runtime, the handler matches the currently focused listitem to the correct binding and reads/writes the corresponding config key.

```json
"contextual_bindings": {
  "linked_config": "{content_type}_view",
  "update_trigger": "focused({content_type}_item)"
}
```

| Field | Description |
|---|---|
| `linked_config` | Template for the config key. Expanded per substitution. |
| `update_trigger` | Condition that identifies which listitem activates this binding. |
| `visible` | Optional visibility condition for this binding. |

The controls builder expands `contextual_bindings` across all substitutions, deduplicating identical results. The output in `controls.json` contains the full array of resolved bindings:

```json
"contextual_bindings": [
  { "linked_config": "movies_view", "update_trigger": "focused(movies_item)" },
  { "linked_config": "tvshows_view", "update_trigger": "focused(tvshows_item)" },
  { "linked_config": "albums_view", "update_trigger": "focused(albums_item)" }
]
```

When `movies_item` is focused, the slider reads from the `movies_view` config. When `albums_item` is focused, it reads from `albums_view`. Same control, different data.

---

## Dynamic field controls

Controls with `"mode": "dynamic"` and a `"field"` value bind directly to a runtime state field rather than using contextual bindings:

```json
"widget_view": {
  "mode": "dynamic",
  "field": "view",
  "id": 201,
  "control_type": "sliderex",
  "window": ["widgetsettings"],
  "label": "View"
}
```

The `field: "view"` means this control reads and writes the `view` field in the current runtime state entry. The config key is resolved dynamically using the mapping's `config_fields` template (e.g. `widget_{widget_preset}_view` → `widget_next_up_view`).

---

## The item picker role

A control with `"role": "item_picker"` serves two purposes:

**As a control**, it lets the user pick from the mapping's `items` list — selecting which item (e.g. "next_up", "latest_movies", "custom") this runtime state entry should use. Its onclick dialog presents the full list of available items from the mapping.

**As a signal**, its presence tells the Dynamic Editor that this window manages runtime state entries. When the editor detects a control with this role, it enables the management buttons (add, delete, move up/down, reset, close). Without a item picker control, the editor assumes a static window and hides the management UI.

When the user changes the selected item:
- `_on_mapping_item_changed()` fires — refreshing all other controls, resetting invalid field values to defaults, and updating the list label.
- On "Add", the item picker's onclick dialog is shown first to let the user choose what type of entry to create before inserting it.

---

## Onclick configuration

The `onclick` object on button controls defines the action triggered when the user presses select:

| Field | Type | Description |
|---|---|---|
| `type` | string | Action type (see below) |
| `heading` | string | Dialog title |
| `items` | list | Override items (if omitted, uses the linked config's items) |
| Plus various type-specific options |

### Action types

| Type | Description |
|---|---|
| `select` | Shows a selection dialog from the items list |
| `browse` | Kodi browse dialog (files/directories) |
| `browse_single` | Single-select browse dialog |
| `browse_multiple` | Multi-select browse dialog |
| `browse_content` | Recursive content path browser (library, playlists, addons, custom paths) |
| `colorpicker` | Kodi colour picker dialog |
| `input` | Keyboard input dialog |
| `numeric` | Numeric input dialog |
| `custom` | Executes an arbitrary Kodi built-in command |

### `browse_content` and sibling fields

The `browse_content` action returns a dict with `path`, `label`, and optionally `icon`, `type`, `window`, `action`. You can use `sibling_fields` to auto-populate other runtime state fields from the result:

```json
"onclick": {
  "type": "browse_content",
  "heading": "Select content path",
  "mode": "widget",
  "sibling_fields": {
    "label": "widget_label"
  }
}
```

When the user selects a path, the `label` from the browse result is written to the `widget_label` control's runtime field — but only if that field is currently empty. This means the user's custom label is preserved if they've already set one.

---

## Visibility conditions

The `visible` field on controls supports `{placeholder}` substitution and is evaluated by the Rule Engine at runtime. For dynamic controls, placeholders like `{widget_preset}` are resolved from the current runtime state entry's `mapping_item`:

```json
"visible": "In({widget_preset}, [custom])"
```

This makes the control visible only when the current widget slot is set to the "custom" preset.

For contextual bindings, visibility can also be set per-binding:

```json
"contextual_bindings": {
  "linked_config": "{content_type}_size",
  "update_trigger": "focused({content_type}_item)",
  "visible": "xml(Skin.String({content_type}_view,list) + Skin.String({content_type}_layout,fanart))"
}
```

---

## Output format

The controls builder writes `controls.json`. Each entry is keyed by the control name:

```json
{
  "movies_item": {
    "mapping": "content_types",
    "control_type": "listitem",
    "window": ["viewsettings"],
    "visible": "true",
    "label": "movies",
    "description": "Configure view settings for movies.",
    "icon": "icons/movies.png"
  },
  "view": {
    "mapping": "content_types",
    "control_type": "sliderex",
    "window": ["viewsettings"],
    "id": 200,
    "contextual_bindings": [
      { "linked_config": "movies_view", "update_trigger": "focused(movies_item)" },
      { "linked_config": "sets_view", "update_trigger": "focused(sets_item)" },
      { "linked_config": "tvshows_view", "update_trigger": "focused(tvshows_item)" }
    ],
    "label": "View",
    "description": "Choose from available views."
  },
  "widget_preset": {
    "mapping": "widgets",
    "mode": "dynamic",
    "role": "item_picker",
    "control_type": "button",
    "window": ["widgetsettings"],
    "id": 200,
    "onclick": { "type": "select", "heading": "Choose widget" },
    "label": "Choose type",
    "description": "Configure settings for '{label}' widget."
  }
}
```

---

## Next

- [Includes Builder](07-includes.md) — Recursive XML template expansion
