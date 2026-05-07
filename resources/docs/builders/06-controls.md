# Controls Builder

The controls builder generates `controls.json`, defining every interactive control that appears in a Dynamic Editor window. It handles three patterns: static controls that expand per-mapping-item, shared controls that bind to different configs based on list focus, and dynamic controls that read/write runtime state fields.

The classic case: a settings panel where the user picks options through sliders, buttons, radio buttons, or text fields. The builder expands compact templates into the full set of control definitions the editor needs at runtime.

---

## Input format

JSON files placed in `extras/builders/controls/`. Each file declares a mapping and a `controls` object:

```json
{
  "mapping": "content_types",
  "controls": {
    "template_name": {
      "control_type": "sliderex",
      "id": 200,
      "window": ["viewsettings"],
      "label": "Layout",
      "description": "Choose from available layouts.",
      "contextual_bindings": { "..." }
    }
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `mapping` | string | Yes | Mapping name. Either built-in (`content_types`), a custom one in `extras/builders/mappings/`, or `"none"` — see [Mappings](02-mappings.md). |
| `control_type` | string | Yes | One of: `listitem`, `button`, `sliderex`, `slider`, `radiobutton`, `edit` |
| `id` | integer | Yes* | Kodi control ID in the XML layout (*not required for listitems) |
| `id_start` | integer | No | Starting ID for auto-incrementing across expanded controls |
| `window` | list | Yes | Window XML filenames this control belongs to |
| `mode` | string | No | `"dynamic"` to share one control across all runtime entries (each entry's field read/written when focused). Default is static, which expands once per item in the mapping. |
| `field` | string | No | Runtime state field name (for dynamic mode) |
| `role` | string | No | Special role identifier (e.g. `"item_picker"`) |
| `label` | string | No | Display label (supports `{placeholder}` tokens and `$LOCALIZE[]`) |
| `label2` | string | No | Secondary label |
| `description` | string | No | Help text shown at bottom of editor |
| `visible` | string | No | Visibility condition (supports `{placeholder}` tokens) |
| `onclick` | object | No | Action configuration for button controls |
| `contextual_bindings` | object | No | Dynamic config binding (for static/shared controls) |
| `textcolor`, `focusedcolor`, `disabledcolor`, `shadowcolor` | string | No | Colour values or `$INFO[]` references |

---

## Control types

### `listitem`

Listitems define entries in the left-hand list panel. They aren't interactive controls themselves — they represent the items the user scrolls through. When a listitem is focused, the right-hand controls update to show that item's settings.

```json
"{content_type}_item": {
  "control_type": "listitem",
  "window": ["viewsettings"],
  "label": "{content_type}",
  "description": "Configure layout settings for {content_type}.",
  "icon": "icons/{content_type}.png"
}
```

With the `content_types` mapping, this expands to `movies_item`, `tvshows_item`, `albums_item`, etc.

Dynamic listitems use `"mode": "dynamic"` and get their entries from `runtime_state.json`:

```json
"widget_{index}": {
  "mode": "dynamic",
  "control_type": "listitem",
  "window": ["widgetsettings"],
  "label": "{label}",
  "description": "Select widget to configure."
}
```

The `{label}` token resolves from runtime fields or metadata at runtime — `$LOCALIZE[31201]` for "Next Up" or the user's custom label.

### `button`

Buttons trigger an action when pressed. The `onclick` field defines what happens:

```json
"widget_preset": {
  "mode": "dynamic",
  "role": "item_picker",
  "id": 200,
  "control_type": "button",
  "window": ["widgetsettings"],
  "onclick": { "type": "select", "heading": "Choose widget" },
  "label": "Choose type"
}
```

See [Onclick configuration](#onclick-configuration) below for action types.

### `sliderex`

A composite control pairing a slider with a label button. A Kodi slider on its own is a draggable bar with no text — it can't display a label or show the current value. `sliderex` solves that by associating a button control with the slider. The button shows `label` (the setting name) and `label2` (the current value); the slider handles left/right input. Pressing select toggles focus between the two.

```json
"layout": {
  "id": 200,
  "control_type": "sliderex",
  "window": ["viewsettings"],
  "contextual_bindings": {
    "linked_config": "{content_type}_layout",
    "update_trigger": "focused({content_type}_item)"
  },
  "label": "Layout"
}
```

The button companion control ID is derived by appending `0` to the slider ID (e.g. slider 200 → button 2000). This convention must be followed in your window XML.

#### XML template for sliderex

Kodi has no native composite slider+button, so build one in your window XML using a parameterised include:

```xml
<include name="settings_slider">
  <control type="grouplist" id="$PARAM[id]1">
    <visible>Control.IsVisible($PARAM[id])</visible>
    <defaultcontrol always="true">$PARAM[id]0</defaultcontrol>
    <orientation>horizontal</orientation>
    <usecontrolcoords>true</usecontrolcoords>
    <control type="button" id="$PARAM[id]0">
      <visible>Control.IsVisible($PARAM[id])</visible>
      <textcolor>pearl</textcolor>
      <focusedcolor>gunmetal</focusedcolor>
      <onup>$PARAM[onup]</onup>
      <ondown>$PARAM[ondown]</ondown>
    </control>
    <control type="slider" id="$PARAM[id]">
      <onup>$PARAM[onup]</onup>
      <ondown>$PARAM[ondown]</ondown>
    </control>
  </control>
</include>
```

Pass the slider's `id` as a parameter; the button ID is `$PARAM[id]0` to match the convention the editor expects. `defaultcontrol` is the button so the user lands on the labelled side first, then presses select to switch to the slider.

### `slider`

A standalone slider without the companion button. Works the same as `sliderex` but without the focus-toggle behaviour.

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

### `edit`

An inline text input. The user types via Kodi's keyboard; the value is saved when they navigate away or press select:

```json
"widget_label": {
  "mode": "dynamic",
  "field": "label",
  "id": 204,
  "control_type": "edit",
  "window": ["widgetsettings"],
  "label": "Widget name",
  "visible": "In({widget_preset}, [custom])"
}
```

---

## Contextual bindings (static controls)

In a static editor window, the left-hand list contains one listitem per loop item from the mapping. The right-hand panel has a fixed set of controls — but each control needs to read/write a different config key depending on which listitem is focused. Contextual bindings link them.

A single control definition produces one control instance, with an array of bindings — one per listitem. At runtime, the editor matches the focused listitem to the correct binding.

```json
"contextual_bindings": {
  "linked_config": "{content_type}_layout",
  "update_trigger": "focused({content_type}_item)"
}
```

| Field | Description |
|---|---|
| `linked_config` | Template for the config key. Expanded per substitution. |
| `update_trigger` | Condition that identifies which listitem activates this binding. |
| `visible` | Optional visibility condition for this binding. |

The builder expands `contextual_bindings` across all substitutions, deduplicating identical results:

```json
"contextual_bindings": [
  { "linked_config": "movies_layout", "update_trigger": "focused(movies_item)" },
  { "linked_config": "tvshows_layout", "update_trigger": "focused(tvshows_item)" },
  { "linked_config": "albums_layout", "update_trigger": "focused(albums_item)" }
]
```

Same control, different data depending on which listitem has focus.

---

## Dynamic field controls

Controls with `"mode": "dynamic"` and a `"field"` value bind directly to a runtime state field instead of a config key:

```json
"widget_layout": {
  "mode": "dynamic",
  "field": "layout",
  "id": 201,
  "control_type": "sliderex",
  "window": ["widgetsettings"],
  "label": "Layout"
}
```

`field: "layout"` means this control reads and writes the `layout` field on whichever runtime entry is currently focused. The config key for option lookup is resolved through the mapping's `config_fields` template (e.g. `widget_{widget_preset}_layout` → `widget_next_up_layout`).

---

## The item picker role

A control with `"role": "item_picker"` does two things:

**As a control**, it lets the user pick from the mapping's `items` list — selecting which preset the current entry uses (e.g. "next_up", "latest_movies", "custom").

**As a signal**, its presence tells the Dynamic Editor that this window manages runtime state entries. When the editor sees an item picker, it enables the management buttons (add, delete, move up/down, reset, close). Without one, the editor assumes a static window.

When the user picks a different preset, the editor refreshes the other controls, resets invalid field values to defaults, and updates the list label.

---

## Onclick configuration

The `onclick` object on button controls defines what happens when the user presses select:

| Field | Description |
|---|---|
| `type` | Action type (see below) |
| `heading` | Dialog title |
| `items` | Override items (if omitted, uses the linked config's items) |
| `then` | Optional chained action (item picker only — see below) |
| `folder` | Starting folder for `browse_image` |
| `result_field` | For dialogs that return dicts: which key from the result becomes the control's own value (default: `path`). See [browse_content](#browse_content-and-sibling-fields). |
| `sibling_fields` | For dialogs that return dicts: which result keys go to which other controls' fields. |
| Plus various type-specific options | `browseType`, `shares`, `mask`, `useThumbs`, `treatAsFolder`, `default`, `enableMultiple`, `mode`, `action`, etc. |
```

### Action types

| Type | Description |
|---|---|
| `select` | Selection dialog from the items list |
| `browse` | Kodi browse dialog (files/directories) |
| `browse_single` | Single-select browse dialog |
| `browse_multiple` | Multi-select browse dialog |
| `browse_content` | Recursive content path browser (library, playlists, addons, custom paths) |
| `browse_image` | Image picker dialog. Returns a single path string. See [browse_image](#browse_image) below. |
| `colorpicker` | Kodi colour picker dialog |
| `input` | Keyboard input dialog |
| `numeric` | Numeric input dialog |
| `custom` | Executes an arbitrary Kodi built-in command |

### `browse_content` and sibling fields

The `browse_content` action returns a dict containing `path`, `label`, and optionally `icon`, `type`, `window`, `action`. Use `sibling_fields` to auto-populate other runtime state fields from the result:

```json
"onclick": {
  "type": "browse_content",
  "heading": "Select content path",
  "mode": "widget",
  "sibling_fields": { "label": "widget_label" }
}
```

When the user picks a path, the `label` from the browse result is written to the `widget_label` control's runtime field — but only if that field is currently empty, so a user-set label is preserved.

### `browse_image`
 
Opens Kodi's image browser for picking a single image file. Returns the chosen path as a plain string — not a dict — so `result_field` and `sibling_fields` don't apply. The path is written directly to the control's own field.
 
```json
"widget_icon": {
  "mode": "dynamic",
  "field": "icon",
  "id": 201,
  "control_type": "button",
  "window": ["widgetsettings"],
  "label": "Icon",
  "onclick": {
    "type": "browse_image",
    "folder": "special://skin/media/icons/genres/"
  }
}
```
 
| Field | Description |
|---|---|
| `folder` | Starting path the picker opens at. Use `special://` paths to point at skin-bundled icons. |
 
For finer control over the picker (file masks, thumbnail mode, etc.), use `browse_single` with `browseType: "images"` instead — see the menu icon control in `controls_menus.json` for a worked example.

### Chained actions: `then`

An `item_picker` button can chain a follow-up action when a specific preset is picked. Map preset names to other controls' names; picking that preset runs the named control's onclick before the entry is inserted.

```json
"widget_preset": {
  "mode": "dynamic",
  "role": "item_picker",
  "id": 200,
  "control_type": "button",
  "window": ["widgetsettings"],
  "onclick": {
    "type": "select",
    "heading": "Choose widget",
    "then": { "custom": "widget_content" }
  },
  "label": "Choose type"
}
```

In this example, picking the `custom` preset while adding a new widget runs the `widget_content` browse dialog as a chained step. A new custom widget never lands with an empty content path. If the user cancels the chained dialog, the whole insert is cancelled.

---

## Visibility conditions

The `visible` field supports `{placeholder}` substitution and is evaluated by the [Rule Engine](08-rule-engine.md) at runtime:

```json
"widget_label": {
  "mode": "dynamic",
  "visible": "In({widget_preset}, [custom])",
  "..."
}
```

This control is only visible when the current entry's preset is `custom`. The editor re-evaluates visibility every time the focused entry changes.

---

## Next

- [Includes Builder](07-includes.md) — Recursive XML template expansion