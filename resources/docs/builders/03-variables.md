# Variables Builder

The variables builder generates Kodi `<variable>` XML elements — each containing a list of condition/value pairs that Kodi evaluates at runtime to resolve a single value. Define one template; the builder expands it once per index, item, or mapping value.

---

## Input format

JSON files placed in `extras/templates/variables/`. Each file declares a mapping and a `variables` object.

| Field | Type | Required | Description |
|---|---|---|---|
| `mapping` | string | Yes | Mapping name. Either built-in (`content_types`), a custom one in `extras/templates/mappings/`, or `"none"` for templates that only use `index`/`items` — see [Mappings](02-mappings.md). |

The variables builder supports two template shapes — **ordinary** (one variable per template) and **cluster** (multiple variables sharing one condition cascade).

---

## Ordinary templates

The common case: a single template producing one variable per loop iteration.

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

| Field | Type | Required | Description |
|---|---|---|---|
| `index` | object | No | Numeric range: `start`, `end`, optional `step` |
| `items` | list | No | Explicit list of values to loop over |
| `values` | list | Yes | Array of `{condition, value}` pairs and/or blocks — see [Blocks](#blocks) |
| `filter` | string | No | Build-time expression; loop values that fail it are skipped — see [Filtering](#filtering) |
| `mode` | string | No | `"dynamic"` to iterate once per runtime entry. Default is static, which iterates once per item in the mapping (and/or the template's own `items`/`index`). |

`index` and `items` can be combined for two-axis expansion. When both are present in a static template, the loop produces every (index × item) combination on top of any mapping iteration; both `{index}` and `{item}` are available as placeholders. In dynamic mode `{index}` is reserved for runtime-entry numbering, so `index` declared on a dynamic template is interpreted as a starting value only; `items` still cross-products with runtime entries. If neither is present, expansion is driven entirely by the mapping.

Each entry in `values` is a `{condition, value}` pair, or a list of pairs forming a block — see [Blocks](#blocks):
- `condition` — A Kodi boolean expression. Optional; omit it (or use `"true"`) for an unconditional row.
- `value` — The value to use when the condition matches. Kodi evaluates conditions top to bottom and uses the first match.

Both fields support `{placeholder}` substitution.

> **Note:** The variables builder doesn't evaluate conditions at build time. They're written into the output XML as native Kodi expressions and resolved by Kodi at runtime. The builder only does placeholder substitution.

---

## Cluster templates

Sometimes you want several parallel variables that share the same condition cascade — e.g. a label and an icon that should both come from the same fallback chain. Cluster templates let you write that cascade once and emit multiple variables from it.

A cluster template uses `outputs` and `rows` instead of `values`:

```json
"_breadcrumb_left_cluster": {
  "outputs": {
    "label": "label_breadcrumb_left",
    "texture": "texture_breadcrumb_left"
  },
  "rows": [
    {
      "condition": "Container.Content(movies)",
      "label": "$LOCALIZE[342]",
      "texture": "icons/movies.png"
    },
    {
      "condition": "Container.Content(tvshows)",
      "label": "$LOCALIZE[20343]",
      "texture": "icons/tvshows.png"
    },
    {
      "condition": "Container.Content(seasons)",
      "label": "$INFO[ListItem.TVShowTitle]",
      "texture": "icons/tvshows.png"
    },
    {
      "condition": "Container.Content(episodes)",
      "label": "$INFO[ListItem.Season,Season ,]$INFO[Container.NumItems, • , episodes]",
      "texture": "icons/tvshows.png"
    },
    {
      "condition": "Container.Content(artists)",
      "label": "$LOCALIZE[133]",
      "texture": "icons/music.png"
    },
    {
      "condition": "Container.Content(albums)",
      "label": "$LOCALIZE[132]",
      "texture": "icons/music.png"
    }
  ]
}
```

| Field | Type | Description |
|---|---|---|
| `outputs` | object | Map of row-key → variable-name template. Each declared output produces one variable per loop iteration. |
| `rows` | list | Shared cascade. Each row has an optional `condition` and one value per output it contributes to. Rows may be grouped into blocks — see [Blocks](#blocks). |

A cluster also accepts the loop-control fields from ordinary templates — `index`, `items`, `mode`, and `filter` — which drive how many times the row cascade expands. The `outputs` name templates and `rows` then expand per loop value, the same way an ordinary template's `values` do. `_primary_base_cluster` in `variables_artwork.json` uses `items` this way: each item produces its own pair of output variables.

The example above produces two variables — `label_breadcrumb_left` and `texture_breadcrumb_left` — both following the same condition cascade. Whatever content type the focused container has, both variables resolve from the same matching row. The skin can use them together (`$VAR[label_breadcrumb_left]` next to `$VAR[texture_breadcrumb_left]`) without having to maintain two separate cascades that must stay in sync.

The template name (`_breadcrumb_left_cluster`) is internal — only the `outputs` values become real variables. A leading underscore is a convention for "this isn't a real variable, don't reference it directly".

### Sparse rows

Rows don't have to provide a value for every output. A row that contributes to one output but not another simply omits the missing key:

```json
{ "condition": "Container.Content(movies)", "label": "$LOCALIZE[342]" }
```

This row contributes to the `label` cascade but not `texture` — useful when one output's chain is a strict subset of another's.

### Empty terminators

A row whose value is the empty string `""` produces a self-closing `<value condition="..."/>` element. Kodi treats this as an explicit unconditional terminator: stop evaluating, return empty. Useful for forcing a clean exit on the fallback row when you don't want any default value.

---

## Filtering

A `filter` narrows which loop values a template expands over. It's an expression evaluated **at build time** by the [Rule Engine](08-rule-engine.md): each substitution is tested, and those that fail are dropped before expansion. It works on both ordinary and cluster templates.

```json
"label_multiart_home_dualwidgets": {
  "mode": "dynamic",
  "index": { "start": 3200 },
  "filter": "In({widget_preset}, [drilldown, group])",
  "values": [ "..." ]
}
```

Only widgets whose `widget_preset` is `drilldown` or `group` keep their indexed rows; every other configured widget is skipped.

`filter` uses the same grammar as Rule Engine conditions — `In(...)`, `equals(...)`, `not`, `xml(...)` — with `{placeholder}` substitution against the current loop value.

It is distinct from a row's `condition`. `filter` is build-time and decides whether a row is **generated at all**; `condition` is the runtime Kodi expression that decides whether Kodi **uses** a generated row.

When a filter excludes every match, placeholder-bearing rows expand to nothing — but placeholder-free rows still emit, so a constant-named template with a fallback still produces its variable. See [Always-present variables](#always-present-variables).

---

## Blocks

Both `values` (ordinary templates) and `rows` (cluster templates) can mix rows that vary per index or item with rows that are fixed. Each row expands by the same rule:

| Row contains | Expansion |
|---|---|
| A `{placeholder}` | Repeated once per index or item value, in place |
| No placeholder | Emitted once, in place |

Rows resolving to identical `(condition, value)` pairs are collapsed to the first occurrence. This handles the case where a placeholder-bearing row's placeholders are constant across the substitution group — for example, a terminal row whose `{listitem}`/`{position}` placeholders don't vary within a `{type, position}` group. Kodi's `<value>` cascade picks the first matching row, so dropped duplicates would have been dead code anyway.

Rows expand in the order written. A placeholder-free row keeps a fixed position — top, middle, or end of the cascade — so one template can combine indexed rows with a shared fallback:

```json
{
  "mapping": "widgets",
  "variables": {
    "label_multiart_home_dualwidgets": {
      "mode": "dynamic",
      "index": { "start": 3200 },
      "values": [
        {
          "condition": "Control.HasFocus({index}) + !String.IsEmpty(Container({index}).ListItem.Art(poster1))",
          "value": "poster"
        },
        {
          "condition": "Control.HasFocus({index}) + !String.IsEmpty(Container({index}).ListItem.Art(fanart1))",
          "value": "fanart"
        },
        { "value": "$VAR[label_multiart_home]" }
      ]
    }
  }
}
```

With two widgets configured (`3200`, `3201`), each indexed row expands once per widget and the placeholder-free row emits once, last (conditions abbreviated):

```xml
<variable name="label_multiart_home_dualwidgets">
  <value condition="Control.HasFocus(3200) + !String.IsEmpty(Container(3200).ListItem.Art(poster1))">poster</value>
  <value condition="Control.HasFocus(3201) + !String.IsEmpty(Container(3201).ListItem.Art(poster1))">poster</value>
  <value condition="Control.HasFocus(3200) + !String.IsEmpty(Container(3200).ListItem.Art(fanart1))">fanart</value>
  <value condition="Control.HasFocus(3201) + !String.IsEmpty(Container(3201).ListItem.Art(fanart1))">fanart</value>
  <value>$VAR[label_multiart_home]</value>
</variable>
```

The indexed rows interleave — `poster` for every widget, then `fanart` for every widget.

### Grouping rows

Wrap rows in a list to keep them together as one block. If any row in a block contains a placeholder, the whole block repeats per index or item as a unit, with its rows kept contiguous and in order:

```json
"values": [
  [
    {
      "condition": "Control.HasFocus({index}) + !String.IsEmpty(Container({index}).ListItem.Art(poster1))",
      "value": "poster"
    },
    {
      "condition": "Control.HasFocus({index}) + !String.IsEmpty(Container({index}).ListItem.Art(fanart1))",
      "value": "fanart"
    }
  ],
  { "value": "$VAR[label_multiart_home]" }
]
```

```xml
<variable name="label_multiart_home_dualwidgets">
  <value condition="Control.HasFocus(3200) + !String.IsEmpty(Container(3200).ListItem.Art(poster1))">poster</value>
  <value condition="Control.HasFocus(3200) + !String.IsEmpty(Container(3200).ListItem.Art(fanart1))">fanart</value>
  <value condition="Control.HasFocus(3201) + !String.IsEmpty(Container(3201).ListItem.Art(poster1))">poster</value>
  <value condition="Control.HasFocus(3201) + !String.IsEmpty(Container(3201).ListItem.Art(fanart1))">fanart</value>
  <value>$VAR[label_multiart_home]</value>
</variable>
```

Now each widget's rows stay contiguous. A single row written on its own is a one-row block; reach for a multi-row block when a group of indexed rows must stay contiguous relative to each other. Cluster `rows` group into blocks the same way.

### Rows without a condition

Omit `condition` for an unconditional row. It produces a bare `<value>value</value>` with no attribute, the same as `"condition": "true"`. (An empty `value` is a different case — see [Empty terminators](#empty-terminators).)

### Always-present variables

Placeholder-free rows don't depend on any index or item, so they survive even when a template produces no substitutions at all — a dynamic template with no configured entries, or a `filter` that excludes every match. A template whose name has no `{placeholder}` and carries at least one placeholder-free row therefore always produces its variable, so `$VAR[...]` references to it stay safe to use.

---

## Available placeholders

Inside conditions and values (in either shape), `{placeholder}` tokens are substituted before output. What's available depends on what's driving the expansion:

- The mapping's loop values (e.g. `{window}`, `{content_type}`, or whatever the mapping declares)
- All string-valued metadata for the current item, if the mapping defines metadata
- `{index}` if the template uses an `index` range
- `{item}` if the template uses an explicit `items` list

Plus three loop-position values injected automatically:

| Placeholder | Description |
|---|---|
| `{count}` | Total number of substitutions in this expansion |
| `{is_first}` | `"true"` on the first substitution, `"false"` otherwise |
| `{is_last}` | `"true"` on the last substitution, `"false"` otherwise |

Useful for variables that need to know where they sit in a sequence — for example, sizing a fallback chain to `{count}` entries, or producing different output for the first or last index.

---

## Example: texture art variables

This is from Copacetic 2's `variables.json`. It uses `"mapping": "none"` because it only needs an index range:

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

The index range expands to -3 through 6 — ten variables. For each, the condition and value strings get `{index}` substituted. Output:

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

Without the builder, you'd write ten near-identical `<variable>` blocks by hand — and maintain them all if the art fallback chain changes.

---

## Using with a mapping

When a template references a mapping other than `"none"`, the mapping's loop values combine with any `items` or `index` in the template itself.

For example, with the `content_types` mapping (dict-of-lists: window → content_types), a template can use both `{window}` and `{content_type}` in addition to `{index}`:

```json
{
  "mapping": "content_types",
  "variables": {
    "viewsettings_{index}_txtcolor": {
      "index": { "start": 100, "end": 111 },
      "values": [
        { "condition": "ControlGroup(3200).HasFocus", "value": "pearl" },
        { "condition": "true", "value": "grout" }
      ]
    }
  }
}
```

This particular example doesn't use `{window}` or `{content_type}` in its template name or values — only `{index}`. The mapping is referenced but the template name contains no mapping placeholders, so it expands once per index value rather than once per content type × index combination. The builder avoids duplicate expansions automatically.

---

## Output format

The builder writes `script-copacetic-helper_variables.xml`. Reference it from your skin's `Includes.xml`:

```xml
<include file="script-copacetic-helper_variables.xml" />
```

Then use the variables anywhere with `$VAR[variable_name]`.

---

## Next

- [Expressions Builder](04-expressions.md) — Boolean logic with grouping and fallbacks