# Rule Engine

The Rule Engine is the condition evaluator used across multiple builders and the Dynamic Editor. It parses condition strings, evaluates them against current state, and returns boolean results. It supports built-in comparison operators, native Kodi conditions, and result caching.

It's used by the **configs builder** (filter rule conditions), the **expressions builder** (rule conditions), and the **Dynamic Editor** (control visibility conditions at runtime).

---

## Condition types

### Literal values

The simplest conditions are bare `true` and `false`:

```
"true"   → True
"false"  → False
```

### Native Kodi: `xml(...)`

Wrapping a condition in `xml()` delegates evaluation to Kodi's own `getCondVisibility()`:

```
xml(Skin.String(movies_layout,fanart))
xml(Skin.String(movies_layout,fanart) + Skin.String(movies_details_title,true))
xml(!Skin.HasSetting(some_toggle))
```

Inside the parentheses, you write any valid Kodi boolean expression using `+` (AND), `|` (OR), `!` (NOT), and brackets.

This is evaluated live — it reflects the current state of skin strings, settings, and other Kodi conditions at the moment it runs. At build time, that means whatever the user has currently configured.

### Focus: `focused(...)`

Checks if a specific control has focus:

```
focused(movies_item)
focused(123)
```

A numeric argument evaluates to `Control.HasFocus(ID)`. A string argument (like a listitem name) returns false at build time but is resolved by the Dynamic Editor at runtime to match contextual bindings.

### Comparison operators

All other conditions use the format:

```
[not] operator(subject, value)
```

The optional `not` prefix inverts the result.

| Operator | Description | Example |
|---|---|---|
| `in` | Subject is in a comma-separated list | `In({content_type}, [movies, sets, tvshows])` |
| `equals` | Exact string match | `equals({layout}, poster)` |
| `not_equals` | Strings don't match | `not_equals({layout}, fanart)` |
| `startswith` | Subject starts with prefix | `startswith({window}, vid)` |
| `endswith` | Subject ends with suffix | `endswith({path}, .xsp)` |
| `contains` | Subject contains substring | `contains({content}, plugin)` |
| `greaterthan` | Numeric greater than | `greaterthan({limit}, 5)` |
| `lessthan` | Numeric less than | `lessthan({index}, 10)` |
| `greaterorequal` | Numeric ≥ | `greaterorequal({index}, 5)` |
| `lessorequal` | Numeric ≤ | `lessorequal({index}, 5)` |

### The `In` operator

The most common one. The second argument is a comma-separated list wrapped in square brackets:

```
In({content_type}, [addons, favourites, albums, songs, images])
```

After substitution with `{content_type} = "albums"`:

```
In(albums, [addons, favourites, albums, songs, images])  → True
```

### Negation

Prefix any condition with `not` followed by a space:

```
not In({content_type}, [movies, sets, tvshows, seasons])
not equals({window}, videos)
```

> **Note on Kodi limitations:** Kodi's own string comparison operators (`String.IsEqual`, `String.Contains`, etc.) inside `xml()` conditions do **not** resolve `$VAR[...]` references in their operands — only `$INFO` labels and direct skin strings do. If a pattern needs to compare a variable's resolved value, lift the comparison into the rule conditions or template structure rather than relying on `String.IsEqual($VAR[...], ...)`.

---

## Placeholder substitution

Conditions support `{placeholder}` tokens like any other template string. Substitution happens before evaluation, so the same rule definition produces different results for different loop values:

```json
{
  "condition": "In({content_type}, [songs])",
  "value": ["showcase", "strip", "grid"]
}
```

When processing `{content_type} = "songs"`, the condition becomes `In(songs, [songs])` → true. For any other content type, false.

---

## Caching

The Rule Engine caches condition results by string. Once a condition has been evaluated, subsequent evaluations of the same string return the cached result.

Safe at build time because conditions evaluate against fixed state. The Dynamic Editor bypasses the cache when re-evaluating visibility at runtime, since the user can change settings between evaluations.

---

## The `invert()` method

Used by the expressions builder's fallback system. Given a group of expression values, it produces a Kodi boolean inversion that's true when none of them are. For:

```
{
  "layout_showcase_visible_videos": "Container.Content(movies)",
  "layout_grid_visible_videos": "Container.Content(tvshows)"
}
```

`invert()` produces:

```
![Container.Content(movies) | Container.Content(tvshows)]
```

Values of `"true"` or `"false"` are filtered out before the inversion is built. If everything is filtered, `invert()` returns `"true"` — the fallback is unconditionally visible when nothing else applies.

---

## Examples in context

### Configs rule (exclude mode)

```json
"rules": [
  {
    "condition": "In({content_type}, [addons, favourites, albums, songs, images])",
    "value": ["fanart", "poster"]
  }
]
```

For albums: condition is true → `fanart` and `poster` join the excluded set → only `square` remains.

### Expression rule (assign)

```json
"rules": [
  {
    "condition": "xml(Skin.String({content_type}_layout,{item}))",
    "type": "assign",
    "value": "true"
  }
]
```

For `(movies, list)`: if `Skin.String(movies_layout)` equals `"list"` at build time → expression resolves to `"true"`. Otherwise the next rule runs (or it defaults to `"false"`).

### Visibility condition (Dynamic Editor)

```json
"visible": "In({widget_preset}, [custom])"
```

At runtime, `{widget_preset}` is resolved from the focused entry's `mapping_item`. If it's `"custom"`, the control is visible; otherwise hidden.

---

## Next

- [Runtime State & Dynamic Editor](09-runtime-state.md) — How user settings are stored and managed