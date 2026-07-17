# Quickstart — Add a Setting End to End

This walks through one small feature — a per-content-type **clearlogo toggle** — touching every builder it needs and skipping the ones it doesn't.

The feature: in the view settings window, the user turns "show clearlogo" on or off for each content type (movies, tvshows, artists, …). Wherever your skin draws a clearlogo, it checks an expression built from those choices.

Five edits. The skin reloads.

---

## Before you start — turn on dev mode

Addon Settings → Developers → **Enable Dev mode**. With it on, every Kodi start rebuilds everything and reloads the skin. **Rebuild now** in the same panel does it without a restart.

Without dev mode, the service only builds files that are missing — right for users, annoying while you're iterating.

---

## 1. Register the field on the mapping

The `content_types` mapping ships with the addon. It lists the content types and tags each one with its window:

```json
{
  "content_types": {
    "mode": "dynamic",
    "items": ["movies", "sets", "tvshows", "seasons", "episodes", "..."],
    "placeholders": { "key": "content_type" },
    "config_fields": {
      "global": { "clearlogo": "{content_type}_clearlogo" }
    },
    "metadata": {
      "movies": { "window": "videos" },
      "tvshows": { "window": "videos" }
    }
  }
}
```

Your one edit here: add `"clearlogo": "{content_type}_clearlogo"` under `config_fields.global`. This says: entries in this list have a `clearlogo` setting, and the config named `{content_type}_clearlogo` decides its allowed values.

Any template that says `"mapping": "content_types"` can use `{content_type}` — and `{window}`, via metadata — in its strings.

If you need your own list to loop over, add a file under `extras/templates/mappings/`. See [Mappings](02-mappings.md).

## 2. Configs — what values are allowed

New file in `extras/templates/configs/`:

```json
{
  "mapping": "content_types",
  "configs": {
    "{content_type}_clearlogo": {
      "items": { "true": "$LOCALIZE[186]", "false": "$LOCALIZE[106]" },
      "filter_mode": "include",
      "rules": [
        {
          "condition": "In({content_type}, [movies, sets, tvshows, artists])",
          "value": ["true", "false"]
        }
      ],
      "defaults": { "*": "false" }
    }
  }
}
```

Result: movies, sets, tvshows, and artists get a true/false choice, shown as "Enabled / Disabled". Every other content type gets an empty list — no toggle for them.

[Configs Builder →](05-configs.md)

## 3. Controls — what the user clicks

Add one control to your controls file:

```json
"clearlogo": {
  "field": "clearlogo",
  "id": 203,
  "control_type": "radiobutton",
  "visible": "In({content_type}, [movies, sets, tvshows, artists])",
  "label": "Show clearlogo"
}
```

One radiobutton. It reads and writes the `clearlogo` setting of whichever row is highlighted in the left-hand list. First allowed value = on, second = off.

[Controls Builder →](06-controls.md)

## 4. Window XML — where the control lives

Your normal skin XML. The viewsettings window needs a radiobutton with id 203; the editor finds it by id and takes over. Skip this step if the window already exists. A copy-paste skeleton is in [Runtime State → Window XML](09-runtime-state.md#a-minimal-window-xml).

## 5. Expressions — the boolean the skin uses

New file in `extras/templates/expressions/`:

```json
{
  "mapping": "content_types",
  "expressions": {
    "art_clearlogo_visible_{window}": {
      "rules": [
        {
          "condition": "equals({clearlogo}, true)",
          "type": "append",
          "value": "Container.Content({content_type})"
        }
      ]
    }
  }
}
```

For each window, this collects every content type where the toggle is on and joins them with `|`. If the user enables it for movies and tvshows, `art_clearlogo_visible_videos` becomes `Container.Content(movies) | Container.Content(tvshows)`.

[Expressions Builder →](04-expressions.md)

## 6. Skin XML — use the result

```xml
<control type="image">
  <visible>$EXP[art_clearlogo_visible_videos]</visible>
  <texture>$VAR[texture_clearlogo]</texture>
</control>
```

Done. The user opens the editor, flips the toggle for movies, presses Close. The builders re-run, the skin reloads, clearlogos appear on movies but not episodes.

---

## One setting, four names

You just gave the same setting four names in four places. This trips everyone up once, so here's the map:

| Name | What it is | Where it lives |
|---|---|---|
| `clearlogo` | The **field** — the key stored per entry in the settings file | `config_fields` on the mapping, `field` on the control |
| `{content_type}_clearlogo` | The **config** — the rules for what values are allowed | The configs file |
| `clearlogo` (again) | The **control** — the template name for the UI element | The controls file (the name itself is only a label; `field` does the linking) |
| `203` | The **control ID** — where it sits in your window XML | The controls file and your window XML |

The chain: control `id` finds the XML control → control `field` names the setting → the mapping's `config_fields` points that field at a config → the config decides the values. If a setting misbehaves, walk that chain.

---

## What you just did

- The **mapping** listed the loop values and registered the new field.
- A **config** said which values are allowed, per content type.
- A **control** gave the user a radiobutton for it.
- The user's choices are stored in the **settings file** (`runtime_state.json`), one entry per content type.
- The **expressions builder** turned those entries into one expression per window.

The view settings window is a **fixed list**: the rows are created automatically and the user can't add or remove them — only change each row's settings. The widget and menu editors are **editable lists**: same machinery, plus one control with a `role` that unlocks Add / Delete / Move buttons. See [Runtime State & Dynamic Editor](09-runtime-state.md) and [the widgets use case](10-use-cases.md#3-widgets--editable-lists).

---

## Where next

| You want | Read |
|---|---|
| A per-content-type setting (fixed list) | [Use case 2: Views](10-use-cases.md#2-views--a-fixed-list) |
| A list the user can add to and reorder | [Use case 3: Widgets](10-use-cases.md#3-widgets--editable-lists) |
| Just lots of similar variables | [Use case 1: Standalone variables](10-use-cases.md#1-standalone-variables) |
| The big picture first | [Overview](01-overview.md) |
| Something's broken | [Troubleshooting](11-troubleshooting.md) |
