# Rule Engine

The Rule Engine is the condition evaluator used across multiple builders and the Dynamic Editor. It parses condition strings, evaluates them against current state, and returns boolean results. It supports a set of built-in comparison operators, Kodi native conditions, and a caching system for build-time performance.

---

## Where it's used

- **Configs builder** — evaluates filter rules to determine which items to exclude/include
- **Expressions builder** — evaluates rule conditions to determine which values to assign/append
- **Dynamic Editor** — evaluates visibility conditions on controls at runtime

---

## Condition types

### Literal values

The simplest conditions are bare `true` and `false` strings:

```
"true"   → True
"false"  → False
```

### Kodi native conditions: `xml()`

Wrapping a condition in `xml()` delegates evaluation to Kodi's own `getCondVisibility()`:

```
xml(Skin.String(movies_view,list))
xml(Skin.String(movies_layout,poster) + Skin.String(movies_view,list))
xml(!Skin.HasSetting(some_toggle))
```

Inside the parentheses, you write any valid Kodi boolean expression using `+` (AND), `|` (OR), `!` (NOT), and brackets.

This is evaluated live — it reflects the current state of skin strings, settings, and Kodi conditions. At build time, `xml()` conditions query Kodi's actual state, making them useful for expressions and configs that depend on what the user has currently configured.

### Focus conditions: `focused()`

The `focused()` condition checks if a specific control has focus:

```
focused(movies_item)
focused(123)
```

If the argument is a numeric control ID, it evaluates to `Control.HasFocus(ID)` via Kodi. If it's a string (like a listitem name), it returns false during build but is used by the Dynamic Editor at runtime to match contextual bindings.

### Comparison operators

All other conditions use the format:

```
[not] operator(subject, value)
```

The optional `not` prefix inverts the result. Available operators:

| Operator | Description | Example |
|---|---|---|
| `in` | Subject is in a comma-separated list | `In({content_type}, [movies, sets, tvshows])` |
| `equals` | Exact string match | `equals({layout}, poster)` |
| `not_equals` | Strings don't match | `not_equals({layout}, fanart)` |
| `startswith` | Subject starts with prefix | `startswith({window}, vid)` |
| `endswith` | Subject ends with suffix | `endswith({path}, .xsp)` |
| `contains` | Subject contains substring | `contains({content_path}, plugin)` |
| `greaterthan` | Numeric greater than | `greaterthan({limit}, 5)` |
| `lessthan` | Numeric less than | `lessthan({index}, 10)` |
| `greaterorequal` | Numeric ≥ | `greaterorequal({index}, 5)` |
| `lessorequal` | Numeric ≤ | `lessorequal({index}, 5)` |

### The `In` operator

The most commonly used operator. The second argument is a comma-separated list wrapped in square brackets:

```
In({content_type}, [addons, favourites, albums, songs, images])
```

After placeholder substitution, if `{content_type}` is `"albums"`, this becomes:

```
In(albums, [addons, favourites, albums, songs, images])  → True
```

### Negation

Prefix any condition with `not` followed by a space:

```
not In({content_type}, [movies, sets, tvshows, seasons])
not equals({window}, videos)
```

---

## Placeholder substitution in conditions

Conditions support `{placeholder}` tokens just like any other template string. They are substituted before evaluation. This is what makes rules dynamic — the same rule definition produces different results for different loop values:

```json
{
  "condition": "In({content_type}, [songs])",
  "value": ["showcase", "strip", "grid"]
}
```

When processing `{content_type} = "songs"`, the condition is `In(songs, [songs])` → true. For any other content type, it's false.

---

## Caching

The Rule Engine caches condition results by default. Once a condition string has been evaluated, subsequent evaluations of the same string return the cached result without re-evaluating.

This is safe at build time because conditions are evaluated against a fixed state. However, at runtime in the Dynamic Editor, conditions may need re-evaluation as the user changes settings. For this reason, runtime callers pass `runtime=True`, which bypasses the cache:

```python
self.rule_engine.evaluate(condition, runtime=True)
```

---

## The `invert()` method

The Rule Engine provides an `invert()` method used by the expressions builder's fallback system. Given a dict of expression values, it produces a Kodi boolean inversion:

```python
rule_engine.invert({
    "videos_views_visible_showcase": "Container.Content(movies)",
    "videos_views_visible_grid": "Container.Content(tvshows)",
})
# Returns: "![Container.Content(movies) | Container.Content(tvshows)]"
```

Values of `"false"` or `"true"` are filtered out before building the inversion. If no values remain after filtering, it returns `"true"` (the fallback is always visible when nothing else is).

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

For albums: condition is true → `fanart` and `poster` are added to the excluded set → only `square` remains.

### Expression rule (assign)

```json
"rules": [
  {
    "condition": "xml(Skin.String({content_type}_view,{item}))",
    "type": "assign",
    "value": "true"
  }
]
```

For movies with item=list: if `Skin.String(movies_view)` equals "list" → expression is `"true"`. Otherwise processing continues to the next rule (or defaults to `"false"`).

### Visibility condition (Dynamic Editor)

```json
"visible": "In({widget_preset}, [custom])"
```

At runtime, `{widget_preset}` is resolved from the current entry's `mapping_item`. If it's `"custom"`, the control is visible. Otherwise it's hidden.

---

## Next

- [Runtime State & Dynamic Editor](09-runtime-state.md) — How user settings are stored and managed