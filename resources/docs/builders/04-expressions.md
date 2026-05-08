# Expressions Builder

The expressions builder generates Kodi `<expression>` elements — named boolean expressions that can be referenced in skin XML with `$EXP[expression_name]`. It supports conditional rules, group-based fallbacks, and automatic boolean inversion.

The classic case: per-content-type visibility logic. Instead of writing one expression per content type for every layout × window combination, you define a compact template and the builder produces all the combinations.

---

## Input format

JSON files placed in `extras/builders/expressions/`. Each file declares a mapping and an `expressions` object:

```json
{
  "mapping": "content_types",
  "expressions": {
    "layout_{item}_include_{window}": {
      "items": ["list", "showcase", "strip", "grid"],
      "rules": [
        {
          "condition": "xml(Skin.String({content_type}_layout,{item}))",
          "type": "assign",
          "value": "true"
        }
      ],
      "fallback_key": "window",
      "fallbacks": {
        "*": { "target_item": "list", "value": "true" }
      }
    }
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `mapping` | string | Yes | Mapping name. Either built-in (`content_types`), a custom one in `extras/builders/mappings/`, or `"none"` — see [Mappings](02-mappings.md). |
| `items` | list | No | Values to loop over within each mapping group |
| `index` | object | No | Numeric range (alternative to `items`) |
| `rules` | list | Yes | Condition/type/value rules to evaluate |
| `fallback_key` | string | No | Placeholder name used to group expressions for fallback logic |
| `fallbacks` | object | No | Per-group fallback definitions |
| `mode` | string | No | `"dynamic"` to iterate once per runtime entry. Default is static, which iterates once per item in the mapping. |

---

## Rules

Each rule has three fields:

| Field | Description |
|---|---|
| `condition` | Evaluated by the [Rule Engine](08-rule-engine.md). Supports `{placeholder}` substitution. |
| `type` | Either `"assign"` or `"append"` |
| `value` | The expression value to use. Supports `{placeholder}` substitution. |

**`assign`** — if the condition is true, the value becomes the entire expression result and processing stops. Use when only one rule should ever match.

**`append`** — if the condition is true, the value is added to a list. After all rules and substitutions are processed, the collected values are joined with ` | ` (Kodi's OR operator). Use when multiple substitutions should contribute to a combined condition.

If no rules match for a given substitution, the expression defaults to `"false"`.

---

## Example: layout include expressions

This template determines which layout include is active for each window:

```json
"layout_{item}_include_{window}": {
  "items": ["list", "showcase", "strip", "grid"],
  "rules": [
    {
      "condition": "xml(Skin.String({content_type}_layout,{item}))",
      "type": "assign",
      "value": "true"
    }
  ],
  "fallback_key": "window",
  "fallbacks": {
    "*": { "target_item": "list", "value": "true" }
  }
}
```

Using the `content_types` mapping (window → content_types), the builder loops every `(window, content_type, item)` combination. For `(videos, movies, list)`:

1. Template name resolves to `layout_list_include_videos`.
2. The condition checks: is `Skin.String(movies_layout)` set to `"list"`? If yes — and the type is `assign` — the expression becomes `"true"`.
3. The same expression name is also produced for every other content type in the videos window (`sets`, `tvshows`, `seasons`, etc.). Because `assign` short-circuits, any single matching content type makes the whole expression `"true"`.

Output:

```xml
<expression name="layout_list_include_videos">true</expression>
<expression name="layout_showcase_include_videos">false</expression>
<expression name="layout_strip_include_videos">false</expression>
<expression name="layout_grid_include_videos">false</expression>
```

---

## Example: layout visibility expressions

The companion template uses `append` instead of `assign` to build a combined visibility condition:

```json
"layout_{item}_visible_{window}": {
  "items": ["list", "showcase", "strip", "grid"],
  "rules": [
    {
      "condition": "xml(Skin.String({content_type}_layout,{item}))",
      "type": "append",
      "value": "Container.Content({content_type})"
    }
  ],
  "fallback_key": "window",
  "fallbacks": {
    "*": { "target_item": "list", "value": "invert()" }
  }
}
```

For `layout_fanart_visible_videos`, suppose the user has set `movies_layout = fanart` and `tvshows_layout = fanart` but everything else to something different. The append rule fires for those two content types, contributing `Container.Content(movies)` and `Container.Content(tvshows)` to the list:

```xml
<expression name="layout_fanart_visible_videos">
  Container.Content(movies) | Container.Content(tvshows)
</expression>
```

The expression is true exactly when the active container is a content type configured for fanart — automatically generated, automatically updated when the user changes a setting.

---

## Fallbacks

When a substitution produces no matches (no rule fires), the expression defaults to `"false"`. Fallbacks let one item in each group act as a catch-all instead.

The fallback system needs to know which expressions belong to a "group" — typically all the items for one window. That's the `fallback_key`: the name of a placeholder whose value defines the group:

```json
"fallback_key": "window"
```

With `fallback_key: "window"`, all `layout_*_visible_videos` expressions form one group, all `layout_*_visible_music` form another, and so on.

Within a group, the `fallbacks` object names the **target item** that should act as catch-all and the **value** to put in it.

### Fallback walkthrough

For the visibility template above:

```json
"fallbacks": {
  "*": { "target_item": "list", "value": "invert()" }
}
```

After processing, suppose `layout_showcase_visible_videos` resolves to `Container.Content(movies)` and `layout_grid_visible_videos` resolves to `Container.Content(tvshows)`. Both `layout_list_visible_videos` and `layout_strip_visible_videos` resolved to `"false"`.

The fallback says: in every group, `list` is the catch-all, with value `invert()`. The builder collects the non-false values from the rest of the group and produces:

```xml
<expression name="layout_list_visible_videos">
  ![Container.Content(movies) | Container.Content(tvshows)]
</expression>
```

Now `list` is visible for any content type that doesn't have a specific layout assigned.

### Literal fallback values

For include expressions, the fallback typically uses `"value": "true"`:

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

The `videos` window group falls back to `fanart`; all other windows fall back to `square`.

---

## On-demand rebuilds

Expressions are rebuilt:

- During skin development on every Kodi start (when dev mode is on)
- When the user closes a Dynamic Editor window and runtime state or skin strings have changed
- Manually via `RunScript(script.copacetic.helper,action=rebuild)`

Every rebuild includes an automatic `ReloadSkin()` call. Kodi caches include file contents at load time, so writing the new XML to disk isn't enough on its own — even navigating between windows won't pick up the changes. `ReloadSkin()` forces Kodi to re-read all include files.

---

## Build-time conditions, runtime values

The most important concept: **the builder evaluates conditions at build time, but the output values are themselves conditions that Kodi evaluates at runtime**.

When a rule's condition uses `xml(Skin.String(...))`, the builder checks the current skin string value at build time. If the condition is true, the rule's value — typically a runtime condition like `Container.Content(movies)` — is written into the output. The result is that build-time state (which skin strings are set to what) gets baked into compact runtime conditions. The builder does the combinatorial work once; Kodi gets a simple expression to evaluate every frame.

In Copacetic 1, the equivalent logic was handled with one hand-written expression per (view, layout, content_type) combination plus a master expression to combine them — verbose, error-prone, and painful to maintain. The builder replaces that with a single template that handles every combination automatically.

---

## Output format

The builder writes `script-copacetic-helper_expressions.xml`. Output keys are sorted alphabetically (case-insensitive):

```xml
<?xml version='1.0' encoding='utf-8'?>
<includes>
  <expression name="art_fanart_include_videos">true</expression>
  <expression name="art_fanart_visible_videos">Container.Content(movies) | Container.Content(tvshows)</expression>
  <expression name="layout_list_include_videos">true</expression>
  <expression name="layout_list_visible_videos">![Container.Content(movies)]</expression>
  <expression name="layout_showcase_visible_videos">Container.Content(movies)</expression>
  <!-- ... -->
</includes>
```

Reference them in your skin XML with `$EXP[expression_name]`. Add the file to your skin's `Includes.xml`:

```xml
<include file="script-copacetic-helper_expressions.xml" />
```

---

## Next

- [Configs Builder](05-configs.md) — How valid options are resolved per setting