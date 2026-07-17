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
    "texture_primary_poster{index}": {
      "index": { "start": -3, "end": 6 },
      "values": [
        {
          "condition": "!String.IsEmpty(ListItemNoWrap({index}).Art(poster))",
          "value": "$INFO[ListItem({index}).Art(poster)]"
        },
        { "value": "$INFO[ListItem({index}).Icon]" }
      ]
    }
  }
}
```

Ten variables out — `texture_primary_poster-3` through `...poster6` — each with the chain and its own number baked in.

| Field | What it does |
|---|---|
| `index` | Number range: `start`, `end`, optional `step` |
| `items` | An explicit list to loop over — each value becomes `{item}` |
| `values` | The rows — `{condition, value}` dicts, or lists of them (blocks, below) |
| `filter` | Skip loop passes at build time — see [Filtering](#filtering) |
| `mode` | `"dynamic"` = loop the settings-file entries instead of the mapping's items |

`index` and `items` combine: with both, you get every index × item pairing, and both `{index}` and `{item}` are available. In dynamic mode, `{index}` numbers the settings entries, so a declared `index` is just the starting value; `items` still multiplies with the entries. With neither, the mapping alone drives the loop.

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
- **Loop controls work here too.** `index`, `items`, `mode`, and `filter` behave exactly as on ordinary templates; the `outputs` names and `rows` expand per pass. `_primary_base_cluster` in `variables_textures.json` loops `items: [poster, fanart, square]` — each art type gets its own main/fallback pair from one cascade.
- **Sparse rows.** A row can feed some outputs and skip others — just leave the key off. That output's cascade simply doesn't have that row. Useful when one output's chain is a subset of another's.
- **Blocks apply.** `rows` groups with `[...]` the same way `values` does.

---

## Filtering

`filter` is a build-time test per loop pass ([Rule Engine](08-rule-engine.md)). Passes that fail simply don't expand:

```json
"filter": "In({widget_preset}, [drilldown, group])"
```

Only drilldown and group widgets get their rows; other configured widgets are skipped entirely.

Don't confuse it with a row's `condition`: **filter decides at build time whether rows exist; condition decides at runtime whether Kodi uses them.** The two-axis trick — one loop value passing everywhere, another only in a range — is covered in [Includes → Filtering](07-includes.md#filtering-skipping-loop-passes) and works identically here; `texture_primary_poster{suffix}{index}` in `variables_textures.json` is the live example.

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