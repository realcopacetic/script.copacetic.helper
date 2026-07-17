# Troubleshooting

Symptom → likely cause → fix. Grab the log first: enable debug logging in Kodi (Settings → System → Logging); the addon's messages are tagged `script.copacetic.helper` in `kodi.log`.

---

## "I changed a template and nothing happened"

In production mode the service only builds files that are **missing** — it doesn't notice edits. Turn on dev mode, or run:

```
RunScript(script.copacetic.helper,action=rebuild)
```

If you changed a mapping's `default_order`, `config_fields`, or `metadata` and want the settings list itself regenerated, use dev mode's **Reset on next start** (or `rebuild` with `reset=true`) — a plain rebuild keeps the user's existing entries.

---

## "My control doesn't show up in the editor"

The editor looks up each control by its `id` in your window XML. If the XML control is missing — or is the wrong type (template says `radiobutton`, XML says `button`) — that control is skipped and hidden. The window still opens; the control just never appears. The log gets a warning naming the id.

Check, in order: the `id` matches between template and XML; the `control_type` matches the XML control type; for a `sliderex`, the companion button exists at the slider id + a trailing `0` (202 → 2020).

If the control exists but is *hidden*, its `visible` condition is false for the highlighted row — check its tokens against that entry's actual settings.

---

## "The Add/Delete/Move buttons don't appear"

They only show when one of the window's controls has `role: "item_picker"` or `role: "add_action"` — see [Controls → The Add control](06-controls.md#the-add-control-item_picker-and-add_action). No role, no buttons: the window is a fixed list on purpose.

If a control *has* the role but its XML control is missing, the role never attaches — fix the XML control first (previous section).

---

## "A setting shows no options / the control is greyed out"

The config resolved to one value or none. Usual causes:

- **`filter_mode: "include"` with no catch-all.** Include mode keeps *only* what rules match — an item no rule mentions is gone. Add a `"condition": "true"` rule for values that should always survive.
- **A rule value or default isn't in `items`.** `items` is the whole universe: rule values outside it do nothing, silently; a default outside it falls back to the first survivor. Check spelling against the `items` keys (the keys, not the display labels).
- **One value survived on purpose.** Rules narrowed it to one option, so the control disables itself — that's the "effectively locked" state, and may be exactly what you wanted.

---

## "A config rule errors, or a value never resolves"

If a rule reads another setting's token — `{layout}`, `{art}`, `{autoplay}` — that setting must be listed in the config's `dependent_fields`. Without it the config can resolve before the other setting exists, and the rule fails instead of waiting. See [Configs → rules that read another setting](05-configs.md#rules-that-read-another-setting).

Also check the loop-token rule: a config with a plain (no-token) name is shared — its rules and defaults can't use the loop token, and the resolver errors if they try. See [Configs → one per item or one shared](05-configs.md#one-config-per-item-or-one-shared).

---

## "My expression is always false"

No rule matched and there's no fallback. Either a rule should have matched (check the condition's tokens — a typo'd token stays as literal `{typo}` and never equals anything) or you want a fallback so one item catches the leftovers. See [Expressions → Fallbacks](04-expressions.md#fallbacks).

If the expression *file* doesn't contain your expression at all, the whole loop pass may have been filtered out, or the mapping name in the template doesn't match.

---

## "A `{token}` appears literally in my output"

Unresolvable tokens are left as-is on purpose, so they're visible instead of silently vanishing. The token name doesn't match anything available on that loop pass — check it against [Overview → Placeholders](01-overview.md#placeholders), and remember: entry fields only exist on `dynamic` passes, and only string metadata is available as text.

---

## "A param vanished from my include output"

Its value resolved to empty, and empty means dropped — that's the pruning rule, so your include's `$PARAM` defaults apply. If the param should have had a value, the entry or metadata doesn't actually contain it.

---

## "My condition comparing a $VAR never works"

Kodi's own string checks (`String.IsEqual`, `String.Contains`, …) don't resolve `$VAR[...]` in their arguments — only `$INFO` labels and plain strings. This is a Kodi engine limit, not a builder one. Move the comparison into rule conditions or template structure. See the note in [Rule Engine](08-rule-engine.md#live-kodi-state-xml).

---

## "The list rows have no label or icon"

Row labels and icons come from the listitem template's tokens (`{label}`, `{icon}`, or `{content_type}`-style). Blank rows mean the tokens resolve to nothing for those entries — usually a custom entry whose `label` was never filled, or an icon path token that isn't a string in metadata.

---

## "User settings survived a change they shouldn't have" (or vice versa)

Untouched settings aren't stored — they read their config default live, so template default changes reach everyone who never overrode them. Settings the user *did* change are stored and win. If you need everyone back on defaults, that's a reset, not a rebuild.

---

## "Something in a nested editor didn't stick until later"

By design: when one editor opens another (the hub pattern), the rebuild and skin reload wait for the **outermost** editor to close, so a whole session reloads once. Close all the way out.

---

## Still stuck?

Reproduce with dev mode on and debug logging enabled, then read `kodi.log` bottom-up for the first `script.copacetic.helper` warning — the builders and editor log skipped controls, failed lookups, and empty resolutions with the names involved.
