# Expressions Builder

The expressions builder generates Kodi `<expression>` elements — named boolean expressions that can be referenced in skin XML with `$EXP[expression_name]`. Expressions are the most logic-heavy builder, supporting conditional rules, group-based fallbacks, and automatic boolean inversion.

---

## When to use it

Use the expressions builder when you need to generate sets of related boolean expressions from a common pattern. This is especially useful for visibility and include conditions that depend on skin string values across multiple content types or widget presets.

---

## Input format

Expression inputs are JSON files placed in `extras/builders/expressions/`. Each file declares a mapping and an `expressions` object:

```json
{
  "mapping": "content_types",
  "expressions": {
    "template_name_{item}": {
      "items": ["list", "showcase", "strip", "grid"],
      "rules": [
        {
          "condition": "xml(Skin.String({content_type}_view,{item}))",
          "type": "assign",
          "value": "true"
        }
      ],
      "fallback_key": "window",
      "fallbacks": {
        "*": {
          "target_item": "list",
          "value": "true"
        }
      }
    }
  }
}
```

### Template fields

| Field | Type | Required | Description |
|---|---|---|---|
| `items` | list | No | Values to loop over within each mapping group |
| `index` | object | No | Numeric range (alternative to `items`) |
| `rules` | list | Yes | Condition/type/value rules to evaluate |
| `fallback_key` | string | No | Placeholder name used to group expressions for fallback logic |
| `fallbacks` | object | No | Per-group fallback definitions |
| `mode` | string | No | `"static"` (default) or `"dynamic"` |

---

## Rules

Each rule in the `rules` array has three fields:

| Field | Type | Description |
|---|---|---|
| `condition` | string | A condition string evaluated by the [Rule Engine](08-rule-engine.md). Supports `{placeholder}` substitution. |
| `type` | string | Either `"assign"` or `"append"` |
| `value` | string | The expression value to use. Supports `{placeholder}` substitution. |

### Rule types

**`assign`** — If the condition evaluates to true, the value is used as the entire expression result. Processing stops immediately (short-circuit). Use this when only one value should ever match.

**`append`** — If the condition evaluates to true, the value is added to a list. After all rules are processed, the collected values are joined with ` | ` (Kodi's OR operator). Use this when multiple content types should contribute to a combined visibility condition.

If no rules match for a given substitution, the expression defaults to `"false"`.

---

## Example: view include expressions

This template determines which view include is active for each window:

```json
"{window}_views_include_{item}": {
  "items": ["list", "showcase", "strip", "grid"],
  "rules": [
    {
      "condition": "xml(Skin.String({content_type}_view,{item}))",
      "type": "assign",
      "value": "true"
    }
  ],
  "fallback_key": "window",
  "fallbacks": {
    "*": {
      "target_item": "list",
      "value": "true"
    }
  }
}
```

### How it expands

Using the `content_types` mapping (dict with window keys → content_type values), the builder processes each combination. For the `videos` window with `item: "list"`:

1. Template name becomes `videos_views_include_list`
2. The rule checks: for each content type in the videos window (movies, sets, tvshows, ...), is `Skin.String(movies_view, list)` true?
3. Since the rule type is `assign`, if any content type has "list" set, the expression becomes `"true"`.

This produces expressions like:
```xml
<expression name="videos_views_include_list">true</expression>
<expression name="videos_views_include_showcase">false</expression>
```

---

## Example: view visibility expressions

This companion template uses `append` instead of `assign` to build a combined visibility condition:

```json
"{window}_views_visible_{item}": {
  "items": ["list", "showcase", "strip", "grid"],
  "rules": [
    {
      "condition": "xml(Skin.String({content_type}_view,{item}))",
      "type": "append",
      "value": "Container.Content({content_type})"
    }
  ],
  "fallback_key": "window",
  "fallbacks": {
    "*": {
      "target_item": "list",
      "value": "invert()"
    }
  }
}
```

For `videos_views_visible_showcase`, if movies and tvshows both have "showcase" as their view:

```xml
<expression name="videos_views_visible_showcase">Container.Content(movies) | Container.Content(tvshows)</expression>
```

The expression is true when the active container content is either movies or tvshows — exactly the content types where showcase view is configured.

---

## Example: combining multiple rules

A template can have multiple rules that work together. Rules are evaluated in order for each substitution — an `assign` rule short-circuits immediately, while `append` rules accumulate. This lets you handle special cases and general cases in the same template:

```json
"{window}_feature_visible_{item}": {
  "items": ["standard", "enhanced", "minimal"],
  "rules": [
    {
      "condition": "In({content_type}, [songs])",
      "type": "assign",
      "value": "false"
    },
    {
      "condition": "xml(Skin.String({content_type}_feature,{item}))",
      "type": "append",
      "value": "Container.Content({content_type})"
    }
  ]
}
```

Here, the first rule short-circuits for songs — no matter what feature is configured, songs always get `"false"` (the feature is disabled). For all other content types, the second rule appends visibility conditions as normal. Because `assign` returns immediately, the `append` rule is never reached for songs.

---

## Fallbacks

Fallbacks ensure that one expression in each group always evaluates to `true`, acting as a catch-all default. They are applied after all rules have been processed.

### Configuration

| Field | Type | Description |
|---|---|---|
| `fallback_key` | string | The placeholder name used to group expressions. All expressions with the same value for this placeholder form a group. |
| `fallbacks` | object | Keys are group values (or `"*"` for all groups). Each entry has `target_item` and `value`. |

Within a fallback entry:

| Field | Description |
|---|---|
| `target_item` | The `item` value that should receive the fallback |
| `value` | Either a literal value (e.g. `"true"`) or the special token `"invert()"` |

### How `invert()` works

When `value` is `"invert()"`, the builder collects all other resolved expressions in the same group that aren't `"false"`, and generates a Kodi boolean inversion:

```
![Container.Content(movies) | Container.Content(tvshows) | Container.Content(sets)]
```

This means: the fallback item is visible when none of the other items are visible. It's the "everything else" logic.

### Walkthrough

Given the `videos` window with four view items (list, showcase, strip, grid):

1. After rule processing, suppose showcase has `Container.Content(movies)` and grid has `Container.Content(tvshows)`.
2. List and strip resolved to `"false"`.
3. The fallback says `target_item: "list"` with `value: "invert()"`.
4. The builder collects the non-false others: showcase and grid.
5. `videos_views_visible_list` becomes `![Container.Content(movies) | Container.Content(tvshows)]`.

Now the list view is visible for any content type that doesn't have a specific view assigned — it's the catch-all.

### Fallback with literal values

For include expressions (not visibility), the fallback typically uses `"value": "true"`:

```json
"fallbacks": {
  "*": { "target_item": "list", "value": "true" }
}
```

This makes the fallback item's include expression unconditionally true when no other item in the group matched.

### Per-group fallbacks

You can specify different fallback targets for different groups:

```json
"fallbacks": {
  "videos": { "target_item": "fanart", "value": "true" },
  "*": { "target_item": "square", "value": "true" }
}
```

Here, the `videos` window group falls back to `fanart`, while all other windows fall back to `square`.

---

## Static vs dynamic mode

In `"mode": "dynamic"`, the builder reads from `runtime_state.json` instead of the mapping's item list. Each runtime state entry provides a substitution dictionary that includes all stored fields (`mapping_item`, `view`, `layout`, etc.) plus `runtime|field` prefixed versions and the numeric `index`.

This allows expressions to be generated per-widget-slot rather than per-content-type — for example, visibility conditions based on what the user has configured for widget slot 3.

---

## On-demand rebuilds

The expressions builder can be triggered on demand — not just at skin build time. Expressions are rebuilt:

- At **build time** during skin development (`build` context)
- When the user **closes a Dynamic Editor window** and the runtime state has changed (`runtime` context)
- When triggered manually via script action:

```
RunScript(script.copacetic.helper,action=rebuild,context=runtime)
```

Every rebuild includes an automatic `ReloadSkin()` call. This is required because Kodi caches the contents of include files (including expressions) at load time — writing new XML to disk is not enough on its own. Even navigating between windows will not cause Kodi to re-read the file. A `ReloadSkin()` forces Kodi to reload all include files, picking up the newly generated expressions.

---

## Build-time evaluation, runtime values

This is the most important concept to understand about expressions: **the builder evaluates conditions at build time, but the output values are themselves conditions that Kodi evaluates at runtime**.

When a rule's condition uses `xml(Skin.String(...))`, the builder checks the current skin string value right now, at the moment of the build. If the condition is true, the rule's value — which is typically a runtime condition like `Container.Content(movies)` — is written into the expression output.

The result is that build-time state (which skin strings are set to what) gets baked into compact runtime conditions. The builder does the combinatorial work once, and Kodi gets a simple expression to evaluate on every frame.

### Before and after

To see why this matters, consider how Copacetic 1 handled layout visibility without the builder. Each view × layout × content type combination needed its own hand-written expression, plus a master expression to combine them all:

```xml
<expression name="StripView_Display_IsFanart">
  $EXP[StripView_Media_IsVisible] + [
    $EXP[StripView_Display_IsFanart_Movies] |
    $EXP[StripView_Display_IsFanart_Sets] |
    $EXP[StripView_Display_IsFanart_TVShows] |
    $EXP[StripView_Display_IsFanart_Seasons] |
    Container.Content(episodes) |
    Container.Content(videos) |
    $EXP[StripView_Display_IsFanart_Artists] |
    Container.Content(musicvideos) |
    $EXP[StripView_Display_IsFanart_Favourites]
  ]
</expression>
<expression name="StripView_Display_IsFanart_Movies">
  Container.Content(movies) + Skin.String(StripView_Display_Movies,Fanart)
</expression>
<expression name="StripView_Display_IsFanart_Sets">
  Container.Content(sets) + Skin.String(StripView_Display_Sets,Fanart)
</expression>
<!-- ... repeated for every content type, every layout, every view -->
```

Every content type needed a separate expression. Every view needed its own set. Adding a new content type or layout meant adding expressions across multiple files. The XML was verbose, error-prone, and painful to maintain.

In Copacetic 2, the builder evaluates `Skin.String({content_type}_layout, fanart)` for each content type at build time, then appends `Container.Content({content_type})` only for the ones where it's true. The entire tree of per-content-type sub-expressions collapses into a single line:

```xml
<expression name="videos_layouts_visible_fanart">
  ![Container.Content(movies) | Container.Content(tvshows)]
</expression>
```

One expression that covers all content types in the videos window, automatically generated from the same compact template that also handles every other view, layout, and window combination. If the user changes a setting in the Dynamic Editor, the builder re-evaluates, regenerates, and the skin refreshes — all in one step.

---

## Output format

The expressions builder writes `script-copacetic-helper_expressions.xml`. Output keys are sorted alphabetically (case-insensitive) for readability:

```xml
<?xml version='1.0' encoding='utf-8'?>
<includes>
  <expression name="music_layouts_include_fanart">false</expression>
  <expression name="music_layouts_include_poster">false</expression>
  <expression name="music_layouts_include_square">true</expression>
  <expression name="music_layouts_visible_fanart">false</expression>
  <expression name="music_layouts_visible_poster">false</expression>
  <expression name="music_layouts_visible_square">![false]</expression>
  <expression name="videos_views_include_list">true</expression>
  <expression name="videos_views_visible_list">![Container.Content(movies)]</expression>
  <expression name="videos_views_visible_showcase">Container.Content(movies)</expression>
  <!-- ... -->
</includes>
```

You reference these in your skin XML with `$EXP[expression_name]`. To make them available, add the generated file to your skin's `Includes.xml`:

```xml
<include file="script-copacetic-helper_expressions.xml" />
```

---

## Next

- [Configs Builder](05-configs.md) — How valid options are resolved per setting
