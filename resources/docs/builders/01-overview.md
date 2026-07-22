# Overview

The builder system writes the repetitive parts of your skin for you: variables, expressions, and include calls. It also powers the settings windows (the Dynamic Editor) where users configure views, widgets, and menus.

The pieces:

- **Mappings** — the lists you loop over, and what each item knows about itself.
- **Configs and controls** — the settings UI: what options exist, what the user can change.
- **Variables, expressions, includes** — templates that turn into skin XML.
- **The settings file** (`runtime_state.json`) — where every user choice is stored. The editor writes it; the builders read it.

---

## One value, start to finish

How a widget's `layout` setting travels through the system:

**1. The mapping** says widgets have a `layout` field, and names the config that governs it:

```json
"config_fields": { "global": { "layout": "{widget_preset}_layout" } }
```

**2. The config** says which layouts each preset allows:

```json
"{widget_preset}_layout": {
  "items": { "strip": "Strip", "grid": "Grid", "showcase": "Showcase" },
  "defaults": { "*": "strip" }
}
```

**3. The control** gives the user a slider for it:

```json
"widget_layout": { "field": "layout", "id": 202, "control_type": "sliderex", "label": "Layout" }
```

**4. The settings file** stores the choice:

```json
{ "runtime_id": "f6698793-...", "mapping_item": "next_up", "layout": "strip" }
```

**5. The includes template** puts it in your skin:

```xml
<include content="ctn_{layout}">  →  <include content="ctn_strip">
```

---

## When things build

| When | What runs |
|---|---|
| First boot / skin install or update | Variables, includes, expressions |
| User closes a settings window with changes | Includes and expressions rebuild, then `ReloadSkin()` |
| A settings window opens | Configs and controls are read from the resolver cache — refreshed by every build; nothing new is "built" |

---

## Working on your skin

**Production (default):** the service only builds files that are missing. Fast starts for users, no reloads.

**Dev mode** (Addon Settings → Developers): rebuild everything on every Kodi start, then reload the skin.

**Reset on next start** (sub-toggle of dev mode): also deletes the settings file and all outputs first, so everything regenerates from defaults. Use after changing a mapping's `default_order`, `config_fields`, or `metadata`. Clears itself after running.

**Rebuild from anywhere:**

| Script | Effect |
|---|---|
| `RunScript(script.copacetic.helper,action=rebuild)` | Rebuild everything, keep user settings, reload |
| `RunScript(script.copacetic.helper,action=rebuild,reset=true)` | Wipe settings and outputs, rebuild from defaults |

---

## Placeholders

Templates use `{curly_brace}` tokens. The builder fills them in, once per loop pass. Available:

- The mapping's declared names — `{content_type}`, `{widget_preset}`, …
- Everything in the current item's `metadata` — `{label}`, `{window}`, …
- Everything stored on the entry, when looping the settings file — `{layout}`, `{content}`, …
- `{index}` when the template declares an index range
- `{count}`, `{is_first}`, `{is_last}` — total loop size and position, as `"true"`/`"false"` strings you can drop straight into Kodi conditions
- Simple maths on numbers: `{index+2002}` — handy for derived control IDs

A token that can't be filled in is left as-is, so mistakes show up in the output instead of disappearing.

---

## The three kinds of mapping

A mapping's `mode` plus one control decide everything about how it behaves:

| Mapping `mode` | Has an Add control? | What you get |
|---|---|---|
| `static` | — | Loop values for building only. Nothing stored, no settings window. (Example: `windows`.) |
| `dynamic` | No | A **fixed list**: entries created automatically, user edits each entry's settings but can't add or remove. (Example: view settings.) |
| `dynamic` | Yes | An **editable list**: user adds, deletes, and reorders entries. (Example: widgets, menus.) |

"An Add control" means one control in the window carries `role: "item_picker"` or `role: "add_action"` — see [Controls](06-controls.md#the-add-control-item_picker-and-add_action). Its presence is the only thing that separates a fixed list from an editable one.

Put simply: anything that gets a settings window must be `dynamic`. `static` mappings exist only as loop fuel for the builders.

Two useful details:

- **Nothing is stored as a Kodi skin string.** Every user choice is a field on an entry in the settings file. When skin XML outside the editor needs to read one, declare a [skin mirror](02-mappings.md#skin_mirrors--let-skin-xml-read-a-runtime-value) — the skin setting is a one-way projection; the entry stays the source of truth.
- **Automatic entries get the same ids every time.** Reset the list and the ids come back identical, so anything referencing them (parent links, baked XML) keeps working. Entries the *user* adds get random ids.

The payoff over old-style pre-allocated skin strings: an editable list has no size limit. You define a "custom" widget once; the user makes as many as they like.

---

## The docs

- [Quickstart](00-quickstart.md) — one feature, end to end. Start here.
- [Mappings](02-mappings.md) — the lists behind everything
- [Variables](03-variables.md) — the simplest builder
- [Expressions](04-expressions.md) — combined boolean conditions
- [Configs](05-configs.md) — allowed values and defaults
- [Controls](06-controls.md) — the settings UI
- [Includes](07-includes.md) — filling your own includes with data
- [Rule Engine](08-rule-engine.md) — the condition language
- [Runtime State & Dynamic Editor](09-runtime-state.md) — the settings file and windows
- [Use cases](10-use-cases.md) — three worked examples
- [Troubleshooting](11-troubleshooting.md) — symptom → cause → fix