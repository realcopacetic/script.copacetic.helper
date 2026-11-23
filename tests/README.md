# Verification harness

Dev-only (excluded from `git archive` via `.gitattributes`). Python 3.11.4+, stdlib only. Run from the helper root.

```sh
# Build outside Kodi: 16x9/*.xml, runtime_state.json, resolver_cache.json → OUT (never into the skin)
python tests/build_offline.py ../skin.copacetic2 /tmp/c2-build [--state runtime_state.json] [-v]

# Before a patch: skin HEAD vs working tree (exit 1 = outputs differ, 2 = harness/build failed)
python tests/snapshot_diff.py ../skin.copacetic2 [--base REF] [--head REF] [--helper-base REF] [--state FILE]

# The builder with no rows: each runtime_state mapping emptied in turn, then all
# (from a fresh build's state, or --state); exit 2 at the first build that fails
python tests/emptied_offline.py ../skin.copacetic2 [--state runtime_state.json]

# Lint what the migrated (C2) windows load, plus a fresh build (exit 1 on errors)
python tests/skin_lint.py ../skin.copacetic2 [--window MyPics.xml ...] [--all] [--generated /tmp/c2-build] [--exclude 'GLOB' ...] [--count] [--reach reach.json]

# Every-setting reachability: a build per config option value, every window expanded in
# each; the skin's includes, variables and expressions no build reaches (about an hour)
python tests/skin_reach.py ../skin.copacetic2 [--json reach.json] [--list]

# Artwork prepare + compose on synthetic posters: label rects, element step, colour, band alpha and ratio, palette PNG transparency, measure version, RGB PNG tRNS resize, timings (needs Pillow; reads the skin's fonts)
python tests/artwork_check.py ../skin.copacetic2

# Web API layer (http, api_cache, ListenBrainz, Deezer, TheIntroDB, LRCLIB, the top_songs/discography blend, music info's popularity words, TMDB) against recorded answers, no network
python tests/api_offline.py

# The artwork serve (plugin/handlers.py artwork()) with Kodi's reads stubbed: the logo
# read from clearlogo_source (headers kept; the URL's under a menu, none if cut), with
# and without a favourite's multiart_target; the icon from icon_source, a cut band
# label the item's own; a background read whole by a variable's name (a Plex URL's
# &X-Plex-Token= kept), standing only where it extends the URL's raw value, under a
# menu only with a value, a family outranking it; multiart_first read from the serve's
# own item, not multiart_target's; url_decode_path leaves a bare URL as
# Kodi keys it; a held serve names its position (the
# jumpbar's re-serve) only for a move that stamped no visit, by the guard's own read;
# served, a settle's cursor and visit the request's, a move's visit the live one, no
# cursor stamp and no held item, every serve naming its identity, no art a blank;
# the TV guide's time left (epg_time_left) from the programme's start and runtime,
# across midnight too, only while the URL's channel is on air and before its end
python tests/artwork_serve_offline.py

# Soundtrack title matching (plugin/soundtracks.py) against real album titles
python tests/soundtracks_offline.py

# Mixes and the endless queue (shared/mix.py, service/player.py) with the library
# faked: a random draw out of Kodi's song id order; a mix from seed songs leaving out
# what it's told, leaning a fair share on its artists' own albums, familiar seeds
# first, kept to a genre or year; daily mixes a genre bucket a card, by songs played,
# kept until midnight, redrawn when similar artists answer otherwise; the cards in
# play order; a card's click plays its bucket, a genre node's mix its genre alone;
# the queue growing below ten songs left, kept to a mix's genres, the same queue
python tests/mix_offline.py

# Genre buckets (shared/genres.py): any case, a whole ListItem.Genre of several genres
# (the first row found), exceptions before the keywords they'd fall to, MusicBrainz
# subgenres by their parent's bucket, unknown genres; every MusicBrainz genre as the
# last snapshot left it (fixtures/genre_buckets.json); the music_genres mapping
python tests/genre_offline.py

# By hand, when MusicBrainz adds genres or EXCEPTIONS/KEYWORDS change (network, an hour
# or more at MusicBrainz's request a second): rewrites SUBGENRES and the fixture; with
# --cache the pages are kept, so a rules change reruns in a second without the network
python tests/genre_snapshot.py [--cache /tmp/mb-genres]

# Gallery tiles' share-out (art/multiart.py): an image shows in one tile only,
# unless a tile has no other image free; a joined family; the first frame
# (multiart_first) leading a family and dropped from later in it; seed_multiart's
# blind seed under a dialog and its seed keys
python tests/multiart_offline.py

# Service build boundary (service/monitor.py): a build that raises is logged, the
# player monitor, slideshow and helper_active still start, helper_speed_dial follows
# the skin naming info=speed_dial, a failure after a seed (builders/runtime.py)
# is retried next start, each skin keeps its own runtime state (Copacetic 2 adopts
# the old shared files only while it has none; a dev reset clears one skin), an
# output another profile wrote is rebuilt, and a deleted one is built alone; a script
# rebuild (script/actions.py) sets helper_reloading and clears it on failure, and the
# editor close and delete_orphans reload only when the build wrote a file (or for a
# host open once the session has closed), else clear it; a skin switch, update or
# reload drops the loaded fonts
python tests/service_offline.py

# Served focus calls (service/serve.py): a ring's kind, region, known lists and mark;
# a probe's params handled and bound with the request's current, none one blank item,
# an empty probe nothing, wait read again; under a dialog the request waits, and a
# newer ring, a window change or a moved cursor drops it; a list covered mid-run owed
# again; a repeat does nothing; a move with no lists the window's last request;
# again() one list of it, the whole arrival mid-serve, only for the arrival that
# asked (TMDb's late answer); a move's item read before its handler; clean_name's
# query, not argv; a favourite with no library item a blank; the guard's superseded
# test first; a bind's paths and new Window; Font.xml read once per version, clamps
# keyed by the font's file and size; SQLite's connection per thread, schema once;
# cache_only per thread; a settle hands on its cursor, a move none; served artwork's
# TMDb extras fetched aside; a late list (9300, 9301) bound none watched without
# holding the next, served once its probe reads params, until its arrival ends or
# WAIT_MAX; a thumb's digest kept by its file's mtime and size; a serve's opened
# images closed however it ends
python tests/serve_offline.py

# Settings editor edges (builders/runtime.py, windows/dynamiceditor.py, controls.py) with
# Kodi stubbed: a new or re-preset parent gets a seed_with_parent mapping's default
# children once (a group widget's tabs); a removed parent's children's children go too;
# a new rail page is flagged for the rail's Right only once its rows are up; a mouse
# click acts as Select, and a click on a sliderex's slider keeps its value
python tests/editor_offline.py

# Add-ons that clash (service/clashes.py) with Kodi's reads stubbed: asked once Home
# settles; Switch off, Keep both, and Not now, Back or a close asking again; answers
# applied at each entry without asking, one switched back on elsewhere kept but one an
# update switched back on switched off again; a feature turned off, a skin left or a
# reset gives the add-on back, at once while a check waits; questions stop when the
# skin is left; two checks at once ask once and only the service writes; a switch Kodi
# refuses isn't recorded; the service queues the check on entering a skin and gives
# add-ons back in any other
python tests/clashes_offline.py

# Skip segments (service/segments.py): chapter starts from Player.Chapters, TheIntroDB's
# times snapped to chapter marks (another cut only on marks), the tick pattern, named
# chapters taking over on entry, and what is published as the playhead moves
python tests/segments_offline.py

# The live channel list's guide (plugin/pvr.py, info=broadcasts) with JSON-RPC
# stubbed: programmes from the one on air, start and end as local clock times
# (Europe/London, GMT and BST), time left to the end by the clock (empty once ended),
# Kodi's label and no image when parental locked, no favourite in the menu, the state
# icon's order, and the handler's calls (none without a channel, no logo call without
# rows); the smart select on a later programme (script/actions.py pvr_smart_select):
# Kodi's strings per case, record or reminder by the client, Switch's builtins or
# Player.Open once the list moved on, on air switching unasked, Back, delete (only
# this or the rule) for an existing timer, the failed-delete dialog, the stamp after
# Kodi's timers catch up, busy cleared on every way out; the channel manager's Back
# (script/actions.py pvr_manager_back): Kodi's own question, Yes OK 4, No Cancel 6,
# Back refocusing what it left, nothing once the manager isn't topmost, busy cleared on
# every way out
python tests/pvr_offline.py

# Lyrics (shared/lrc.py, service/lyrics.py): the LRC parser; the sources in order (a
# .lrc beside the song in any encoding, its tags, LRCLIB off the service thread) and
# the next song's prefetch, one request per song; what is published, lines before
# their state; the follow (3510) and browse (3511) lists put on the line by their own
# selected item, a queued move never added to; the poller hook;
# the info=lyrics plugin path (an item per line) and the lyrics_seek action
python tests/lyrics_offline.py

# The add-on's own directory (plugin/listing.py): the root's Videos and Music folders,
# each group's plain folders on the Home rails' paths (live params read only when a
# group lists, none at the root), and every handler offered or excluded on purpose
python tests/listing_offline.py

# Clean names (shared/utilities.py clean_name) against a port of Kodi's CleanString:
# a film's title and year; an episode's show, 1x07 and title in the scene, Sonarr,
# underscore and title-less forms
python tests/clean_name_offline.py

# Builder passes (builders/modules.py): an item's `also` metadata gives a pass more per
# row, so one settings entry feeds a second window's expressions (append, assign, the
# inverted fallback) and variables, in static and dynamic mappings. Skin mirrors
# (builders/runtime.py): a new mirrored field's config default reaches its skin
# setting when the state is checked, fresh or saved without it; a saved value wins
python tests/builder_offline.py

# Games (service/games.py, service/player.py): the emulator from a game add-on's name
# as Kodi reads it; the system from the skin's emulators mapping (one system, several
# by extension, a shared extension, no row, no mapping); a game's start publishing
# both, its stop clearing them; a library video's start (rails' paths and a set's
# name, no parent ids; Play next given the show id it looked up); the autosave blur
# (needs Pillow): the newest save picture, a file per picture, the last one dropped,
# none while Kodi writes it, once per opening of the game OSD and cleared when it
# closes; the content browser's Game
# add-ons source, its Games window target (a plugin picked under it too, and under each
# other add-on source its own window), a standalone game played from a menu item and
# not offered to a widget. With a skin that has the mapping, its shape and one
# emulator of each kind
python tests/games_offline.py [../skin.copacetic2]
```

- `build_offline` stubs only the `xbmc*` calls the builders make; a new Kodi call fails loudly — add it to `install_stubs`. Any ERROR log line fails the build.
- `snapshot_diff` has no committed goldens: the base ref's build is the golden. Use `--helper-base main` to check a helper change against the same skin.
- `skin_lint` checks, by default, only the windows that call a C2 shell include (`tpl_window`, `blk_modal_*`, `img_modal_*`, `blk_hud_*` …, `tpl_editor*` and `blk_settings_panels` for the editors and the settings windows, `blk_osd_*` for `VideoOSD`, `DialogSeekBar` and `DialogFullScreenInfo`, `blk_musicosd*` for `MusicOSD`, and `blk_game*` for `DialogGameControllers` and `GameOSD`) and everything they reach; `--window` adds one, `--all` lints every file, and so does a skin with no such window (C1). A builder window without a `scope` in `mappings_windows.json` (all of C1's) only names its own family. It expands includes the way Omega's `CGUIIncludes` does. Names built from `$PARAM` are checked after expansion only. An include whose `condition` is false whatever its infos after `$PARAM` substitution (e.g. `!$PARAM[item]` in the info dialogs, `$PARAM[progressbar] + !$PARAM[item]` in `tpl_window`), or a bare `$EXP` whose generated body is `false` (e.g. `layout_showcase_include_search`), is skipped, as Kodi evaluates it at load and skips it. With `--all`, a `$VAR`/`$EXP` in a call's param value is reported only if expanding that call keeps it: one that reaches only includes Kodi always skips is never read (the info dialogs' Cast and Screenshots rails are Kodi's own list 50 and pass a `content` that `atr_widget_content`, `provider` false, drops). `unknown-param` pools every include a call site reaches, so a call named by `$PARAM` may pass what any of its targets needs, counting the default its definition gives that param even where no linted window loads it (e.g. `ani_visible` in the panorama, billboard, reel and showcase views), so a param only that default reads is accepted: a possible missed warning, never a false one. A generated call also passes, unflagged, every param that any `extras/templates/includes` call to a matching name fills from its mapping row (a `{…}` in the value; `{…}` and `$PARAM[…]` in the template's `content` match anything, and a `content` that is only `$PARAM[…]` or `{…}`, such as `$PARAM[base]`, matches nothing): a rail passes its row's whole field set to whichever container it picks (`ctn_strip` gets `size`, `grid_top` …) and Kodi ignores params a definition never names. The pairs are pooled across templates by include name and param name, not traced to the template that wrote the call, so a generated call that passes such a param with a literal value (`grid_top="5"` on a `ctn_strip`) goes unflagged too. A generated param no template fills from a row anywhere for that include name, and any hand-written call, is still checked. `duplicate-id` is a warning: Kodi's control lookup prefers the visible one of several same-id controls, and ids from include branches with different `condition`s are skipped. `unreferenced-definition` (warning, window mode only) lists generated variables and expressions that no linted window reaches through its values or include conditions (a skipped include's too: `ResolveIncludes` registers the condition before it skips the call); the `_addonbrowser`/`_pictures` families are skipped until those windows migrate. A member of a per-window or per-scope family (`*_<window>` or `*_<scope>` for each `mappings_windows.json` window and the `scope` it names) is skipped when another member of the same family is reached: the builder writes one for every window or scope whether it mounts the reader or not (`layout_*_include_home`, read only inside `blk_media_views`, which Home never mounts), and Omega builds a variable only on first use (`CGUIIncludes::CreateSkinVariable`). A family no linted window reads at all is still listed. Hand-written definitions are never checked. `media-window-info` (warning; window mode only, apart from `Timers.xml`) flags the label-form container infos with no id, `Container()` or `Container(0)` (`NumItems`, `CurrentItem`, `NumPages`, `CurrentPage`, `NumAllItems`, `NumNonFolderItems`, and `Position`, `Row`, `Column` without `(n)`) wherever a non-media window (Home, search, the dialogs) reaches them, and in the timer elements Kodi reads in `Timers.xml` (not `<description>`, nor a later timer that reuses a name, which Kodi drops; `--all` checks that file this way only): Omega reads them through `GetMediaWindow`, which takes the context window, the topmost modal dialog or the active window only if it is a media window, so they are empty on Home and search and in dialogs over them, and `Integer.*` sees 0 (coding-notes law *Bare `Container.NumItems`/`CurrentItem` read the media window only*). Give the container id, or use a bool form (`Container.HasNext`, `ListItemNoWrap(1).Label`). `empty-container-id` (warning, window mode only) flags `Container()` with empty brackets in what a non-media window reaches, almost always an include call that left out its `id` param (`tpl_art_unfocused` has no default): Omega's `GetActiveContainer` then takes the focused control, not the list. The walk stops flagging below a value that is false whatever its infos (`[false] + a`, `[false] | [false]`; `yes`/`no` are `true`/`false`; `!` binds tightest, then `+`, then `|`), and below a generated media-window family definition (`*_<window>` for each `mappings_windows.json` window with `mode` `media`: today `*_videos`, `*_music`, `*_addonbrowser`, `*_favourites`, `*_pictures`, `*_programs`, `*_playlist`) referenced from generated output, which the `_active` dispatchers gate by window; hand-written definitions with those names stay live. `timer-unresolved` (error) flags what stays literal in `Timers.xml` (Omega loads it straight into `CXBMCTinyXML2` in `CSkinTimerManager::LoadTimers`, never through `CGUIIncludes`): `<include>` and `<constant>` elements, `$EXP[…]` and `$PARAM[…]` anywhere, and `$VAR[…]`/`$ESCVAR[…]` in `<start>`, `<reset>`, `<stop>` and an action's `condition`, which `Register` reads with only `$LOCALIZE` replaced. `$INFO`/`$VAR` in `<onstart>`/`<onstop>` text are fine (resolved when the action runs; an undefined `$VAR` there is `undefined-variable`, in both modes); `<description>` is never read. Route a condition that needs them through a probe control (`Control.IsVisible(id)`). `escaped-expression` (error) flags `$ESCEXP[…]`: Omega replaces only `$EXP[` (`CGUIIncludes::ResolveExpressions`) and knows `$ESCINFO[`/`$ESCVAR[` but no `$ESCEXP[`, so it shows literally. `undefined-constant` (warning, window mode only) flags an `<animation>` or `<effect>` `time`/`delay` that is no number once `CGUIIncludes::ResolveConstant` has swapped in the `<constant>`s: `QueryFloatAttribute` fails and Kodi keeps the default (`transition_0x` before it was defined). `texture-clear` (error) names every `media` PNG or APNG (any frame) that stores a colour other than white under its fully transparent pixels: Kodi samples textures with `GL_LINEAR`, so that colour bleeds into the visible edge as a dark rim. Fix with `magick f.png -background white -alpha background PNG32:f.png`, then `oxipng -o 4 --strip safe f.png`. `duplicate-string` (error) flags a `msgctxt "#id"` defined twice in a `language/*/strings.po`: Kodi keeps the first and ignores the later one, so its readers show the other text (a rebase once left the music OSD's buttons showing the rating flags' names). `--count` prints a line per linted window sizing what `CGUIWindow::Prepare` builds: elements (the skipped includes left in the tree, as `ResolveIncludes` leaves them, counting as skipped every condition that is false once `$EXP` is flattened, whatever its infos (`true + !true`, `false + a`), and each control's `<default type>` tags added, as `SetDefaults` does) and controls, and how many distinct include conditions it records that are not constant once `$EXP` is flattened (any of them changing value reloads the window). The lint takes runtime include conditions as true, so a window with type branches (the info dialogs) counts the union of its branches, conditions included, where Kodi records only those on the branches it loads.
- `skin_lint`'s leftover rules (warnings, window mode only): `unread-param`, a param an include declares that its definition never reads as `$PARAM`; `constant-param`, a param with one literal value at every call that can reach its include (the skin's `16x9` calls and the include templates', a `$PARAM` or `{…}` in a name matching any include, and a value holding one counting as varying): either no call passes it (inline the default) or every call passes the same value; `empty-control`, a `<control>` with no children and no attribute but `type`, apart from the includes in `EMPTY_CONTROLS`, each with its reason (dispatch stubs, `videowindow`s that fill their parent); `window-property`, a window property the skin (its XML, the generated XML, windows expanded, the builder templates) or the helper (its Python and `addon.xml`) writes and nothing reads, or reads and nothing writes. Kodi keys window properties in any case (`CGUIWindow::m_mapProperties`, `icompare`), and the rule matches names only, ignoring which window holds them (a `home` write satisfies a read of the same name on another window); a built part of a name (`$PARAM`, `$INFO`, `{…}`, an f-string's field) matches anything, Python names spelled by a variable count when its function or module assigns the variable a string, and any other Python string can stand for a name passed in a variable; `PROPERTIES` lists names written or read where none of this sees (Kodi's or another add-on's own, a name the skin hands a script action), each with where. `unreached-definition` (warning, with `--reach FILE` from `skin_reach.py --json` on the same skin commit): a skin include, variable or expression no window reaches under any setting; the same file also stops `unreferenced-definition` reporting a generated name another setting's build reads. A finding `ACCEPTED` lists (by rule, file and the start of its message, each with why it stands: exclusive twin ids, a `$PARAM` dispatch's pooled params, a media-window info read only where it can't be empty, a generated family another setting reads) is counted at the end, not shown; `media-window-info` names the expression a hit sits in and every window that reaches it, and its entries hold the whole message, so a new window reaching it shows again. The generated families are those `skin_reach` found read only under another setting, each entry naming the setting, so a plain run lists only what `--reach` would; a member of an accepted family that no setting reads hides too in a plain run; with `--reach` these entries don't apply (the union decides which generated names another setting reads), so such a member shows. A variable counts as read where the skin names it to the helper in a plugin URL (`background_var=NAME`, any `…_var=`: the helper reads `$VAR[NAME]`, `plugin/opts.py`), and where a `Timers.xml` `<onstart>`/`<onstop>` names it, in `unreferenced-definition`, `unreached-definition` and `skin_reach` alike.
- `skin_reach` starts from a fresh build's runtime state, adds a row for each item of a dynamic mapping that has none (a widget preset, a menu item, a group's tabs, so every item's own config fields vary), then makes one state per config option value that some row keeps after the config's `rules` and that changes a row, setting it on every row that keeps it. After every single option, a field with `dependent_fields` varies once per value of each field it depends on, if that gives a state no single option did (on skin `5a4b23a` no pair reached a skin name the singles hadn't, but the generated `nowplaying_live_false_widgets_3206` is read only under a widget's `layout=reel` with `transition=zoom`). Options that resolve every row alike, and builds that come out byte-identical, run once. Each build is expanded as `skin_lint` expands a window, for every window, and so are the settings editor's control templates (the helper resolves their `$VAR`s with `infolabel`); a name only an unmigrated window reaches is marked as such, and a name a pair reaches first is one no single option reaches. `--json` saves the union (`c2`, `all`, and the generated names any build `emitted`), which `skin_lint --reach` reads; `--list` prints the variants without building.

## In-Kodi dialog checks

Two scripts that run inside Kodi, not from the shell. Bind one to a key with its path, e.g. `<f8>RunScript(special://home/addons/script.copacetic.helper/tests/dialogs_test.py)</f8>`. Each title names what to check.

- `dialogs_test.py`: a Select menu of every dialog, window and notification Python can open: Select detailed and multi-select, context menu, FileBrowser (folder, image thumbs, several files), keyboard, numeric, text viewer, colour picker, video info for a non-library item, this add-on's settings, the shutdown menu, notifications, background progress, the busy spinner and the volume bar. Back closes it.
- `confirm_test.py`: every DialogConfirm variant in turn: stock yes/no, the Settings custom button, known and unknown labels, long text, progress, and a yes/no over a progress dialog. Also a `dialogs_test.py` entry.

Not reachable from Python: MediaSource, DialogSettings dialogs, the disc Play/Eject prompt and the gamepad lock dialog. Open those from Kodi itself.

