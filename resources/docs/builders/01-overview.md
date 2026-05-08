# Builder System Overview

The builder system generates Kodi skin XML and JSON files from compact JSON or XML templates. Instead of writing hundreds of repetitive `<variable>`, `<expression>`, and `<include>` elements by hand — or maintaining sprawling settings files — you define your intent once and the builders expand it using loops, placeholder substitution, conditional logic, and metadata injection.

The system is general-purpose. Use a single builder in isolation (e.g. just variables), or chain them together for features like per-content-type view settings or user-configurable widget systems.

If you're new here, start with the [Quickstart](00-quickstart.md) — one feature, end to end, in five short steps.

---

## What the builders produce

| Builder | Input format | Output | Purpose |
|---|---|---|---|
| **Configs** | JSON | Resolved on demand | Resolves which options are valid for each setting |
| **Controls** | JSON | Resolved on demand | Defines the controls that appear in a Dynamic Editor window |
| **Variables** | JSON | `script-copacetic-helper_variables.xml` | Generates Kodi `<variable>` elements |
| **Expressions** | JSON | `script-copacetic-helper_expressions.xml` | Generates Kodi `<expression>` elements |
| **Includes** | XML | `script-copacetic-helper_includes.xml` | Generates parameterised `<include>` calls |

Configs and controls don't produce files — their templates are resolved on demand by the Dynamic Editor when a settings window opens. Variables, expressions, and includes produce final XML that Kodi loads as part of the skin.

---

## How the parts connect

```
                         mappings/
                             |
              +--------------+---------------+
              |              |               |
              v              v               v
         configs/        controls/      expressions/, includes/, variables/
              |              |               |
              |              |               v
              |              |         XML outputs (variables, expressions, includes)
              |              |               |
              +------+-------+               |
                     |                       |
                     v                       |
           runtime_state.json  <----+        |
                     ^              |        |
                     |              |        |
               Dynamic Editor  -----+        |
               (resolves templates,          |
                reads/writes state)          |
                                             v
                                       Kodi skin XML
                                       ($VAR / $EXP / <include>)
```

- **Mappings** declare the loop values and placeholder names.
- **Configs and controls** define the editor UI: what options exist, what the user can change. Resolved on demand from templates when an editor window opens.
- **Variables, expressions, and includes** produce the XML the skin actually consumes.
- **Runtime state** stores user-managed lists (widgets, menus). The Dynamic Editor writes it; includes and expressions read it.

### Following a single value through the system

Here's how the `layout` field on a widget slot flows from definition to output. One field, four builders.

**1. The mapping** declares that widgets have a `layout` field, and links it to a config key template:

```json
"config_fields":
  "global": {
    "layout": "widget_{widget_preset}_layout"
  }
```

**2. The configs builder** resolves which layouts are available for each preset:

```json
"widget_{widget_preset}_layout": {
  "mode": "dynamic",
  "items": ["list", "showcase", "strip", "grid"],
  "defaults": { "*": "strip" }
}
```

The Dynamic Editor resolves this template against each widget preset on demand — so `widget_next_up_layout` returns `["list", "showcase", "strip", "grid"]` with default `"strip"` when the editor opens.

**3. The controls builder** defines a slider control bound to this field:

```json
"widget_layout": {
  "mode": "dynamic",
  "field": "layout",
  "id": 201,
  "control_type": "sliderex",
  "label": "Layout"
}
```

The Dynamic Editor resolves the configs template to populate the slider with the allowed layouts, and reads/writes the `layout` field in `runtime_state.json` when the user makes a selection.

**4. The runtime state** captures the user's choice:

```json
{
  "runtime_id": "f6698793-...",
  "mapping_item": "next_up",
  "layout": "strip"
}
```

**5. The includes builder** reads this entry and substitutes `{layout}` into the template:

```xml
<include content="lst_{layout}">
```

Output:
```xml
<include content="lst_strip">
  <!-- ... params from metadata and runtime state ... -->
</include>
```

One value — defined in a mapping, filtered by configs, selected by the user through a control, stored in runtime state, and substituted into the final include. Each builder handles its part without knowing about the others.

---

## The pipeline

The builders run at different stages of the skin's lifecycle, controlled by **run contexts**:

| Context | When it runs | Builders active |
|---|---|---|
| `build` | First boot, on skin install/update, or when source files change | Variables, Includes, Expressions |
| `runtime` | When the user closes a Dynamic Editor window | Includes, Expressions |

`build` is the **skinner context** — it runs during skin development and the XML outputs are packaged with the skin. When a user installs the skin, the three XML files and a default `runtime_state.json` are already in place.

`runtime` is the **user context** — it runs after a user changes settings in a Dynamic Editor (e.g. rearranging widgets, changing a widget's layout). Only the outputs that depend on user configuration get rebuilt, and `ReloadSkin()` is called so changes take effect immediately.

---

## Development workflow

How builds are triggered in production vs development, and how to rebuild on demand while you're working.

### Production mode (default)

When `dev_mode` is off, the background service runs at Kodi start and only builds outputs that are missing on disk. A clean install runs the full pipeline once; every subsequent start skips straight to the pre-built outputs and the skin loads instantly. `ReloadSkin()` is not called.

This is the right configuration for shipped skins — end users don't pay the build cost on every boot.

### Dev mode

Found at **Settings → Developers → Enable Dev mode** (in the addon settings, not the skin settings).

With dev mode on, the service rebuilds everything in the `build` context with `force_rebuild=True` every time Kodi starts, then calls `ReloadSkin()`. Use this while iterating: every Kodi start gives you a fresh build, no manual step required.

### Reset on next start

Sub-toggle of dev mode at **Settings → Developers → Reset on next start**. Visible only when dev mode is on.

When set, the service deletes `runtime_state.json` and every builder output file on the next start, then rebuilds from scratch. The toggle clears itself after being applied.

Use this when you've changed a mapping's `default_order`, `config_fields`, or `metadata` and want the runtime state regenerated from defaults rather than carrying over the user's (or your test) existing list.

### Rebuild now

Button at **Settings → Developers → Rebuild now**. Visible only when dev mode is on.

Triggers a full `build` immediately and reloads the skin. Preserves `runtime_state.json` (unlike Reset on next start). A notification confirms when it's done.

Under the hood this runs the script action below — wire it into your own button or keymap if you want a quicker path than opening addon settings.

### Script actions

These can be triggered from anywhere — skin XML button onclicks, keymaps, custom shortcuts, the Dynamic Editor:

| Script | What it does |
|---|---|
| `RunScript(script.copacetic.helper,action=rebuild)` | Regenerates all builder outputs from current runtime state and skin strings, then reloads. Preserves user preferences. This is what the Dynamic Editor runs on close. |
| `RunScript(script.copacetic.helper,action=rebuild,full=true)` | Full rebuild with `force_rebuild=True`. Re-seeds any unset skin strings and adds missing runtime entries from `default_order`. Reloads and notifies. Same as the Rebuild now button. |
| `RunScript(script.copacetic.helper,action=rebuild,reset=true)` | Deletes `runtime_state.json` and all builder outputs, then full-rebuilds from defaults. Reloads and notifies. Use after changing a mapping's `default_order`, `config_fields`, or `metadata` if you want a clean slate. |

### Suggested workflow

1. Turn dev mode on while you're working on the skin.
2. Edit your builder inputs in `extras/builders/*/`.
3. Either restart Kodi or hit Rebuild now — same result, no restart needed for the second.
4. If you've changed a dynamic mapping's structure (added items, changed `config_fields`, reordered `default_order`), also tick Reset on next start before you restart so runtime state regenerates from your new defaults.
5. Turn dev mode off before shipping. Users will get the pre-built outputs instantly on first install.

---

## Folder structure

All builder input files live under the skin's `extras/builders/` directory:

```
extras/
└── builders/
    ├── mappings/         ← Custom mapping definitions (JSON)
    ├── configs/          ← Configs builder inputs (JSON)
    ├── controls/         ← Controls builder inputs (JSON)
    ├── variables/        ← Variables builder inputs (JSON)
    ├── expressions/      ← Expressions builder inputs (JSON)
    └── includes/         ← Includes builder inputs (XML)
```

Each subfolder can hold any number of input files. The system merges all files in a folder and groups them by their `"mapping"` key, so you can organise inputs however suits your skin — one file per feature, one per mapping, or all in one.

The three XML outputs go to `16x9/` (the skin's resolution folder), where Kodi picks them up as includes. The Dynamic Editor's runtime state lives at `addon_data/script.copacetic.helper/runtime_state.json`.

---

## The substitution engine

Every builder uses the same core mechanism. A **mapping** declares loop values and placeholder names. Each input template contains `{placeholder}` tokens. The builder generates a substitution dictionary for each loop value and formats the template strings.

Mapping items can be a **flat list** or a **dictionary of lists**:

**Flat list** — for simple iteration. A skinner-defined mapping for widgets:

```json
{
  "items": ["next_up", "in_progress", "latest_movies", "custom"],
  "placeholders": { "key": "widget_preset" }
}
```

A template named `widget_{widget_preset}_layout` expands to `widget_next_up_layout`, `widget_in_progress_layout`, etc.

**Dictionary of lists** — for two-level relationships. The built-in `content_types` mapping models Kodi windows and their content types:

```json
{
  "items": {
    "videos": ["movies", "sets", "tvshows", "seasons", "episodes"],
    "music": ["artists", "albums", "songs"]
  },
  "placeholders": { "key": "window", "value": "content_type" }
}
```

A template named `{content_type}_layout` expands once per inner value (`movies_layout`, `tvshows_layout`, `albums_layout`, etc.). Both `{window}` and `{content_type}` are available in templates, so a condition like `In({content_type}, [songs])` can filter on content type while a name like `{window}_views_include_{item}` groups results by window.

### Auto-injected placeholders

In addition to the mapping's own placeholders, every substitution gets three loop-position values injected automatically:

| Placeholder | Description |
|---|---|
| `{count}` | Total number of substitutions in this expansion |
| `{is_first}` | `"true"` on the first substitution, `"false"` otherwise |
| `{is_last}` | `"true"` on the last substitution, `"false"` otherwise |

Useful for conditional rendering — suppressing a separator on the last item, sizing a list control to fit `{count}` entries, applying special styling on the first row, and so on. Strings rather than booleans, so they slot directly into Kodi conditions: `String.IsEqual({is_last},true)`.

In dynamic mode templates, an `{index}` placeholder is also injected (one per runtime entry, starting from `<index start="N">` if declared).

### Arithmetic in placeholders

Placeholders can contain arithmetic expressions instead of bare names. When a placeholder doesn't match a substitution key directly, the builder evaluates it as a numeric expression against the current substitution dict:

```
{index}        → 3201
{index+2002}   → 5203
{count*100}    → 1200
{min(count*100, 800)}  → 800
```

Supported: `+`, `-`, `*`, `/`, `//`, `%`, unary minus, parentheses, and the functions `min()` and `max()`. Used in production for control IDs derived from a base index (e.g. paired focus latches at `{index+2002}`).

Placeholders that don't match a substitution key and don't evaluate as a numeric expression resolve to an empty string.

---

## Static vs dynamic mode

Configs, controls, expressions, and includes templates can declare a `"mode"` field that changes how loop values are sourced:

**Static mode (default)** — the builder iterates once per item in the mapping's `items` list (or dict). The number of outputs is fixed at build time. Setting values are stored as Kodi skin strings — one skin string per setting per item. Suits features where the set is known up front, like per-content-type view settings.

**Dynamic mode** — the builder iterates once per entry in `runtime_state.json` for the mapping. The number of iterations grows and shrinks with what the user has configured. Setting values are stored as fields on those runtime entries, not as skin strings. Suits multi-instance features where the user adds and removes instances at runtime: widgets, menu items.

All template-driven builders (configs, controls, variables, expressions, includes) honour `mode`. Variables in dynamic mode iterate once per runtime entry — see `params_focus_widgets` in `variables_widgets.json`.

The advantage of dynamic mode over skin strings is there's no predetermined limit on the number of instances. A skinner defines a "custom" widget once and the user can create as many instances as they want — each with its own content path, label, and layout. With skin strings, you'd need to pre-allocate a fixed number of slots.

---

## Picking a path

| You want | Read |
|---|---|
| A walkthrough of one feature, end to end | [Quickstart](00-quickstart.md) |
| Reference for one builder | [Mappings](02-mappings.md), then the per-builder doc |
| A per-content-type setting | [Use case 2: Views](10-use-cases.md#2-views--static-skin-string-driven) |
| A user-managed list (widgets, menus) | [Use case 3: Widgets](10-use-cases.md#3-widgets--dynamic-runtime-state-driven) |
| Just generate variables for repeated XML | [Use case 1: Standalone variables](10-use-cases.md#1-standalone-variables) |

---

## Reference docs
 
Field tables, behaviour notes, and corner cases. Use these when you know what you need; not the place to start.
 
- [Mappings](02-mappings.md) — The loop definitions that drive every builder
- [Variables Builder](03-variables.md) — The simplest builder
- [Expressions Builder](04-expressions.md) — Boolean logic with fallbacks
- [Configs Builder](05-configs.md) — Option filtering and defaults
- [Controls Builder](06-controls.md) — Dynamic Editor UI definitions
- [Includes Builder](07-includes.md) — Recursive XML template expansion
- [Rule Engine](08-rule-engine.md) — The condition evaluator
- [Runtime State & Dynamic Editor](09-runtime-state.md) — User-facing settings
- [Chaining Builders](10-use-cases.md) — Worked examples