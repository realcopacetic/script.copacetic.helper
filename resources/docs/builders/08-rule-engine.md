# Rule Engine

One condition language, used everywhere: config rules, expression rules, template filters, and control `visible` conditions. Tokens fill in first, then the condition comes out true or false.

---

## The pieces

### Literals

`"true"` and `"false"`. Useful as catch-all rules.

### Comparisons

```
[not] operator(subject, value)
```

| Operator | Example |
|---|---|
| `In` | `In({content_type}, [movies, sets, tvshows])` |
| `equals` | `equals({layout}, poster)` |
| `not_equals` | `not_equals({layout}, fanart)` |
| `startswith` | `startswith({window}, vid)` |
| `endswith` | `endswith({path}, .xsp)` |
| `contains` | `contains({content}, plugin)` |
| `greaterthan` / `lessthan` | `greaterthan({limit}, 5)` |
| `greaterorequal` / `lessorequal` | `lessorequal({index}, 2)` |

`In` takes a comma-separated list in square brackets. Put `not ` in front of anything to flip it:

```
not In({content_type}, [movies, sets, tvshows, seasons])
```

### Combining

`+` is AND, `|` is OR:

```
equals({autoplay}, true) + In({widget_preset}, [random_movies, random_tvshows])
equals({wrapness}, nowrap) | In({index}, [-1, 0, 1])
In({widget_preset}, [custom, drilldown]) + not equals({layout}, marquee)
```

The middle one is the filter trick from [Includes → Filtering](07-includes.md#filtering-skipping-loop-passes): two ways to survive, OR'd together.

### Live Kodi state: `xml(...)`

Hands the condition to Kodi's own `getCondVisibility()` — checked against whatever's true right now:

```
xml(!Skin.HasSetting(widgets_per_menu))
xml(String.IsEqual(Window(home).Property(current_mapping),mainmenu) + Skin.HasSetting(widgets_per_menu))
```

Inside the brackets you write normal Kodi condition syntax: `+`, `|`, `!`, brackets.

> **Kodi limitation worth knowing:** Kodi's own string checks (`String.IsEqual`, `String.Contains`, …) will **not** resolve a `$VAR[...]` you pass them — only `$INFO` labels and plain strings work. If you need to compare a variable's value, move the comparison into rule conditions or template structure instead.

### Focus: `focused(...)`

`focused(123)` = `Control.HasFocus(123)`.

---

## Tokens make one rule serve everyone

Tokens fill in before the check, so:

```json
{ "condition": "In({content_type}, [songs])", "value": ["showcase", "strip", "grid"] }
```

For songs this becomes `In(songs, [songs])` → true. For everything else, false. In the editor, tokens fill from the highlighted entry — `{widget_preset}` is its preset, `{layout}` its current layout — and `visible` conditions re-check as the user changes things.

---

## `invert()`

Only used in expression fallbacks: "true whenever none of the others are". It collects the group's non-false values and negates their OR:

```
![Container.Content(movies) | Container.Content(tvshows)]
```

If everything else in the group is false, it gives plain `"true"`. See [Expressions → Fallbacks](04-expressions.md#fallbacks).

---

## Next

- [Runtime State & Dynamic Editor](09-runtime-state.md) — the settings file and windows
