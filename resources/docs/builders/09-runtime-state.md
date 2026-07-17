# Runtime State & Dynamic Editor

Two halves: the **settings file** (`runtime_state.json`) where every user choice lives, and the **editor windows** that write it. The file first — it exists and matters even if you never open a window.

---

## The settings file

One list of entries per dynamic mapping:

```json
{
  "widgets": [
    {
      "runtime_id": "e1b39d85-a10b-5672-a48e-296db8bc1e38",
      "mapping_item": "latest_movies",
      "parent": "3ad35bab-f50e-5752-be73-c515e4f6b555",
      "layout": "strip"
    }
  ]
}
```

- `runtime_id` — the entry's permanent id.
- `mapping_item` — which mapping item this is an instance of.
- `parent` — the owning entry's id, for [hub](07-includes.md#hubs-each-parent-owns-its-own-children) mappings.
- Everything else — settings the user has actually changed.

### Life of the file

**Created** on first run: every dynamic mapping gets entries from its `default_order` (or full `items`). Each entry stores its identity plus the item's string metadata — nothing else.

**Settings appear when changed.** An untouched setting isn't stored; it reads its config default live, every time. Two consequences worth knowing: changing a default in your templates instantly reaches every entry the user never overrode, and an entry in the file tells you exactly what the user has deliberately set — nothing more.

**Ids are stable where it counts.** Automatic entries (first creation, and every reset) get the *same* id every time — derived from the mapping and item name, not random. Reset the list and the ids come back identical, so baked XML references and parent links keep working. Entries the *user* adds get random ids, because there's nothing stable to derive them from.

### Parent links

A child item's metadata names its parent by item name (`"parent": "movies"`). When entries are created, that name is swapped for the parent entry's id. From then on the link is by id, so reordering either list changes nothing.

Two maintenance behaviours keep links sane:

- **Reset remaps.** Resetting the *parent* mapping recreates its entries with the same ids — and any children pointing at a surviving parent are re-linked to the fresh entry. Children whose parent didn't survive the reset are removed.
- **Deletes prune orphans.** Deleting an entry also removes any children in other mappings that pointed at it, so no widget lingers attached to a menu item that's gone.

### Reset vs rebuild

They're different operations and the difference matters:

| | Keeps user choices? | Regenerates output XML? |
|---|---|---|
| **Rebuild** (`action=rebuild`, editor close, dev-mode start) | Yes | Yes |
| **Reset** (`reset=true`, dev-mode "Reset on next start", the editor's Reset button) | No — back to defaults | Yes |

Changed a mapping's `default_order`, `metadata`, or `config_fields` and want the *list itself* regenerated? That's a reset. A rebuild only re-reads what's already in the file.

---

## Opening a settings window

```
RunScript(script.copacetic.helper,action=dynamic_settings_window,name=widgetsettings,mapping=widgets)
```

`name` = your window XML filename. `mapping` = which mapping this window edits. Two optional extras:

**`parent=<runtime_id>`** — stamp the session to one hub: only that parent's entries appear, adds arrive with `parent` already set and slot in next to their siblings, and moves, deletes, and Reset stay inside the hub. The full walkthrough — why, the template handshake, and the resolved output — is in [Includes → Hubs](07-includes.md#hubs-each-parent-owns-its-own-children).

**`controls_from=<mapping>`** — also load another mapping's controls into this window. For when two mappings share a shape and one window serves both — the shutdown menu borrows the main menu's controls:

```
RunScript(script.copacetic.helper,action=dynamic_settings_window,name=menusettings,mapping=shutdownmenu,controls_from=mainmenu)
```

Every control in the session edits the *session's* mapping, whoever it was borrowed from. Only borrow when the fields really match — a borrowed control naming a field the mapping doesn't have will create it on first write.

---

## Fixed vs editable

**Fixed list** (view settings): no control has a `role`. One row per automatic entry; the user edits each row's settings but the list itself never changes.

**Editable list** (widgets, menus): one control has `role: "item_picker"` or `"add_action"` — see [Controls → The Add control](06-controls.md#the-add-control-item_picker-and-add_action). The management buttons appear and the user adds, deletes, and reorders.

The right-hand controls work the same in both: each edits one setting on the highlighted row. Writes happen immediately as the user changes things — Close doesn't "save", it just ends the session.

---

## What your window XML must contain

| Control | ID | Purpose |
|---|---|---|
| List | 100 | The left-hand list. Filled automatically. |
| Textbox / label | 6 | Description text at the bottom. Set automatically. |
| Your controls | as declared | IDs matching each control template's `id`. A sliderex also needs its button at the id + a trailing `0`. |
| Colour labels | 420 / 421 | Optional. Hidden labels whose *text* names your focused / unfocused colours; used to tint sliderex value text. White / 50% white if absent. |
| Management buttons | 410–415 | Only needed for editable lists. Hidden otherwise. |

| Button | ID | Does |
|---|---|---|
| Add | 410 | Run the Add control's dialog, then insert. Cancel = nothing written. |
| Move up | 411 | Swap with the row above |
| Move down | 412 | Swap with the row below |
| Delete | 413 | Remove the row (disabled when only one is left) |
| Reset | 414 | Back to defaults — the whole mapping, or just the open hub — with a confirm dialog |
| Close | 415 | Save and close |

You only supply focusable buttons; the editor handles the presses.

### A minimal window XML

Strip the styling from this and it won't work; add styling and it will:

```xml
<?xml version="1.0" encoding="utf-8"?>
<window type="dialog" id="1105">
  <controls>
    <control type="list" id="100">
      <!-- your geometry, itemlayout and focusedlayout; label from ListItem.Label,
           icon from ListItem.Icon -->
      <onright>200</onright>
    </control>

    <control type="grouplist" id="101">
      <onleft>100</onleft>
      <!-- one control per template, ids matching: -->
      <control type="button" id="200" />          <!-- e.g. the Add control -->
      <control type="slider" id="202" />          <!-- sliderex: slider... -->
      <control type="button" id="2020" />         <!-- ...plus its label button -->
      <control type="radiobutton" id="203" />
      <control type="edit" id="206" />
    </control>

    <control type="grouplist" id="102">
      <control type="button" id="410" />  <!-- Add -->
      <control type="button" id="411" />  <!-- Up -->
      <control type="button" id="412" />  <!-- Down -->
      <control type="button" id="413" />  <!-- Delete -->
      <control type="button" id="414" />  <!-- Reset -->
      <control type="button" id="415" />  <!-- Close -->
    </control>

    <control type="textbox" id="6" />     <!-- description -->
  </controls>
</window>
```

Controls a template declares but the XML lacks are skipped and hidden — the window still opens, that control just never appears. (See [Troubleshooting](11-troubleshooting.md).)

---

## Asking about the editor from skin XML

While a window is open, two properties sit on `Window(home)`:

| Property | Value |
|---|---|
| `<name>` | `"true"` — "this window is open" |
| `current_mapping` | the session's mapping |

```
!String.IsEmpty(Window(home).Property(menusettings))
String.IsEqual(Window(home).Property(current_mapping),shutdownmenu)
```

Both clear on close. When an editor is opened *inside* another (with `parent=`), its mapping property gets the parent id as a suffix — `current_mapping_<uuid>` — so inner and outer don't fight over the name. The open flag stays plain. In a template that already has `{runtime_id}`, you can target the inner one directly:

```
String.IsEqual(Window(home).Property(current_mapping_{runtime_id}),tabs)
```

---

## On close

If anything changed, the includes and expressions rebuild and `ReloadSkin()` fires — changes show immediately. Nested editors wait for the outermost one to close, so a whole session reloads once.