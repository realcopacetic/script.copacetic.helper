# Rule Engine

One condition language, used everywhere: config rules, expression rules, template filters, control `visible` conditions and `confirm` conditions. Tokens fill in first, then the condition comes out true or false. It is the addon's own small language, not Kodi's: it runs in Python, at build time or in the settings window.

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

Operator names are not case-sensitive. The subject can't contain a comma and the value can't contain a `)`. Both are compared as plain text after trimming spaces, except the four numeric operators, which need numbers on both sides — a non-number there stops the build. A condition that matches none of these forms, or names an unknown operator, is simply false; nothing is logged.

`In` takes a comma-separated list in square brackets. Put `not ` (lower case, followed by a space) in front of a comparison to flip it:

```
not In({content_type}, [movies, sets, tvshows, seasons])
```

### Combining

`+` is AND, `|` is OR, and `|` binds looser than `+` (`a + b | c` means "a and b, or c"):

```
equals({autoplay}, true) + In({widget_preset}, [random_movies, random_tvshows])
equals({wrapness}, nowrap) | In({index}, [-1, 0, 1])
In({widget_preset}, [custom, drilldown]) + not equals({layout}, marquee)
```

The middle one is the filter trick from [Includes → Filtering](07-includes.md#filtering-skipping-loop-passes): two ways to survive, OR'd together.

There is no grouping: square brackets don't group, and the condition is split at *every* `+` and `|`, even one inside a value. So a token whose value contains `+` or `|` breaks a rule — and the builder wraps such mapping tokens in `[...]`, which this language doesn't understand. Keep tokens used in rules and filters to single comparisons, or write the OR at the top level.

### Live Kodi state: `xml(...)`

Hands the condition to Kodi's own `getCondVisibility()` — checked against whatever's true right now. `xml(...)` must be the whole condition; it can't be combined with other parts using `+` or `|` outside the brackets:

```
xml(!Skin.HasSetting(widgets_per_menu))
xml(String.IsEqual(Window(home).Property(current_mapping),mainmenu) + Skin.HasSetting(widgets_per_menu))
```

Inside the brackets you write normal Kodi condition syntax: `+`, `|`, `!`, brackets. In the settings window it is re-checked every time. At build time it is checked once per build against Kodi's state at that moment, and the same answer is reused for the rest of the build.

> **Kodi limitation worth knowing:** in Kodi's own string checks (`String.IsEqual`, `String.Contains`, …) the first argument must be an infolabel name, and the second is either an infolabel name (compared live) or a fixed string. A `$VAR[...]` or `$INFO[...]` in the second argument is resolved once, when Kodi first reads the condition, not live. If you need to compare a variable's value, move the comparison into rule conditions or template structure instead.

### Focus: `focused(...)`

`focused(123)` = `Control.HasFocus(123)`. Like `xml(...)`, it must be the whole condition. The id must be a number; anything else is false.

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

Values that are exactly `true` or `false` are ignored; if nothing is left, it gives plain `"true"`. See [Expressions → Fallbacks](04-expressions.md#fallbacks).

---

## Next

- [Runtime State & Dynamic Editor](09-runtime-state.md) — the settings file and windows
