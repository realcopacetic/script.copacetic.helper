# Controls Builder

Controls templates define the settings UI: the rows in the left-hand list, and the controls on the right that edit whichever row is highlighted. Each control reads and writes one setting on the highlighted entry.

---

## Input

JSON files in `extras/templates/controls/`:

```json
{
  "mapping": "widgets",
  "controls": {
    "widget_layout": {
      "field": "layout",
      "id": 202,
      "control_type": "sliderex",
      "label": "Layout",
      "description": "Choose from available layouts."
    }
  }
}
```

| Field | Required | What it does |
|---|---|---|
| `mapping` | Yes | Mapping name |
| `control_type` | Yes | `listitem`, `button`, `sliderex`, `slider`, `radiobutton`, `edit`, `cycle` |
| `id` | Yes* | The control's ID in your window XML (*not for listitems) |
| `field` | No | Which setting this control edits |
| `role` | No | `"item_picker"` or `"add_action"` — makes this the Add control, see below |
| `label`, `label2` | No | Text (supports `{tokens}` and `$LOCALIZE[]`) |
| `description` | No | Help text shown at the bottom of the window |
| `icon` | No | Row icon (listitems only) |
| `visible` | No | Show/hide condition, re-checked as the user moves and edits |
| `onclick` | No | What a button does — see [Onclick](#onclick) |
| `textcolor`, `focusedcolor`, `disabledcolor`, `shadowcolor` | No | Hex colours or `$INFO[]` |

The allowed values for a `field` come from the mapping's `config_fields` — the control just names the field. (See [One setting, four names](00-quickstart.md#one-setting-four-names) if that chain is fuzzy.)

---

## Control types

### `listitem` — the rows

Not interactive itself; it describes the rows in the left-hand list. One template covers every row — the editor makes one row per entry and fills the tokens per entry:

```json
"content_type_item": {
  "control_type": "listitem",
  "label": "{content_type}",
  "icon": "icons/{content_type}.png",
  "description": "Configure view settings for {content_type}."
}
```

In editable lists, label and icon usually come from stored settings so the user can set their own:

```json
"widget_{index}": {
  "control_type": "listitem",
  "label": "{label}",
  "icon": "{icon}",
  "description": "Select widget to configure."
}
```

### `button`

Runs its `onclick` when pressed:

```json
"widget_icon": {
  "field": "icon",
  "id": 201,
  "control_type": "button",
  "label": "Icon",
  "onclick": { "type": "browse_image", "folder": "special://skin/media/icons/genres/" }
}
```

### `sliderex` — slider with a label

Kodi sliders can't show text, so this pairs a slider with a button: the button shows the name and current value, the slider takes left/right, select flips focus between them. **The button's ID is the slider's ID with a `0` on the end** (202 → 2020). Your window XML must follow this.

```json
"widget_layout": { "field": "layout", "id": 202, "control_type": "sliderex", "label": "Layout" }
```

### `radiobutton` — on/off

First allowed value = on, second = off. Disables itself when filtering leaves only one option.

```json
"art_clearlogo": {
  "field": "art_clearlogo",
  "id": 203,
  "control_type": "radiobutton",
  "visible": "In({content_type}, [movies, sets, tvshows, artists])",
  "label": "$LOCALIZE[31443]"
}
```

### `edit` — free text

Kodi keyboard input; saves on select or when the user moves away:

```json
"widget_label": {
  "field": "label",
  "id": 206,
  "control_type": "edit",
  "label": "Widget name",
  "visible": "In({widget_preset}, [custom, drilldown, group])"
}
```

### `cycle` — step through values

Each press moves to the next allowed value, wrapping at the end. For short lists where a slider is overkill. Disables itself below two options.

```json
"widget_sortorder": {
  "field": "sortorder",
  "id": 208,
  "control_type": "cycle",
  "label": "Sort order",
  "visible": "In({widget_preset}, [custom])"
}
```

---

## The Add control: `item_picker` and `add_action`

Give exactly one control a `role` and the window becomes an **editable list**: the Add / Delete / Move / Reset buttons appear and the user manages the entries. No role anywhere → fixed list, no buttons.

The role also decides what pressing **Add** does. Two flavours:

### `item_picker` — "which kind?"

Adding means picking one of your presets. The widget editor:

```json
"widget_preset": {
  "role": "item_picker",
  "id": 200,
  "control_type": "button",
  "onclick": { "type": "select", "heading": "Choose widget" },
  "label": "Change type"
}
```

Add opens the picker; the new entry is created from the chosen preset's metadata. Pressing the same control on an *existing* entry changes its preset: the entry is rebuilt for the new shape, invalid settings snap to defaults, the row label updates. Picking the same preset again does nothing.

### `add_action` — "do what?"

Adding means running one dialog whose result *is* the entry. The menu editor — there are no menu presets; adding a menu item means browsing to what it should do:

```json
"menu_action": {
  "field": "action",
  "role": "add_action",
  "id": 201,
  "control_type": "button",
  "label": "Shortcut",
  "onclick": {
    "type": "browse_content",
    "heading": "Select shortcut",
    "mode": "menu",
    "result_field": "action",
    "sibling_fields": { "label": "menu_label", "icon": "menu_icon" }
  }
}
```

Either way the dialog runs **before** anything is written — cancel and nothing changes.

---

## Onclick

A button's `onclick` names an action `type` plus options:

| Type | What happens |
|---|---|
| `select` | Choice dialog over the control's allowed values (shown with their labels) |
| `browse_content` | The addon's content browser — returns a path plus extras (label, icon, target, …) |
| `browse_image` | Kodi's image browser, opened at `folder` |
| `browse` / `browse_single` / `browse_multiple` | Kodi's generic file browsers |
| `input` / `numeric` | Keyboard / number entry |
| `colorpicker` | Kodi's colour picker |
| `custom` | Run a Kodi builtin from `action`. Tokens fill from the highlighted entry, so `parent={runtime_id}` works. |

Useful options beyond `heading` and `default`:

**`result_field`** — which part of a `browse_content` result this control's own field gets (default: the path).

**`sibling_fields`** — send other parts of the result to other fields in the same go:

```json
"sibling_fields": { "label": "widget_label", "target": "target" }
```

The browse result's label lands on the field behind the `widget_label` control; its target lands on the entry's `target` field. One dialog, several fields filled.

**`then`** (item_picker only) — chain a second dialog for certain picks during Add:

```json
"onclick": {
  "type": "select",
  "heading": "Choose widget",
  "then": { "custom": "widget_content" }
}
```

Picking `custom` while adding runs the `widget_content` browse dialog before the entry is created — so a new custom widget never arrives with an empty content path. Cancel the second dialog and the whole add is cancelled.

---

## Visibility

`visible` uses the [Rule Engine](08-rule-engine.md) and re-checks live, so controls can react to the highlighted entry's other settings:

```json
"visible": "In({widget_preset}, [custom, drilldown]) + not equals({layout}, marquee)"
```

Use `xml(...)` for live Kodi state — for example, only showing a control when the window is editing a particular mapping:

```json
"visible": "xml(String.IsEqual(Window(home).Property(current_mapping),mainmenu))"
```

---

## Next

- [Includes](07-includes.md) — turning the entries these controls edit into skin XML
