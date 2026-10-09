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

## Where the files live

Everything the builder reads lives in your skin, under `extras/templates/`:

| Folder | Holds | Format |
|---|---|---|
| `mappings/` | The lists you loop over | JSON |
| `configs/` | Allowed values and defaults for each setting | JSON |
| `controls/` | The settings window controls | JSON |
| `variables/` | Variable templates | JSON |
| `expressions/` | Expression templates | JSON |
| `includes/` | Include templates | XML |

Every `*.json` (or `*.xml` for includes) file directly inside a folder is read, in file-name order. Sub-folders are not read. Having at least one of these folders is how a skin opts in: the service only runs the builder, and everything else it does (see [Background Service](../service/index.md#opting-in)), for a skin that has one. The helper's context menu items also show only in such a skin.

The builder writes three files into your skin's `16x9/` folder:

| File | Use with |
|---|---|
| `script-copacetic-helper_variables.xml` | `$VAR[name]` |
| `script-copacetic-helper_expressions.xml` | `$EXP[name]` |
| `script-copacetic-helper_includes.xml` | `<include>name</include>` |

Include each one once from your skin. The addon also keeps two files in its own profile folder (`special://profile/addon_data/script.copacetic.helper/`): `runtime_state.json` (the settings file) and `resolver_cache.json` (a copy of your mappings, configs and controls that the settings windows read).

---

## When things build

| When | What runs |
|---|---|
| Kodi starts, or the user switches to your skin (production) | The settings file gains entries for any `dynamic` mapping it doesn't have yet. If that happened, or the resolver cache is missing or belongs to another skin, everything is rebuilt. Otherwise only output files that are missing are built. If anything was built, `ReloadSkin()` follows. |
| Kodi starts, or the user switches to your skin (dev mode) | Everything is rebuilt, then `ReloadSkin()` |
| User closes a settings window with changes | Everything is rebuilt, then `ReloadSkin()` |
| `action=rebuild` | Everything is rebuilt, then `ReloadSkin()` |
| A settings window opens | Configs and controls are read from the resolver cache, which every build refreshes. Nothing is built. |

"Everything" means all three output files and the resolver cache. The start-up check runs each time your skin becomes active.

---

## Working on your skin

**Production (default):** the service only builds what is missing, as above. Fast starts for users: the skin reloads only on a start that built something.

**Dev mode** (Addon Settings → Developers): rebuild everything on every Kodi start, then reload the skin.

**Reset on next start** (sub-toggle of dev mode): also deletes the settings file, the resolver cache and all outputs first, so everything regenerates from defaults. Clears itself after running. You need a reset only when the *list of entries* should change: a new `items` or `default_order` on an existing dynamic mapping, or a changed `parent` in metadata. Other metadata and `config_fields` are read live, so a rebuild picks them up. A brand-new dynamic mapping gets its entries on the next start without a reset.

**Rebuild from anywhere:**

| Script | Effect |
|---|---|
| `RunScript(script.copacetic.helper,action=rebuild)` | Rebuild everything, keep user settings, reload |
| `RunScript(script.copacetic.helper,action=rebuild,reset=true)` | Delete the settings file, resolver cache and outputs, rebuild from defaults, reload |

---

## Placeholders

Templates use `{curly_brace}` tokens. The builder fills them in, once per loop pass. Available:

- The mapping's declared names — `{content_type}`, `{widget_preset}`, …
- Everything in the current item's `metadata` — `{label}`, `{window}`, …
- Everything on the entry, when the mapping is `dynamic` — stored values, config defaults for unset fields, and `{runtime_id}` / `{parent}`
- `{index}` — on a `dynamic` mapping always (counting from 1, or from the template's `index` start); on a static mapping only when the template declares `index`
- `{range}` when the template declares `range`, `{item}` when it declares `items`, and the borrowed mapping's own names when it declares `items_from`
- `{count}`, `{is_first}`, `{is_last}` — total loop size and position after filtering, as strings (`"true"`/`"false"` for the last two) you can drop straight into Kodi conditions
- Simple maths on whole numbers: `{index+2002}`, `{index*10}`, `{min(count*100, 800)}`. Operators: `+ - * / // %`, brackets and a leading minus; functions: `min`, `max`, `ceil`, `sqrt`. Every name in the sum must hold a whole number.
- The mapping's `tokens` — see [Mappings → tokens](02-mappings.md#tokens--shared-snippets-for-borrowing-templates)
- `{@mapping:item.field}` — reach into *any* mapping's metadata directly, no loop required: `{@windows:{window}.window_is}` reads the `window_is` field from the windows item named by `{window}` (inner tokens fill first). The field must be a string.

Tokens can nest: inner braces fill first. There is no escape for a literal `{`: any `{…}` in a template is read as a token.

**When a token can't be filled in**, what happens depends on where it is:

| Where | Unknown token |
|---|---|
| Template names, `filter`, and inside a mapping's `tokens` | The build stops with an error naming the token and the template |
| Values: variable rows, expression rules, include bodies | Becomes an empty string (and an empty include param or attribute is dropped) |
| `{@mapping:item.field}`, anywhere | The build stops — an unknown mapping, item or field, or a non-string field, can't silently become an empty string |

**Who wins when names collide.** Each pass builds one dictionary of values, and lookups go: the pass's own values first — loop names, item metadata, entry fields (dynamic mode) — then the mapping's `tokens` underneath. A token never overrides something the pass already knows. Tokens are themselves rendered against the pass before they're added, so they can contain placeholders and `{@…}` reaches (`"slot_range": "{@views:{layout}.slot_range}"` on Copacetic's widgets mapping fills from each entry's `layout`). `{@…}` values, by contrast, are looked up and pasted literally — anything inside them is *not* rendered again, so `"range": "{slot_range}"` on a borrowed item stays as those twelve characters. Rule of thumb: caller-dependent placeholders go in the caller's tokens, never in the borrowed field. And a token can stand in for a placeholder the template expects but the pass doesn't supply — see [Mappings → tokens](02-mappings.md#tokens--shared-snippets-for-borrowing-templates).

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
