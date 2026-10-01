# Troubleshooting

Symptom → likely cause → fix. Grab the log first: enable debug logging in Kodi (Settings → System → Logging), or turn on the addon's own Troubleshooting → Logs → **Enable extra debug logs**, which writes the addon's debug lines at info level. The addon's messages start with `script.copacetic.helper →` in `kodi.log`.

---

## "I changed a template and nothing happened"

In production mode the service only builds files that are **missing** (or everything, when the settings file gains a new mapping or the resolver cache is stale) — it doesn't notice edits. Turn on dev mode, or run:

```
RunScript(script.copacetic.helper,action=rebuild)
```

If you changed a dynamic mapping's `items` or `default_order`, or an item's `parent`, and want the settings list itself regenerated, use dev mode's **Reset on next start** (or `rebuild` with `reset=true`) — a plain rebuild keeps the user's existing entries. Other metadata and `config_fields` changes only need a rebuild.

---

## "My control doesn't show up in the editor"

The editor looks up each control by its `id` in your window XML. If the XML control is missing — or is the wrong type (template says `radiobutton`, XML says `button`) — that control is skipped and hidden. The window still opens; the control just never appears. The log gets a warning naming the id.

Check, in order: the template names a known `control_type` (missing or unknown → the control is skipped); the `id` matches between template and XML; the `control_type` matches the XML control type; for a `sliderex`, the companion button exists at the slider id + a trailing `0` (202 → 2020).

Edited a controls file and the window still shows the old shape? The editor reads templates from the resolver cache, refreshed by every build — run `action=rebuild` (dev mode does this on every start).

If the control exists but is *hidden*, its `visible` condition is false for the highlighted row — check its tokens against that entry's actual settings.

---

## "The Add/Delete/Move buttons don't appear"

Add, Move, and Delete only attach when one of the window's controls has `role: "item_picker"` or `role: "add_action"` — see [Controls → The Add control](06-controls.md#the-add-control-item_picker-and-add_action). No role, no mutation buttons: the window is a fixed list on purpose. Reset and Close are separate — they work in fixed lists too.

If a control *has* the role but its XML control is missing, the role never attaches — fix the XML control first (previous section).

---

## "A setting shows no options / the control is greyed out"

The config resolved to one value or none. Usual causes:

- **`exclude` mode removed everything.** The setting then has no values and no default, and the log warns that the config "resolved no items". (In `include` mode, matching nothing is an error that stops the build — see the next section.)
- **A rule value or default isn't in `items`.** `items` is the whole universe: rule values outside it do nothing, silently; a default outside it falls back to the first survivor. Check spelling against the `items` keys (the keys, not the display labels).
- **One value survived on purpose.** Rules narrowed it to one option, so the control disables itself — that's the "effectively locked" state, and may be exactly what you wanted.

---

## "The build stops with a config error"

`include-mode config '…' matched no items … add a 'true' catch-all rule` — include mode keeps *only* what rules match, and for at least one item no rule matched. Add a last rule with `"condition": "true"` listing the values that should survive otherwise.

`unknown token '{…}' in config rule` — if a rule reads another setting's token — `{layout}`, `{art}`, `{autoplay}` — that setting must be listed in the config's `dependent_fields`. Without it the config can resolve before the other setting exists, and the build stops instead of waiting. See [Configs → rules that read another setting](05-configs.md#rules-that-read-another-setting). Otherwise the token is simply misspelt.

`Unresolvable seed templates` — two settings' configs wait for each other through `dependent_fields`, or a config name in `config_fields` uses a token the entry doesn't have.

---

## "My expression is always false"

No rule matched and there's no fallback. Either a rule should have matched (check the condition's tokens — a misspelt token in a rule becomes an empty string, so the comparison quietly fails) or you want a fallback so one item catches the leftovers. See [Expressions → Fallbacks](04-expressions.md#fallbacks).

If the expression *file* doesn't contain your expression at all, the whole loop pass may have been filtered out, or the mapping name in the template doesn't match.

---

## "A `{token}` came out empty in my output"

In values — variable rows, expression rules, include bodies — a token that matches nothing on that loop pass becomes an empty string (and an include param or attribute that ends up empty is dropped). Check the name against [Overview → Placeholders](01-overview.md#placeholders), and remember: entry fields only exist when the mapping is `dynamic`. In template names, filters and mapping `tokens` the same mistake stops the build instead, with the token named in the error.

## "A `{token}` shows literally in the settings window"

Editor labels, descriptions, `visible` conditions and onclick actions use plain `{name}` lookups. If any token in the string is unknown for the highlighted entry, the whole string is used unchanged. Maths and `{@mapping:item.field}` don't work there — see [Controls → Tokens in the editor](06-controls.md#tokens-in-the-editor).

---

## "A whole family of variables vanished after I touched a mapping"

A filter on those templates is failing every pass — usually a condition that's well-formed but always false: a typo'd operator (`!equals`), a token that rendered to something the rule never matches, a `+` or `|` inside a token's value (the rule engine splits at every one; it has no grouping). The engine doesn't log these. Diff the generated output against the last good build; the missing names tell you which template's filter to check. (An unresolved `{placeholder}` in a filter *does* stop the build, naming the template.)

---

## "The build stops with an unknown mapping / item / field error"

`items_from` and `{@mapping:item.field}` references are checked loudly — a name that doesn't resolve stops the build with a message naming the reference. (A misspelt mapping in `mapping` or `templates_from` is *not* caught: it quietly expands as `none`, one pass with no loop values.) Check: the mapping file exists and its top-level key matches the name used; for foreign references, the item and field exist in that mapping's `metadata` and the field is a string. If you renamed or deleted a mapping, grep the templates for borrowers before rebuilding — and delete the resolver cache so the editor doesn't keep serving the old shape.

---

## "A param vanished from my include output"

Its value resolved to empty, and empty means dropped — that's the pruning rule, so your include's `$PARAM` defaults apply. If the param should have had a value, the entry or metadata doesn't actually contain it.

---

## "My condition comparing a $VAR never works"

In Kodi's own string checks (`String.IsEqual`, `String.Contains`, …) the second argument is either an infolabel name or a fixed string; a `$VAR[...]` there is resolved once, when Kodi first reads the condition, not live. This is a Kodi engine limit, not a builder one. Move the comparison into rule conditions or template structure. See the note in [Rule Engine](08-rule-engine.md#live-kodi-state-xml).

---

## "The list rows have no label or icon"

Row labels and icons come from the listitem template's tokens (`{label}`, `{icon}`, or `{content_type}`-style). Blank rows mean the tokens resolve to nothing for those entries — usually a custom entry whose `label` was never filled, or an icon path token that isn't a string in metadata.

---

## "User settings survived a change they shouldn't have" (or vice versa)

Untouched settings aren't stored — they read their config default live, so template default changes reach everyone who never overrode them. Settings the user *did* change are stored and win. If you need everyone back on defaults, that's a reset, not a rebuild.

---

## "Something in a nested editor didn't stick until later"

By design: when one editor opens another (for example a child list opened with `parent=`), the rebuild and skin reload wait for the **outermost** editor to close, so a whole session reloads once. Close all the way out.

---

## "Management buttons appeared on a fixed list"

Editability comes from a control carrying a `role` — grep your controls JSON for `"role"` first; a copy-pasted picker shape is the usual cause. Without a role the addon hides buttons 410–413 when the window opens, so if they show, some control loaded into the window (including one borrowed with `controls_from`) has a role.

---

## "Hosted editor: the shell shows with no dialog over it"

The session gate blocked the forward — `active_editor_name` was still set when the shell's onload ran. Normal for a moment while a previous session's rebuild finishes; permanent only if the property is stuck (a crash inside a session before its cleanup). Reopen from anywhere or restart; the property clears with the session. See [Runtime State → Hosting](09-runtime-state.md#hosting--binding-an-editor-to-a-real-window).

---

## Still stuck?

Reproduce with dev mode on and debug logging enabled, then read `kodi.log` bottom-up for the first `script.copacetic.helper` warning — the builders and editor log skipped controls, failed lookups, and empty resolutions with the names involved.
