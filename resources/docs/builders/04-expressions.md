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
| `items_from` | Loop another mapping's items, under its own placeholder names — same behaviour as [Variables → items_from](03-variables.md#items_from--borrow-another-mappings-list) |
| `templates_from` | Stamp the template once per listed mapping with its `tokens` filled — [Variables → templates_from](03-variables.md#templates_from--one-template-several-mappings) |
| `index` | `{"start": N}` — numbers the passes as `{index}`; never adds passes |
| `range` | Numeric loop (`start`, `end`, optional `step`) — multiplies every pass, available as `{range}`; `ready_typewriter_{region}_{range}` uses it |
| `rules` | Condition / type / value rows — see below |
| `fallback_key` | Which token groups expressions for the fallback step |
| `fallbacks` | What the catch-all in each group gets |
| `filter` | Skip loop passes — see [Includes → Filtering](07-includes.md#filtering-skipping-loop-passes) |

The expansion order is the same as for [variables](03-variables.md#ordinary-templates). Whether the template loops settings-file entries is decided by the mapping's `mode`; a `mode` key on the template is ignored. In this example (Copacetic's `content_types`) the mapping is dynamic, so `{layout}` is each entry's stored value (or its default) at build time.

The template name is filled in for every pass, and passes that give the same name build one expression together.

Note the split: a rule's `condition` is checked **by the builder at build time** ([Rule Engine](08-rule-engine.md)); the rule's `value` is a **Kodi condition** written into the output for Kodi to check at runtime. The builder never evaluates the value.

---

## Rules

| Field | Required | What it does |
|---|---|---|
| `condition` | No | [Rule Engine](08-rule-engine.md) test, checked per pass at build time. Leave it off and the rule always fires. |
| `type` | Yes | `assign` or `append`. Anything else stops the build. |
| `value` | Yes | The Kodi condition written into the output |

For each expression, the builder walks its passes in order and, for each pass, its rules in order. Unknown tokens in `condition` and `value` become empty strings.

**`assign`** — the first rule that fires with `assign` ends the walk; its value becomes the whole expression, replacing anything `append` rules collected before it:

```json
{ "condition": "equals({layout}, {item})", "type": "assign", "value": "true" }
```

`layout_list_include_videos` becomes `true` if *any* content type in the videos window uses layout `list`.

**`append`** — every true rule adds its value; results join with ` | ` (Kodi OR). If movies and tvshows both use fanart:

```xml
<expression name="art_fanart_visible_videos">Container.Content(movies) | Container.Content(tvshows)</expression>
```

True exactly when the screen shows a content type set to fanart — rebuilt automatically whenever the user changes a setting.

A value that begins `true + ` (a `{guard}` token that rendered `true`, say) has that prefix stripped, so places with no guard emit clean conditions. Only a `true + ` at the start of the value, or straight after a `[`, is removed — put the guard first. A value that is just `true` stays `true`.

**No `condition` at all** — the rule always fires. This is the shorthand pattern: no user setting involved, just a long Kodi condition getting a name. The whole `expressions_windows.json` file works this way:

```json
"window_active_{window}": {
  "rules": [
    { "type": "assign", "value": "$EXP[content_visible_{window}] + !$EXP[container_switchingto_primary]" }
  ]
}
```

One template, one expression per window, each composing other expressions — build-time macros. Values can reference other generated expressions freely; Kodi resolves the `$EXP[...]` chain at runtime.

If no rule fires for a pass, the expression is `"false"` (unless a fallback catches it).

Two more tools rules can use. Values can reach across mappings with `{@mapping:item.field}` ([Overview → Placeholders](01-overview.md#placeholders)) — Copacetic's grid templates compose `$EXP[art_{@grid:{grid_layout}.art}_visible_{window}]` without looping the grid mapping itself. And rule *conditions* can test the loop item's name — `In({region}, [secondary])` — so one template emits structurally different expressions per item of a static mapping: each item takes the first rule whose condition matches it, `assign` short-circuiting past the rest.

---

## Fallbacks

Fallbacks make one item per group the catch-all instead of `"false"`.

`fallback_key` names the token that defines the groups. With `"window"`, all `layout_*_visible_videos` are one group, all `layout_*_visible_music` another. `fallbacks` names which item catches, and what it gets. `target_item` is one of the template's `items` values (the `{item}` token), so fallbacks need an `items` list:

```json
"fallbacks": { "*": { "target_item": "list", "value": "invert()" } }
```

**`invert()`** = "true whenever none of the others are". If showcase covers movies and grid covers tvshows, the list expression becomes:

```xml
<expression name="layout_list_visible_videos">![Container.Content(movies) | Container.Content(tvshows)]</expression>
```

List shows for anything without a specific layout. `invert()` ignores the other expressions that are exactly `false` or `true`; if nothing is left, it gives plain `"true"`. `"{invert}"` is accepted as another spelling.

**Literal values** suit on/off gating: `"value": "true"` makes the catch-all unconditionally active. A literal replaces whatever the catch-all's own rules produced. An empty value gives `"true"`.

**Different catch-alls per group**, `"*"` as the wildcard. A group with no matching entry, or whose `target_item` isn't in it, is left as it is:

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
