# Builder System Overview

The builder system is a Python-powered pipeline that generates Kodi skin XML and JSON files from skinner-defined templates. Instead of manually writing hundreds of repetitive `<variable>`, `<expression>`, and `<include>` elements — or maintaining countless skin strings and sprawling settings files — you define your intent once in small JSON or XML input files, and the builders expand them using loops, placeholder substitution, conditional logic, and metadata injection.

The system is fully generalised. Nothing about it is hardcoded to a specific use case. You can use a single builder in isolation (e.g. just variables), or chain multiple builders together to create complex features like per-content-type view settings, or user-configurable menu and widget systems.

---

## What the builders produce

There are five builder modules. Each reads input templates, processes them against a shared mapping definition, and writes output:

| Builder | Input format | Output file | Purpose |
|---|---|---|---|
| **Configs** | JSON | `configs.json` | Resolves which options are valid for each setting (e.g. which layouts are available for a given content type) |
| **Controls** | JSON | `controls.json` | Expands control definitions for the Dynamic Editor window |
| **Variables** | JSON | `script-copacetic-helper_variables.xml` | Generates Kodi `<variable>` elements with condition/value pairs |
| **Expressions** | JSON | `script-copacetic-helper_expressions.xml` | Generates Kodi `<expression>` elements for boolean visibility logic |
| **Includes** | XML | `script-copacetic-helper_includes.xml` | Expands Kodi `<include>` templates with recursive substitution |

The first two (configs, controls) produce intermediate JSON used by the Dynamic Editor UI at runtime. The last three (variables, expressions, includes) produce final XML that Kodi loads directly as part of the skin.

### Following a single value through the system

To see how the builders connect, let's trace the `view` setting for a widget slot from definition through to output. This is one field on one widget — but it passes through four builders on its way to the final skin XML.

**1. The mapping** defines that widgets have a `view` field, and links it to a config key template:

```json
"config_fields": {
  "view": "widget_{widget_preset}_view"
}
```

**2. The configs builder** resolves which views are available for each preset. For "next_up", all four views are allowed. For "liked_songs", rules exclude some:

```json
"widget_{widget_preset}_view": {
  "mode": "dynamic",
  "items": ["list", "showcase", "strip", "grid"],
  "defaults": { "next_up": "strip", "*": "grid" }
}
```

Output in `configs.json`:
```json
"widget_next_up_view": { "items": ["list", "showcase", "strip", "grid"], "default": "strip" }
```

**3. The controls builder** creates a slider control linked to this field:

```json
"widget_view": {
  "mode": "dynamic",
  "field": "view",
  "id": 201,
  "control_type": "sliderex",
  "label": "View"
}
```

At runtime, the Dynamic Editor reads `configs.json` to populate the slider with the allowed views, and reads/writes the `view` field in `runtime_state.json` when the user makes a selection.

**4. The runtime state** captures the user's choice. The user selected "strip" for their first widget:

```json
{
  "runtime_id": "912e...",
  "mapping_item": "next_up",
  "view": "strip",
  "layout": "poster"
}
```

**5. The includes builder** reads this entry and substitutes `{view}` into the template:

```xml
<param name="view" value="{view}" />
```

Output:
```xml
<include content="widget_next_up">
  <param name="view" value="strip" />
  <!-- ... other params from metadata and runtime state -->
</include>
```

One value — defined in a mapping, filtered by configs, selected by the user through a control, stored in runtime state, and substituted into the final include. Each builder handled its part without knowing about the others.

---

## The pipeline

The builders run at different stages of the skin's lifecycle, controlled by **run contexts**:

| Context | When it runs | Builders active |
|---|---|---|
| `prep` | On first boot or when source files change | Configs |
| `build` | After prep, or on skin install/update | Controls, Variables, Includes, Expressions |
| `runtime` | When the user closes a Dynamic Editor window | Includes, Expressions |

The `prep` and `build` contexts are **skinner contexts**. They run during skin development and the outputs are packaged with the skin — `configs.json`, `controls.json`, the three XML files, and a default `runtime_state.json`. When a user installs the skin, these files are already in place and ready to use.

The `runtime` context is the **user context**. It runs when a user makes changes through a Dynamic Editor window (e.g. rearranging widgets, changing a widget's view or content source). It rebuilds only the outputs that depend on user configuration — includes and expressions — then triggers a `ReloadSkin()` so changes take effect immediately. This is what makes the system interactive: the user edits settings in a dialog, and the skin updates live.

The `prep` context generates `configs.json`, which subsequent builders depend on for option lists and defaults. The `build` context produces all output files and initialises `runtime_state.json` with default entries. Skinners can trigger a full rebuild during development via the addon's settings (Dev mode) or a script action.

---

## Folder structure

All builder input files live under the skin's `extras/builders/` directory:

```
extras/
└── builders/
    ├── custom_mappings/       ← Custom mapping definitions (JSON)
    ├── configs/               ← Configs builder inputs (JSON)
    ├── controls/              ← Controls builder inputs (JSON)
    ├── variables/             ← Variables builder inputs (JSON)
    ├── expressions/           ← Expressions builder inputs (JSON)
    └── includes/              ← Includes builder inputs (XML)
```

Each subfolder can contain any number of input files. The system merges all files in a folder together, grouping them by their `"mapping"` key. This means you can organise inputs however you like — one file per feature, one per mapping, or all in one file.

Output files are written to two locations:

- **XML outputs** → `16x9/` (the skin's resolution folder), where Kodi picks them up as includes
- **JSON intermediates** → `addon_data/script.copacetic.helper/` (the addon's user data folder)

---

## How `BuildElements` orchestrates everything

The `BuildElements` class is the pipeline controller. When instantiated with a run context, it:

1. **Merges mappings** — Loads built-in mappings from `BUILDER_MAPPINGS` and any custom mappings from `extras/builders/custom_mappings/`.
2. **Merges inputs** — Uses `JSONMerger` and `XMLMerger` to lazily combine all input files across the relevant builder subfolders, grouped by their `"mapping"` key.
3. **Dispatches to builders** — For each mapping's data, it finds the matching builder module (from `BUILDER_CONFIG`), instantiates it, and calls `process_elements()` on each template.
4. **Writes outputs** — Collects all processed data per builder, then writes each to disk using the configured handler (JSON or XML).

If the run context is `build`, it also initialises `runtime_state.json` from mapping defaults and sets any unset skin strings to their default values.

---

## The substitution engine

At the heart of every builder is the same substitution mechanism. A **mapping** defines a set of loop values and placeholder names. Each input template contains `{placeholder}` tokens. The builder generates every combination of loop values, creates a substitution dictionary for each, and formats the template strings.

Mapping items can be either a **flat list** or a **dictionary of lists**, and the builder handles both:

**Dictionary of lists** — for two-level relationships. The built-in `content_types` mapping uses this to model Kodi windows and their content types:

```json
{
  "items": {
    "videos": ["movies", "sets", "tvshows", "seasons", "episodes"],
    "music": ["artists", "albums", "songs"]
  },
  "placeholders": { "key": "window", "value": "content_type" }
}
```

A template named `{content_type}_view` expands to `movies_view`, `sets_view`, `tvshows_view`, `artists_view`, `albums_view`, etc. — one per inner value. Both `{window}` and `{content_type}` are available in template strings, so a rule condition like `In({content_type}, [songs])` can filter based on the content type while an expression name like `{window}_views_include_{item}` groups results by window.

**Flat list** — for simple iteration. A skinner-defined mapping for widgets might look like this:

```json
{
  "items": ["next_up", "in_progress", "latest_movies", "latest_tvshows", "custom"],
  "placeholders": { "key": "widget_preset" }
}
```

A template named `widget_{widget_preset}_view` would then expand to `widget_next_up_view`, `widget_in_progress_view`, `widget_latest_movies_view`, etc.

Each builder then applies its own logic on top of this core expansion — configs filter items by rules, expressions evaluate conditions and build boolean chains, includes recurse into nested XML structures, and so on.

---

## Static vs dynamic mode

Some builders support a `"mode"` field on their templates that changes how loop values are sourced and where settings are stored. This applies to the **configs**, **controls**, **expressions**, and **includes** builders — not to the variables builder, which always expands from its own items/index definitions.

- **`static`** (default) — The builder loops over the mapping's `items` using standard substitution. Setting values are stored as **Kodi skin strings**, which have a fixed, one-to-one relationship: one skin string per setting per content type. This is ideal for features like view settings, where the number of content types is known at build time.

- **`dynamic`** — The builder reads entries from `runtime_state.json` instead of the mapping's item list. Each entry in the runtime state becomes a substitution set, with all its stored fields available as placeholders. Setting values are stored in the **runtime state JSON file** rather than as skin strings.

Dynamic mode is what makes features like user-configurable widgets possible. The key advantage over skin strings is that there is **no predetermined limit on the number of instances**. A skinner defines a "custom" widget template once, and the user can create as many instances of it as they want — each with its own content path, label, view, and layout. With skin strings, you would need to pre-allocate a fixed number of slots (Widget1, Widget2, ... WidgetN), each with its own set of strings, and the user could never exceed that limit.

Runtime state also makes management operations trivial. Reordering widgets is a list swap in JSON. Deleting a widget removes one entry. Adding a widget inserts a new entry with defaults. All of this happens instantly through the Dynamic Editor without the skinner needing to write any management logic.

---

## Next steps

- [Mappings](02-mappings.md) — The loop definitions that drive all builders
- [Variables Builder](03-variables.md) — The simplest builder, good for understanding the core concepts
- [Expressions Builder](04-expressions.md) — Boolean logic with fallbacks
- [Configs Builder](05-configs.md) — Option filtering and defaults
- [Controls Builder](06-controls.md) — Dynamic Editor UI definitions
- [Includes Builder](07-includes.md) — Recursive XML template expansion
- [Rule Engine](08-rule-engine.md) — The condition evaluator used across builders
- [Runtime State & Dynamic Editor](09-runtime-state.md) — User-facing settings management
- [Chaining Builders](10-use-cases.md) — Real-world examples combining multiple builders