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

The file's `mapping` names the mapping these controls edit. Each key under `controls` is the control's name; it only matters for `then` and `sibling_fields` (below), and names should be unique across the mappings one window loads.

| Field | Required | What it does |
|---|---|---|
| `control_type` | Yes | `listitem`, `button`, `sliderex`, `slider`, `radiobutton`, `edit`, `cycle`. Anything else is skipped. |
| `id` | Yes* | The control's ID in your window XML (*not for listitems). A control without one is skipped. |
| `field` | No | Which setting this control edits |
| `role` | No | `"item_picker"` or `"add_action"` — makes this the Add control, see below |
| `label`, `label2` | No | Text. Supports `{tokens}` and `$LOCALIZE[]` anywhere in the text; a value that then starts with `$` (`$INFO[]`) is resolved by Kodi. |
| `description` | No | Help text shown at the bottom of the window |
| `icon` | No | Row icon (listitems only) |
| `visible` | No | Show/hide condition, re-checked as the user moves and edits |
| `onclick` | No | What a button does — see [Onclick](#onclick) |
| `textcolor`, `focusedcolor`, `disabledcolor`, `shadowcolor` | No | Colour as `AARRGGBB` hex without `0x`, or `$INFO[...]` that returns one. Passed to the control; `textcolor` also tints label2 while the control isn't focused. |

The allowed values for a `field` come from the mapping's `config_fields` — the control just names the field. (See [One setting, four names](00-quickstart.md#one-setting-four-names) if that chain is fuzzy.)

**label2 defaults.** Controls with a `field` show their current value as label2 (the config's display label when it has one); the Add control (field-less, with a `role`) shows the highlighted entry's identity. Field-less controls *without* a role — plain navigation buttons — default to an empty label2. Declaring `"label2"` on the control (including `""`) overrides all of this.

### Tokens in the editor

`label`, `label2`, `description`, `icon`, `visible`, an onclick `action` and the `confirm` texts fill their `{tokens}` from the highlighted entry when the window draws them. Available: the entry's resolved fields (stored values, config defaults, string metadata), the mapping's `key` placeholder, all of the item's metadata, `{mapping}` (the mapping name) and `{index}` — here the entry's 0-based position in the settings file, not the build-time `{index}`. A field missing from the highlighted entry falls back to the first other entry in the mapping that has it.

Before the tokens are filled, each `$LOCALIZE[id]` in `label`, `label2`, `description`, `icon` and the `confirm` texts is replaced with its string. So a translated string can carry `{tokens}` of its own, for example a skin string `Delete {label}?`. After the tokens are filled, a value that starts with `$` is resolved by Kodi.

Editor tokens are plain `{name}` lookups. Maths, `{@mapping:item.field}` and nested tokens don't work here. If any token in a string is unknown, the whole string is used unchanged.

---

## Control types

### `listitem` — the rows

Not interactive itself; it describes the rows in the left-hand list. One template covers every row — the editor makes one row per entry and fills the tokens per entry. Use one `listitem` per mapping. It reads `label`, `icon` and `description` (shown when the focused control has no description of its own, for example on the list):

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

Each row also gets the entry's resolved string fields as list item properties (raw values, not display labels), plus `content_id` holding the entry's `runtime_id`: `Container(100).ListItem.Property(layout)`.

### `button`

Runs its `onclick` when pressed, and writes the result to its `field`:

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

Shows as selected when the stored value is `true`. Selecting it writes the first allowed value; deselecting it writes the second — so give its config `items` with `true` first and `false` second. Disables itself when filtering leaves only one option.

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

Kodi keyboard input; saves on select, or when the user moves away or presses Back. `label` is passed to the control as its label. Shows the stored value, or the item's metadata value for the field when nothing is stored:

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

Give exactly one control a `role` and the window becomes an **editable list**: the Add / Move / Delete buttons attach and the user manages the entries. No role anywhere → fixed list: the addon hides the mutation buttons and never acts on them, even if your window XML has them. Reset and Close aren't part of this — they work in every window (see [Runtime State → window XML](09-runtime-state.md#what-your-window-xml-must-contain)).

The role also decides what pressing **Add** does. Two flavours:

### `item_picker` — "which kind?"

Adding means picking one of your presets: the mapping's items, or the onclick's own `items` list if it has one. Each is shown with its config label, else its metadata `label`, else its name with `_` replaced by spaces in title case. Copacetic's widget editor:

```json
"widget_preset": {
  "role": "item_picker",
  "id": 200,
  "control_type": "button",
  "onclick": { "type": "select", "heading": "Choose widget" },
  "label": "Change type"
}
```

Add opens the picker; the new entry is created from the chosen preset's metadata. Pressing the same control on an *existing* entry changes its preset: the entry is rebuilt from the new preset, keeping only its `runtime_id` and `parent`. Every other stored setting is dropped, so all settings go back to the new preset's defaults. Picking the same preset again does nothing.

### `add_action` — "do what?"

Adding means running one dialog whose result *is* the entry. The new entry is always created as the mapping's `custom` item, so the mapping needs an item named `custom`. The dialog's result is then written like a normal press of the control. Copacetic's menu editor — there are no menu presets; adding a menu item means browsing to what it should do:

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

A button's `onclick` names an action `type` plus options. Types are not case-sensitive; `browsesingle`, `browsemultiple` and `browseimage` are accepted spellings, and an unknown type runs `action` like `custom`. A dialog that returns an index (`select`) writes the matching value; cancelling writes nothing.

| Type | What happens |
|---|---|
| `select` | Choice dialog over the control's allowed values (shown with their labels) |
| `confirm` | Radiobutton and cycle only. Yes/no dialog (`heading`, `message`) that gates the control's own write: Yes → write, then the `yes` action list; No/cancel → nothing written, the `no` list runs if declared. With a `condition` (Rule Engine, against the highlighted entry), the dialog only appears when it is true; otherwise the write just happens. |
| `browse_content` | The addon's content browser — returns a path plus extras (label, icon, target, …). `mode`: `widget` (default) or `menu`, which adds menu shortcuts and also returns `type`, `window` and `action`. When `sibling_fields` maps `item_type`, it also returns the plural type of the items the path lists (`albums`, `movies`, else `unknown`), read from one short listing; `depth: 1` reads it inside the first folder instead, for widgets that show a level below their path. |
| `browse_image` | Kodi's image browser, opened at `folder` (required) |
| `browse` / `browse_single` / `browse_multiple` | Kodi's file browsers. `browseType`: `directories`, `files`, `images` or `writeable` (default `directories` for `browse`, `files` for the others). |
| `input` / `numeric` | Keyboard / number entry |
| `colorpicker` | Kodi's colour picker |
| `custom` | Run a Kodi builtin from `action`. Tokens fill from the highlighted entry, so `parent={runtime_id}` works. |
| `runtime_script` | Run a helper script action from `action` (bare name, e.g. `delete_orphans`), with optional `kwargs`. An unknown name does nothing. For actions that **mutate runtime state**: runs in-process and synchronously, then the session resyncs from disk — list, selection, and handlers all adopt whatever the action wrote. |

**Onclick on value controls.** Radiobuttons and cycles accept an `onclick` too,
Kodi-style. An ordinary type runs *after* the control's own write; `confirm` is
the one exception — it runs before and can cancel it. `yes`/`no` take lists of
ordinary onclick objects (same vocabulary, results discarded — they're side
effects, not writes).

### `runtime_script` vs `custom`

Both can trigger helper actions, but they declare different execution
contracts — pick by what the action *does*, not by preference:

- **`runtime_script`** — the action mutates runtime state. It runs on the session's
  thread against current disk state (editor writes are immediate, so disk is
  the truth), and the resync afterwards is one shared path everywhere the
  onclick vocabulary is accepted: buttons and `confirm` `yes`/`no` lists
  alike. The list redraw is unconditional — deterministic runtime_ids mean a
  reseed can change every value without changing a single key. Selection
  survives when its entry still exists; a wholesale reseed re-anchors to the
  top. If the action's own dialog is cancelled, nothing is written and the
  resync is a harmless redraw.

- **`custom`** — fire-and-forget Kodi builtins, and the *only* correct choice
  for actions that need their own interpreter: `dynamic_settings_window`
  buttons must stay `custom`, because opening a modal in-process would nest
  `doModal` on the handler callback thread — the exact hazard `RunScript`
  exists to avoid.

A `custom` `RunScript` that mutates runtime state is a race against the open
session and will surface as stale lists, skipped rebuilds, or partial
clobbers. If you find one, migrate it:

```json
{ "type": "custom", "action": "RunScript(script.copacetic.helper,action=delete_orphans,child_mapping=widgets,require_parent=true)" }
```

becomes

```json
{ "type": "runtime_script", "action": "delete_orphans", "kwargs": { "child_mapping": "widgets", "require_parent": "true" } }
```

Keep `kwargs` values as strings for `RunScript` parity — actions parse string
parameters either way.

Options the dialogs read, beyond `heading`:

| Option | Used by | What it does |
|---|---|---|
| `items` | `select` | Values to offer instead of the control's allowed values |
| `preselect` | `select` | Starting index. Default: the current value. |
| `autoclose`, `useDetails` | `select` | Passed to Kodi's select dialog |
| `default` | `input`, `numeric`, `colorpicker`, browse types | Starting value |
| `shares`, `mask`, `useThumbs`, `treatAsFolder`, `enableMultiple` | browse types | Passed to Kodi's browse dialog (`shares` default `files`) |
| `folder` | `browse_image` | Folder the browser opens in |
| `mode`, `result_field`, `sibling_fields` | `browse_content` | See above and below |
| `kwargs` | `runtime_script` | Parameters for the action |
| `then` | `item_picker` | See below |

The most useful:

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

Tokens fill in as described in [Tokens in the editor](#tokens-in-the-editor). Use `xml(...)` for live Kodi state — it must be the whole condition. For example, only showing a control when the window is editing a particular mapping:

```json
"visible": "xml(String.IsEqual(Window(home).Property(current_mapping),mainmenu))"
```

In a window opened with `parent=`, the property is `current_mapping_<parent runtime_id>` instead — see [Runtime State → Asking about the editor](09-runtime-state.md#asking-about-the-editor-from-skin-xml).

---

## Next

- [Includes](07-includes.md) — turning the entries these controls edit into skin XML
