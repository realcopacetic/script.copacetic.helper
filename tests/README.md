# Verification harness

Dev-only (excluded from `git archive` via `.gitattributes`). Python 3.11.4+, stdlib only. Run from the helper root.

```sh
# Build outside Kodi: 16x9/*.xml, runtime_state.json, resolver_cache.json → OUT (never into the skin)
python tests/build_offline.py ../skin.copacetic2 /tmp/c2-build [--state runtime_state.json] [-v]

# Before a patch: skin HEAD vs working tree (exit 1 = outputs differ, 2 = harness/build failed)
python tests/snapshot_diff.py ../skin.copacetic2 [--base REF] [--head REF] [--helper-base REF] [--state FILE]

# Lint what the migrated (C2) windows load, plus a fresh build (exit 1 on errors)
python tests/skin_lint.py ../skin.copacetic2 [--window MyPics.xml ...] [--all] [--generated /tmp/c2-build] [--exclude 'GLOB' ...]

# Artwork prepare + compose on synthetic posters: label rects, element step, colour, band alpha and ratio, timings (needs Pillow; reads the skin's fonts)
python tests/artwork_check.py ../skin.copacetic2

# Web API layer (http, api_cache, ListenBrainz, top_songs, TMDb) against recorded answers, no network
python tests/api_offline.py

# Soundtrack title matching (plugin/soundtracks.py) against real album titles
python tests/soundtracks_offline.py
```

- `build_offline` stubs only the `xbmc*` calls the builders make; a new Kodi call fails loudly — add it to `install_stubs`. Any ERROR log line fails the build.
- `snapshot_diff` has no committed goldens: the base ref's build is the golden. Use `--helper-base main` to check a helper change against the same skin.
- `skin_lint` checks, by default, only the windows that call a C2 shell include (`tpl_window`, `blk_modal_*`, `img_modal_*`, `blk_hud_*` …) and everything they reach; `--window` adds one, `--all` lints every file. It expands includes the way Omega's `CGUIIncludes` does. Names built from `$PARAM` are checked after expansion only. An include whose `condition` is `false` or `!true` after `$PARAM` substitution (e.g. `!$PARAM[item]` in the info dialogs), or a bare `$EXP` whose generated body is `false` (e.g. `layout_showcase_include_search`), is skipped, as Kodi evaluates it at load and skips it. `unknown-param` pools every include a call site reaches, so a call named by `$PARAM` may pass what any of its targets needs, counting the default its definition gives that param even where no linted window loads it (e.g. `ani_visible` in the panorama, billboard, reel and showcase views), so a param only that default reads is accepted: a possible missed warning, never a false one. `duplicate-id` is a warning: Kodi's control lookup prefers the visible one of several same-id controls, and ids from include branches with different `condition`s are skipped. `unreferenced-definition` (warning, window mode only) lists generated variables and expressions that no linted window reaches through its values or include conditions; the `_addonbrowser`/`_pictures` families are skipped until those windows migrate. `media-window-info` (warning; window mode only, apart from `Timers.xml`) flags the label-form container infos with no id, `Container()` or `Container(0)` (`NumItems`, `CurrentItem`, `NumPages`, `CurrentPage`, `NumAllItems`, `NumNonFolderItems`, and `Position`, `Row`, `Column` without `(n)`) wherever a non-media window (Home, search, the dialogs) reaches them, and in the timer elements Kodi reads in `Timers.xml` (not `<description>`, nor a later timer that reuses a name, which Kodi drops; `--all` checks that file this way only): Omega reads them through `GetMediaWindow`, which takes the context window, the topmost modal dialog or the active window only if it is a media window, so they are empty on Home and search and in dialogs over them, and `Integer.*` sees 0 (coding-notes law *Bare `Container.NumItems`/`CurrentItem` read the media window only*). Give the container id, or use a bool form (`Container.HasNext`, `ListItemNoWrap(1).Label`). The walk stops flagging below a value that starts `[false] +` with no `|` outside brackets (`+` binds tighter than `|`), and below a generated media-window family definition (`*_<window>` for each `mappings_windows.json` window with `mode` `media`: today `*_videos`, `*_music`, `*_addonbrowser`, `*_favourites`, `*_pictures`, `*_programs`, `*_playlist`) referenced from generated output, which the `_active` dispatchers gate by window; hand-written definitions with those names stay live. `timer-unresolved` (error) flags what stays literal in `Timers.xml` (Omega loads it straight into `CXBMCTinyXML2` in `CSkinTimerManager::LoadTimers`, never through `CGUIIncludes`): `<include>` and `<constant>` elements, `$EXP[…]` and `$PARAM[…]` anywhere, and `$VAR[…]`/`$ESCVAR[…]` in `<start>`, `<reset>`, `<stop>` and an action's `condition`, which `Register` reads with only `$LOCALIZE` replaced. `$INFO`/`$VAR` in `<onstart>`/`<onstop>` text are fine (resolved when the action runs; an undefined `$VAR` there is `undefined-variable`, in both modes); `<description>` is never read. Route a condition that needs them through a probe control (`Control.IsVisible(id)`). `escaped-expression` (error) flags `$ESCEXP[…]`: Omega replaces only `$EXP[` (`CGUIIncludes::ResolveExpressions`) and knows `$ESCINFO[`/`$ESCVAR[` but no `$ESCEXP[`, so it shows literally. `texture-clear` (error) names every `media` PNG or APNG (any frame) that stores a colour other than white under its fully transparent pixels: Kodi samples textures with `GL_LINEAR`, so that colour bleeds into the visible edge as a dark rim. Fix with `magick f.png -background white -alpha background PNG32:f.png`, then `oxipng -o 4 --strip safe f.png`.

## In-Kodi dialog checks

Two scripts that run inside Kodi, not from the shell. Bind one to a key with its path, e.g. `<f8>RunScript(special://home/addons/script.copacetic.helper/tests/dialogs_test.py)</f8>`. Each title names what to check.

- `dialogs_test.py`: a Select menu of every dialog, window and notification Python can open: Select detailed and multi-select, context menu, FileBrowser (folder, image thumbs, several files), keyboard, numeric, text viewer, colour picker, video info for a non-library item, this add-on's settings, the shutdown menu, notifications, background progress, the busy spinner and the volume bar. Back closes it.
- `confirm_test.py`: every DialogConfirm variant in turn: stock yes/no, the Settings custom button, known and unknown labels, long text, progress, and a yes/no over a progress dialog. Also a `dialogs_test.py` entry.

Not reachable from Python: MediaSource, DialogSettings dialogs, the disc Play/Eject prompt and the gamepad lock dialog. Open those from Kodi itself.

