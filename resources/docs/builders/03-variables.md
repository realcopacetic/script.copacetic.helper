# Variables Builder

Generates Kodi `<variable>` elements — the ones you use with `$VAR[name]`. You write one template; it produces the variables with numbers or loop values filled in.

Two template shapes:

- **Ordinary** — one variable per template (times the loop).
- **Cluster** — several variables sharing one condition cascade.

> The builder never evaluates your conditions. They're written into the output as-is and Kodi resolves them at runtime. The builder only fills in the `{tokens}`.

---

## Ordinary templates

JSON files in `extras/templates/variables/`:

```json
{
  "mapping": "none",
  "variables": {
    "texture_primary_poster{range}": {
      "range": { "start": -3, "end": 6 },
      "values": [
        {
          "condition": "!String.IsEmpty(ListItemNoWrap({range}).Art(poster))",
          "value": "$INFO[ListItem({range}).Art(poster)]"
        },
        { "value": "$INFO[ListItem({range}).Icon]" }
      ]
    }
  }
}
```

Ten variables out — `texture_primary_poster-3` through `...poster6` — each with the chain and its own number baked in.

| Field | What it does |
|---|---|
| `index` | Numbers the loop passes: pass N gets `{index}` = `start` + N. Never multiplies — one value per existing pass. |
| `range` | A numeric loop: `start`, `end`, optional `step`. Multiplies — every existing pass repeats once per value, available as `{range}`. |
| `items` | An explicit list to loop over — each value becomes `{item}` |
| `items_from` | Loop a *different* mapping's items instead of typing a list — see below |
| `templates_from` | Stamp this template once per listed mapping, filling each one's `tokens` — see below |
| `values` | The rows — `{condition, value}` dicts, or lists of them (blocks, below) |
| `filter` | Skip loop passes at build time — see [Filtering](#filtering) |
| `mode` | `"dynamic"` = loop the settings-file entries instead of the mapping's items |

**`index` numbers the passes; `range` and `items` multiply them.** Expansion order: the mapping's items make the passes → `index` stamps each with a number → `range` repeats every pass per value → `items` repeats every pass per value → `filter` prunes. So `range` and `items` combine into every pairing, while `index` alone never adds passes — a template with `mapping: "none"` and only an `index` emits exactly one variable. In dynamic mode, `{index}` numbers the settings entries, and a declared `index` sets its starting value.

Rows: `condition` is optional — leave it off for an unconditional row (a bare `<value>`). Kodi reads top to bottom and uses the first match, exactly like a hand-written variable.

---

## How rows expand

Templates usually mix rows that vary per loop pass with rows that don't. The rule:

| Row contains | What happens |
|---|---|
| A `{token}` | Repeated once per loop pass, in place |
| No token | Emitted once, in place |

Order is preserved, so a token-free fallback written last stays last:

```json
"values": [
  { "condition": "Control.HasFocus({index}) + !String.IsEmpty(Container({index}).ListItem.Art(poster1))", "value": "poster" },
  { "condition": "Control.HasFocus({index}) + !String.IsEmpty(Container({index}).ListItem.Art(fanart1))", "value": "fanart" },
  { "value": "$VAR[label_multiart_home]" }
]
```

With two widgets (3200, 3201) this gives: both `poster` rows, then both `fanart` rows, then the fallback:

```xml
<value condition="Control.HasFocus(3200) + ...poster1...">poster</value>
<value condition="Control.HasFocus(3201) + ...poster1...">poster</value>
<value condition="Control.HasFocus(3200) + ...fanart1...">fanart</value>
<value condition="Control.HasFocus(3201) + ...fanart1...">fanart</value>
<value>$VAR[label_multiart_home]</value>
```

Notice the interleaving: each *row* runs the full loop before the next row starts.

### Grouping rows with `[...]`

Wrap rows in a list to keep them together as one **block**. A block with any token repeats *as a unit* per loop pass — its rows stay contiguous and in order, and the whole block finishes each pass before the loop moves on:

```json
"values": [
  [
    { "condition": "Control.HasFocus({index}) + ...poster1...", "value": "poster" },
    { "condition": "Control.HasFocus({index}) + ...fanart1...", "value": "fanart" }
  ],
  { "value": "$VAR[label_multiart_home]" }
]
```

```xml
<value condition="Control.HasFocus(3200) + ...poster1...">poster</value>
<value condition="Control.HasFocus(3200) + ...fanart1...">fanart</value>
<value condition="Control.HasFocus(3201) + ...poster1...">poster</value>
<value condition="Control.HasFocus(3201) + ...fanart1...">fanart</value>
<value>$VAR[label_multiart_home]</value>
```

Same rows, different order: now widget 3200's full chain runs before widget 3201's starts. Reach for a block whenever a set of rows must stay together per pass — a lone row is just a one-row block. `content_typewriter` in `variables_widgets.json` uses several blocks in sequence: the first block loops fully across all widgets, then the second begins.

### Duplicates are dropped

If two rows come out with the identical condition *and* value, only the first is kept. Kodi always picks the first match, so the copy was dead weight anyway. This mostly happens when a row's tokens don't actually vary across the loop.

### Empty terminators

A row with `"value": ""` becomes a self-closing `<value condition="..."/>`. Kodi reads that as: stop here, resolve to nothing. Use it to force a clean exit partway down a chain instead of falling through to a default.

### Variables that always exist

A `<variable>` with no `<value>` rows is undefined in Kodi (`$VAR[...] is not defined` in the log). The builder never lets that happen: if everything expanded away, it emits a single empty `<value/>` so the variable exists and resolves to nothing. And token-free rows survive every filter — so a plain-named template with a token-free fallback always produces its variable, and your `$VAR[...]` references stay safe even when the user has nothing configured.

---

## Cluster templates

Sometimes several variables must follow the *same* condition cascade — a label and an icon that always come from the same matching row, or a main texture and its fallback that must switch in lockstep. Writing two cascades that have to stay in sync by hand is a maintenance trap. A cluster writes the cascade once:

```json
"_breadcrumb_left_videos_cluster": {
  "outputs": {
    "label": "label_breadcrumb_left_videos",
    "texture": "texture_breadcrumb_left_videos"
  },
  "rows": [
    {
      "condition": "Container.Content(movies)",
      "label": "$LOCALIZE[342]",
      "texture": "icons/Ticket.png"
    },
    {
      "condition": "Container.Content(tvshows)",
      "label": "$LOCALIZE[20343]",
      "texture": "icons/TelevisionSimple.png"
    },
    {
      "label": "$VAR[_label_breadcrumb_left]",
      "texture": "$VAR[_texture_breadcrumb_left]"
    }
  ]
}
```

| Field | What it does |
|---|---|
| `outputs` | Map of row-key → variable name. Each entry becomes one real variable. |
| `rows` | The shared cascade. Each row: an optional `condition`, plus one value per output it feeds. |

This emits two variables — `label_breadcrumb_left_videos` and `texture_breadcrumb_left_videos` — with identical condition ladders. Whatever row matches, both resolve from it, so `$VAR[label_...]` and `$VAR[texture_...]` can sit next to each other and never disagree.

Details:

- **The template name isn't a variable.** Only the `outputs` names are emitted. The leading underscore (`_breadcrumb_left_videos_cluster`) is the convention for "internal — don't reference this".
- **Loop controls work here too.** `index`, `items`, `items_from`, `templates_from`, `mode`, and `filter` behave exactly as on ordinary templates; the `outputs` names and `rows` expand per pass. `_{texture_prefix}_base_cluster` in `variables_ladders.json` borrows regions, widgets and search *and* loops `items: [poster, fanart, square]` — every container gets a main/fallback pair per art type from one cascade.
- **Sparse rows.** A row can feed some outputs and skip others — just leave the key off. That output's cascade simply doesn't have that row. Useful when one output's chain is a subset of another's.
- **Blocks apply.** `rows` groups with `[...]` the same way `values` does.

---

## `items_from` — borrow another mapping's list

`items` with a typed list is fine until the list already exists as a mapping. `items_from` names a mapping and loops its items instead — under that mapping's *own* placeholder names:

```json
"vue_grid_{grid_layout}_visible_{window}": {
  "items_from": "grid",
  "..."
}
```

Each pass carries `{grid_layout}` (the grid mapping's declared key) alongside the file mapping's tokens. Like `items`, it multiplies: every existing pass repeats once per borrowed item. Dict rosters work too — both the key and value placeholders inject. One list, one owner: when the roster changes, every template borrowing it follows.

**Reading the borrowed item's metadata.** `{@mapping:item.field}` pulls one string field from another mapping's `metadata`; the item part can itself be a placeholder, so `{@texture_wrapness:{wrapness}.nowrap}` resolves per pass. The lookup is loud — unknown mapping, item, or field stops the build.

**The value comes back literal.** Substitution scans the *template text* once, innermost first; a value returned by a foreign lookup is pasted in and not rescanned. A `{placeholder}` inside the borrowed field is therefore dead text in the caller: `"range": "{slot_range}"` on a `texture_wrapness` item stays `{slot_range}` wherever it lands, and a filter like `In({range}, {@texture_wrapness:{wrapness}.range})` silently fails every pass. Keep borrowed fields to constants; anything that depends on the caller belongs in the caller's own tokens or metadata.

---

## `templates_from` — one template, several mappings

`items_from` borrows a mapping's *list*. `templates_from` borrows the whole template *for* each listed mapping — it expands once per mapping named, with that mapping's [`tokens`](02-mappings.md#tokens--shared-snippets-for-borrowing-templates) filled in:

```json
"art_clearlogo_{scope}": {
  "templates_from": [ "widgets", "search" ],
  "index": { "start": 3200 },
  "filter": "{scope_filter}",
  "values": [
    { "condition": "{focus} + !String.IsEmpty(Container({index}).ListItem.Art(clearlogo))",
      "value": "$INFO[Container({index}).ListItem.Art(clearlogo)]" }
  ]
}
```

One row set; two families out — `art_clearlogo_widgets` per widget, `art_clearlogo_search` per search rail — each speaking its mapping's focus grammar via `{focus}`, each pruned by its own `{scope_filter}`.

`templates_from` *replaces* the file's `mapping` as the loop source. If the file's own mapping should expand too, list it: `expressions_regions.json` declares `"mapping": "regions"` and `"templates_from": ["regions", "widgets", "search", "views"]`. A file that only borrows can say `"mapping": "none"`.

When to reach for it: several mappings need *the same cascade* and differ only in a handful of snippets. Put the snippets in each mapping's `tokens`, write the cascade once. If the cascades differ in *structure* — different rows, not different snippets — they're different templates; don't force it. And when the deltas vary by **item** rather than by mapping, use a static mapping whose `metadata` carries them instead — the regions pattern, [use case 4](10-use-cases.md#4-regions--one-cascade-per-item-deltas).

---

## Filtering

`filter` is a build-time test per loop pass ([Rule Engine](08-rule-engine.md)). Passes that fail simply don't expand:

```json
"filter": "In({widget_preset}, [drilldown, group])"
```

Only drilldown and group widgets get their rows; other configured widgets are skipped entirely.

Don't confuse it with a row's `condition`: **filter decides at build time whether rows exist; condition decides at runtime whether Kodi uses them.** The two-axis trick — different loop values covering different ranges — is covered in [Includes → Filtering](07-includes.md#filtering-skipping-loop-passes) and works identically here; the wrapness ladders in `variables_ladders.json` are the live example.

---

## Where it goes

The builder writes `script-copacetic-helper_variables.xml`. Include it once:

```xml
<include file="script-copacetic-helper_variables.xml" />
```

Then use `$VAR[name]` anywhere.

---

## Next

- [Expressions](04-expressions.md) — combined boolean conditions
