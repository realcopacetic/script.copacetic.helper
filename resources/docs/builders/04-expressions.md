# Expressions Builder

Generates Kodi `<expression>` elements — the ones you use with `$EXP[name]`. Two jobs, same machinery:

1. Turn per-item settings into the combined conditions your skin checks ("which content types use fanart?").
2. Act as build-time shorthand: assemble long Kodi conditions once, under a name, instead of repeating them across your XML.

---

## Input

JSON files in `extras/templates/expressions/`:

```json
{
  "mapping": "content_types",
  "expressions": {
    "layout_{item}_visible_{window}": {
      "items": ["list", "showcase", "strip", "grid"],
      "rules": [
        {
          "condition": "equals({layout}, {item})",
          "type": "append",
          "value": "Container.Content({content_type})"
        }
      ],
      "fallback_key": "window",
      "fallbacks": {
        "*": { "target_item": "list", "value": "invert()" }
      }
    }
  }
}
```

| Field | What it does |
|---|---|
| `mapping` | Mapping name (or `"none"`) |
| `items` | An extra loop on top of the mapping's — here, one expression per layout per window |
| `index` | Number range, as an alternative or addition to `items` |
| `rules` | Condition / type / value rows — see below |
| `fallback_key` | Which token groups expressions for the fallback step |
| `fallbacks` | What the catch-all in each group gets |
| `mode` | `"dynamic"` to loop settings-file entries (the usual choice for user settings) |
| `filter` | Skip loop passes — see [Includes → Filtering](07-includes.md#filtering-skipping-loop-passes) |

`content_types` is a dynamic mapping, so `{layout}` is each entry's stored value (or its default) at build time.

Note the split: a rule's `condition` is checked **by the builder at build time** ([Rule Engine](08-rule-engine.md)); the rule's `value` is a **Kodi condition** written into the output for Kodi to check at runtime. The builder never evaluates the value.

---

## Rules

**`assign`** — first true rule wins; its value becomes the whole expression:

```json
{ "condition": "equals({layout}, {item})", "type": "assign", "value": "true" }
```

`layout_list_include_videos` becomes `true` if *any* content type in the videos window uses layout `list`.

**`append`** — every true rule adds its value; results join with ` | ` (Kodi OR). If movies and tvshows both use fanart:

```xml
<expression name="art_fanart_visible_videos">Container.Content(movies) | Container.Content(tvshows)</expression>
```

True exactly when the screen shows a content type set to fanart — rebuilt automatically whenever the user changes a setting.

**No `condition` at all** — the rule always fires. This is the shorthand pattern: no user setting involved, just a long Kodi condition getting a name. The whole `expressions_windows.json` file works this way:

```json
"window_active_{window}": {
  "rules": [
    { "type": "assign", "value": "$EXP[content_visible_{window}] + !$EXP[level_switching]" }
  ]
}
```

One template, one expression per window, each composing other expressions — build-time macros. Values can reference other generated expressions freely; Kodi resolves the `$EXP[...]` chain at runtime.

If no rule fires for a pass, the expression is `"false"` (unless a fallback catches it).

---

## Fallbacks

Fallbacks make one item per group the catch-all instead of `"false"`.

`fallback_key` names the token that defines the groups. With `"window"`, all `layout_*_visible_videos` are one group, all `layout_*_visible_music` another. `fallbacks` names which item catches, and what it gets:

```json
"fallbacks": { "*": { "target_item": "list", "value": "invert()" } }
```

**`invert()`** = "true whenever none of the others are". If showcase covers movies and grid covers tvshows, the list expression becomes:

```xml
<expression name="layout_list_visible_videos">![Container.Content(movies) | Container.Content(tvshows)]</expression>
```

List shows for anything without a specific layout. If everything else in the group is false, `invert()` gives plain `"true"`.

**Literal values** suit on/off gating: `"value": "true"` makes the catch-all unconditionally active when nothing matched.

**Different catch-alls per group**, `"*"` as the wildcard:

```json
"fallbacks": {
  "videos": { "target_item": "fanart", "value": "true" },
  "*": { "target_item": "square", "value": "true" }
}
```

---

## Where it goes

The builder writes `script-copacetic-helper_expressions.xml`. Include it once:

```xml
<include file="script-copacetic-helper_expressions.xml" />
```

Then use `$EXP[name]` anywhere. Expressions rebuild on every dev-mode start, whenever a settings window closes with changes, and on a manual rebuild.

---

## Next

- [Configs](05-configs.md) — the allowed values these expressions read