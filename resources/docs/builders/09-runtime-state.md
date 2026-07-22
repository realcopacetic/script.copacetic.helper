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

`name` = your window XML filename. `mapping` = which mapping this window edits. Four optional extras:

**`parent=<runtime_id>`** — stamp the session to one hub: only that parent's entries appear, adds arrive with `parent` already set and slot in next to their siblings, and moves, deletes, and Reset stay inside the hub. The full walkthrough — why, the template handshake, and the resolved output — is in [Includes → Hubs](07-includes.md#hubs-each-parent-owns-its-own-children).

**`controls_from=<mapping>`** — also load another mapping's controls into this window. For when two mappings share a shape and one window serves both — the shutdown menu borrows the main menu's controls:

```
RunScript(script.copacetic.helper,action=dynamic_settings_window,name=menusettings,mapping=shutdownmenu,controls_from=mainmenu)
```

Every control in the session edits the *session's* mapping, whoever it was borrowed from. Only borrow when the fields really match — a borrowed control naming a field the mapping doesn't have will create it on first write.

**`host=<window>` + `host_focus=<control id>`** — bind the session to a real window instead of floating it over whatever was open. The window becomes a shell whose only job is to open the editor — see [Hosting](#hosting--binding-an-editor-to-a-real-window).

---

## Hosting — binding an editor to a real window

The editor is a modal dialog, and sometimes that's the wrong shape: a dialog can't be a destination in the window stack, can't be tab-switched to with `ReplaceWindow`, and closing it lands wherever it was floating. Hosting makes an editor stand in for a real window — the skin-settings surface is the built-in example: `skinsettings` is a shell, and the `copaceticsettings` editor *is* the window as far as the user can tell.

**The invariant:** host visible ⇒ editor open. The shell is never a destination in its own right.

Two Kodi engine facts shape the design, and explain why the exits run through python instead of skin actions:

- `ReplaceWindow` is refused while any modal lives — a skin action list can't close-and-replace a python modal.
- `doModal()` returns ~200 ms before the GUI finishes tearing the dialog down, and until then builtins and infolabels address the dying dialog. The exit router waits for provable death before touching windows.

### The contract

| Hook | Who writes it | Typical value | Meaning |
|---|---|---|---|
| `host` (kwarg) | skin, at invocation | `skinsettings` | Names the shell, so the router can tell back-exit from external teardown |
| `host_focus` (kwarg) | skin, at invocation | `4610` | Control id where focus lands on open |
| `active_editor_name` (`Window(home)` property) | python | empty ↔ window name | Session gate — see below |
| `host_exit_target` (`Window(home)` property) | skin, at moment of intent | empty ↔ a window name | Exit verdict — see below |

**The session gate.** The shell's forwarding onload must be conditioned on the gate, or reloads under a closing dialog re-enter the session:

```xml
<onload condition="String.IsEmpty(Window(home).Property(active_editor_name))">RunScript(script.copacetic.helper,action=dynamic_settings_window,name=copaceticsettings,mapping=copacetic,host=skinsettings,host_focus=4610)</onload>
```

**The exit verdict.** Any control in the session may record a forwarding address — write a window name to `host_exit_target` and the editor closes itself; once the dialog is provably dead, the router runs `ReplaceWindow(<target>)`. Close with the verdict *empty* (Back on `host_focus`) and the router leaves the whole system with `Action(Back)`. Two verdicts, nothing else: forward, or leave.

```xml
<onright>SetProperty(host_exit_target,$INFO[Container(3000).ListItem(1).Property(window)],home)</onright>
```

The verdict is only read from actions issued while `host_focus` is focused — put the recording control there.

### What the shell needs

A background, an inert focus anchor, and the gated onload. Nothing else — the editor dialog carries the whole UI:

```xml
<control type="button" id="3"><!-- inert focus anchor -->
  <visible allowhiddenfocus="true">false</visible>
</control>
```

### Polish

Gate the editor window's close fade on the verdict so a forward is instant while a back-exit keeps its fade:

```xml
<param name="fadeout" value="String.IsEmpty(Window(home).Property(host_exit_target))" />
```

### Composition

Hosting composes with the other session kwargs. Editors opened *from inside* a hosted session (`parent=`, or plain drill-in buttons) behave as nested sessions: they skip the exit router, and the rebuild waits for the outermost — hosted — session to close, so a whole visit reloads once.

---

## Fixed vs editable

**Fixed list** (view settings): no control has a `role`. One row per automatic entry; the user edits each row's settings but the list itself never changes. The addon enforces this — without a role, the mutation buttons (410–413) are never attached, so Add, Move, and Delete are inert even if the window XML exposes them.

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
| Mutation buttons | 410–413 | Editable lists only — never attached without an Add control. |
| Reset / Close | 414–415 | Any window. Reset returns settings to defaults; Close ends the session. |

| Button | ID | Does |
|---|---|---|
| Add | 410 | Run the Add control's dialog, then insert. Cancel = nothing written. |
| Move up | 411 | Swap with the row above |
| Move down | 412 | Swap with the row below |
| Delete | 413 | Remove the row (disabled when only one is left) |
| Reset | 414 | Back to defaults — the whole mapping, or just the open hub — with a confirm dialog |
| Close | 415 | Save and close |

You only supply focusable buttons; the editor handles the presses. Only Add, Move up/down, and Delete require the Add control — Reset and Close work in fixed lists too.

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

Each row also carries its resolved entry — metadata, stored values, and config defaults — as listitem properties, raw keys not display labels: `String.IsEqual(Container(100).ListItem.Property(layout),strip)`. Properties re-stamp on every edit, so conditions track the session live.

---

## On close

If anything changed, the includes and expressions rebuild and `ReloadSkin()` fires — changes show immediately. Nested editors wait for the outermost one to close, so a whole session reloads once. Hosted sessions route their window exit before the rebuild, so the reload lands on the right window.