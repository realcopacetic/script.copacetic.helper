# Controls Builder

The controls builder defines every interactive control that appears in a Dynamic Editor window. It handles three patterns: static controls that expand per-mapping-item, shared controls that bind to different configs based on list focus, and dynamic controls that read/write runtime state fields. Templates are resolved on demand when a settings window opens.

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
| `control_type` | string | Yes | One of: `listitem`, `button`, `sliderex`, `slider`, `radiobutton`, `edit`, `cycle` |
| `id` | integer | Yes* | Kodi control ID in the XML layout (*not required for listitems) |
| `window` | list | Yes | Window XML filenames this control belongs to |
| `mode` | string | No | `"dynamic"` to share one control across all runtime entries (each entry's field read/written when focused). Default is static, which expands once per item in the mapping. |
| `field` | string | No | Runtime state field name (for dynamic mode) |
| `role` | string | No | Special role identifier — `"item_picker"` or `"add_action"`. See [Governing roles](#governing-roles-item_picker-and-add_action). |
| `label` | string | No | Display label (supports `{placeholder}` tokens and `$LOCALIZE[]`) |
| `label2` | string | No | Secondary label |
| `description` | string | No | Help text shown at bottom of editor |
| `icon` | string | No | Listitem icon path (supports `{placeholder}` tokens). Listitems only. |
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

With the `content_types` mapping, this expands to `movies_item`, `tvshows_item`, `albums_item`, etc. Each gets a different icon path because `{content_type}` substitutes per row.

The `icon` field is the path Kodi loads for the row's icon image. In dynamic windows the icon usually comes from a runtime field (`"icon": "{icon}"`) so users can pick their own. In static windows it usually comes from the mapping (`"icon": "icons/{content_type}.png"`).

Dynamic listitems use `"mode": "dynamic"` and get their entries from `runtime_state.json`:

```json
"widget_{index}": {
  "mode": "dynamic",
  "control_type": "listitem",
  "window": ["widgetsettings"],
  "label": "{label}",
  "icon": "{icon}",
  "description": "Select widget to configure."
}
```

The `{label}` and `{icon}` tokens resolve from runtime fields or metadata at runtime — `$LOCALIZE[31201]` for "Next Up" or the user's custom label and icon path.

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

A standalone slider without the companion button. Works the same as `sliderex` — left/right cycles through allowed values from the linked config — but without the focus-toggle convention. Use this when the surrounding skin XML already provides the labelling, or when the value itself doesn't need a label.

```json
"limit": {
  "id": 220,
  "control_type": "slider",
  "window": ["widgetsettings"],
  "contextual_bindings": {
    "linked_config": "widget_limit",
    "update_trigger": "focused(widget_item)"
  }
}
```

Unlike `sliderex`, you don't need to follow the `id`-plus-`0` companion-button convention in your window XML.

### `radiobutton`

A toggle control for boolean settings. Reads the linked config's `items` and treats the first as "on" and the second as "off":

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

The radiobutton is automatically disabled when only one value is allowed — useful when filter rules collapse the set to a single option.

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

### `cycle`

A button that cycles through allowed values on each select press, wrapping at the end. Displays the current value as `label2`. Use this for short ordered lists where a slider feels heavy — sort order is the canonical case:

```json
"widget_sortorder": {
  "mode": "dynamic",
  "field": "sortorder",
  "id": 207,
  "control_type": "cycle",
  "window": ["widgetsettings"],
  "visible": "In({widget_preset}, [custom])",
  "label": "Sort order",
  "description": "Toggle between ascending and descending."
}
```

The control auto-disables when fewer than two values are available.

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

When the editor opens, `contextual_bindings` is resolved across all substitutions and deduplicated:

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

## Governing roles: `item_picker` and `add_action`

Every dynamic editor needs exactly one **governing control** — a control with `role: "item_picker"` or `role: "add_action"`. These are mutually exclusive. The governing control's presence tells the editor "this window manages runtime state entries", which enables the management buttons (add, delete, move up/down, reset, close). Without one, the editor assumes a static window.

The governing control's onclick dialog runs when the user presses Add — before any new entry is inserted. If the user cancels the dialog, nothing is written. The two roles model the two patterns for what "Add" means.

### `item_picker` — pick from a list of presets

Use when adding a new entry means choosing one of a fixed set of presets. The widget editor works this way: each preset (`next_up`, `latest_movies`, `custom`, …) is a known shape with associated metadata, and adding a widget means picking which preset to instantiate.

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

When the user picks a different preset on an existing entry, the editor refreshes the other controls, resets invalid field values to defaults, and updates the list label. When the user presses Add, the same dialog runs to choose the new entry's preset; the new entry is seeded from that preset's metadata.

### `add_action` — single action per entry

Use when adding a new entry means running a single action whose result *is* the entry. The menu editor works this way: there are no menu "presets" to pick from — adding a menu item means picking what it does (a library path, a script, a window). The result of the browse dialog becomes the new entry's data directly.

```json
"menu_action": {
  "mode": "dynamic",
  "field": "action",
  "role": "add_action",
  "id": 201,
  "control_type": "button",
  "window": ["menusettings"],
  "label": "Shortcut",
  "description": "Set the action for this menu item.",
  "onclick": {
    "type": "browse_content",
    "heading": "Select shortcut",
    "mode": "menu",
    "result_field": "action",
    "sibling_fields": {
      "label": "menu_label",
      "icon": "menu_icon"
    }
  }
}
```

When the user presses Add, this control's `onclick` runs. The result dict is applied to the newly inserted entry: `result_field: "action"` writes the action path to the entry's `action` field, and `sibling_fields` routes `label` and `icon` from the result to other fields.

The same control is used for editing existing entries — pressing it on an existing menu item lets the user pick a new shortcut.

### Picking between them

- The user is choosing from a fixed catalogue of preconfigured options → `item_picker`.
- The user is configuring something from scratch using a single dialog → `add_action`.

If you need both — a preset list plus a follow-up dialog for some presets — use `item_picker` with the `then` chained-action mechanism described under [Onclick configuration](#chained-actions-then) below.

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