# Verification harness

Dev-only (excluded from `git archive` via `.gitattributes`). Python 3.11.4+, stdlib only. Run from the helper root.

```sh
# Build outside Kodi: 16x9/*.xml, runtime_state.json, resolver_cache.json → OUT (never into the skin)
python tests/build_offline.py ../skin.copacetic2 /tmp/c2-build [--state runtime_state.json] [-v]

# Before a patch: skin HEAD vs working tree (exit 1 = outputs differ, 2 = harness/build failed)
python tests/snapshot_diff.py ../skin.copacetic2 [--base REF] [--head REF] [--helper-base REF] [--state FILE]

# Lint what the migrated (C2) windows load, plus a fresh build (exit 1 on errors)
python tests/skin_lint.py ../skin.copacetic2 [--window MyPics.xml ...] [--all] [--generated /tmp/c2-build] [--exclude 'GLOB' ...]
```

- `build_offline` stubs only the `xbmc*` calls the builders make; a new Kodi call fails loudly — add it to `install_stubs`. Any ERROR log line fails the build.
- `snapshot_diff` has no committed goldens: the base ref's build is the golden. Use `--helper-base main` to check a helper change against the same skin.
- `skin_lint` checks, by default, only the windows that call a C2 shell include (`tpl_window`, `blk_modal_*`, `img_modal_*`, `blk_hud_*` …) and everything they reach; `--window` adds one, `--all` lints every file. It expands includes the way Omega's `CGUIIncludes` does. Names built from `$PARAM` are checked after expansion only. An include whose `condition` is `false` or `!true` after `$PARAM` substitution (e.g. `!$PARAM[item]` in the info dialogs), or a bare `$EXP` whose generated body is `false` (e.g. `layout_showcase_include_search`), is skipped, as Kodi evaluates it at load and skips it. `unknown-param` pools every include a call site reaches, so a call named by `$PARAM` may pass what any of its targets needs. `duplicate-id` is a warning: Kodi's control lookup prefers the visible one of several same-id controls, and ids from include branches with different `condition`s are skipped. `unreferenced-definition` (warning, window mode only) lists generated variables and expressions that no linted window reaches through its values or include conditions; the `_addonbrowser`/`_pictures` families are skipped until those windows migrate.

## In-Kodi dialog checks

Two scripts that run inside Kodi, not from the shell. Bind one to a key with its path, e.g. `<f8>RunScript(special://home/addons/script.copacetic.helper/tests/dialogs_test.py)</f8>`. Each title names what to check.

- `dialogs_test.py`: a Select menu of every dialog, window and notification Python can open: Select detailed and multi-select, context menu, FileBrowser (folder, image thumbs, several files), keyboard, numeric, text viewer, colour picker, video info for a non-library item, this add-on's settings, the shutdown menu, notifications, background progress, the busy spinner and the volume bar. Back closes it.
- `confirm_test.py`: every DialogConfirm variant in turn: stock yes/no, the Settings custom button, known and unknown labels, long text, progress, and a yes/no over a progress dialog. Also a `dialogs_test.py` entry.

Not reachable from Python: MediaSource, DialogSettings dialogs, the disc Play/Eject prompt and the gamepad lock dialog. Open those from Kodi itself.

