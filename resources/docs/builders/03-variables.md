# Variables Builder

The variables builder is the simplest builder and a good starting point for understanding how the system works. It generates Kodi `<variable>` XML elements — each containing a list of condition/value pairs that Kodi evaluates at runtime to resolve a single value.

---

## When to use it

Use the variables builder when you need to generate many similar `<variable>` definitions that differ only by an index, content type, or other repeating pattern. Instead of writing each one by hand, you define a single template and let the builder expand it.

---

## Input format

Variable inputs are JSON files placed in `extras/builders/variables/`. Each file declares a mapping and a `variables` object containing one or more templates:

```json
{
  "mapping": "none",
  "variables": {
    "template_name{index}": {
      "index": { "start": -3, "end": 6 },
      "values": [
        {
          "condition": "some condition using {index}",
          "value": "some value using {index}"
        },
        {
          "condition": "true",
          "value": "fallback value"
        }
      ]
    }
  }
}
```

### Template fields

| Field | Type | Required | Description |
|---|---|---|---|
| `index` | object | No | Numeric range to expand: `@start`, `@end`, optional `@step` |
| `items` | list | No | Explicit list of items to loop over (alternative to `index`) |
| `values` | list | Yes | Array of `{condition, value}` pairs |
| `mode` | string | No | `"static"` (default) or `"dynamic"` for runtime state expansion |

The `index` and `items` fields are mutually exclusive. If neither is present, the template is expanded only from the mapping's own loop values.

Each entry in `values` is an object with:
- `condition` — A Kodi boolean expression string. Use `"true"` for the unconditional fallback.
- `value` — The value to use when the condition is met. Kodi evaluates conditions top to bottom and uses the first match.

Both `condition` and `value` strings support `{placeholder}` substitution.

> **Note:** Unlike the configs and expressions builders, the variables builder does not evaluate conditions at build time using the [Rule Engine](08-rule-engine.md). Conditions are written directly into the output XML as native Kodi boolean expressions (e.g. `!String.IsEmpty(...)`, `Container.Content(...)`) and are resolved by Kodi at runtime. The builder only performs placeholder substitution on them.

---

## Example: texture art variables

This is from Copacetic 2's `variables.json`. It uses `"mapping": "none"` because it doesn't need a mapping loop — it only uses an index range:

```json
{
  "mapping": "none",
  "variables": {
    "texture_primary_poster{index}": {
      "index": { "start": -3, "end": 6 },
      "values": [
        {
          "condition": "!String.IsEmpty(ListItemNoWrap({index}).Art(keyart)) + $EXP[art_keyart_visible]",
          "value": "$INFO[ListItem({index}).Art(keyart)]"
        },
        {
          "condition": "!String.IsEmpty(ListItemNoWrap({index}).Art(poster))",
          "value": "$INFO[ListItem({index}).Art(poster)]"
        },
        {
          "condition": "!String.IsEmpty(ListItemNoWrap({index}).Art(tvshow.poster))",
          "value": "$INFO[ListItem({index}).Art(tvshow.poster)]"
        },
        {
          "condition": "!String.IsEmpty(ListItemNoWrap({index}).Icon)",
          "value": "$INFO[ListItem({index}).Icon]"
        }
      ]
    }
  }
}
```

### What this produces

The `index` range `{ "start": -3, "end": 6 }` expands to indices -3, -2, -1, 0, 1, 2, 3, 4, 5, 6. For each index value, a complete `<variable>` is generated. The output in `script-copacetic-helper_variables.xml` looks like:

```xml
<variable name="texture_primary_poster-3">
  <value condition="!String.IsEmpty(ListItemNoWrap(-3).Art(keyart)) + $EXP[art_keyart_visible]">$INFO[ListItem(-3).Art(keyart)]</value>
  <value condition="!String.IsEmpty(ListItemNoWrap(-3).Art(poster))">$INFO[ListItem(-3).Art(poster)]</value>
  <value condition="!String.IsEmpty(ListItemNoWrap(-3).Art(tvshow.poster))">$INFO[ListItem(-3).Art(tvshow.poster)]</value>
  <value condition="!String.IsEmpty(ListItemNoWrap(-3).Icon)">$INFO[ListItem(-3).Icon]</value>
</variable>
<variable name="texture_primary_poster-2">
  <!-- same structure with -2 substituted -->
</variable>
<!-- ... repeated for each index through 6 -->
```

Without the builder, you would need to write 10 nearly identical `<variable>` blocks by hand — and maintain them all if the art fallback chain changes.

---

## Using with a mapping

When a variable template references a mapping other than `"none"`, the mapping's loop values are combined with any `items` or `index` in the template itself.

For example, with the `content_types` mapping (dict-of-lists: window → content_types), a template could use both `{window}` and `{content_type}` placeholders in addition to `{index}`:

```json
{
  "mapping": "content_types",
  "variables": {
    "viewsettings_{index}_txtcolor": {
      "index": { "start": 100, "end": 111 },
      "values": [
        {
          "condition": "ControlGroup(3200).HasFocus",
          "value": "pearl"
        },
        {
          "condition": "true",
          "value": "grout"
        }
      ]
    }
  }
}
```

Note that this particular example doesn't use `{window}` or `{content_type}` in its template name or values — it only uses `{index}`. The mapping is referenced but the template name contains no mapping placeholders, so it expands once per index value rather than once per content type × index combination. The builder is smart enough to avoid duplicate expansions.

---

## How expansion works under the hood

1. The builder reads the mapping's `items` and `placeholders`.
2. It reads the template's own `items` or `index` field.
3. It calls `generate_substitutions()` which computes the cartesian product of mapping loop values × template items/indices.
4. Each combination becomes a substitution dictionary.
5. The template name is formatted with each substitution to produce the output variable name.
6. The `values` array is formatted with the same substitution to produce condition/value pairs.
7. All results are collected and written as XML.

---

## Output format

The variables builder writes `script-copacetic-helper_variables.xml` using `XMLHandler._simple_dict_to_xml`. The file structure is:

```xml
<?xml version='1.0' encoding='utf-8'?>
<includes>
  <variable name="variable_name_1">
    <value condition="condition1">value1</value>
    <value condition="condition2">value2</value>
  </variable>
  <variable name="variable_name_2">
    <!-- ... -->
  </variable>
</includes>
```

You reference these in your skin XML with `$VAR[variable_name]`. To make them available, add the generated file to your skin's `Includes.xml`:

```xml
<include file="script-copacetic-helper_variables.xml" />
```

---

## Next

- [Expressions Builder](04-expressions.md) — Boolean logic with grouping and fallbacks
