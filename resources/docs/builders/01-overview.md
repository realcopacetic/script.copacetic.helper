# Builder System Overview

The builder system generates Kodi skin XML and JSON files from compact JSON or XML templates. Instead of writing hundreds of repetitive `<variable>`, `<expression>`, and `<include>` elements by hand — or maintaining sprawling settings files — you define your intent once and the builders expand it using loops, placeholder substitution, conditional logic, and metadata injection.

The system is general-purpose. Use a single builder in isolation (e.g. just variables), or chain them together for features like per-content-type view settings or user-configurable widget systems.

---

## What the builders produce

| Builder | Input format | Output file | Purpose |
|---|---|---|---|
| **Configs** | JSON | `configs.json` | Resolves which options are valid for each setting |
| **Controls** | JSON | `controls.json` | Defines the controls that appear in a Dynamic Editor window |
| **Variables** | JSON | `script-copacetic-helper_variables.xml` | Generates Kodi `<variable>` elements |
| **Expressions** | JSON | `script-copacetic-helper_expressions.xml` | Generates Kodi `<expression>` elements |
| **Includes** | XML | `script-copacetic-helper_includes.xml` | Generates parameterised `<include>` calls |

Configs and controls produce intermediate JSON used by the Dynamic Editor at runtime. Variables, expressions, and includes produce final XML that Kodi loads as part of the skin.

### Following a single value through the system

To see how the builders connect, here's how the `layout` field on a widget slot flows from definition to output. One field, four builders.

**1. The mapping** declares that widgets have a `layout` field, and links it to a config key template:

```json
"config_fields": {
  "layout": "widget_{widget_preset}_layout"
}
```

**2. The configs builder** resolves which layouts are available for each preset. Album-style presets exclude `fanart` and `poster`; everything else gets all four:

```json
"widget_{widget_preset}_layout": {
  "mode": "dynamic",
  "items": ["list", "showcase", "strip", "grid"],
  "defaults": { "*": "strip" }
}
```

Output in `configs.json`:
```json
"widget_next_up_layout": { "items": ["list", "showcase", "strip", "grid"], "default": "strip" }
```

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

The Dynamic Editor reads `configs.json` to populate the slider with the allowed layouts, and reads/writes the `layout` field in `runtime_state.json` when the user makes a selection.

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
| `prep` | First boot, or when source files change | Configs |
| `build` | After prep, or on skin install/update | Controls, Variables, Includes, Expressions |
| `runtime` | When the user closes a Dynamic Editor window | Includes, Expressions |

`prep` and `build` are **skinner contexts** — they run during skin development and the outputs are packaged with the skin. When a user installs the skin, `configs.json`, `controls.json`, the three XML files, and a default `runtime_state.json` are already in place.

`runtime` is the **user context** — it runs after a user changes settings in a Dynamic Editor (e.g. rearranging widgets, changing a widget's layout). Only the outputs that depend on user configuration get rebuilt, and `ReloadSkin()` is called so changes take effect immediately.

Skinners can trigger a full rebuild during development via the addon's settings (Dev mode) or a script action.

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

Outputs are written to two locations:

- **XML outputs** → `16x9/` (the skin's resolution folder), where Kodi picks them up as includes
- **JSON intermediates** → `addon_data/script.copacetic.helper/` (the addon's user data folder)

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

Each builder applies its own logic on top of this core expansion — configs filter items by rules, expressions build boolean chains, includes recurse into nested XML structures, and so on.

---

## Static vs dynamic mode

Configs, controls, expressions, and includes templates can declare a `"mode"` field that changes how loop values are sourced:

**Static mode (default)** — the builder iterates once per item in the mapping's `items` list (or dict). The number of outputs is fixed at build time. Setting values are stored as Kodi skin strings — one skin string per setting per item. Suits features where the set is known up front, like per-content-type view settings.

**Dynamic mode** — the builder iterates once per entry in `runtime_state.json` for the mapping. The number of iterations grows and shrinks with what the user has configured. Setting values are stored as fields on those runtime entries, not as skin strings. Suits multi-instance features where the user adds and removes instances at runtime: widgets, menu items.

The variables builder always expands from its own `items` or `index`; mode doesn't apply.

The advantage of dynamic mode over skin strings is there's no predetermined limit on the number of instances. A skinner defines a "custom" widget once and the user can create as many instances as they want — each with its own content path, label, and layout. With skin strings, you'd need to pre-allocate a fixed number of slots.

---

## Next steps

- [Mappings](02-mappings.md) — The loop definitions that drive every builder
- [Variables Builder](03-variables.md) — The simplest builder
- [Expressions Builder](04-expressions.md) — Boolean logic with fallbacks
- [Configs Builder](05-configs.md) — Option filtering and defaults
- [Controls Builder](06-controls.md) — Dynamic Editor UI definitions
- [Includes Builder](07-includes.md) — Recursive XML template expansion
- [Rule Engine](08-rule-engine.md) — The condition evaluator
- [Runtime State & Dynamic Editor](09-runtime-state.md) — User-facing settings
- [Chaining Builders](10-use-cases.md) — Worked examples