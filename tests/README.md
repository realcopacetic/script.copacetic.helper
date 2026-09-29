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
- `skin_lint` checks, by default, only the windows that call a C2 shell include (`tpl_window`, `blk_modal_*`, `img_modal_*`, `blk_hud_*` …) and everything they reach; `--window` adds one, `--all` lints every file. It expands includes the way Omega's `CGUIIncludes` does. Names built from `$PARAM` are checked after expansion only. `duplicate-id` is a warning: Kodi's control lookup prefers the visible one of several same-id controls, and ids from include branches with different `condition`s are skipped.
