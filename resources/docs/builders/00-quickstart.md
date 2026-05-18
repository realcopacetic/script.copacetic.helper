# Quickstart — Add a Setting End to End

This walks through one tiny feature — a per-content-type **clearlogo toggle** — touching every builder it needs and stopping where it doesn't. Read this before the per-builder reference docs.

The feature: in the view settings editor, the user toggles "show clearlogo" per content type (movies, tvshows, artists, …). Wherever the skin chooses to render a clearlogo, it checks an expression generated from those toggles.

Five files. Five edits. The skin reloads.

---

## Before you start — turn on dev mode

Open the addon's Settings → Developers → Enable Dev mode. With dev mode on, every Kodi start rebuilds all the builder outputs and reloads the skin, so your edits take effect on the next launch. You can also use **Rebuild now** in the same settings panel (or the equivalent script action) to apply changes without a restart.

Without dev mode, the service only builds outputs that are missing on disk — fine for users, frustrating while iterating.

Full details and other rebuild paths in [Builder System Overview → Development workflow](01-overview.md#development-workflow).

---

## 1. The mapping is already there

The built-in `content_types` mapping ships with the addon — windows mapped to their content types:

```json
{
  "items": {
    "videos": ["movies", "sets", "tvshows", "seasons", "episodes"],
    "music": ["artists", "albums", "songs"]
  },
  "placeholders": { "key": "window", "value": "content_type" }
}
```

Templates that reference `mapping: "content_types"` get `{window}` and `{content_type}` placeholders.

If you needed your own iteration values, you'd add a JSON file under `extras/templates/mappings/`. See [Mappings](02-mappings.md).

## 2. Configs — what values are allowed

Drop a file in `extras/templates/configs/`:

```json
{
  "mapping": "content_types",
  "configs": {
    "{content_type}_clearlogo": {
      "items": ["true", "false"],
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

Result: `movies_clearlogo`, `tvshows_clearlogo`, `artists_clearlogo`, `sets_clearlogo` each resolve to items `[true, false]` when the editor opens. Every other content type resolves to an empty list — the toggle won't appear for them.

[Configs Builder reference →](05-configs.md)

## 3. Controls — what the user clicks

Add a control to your existing `controls_views.json`:

```json
"clearlogo": {
  "id": 203,
  "control_type": "radiobutton",
  "contextual_bindings": {
    "linked_config": "{content_type}_clearlogo",
    "update_trigger": "focused({content_type}_item)",
    "visible": "In({content_type}, [movies, sets, tvshows, artists])"
  },
  "label": "Show clearlogo"
}
```

One control. The contextual bindings make it read and write a different config key depending on which `{content_type}_item` listitem the user has focused. Hidden for content types that don't support it.

The values the radiobutton flips between come from the resolved config — first allowed item ("true") = on, second ("false") = off.

[Controls Builder reference →](06-controls.md)

## 4. Window XML — where the control lives

This part is your existing skin XML, not a builder input. The viewsettings window has a control with id 203 of type radiobutton. The Dynamic Editor finds it by id and wires it up.

Skip if you've already done this for other settings.

## 5. Expressions — the boolean the skin uses

Drop a file in `extras/templates/expressions/`:

```json
{
  "mapping": "content_types",
  "expressions": {
    "art_clearlogo_visible_{window}": {
      "rules": [
        {
          "condition": "xml(Skin.String({content_type}_clearlogo,true))",
          "type": "append",
          "value": "Container.Content({content_type})"
        }
      ]
    }
  }
}
```

For each window group, this collects every content type whose clearlogo toggle is true and joins them with `|`. After the user enables clearlogo for movies and tvshows, `art_clearlogo_visible_videos` becomes `Container.Content(movies) | Container.Content(tvshows)`.

[Expressions Builder reference →](04-expressions.md)

## 6. Skin XML — use the result

Anywhere your skin renders a clearlogo, gate it on the expression:

```xml
<control type="image">
  <visible>$EXP[art_clearlogo_visible_videos]</visible>
  <texture>$VAR[texture_clearlogo]</texture>
  <!-- ... -->
</control>
```

Done. The user opens the editor, toggles clearlogo for movies, presses Close. The expressions builder re-runs, the skin reloads, and clearlogos appear on movies but not on episodes.

---

## What you just did

- One **mapping** (built-in) declared the iteration values.
- A **configs template** expanded into per-content-type setting definitions, filtered by which content types support the feature. The Dynamic Editor resolves these on demand.
- A **controls template** expanded into one editable control with bindings for each supported content type, resolved when the editor opens.
- The user's choices live in **Kodi skin strings** — `Skin.String(movies_clearlogo)` etc. — written by the editor on close.
- The **expressions builder** turned one template into one expression per window, evaluating the user's choices into a boolean the skin can consume.

That's the static path: skin strings, fixed at build time, edited through the editor.

The other path — runtime state — is what powers the widgets and menu features. Same builders, but configs/controls/expressions flag `mode: "dynamic"` and the values live as fields on entries in `runtime_state.json` instead of as skin strings. The user can grow and shrink the list at runtime. See [Runtime State & Dynamic Editor](09-runtime-state.md) and [the widgets use case](10-use-cases.md#3-widgets--dynamic-runtime-state-driven).

---

## Decision guide

| You want | Read |
|---|---|
| A per-content-type setting (skin strings, fixed set) | [Use case 2: Views](10-use-cases.md#2-views--static-skin-string-driven) |
| A user-managed list (add/delete/reorder, runtime fields) | [Use case 3: Widgets](10-use-cases.md#3-widgets--dynamic-runtime-state-driven) |
| Just generate variables for repeated XML patterns | [Use case 1: Standalone variables](10-use-cases.md#1-standalone-variables) |
| To understand the whole pipeline before picking | [Builder System Overview](01-overview.md) |

---

## Next
 
You've now seen one feature, end to end. Different next steps depending on what you want:
 
- **Build a real, multi-builder feature.** [Use case 3: Widgets](10-use-cases.md#3-widgets--dynamic-runtime-state-driven) is the second tutorial — same teaching shape, but covers configs, controls, includes, and runtime state.
- **Understand the whole system.** [Builder System Overview](01-overview.md) covers the pipeline, run contexts, dev workflow, and substitution engine.
- **Look something up.** Each per-builder doc ([02–08](02-mappings.md)) is reference. Land on the one for the builder you're using; don't read them in order.