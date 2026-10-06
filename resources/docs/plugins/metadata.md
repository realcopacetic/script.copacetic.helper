# Metadata Helpers

Two plugin paths return a cleaned-up copy of the focused item's details on a single
list item:

- `metadata` — reads the focused item's infolabels, tidies them, and can add details
  from TMDb.
- `tmdb_details` — fetches the item's details and artwork from TMDb only.

Both can also cut a long plot to fit a set number of lines.

---

## `metadata`

```xml
<control type="list" id="9100"><!-- hidden helper container; id is an example -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=metadata&amp;target=50&amp;focus_guard=$INFO[Container(50).CurrentItem]&amp;type=$INFO[Container(50).ListItem.DBType]&amp;id=$INFO[Container(50).ListItem.DBID]&amp;random_pick=true</content>
</control>
```

Then read it with `Container(9100).ListItem.Genre`, `Container(9100).ListItem.Studio`
and so on.

### Parameters

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `target` | container id, or `item` | — | Container whose focused item is read. Omit to use `Container` (the current container); `item` reads the window's own item (an info dialog's). |
| `type` | `movie`, `tvshow`, `season`, `episode`, `set`, … | — | The item's `DBType`. Used for TMDb lookups and for sets (see Studio below). |
| `id` | number | — | The item's `DBID`. Used for TMDb lookups, for album artists and set studios (see below), and to keep the `random_pick` choice. |
| `random_pick` | `true`, `false` | `false` | Return one director and one genre picked at random, instead of all of them. The same item gets the same pick until Kodi restarts. |
| `genre_aliases` | `text:name,text:name,…` | — | With `random_pick=true`: if the picked genre contains `text`, it becomes `name`. URL-encode spaces (`Hip-Hop:Hip%20Hop`). |
| `enrich_with_tmdb` | `true`, `false` | `false` | Add details from TMDb. TMDb values replace the library values, except the trailer. See [TMDb lookups](#tmdb-lookups). |
| `tmdb_art` | `true`, `false` | `false` | With `enrich_with_tmdb`: fetch TMDb's image lists too, so the artwork helper's `get_extra_multiart` can read them from the cache. The returned item still carries no TMDb artwork. |
| `tmdb_id`, `tvshowid`, `season`, `language` | | | TMDb lookup inputs. See [TMDb lookups](#tmdb-lookups). |
| `truncate_*` | | | See [Cutting the plot to fit](#cutting-the-plot-to-fit). |
| `focus_guard`, `focus_ids`, `identity_labels`, `identity_container` | | | Focus guard. See [Plugin Helpers](plugin_helpers.md#3-guarding-against-fast-scrolls-and-container-moves). |

### What you get back

| Infolabel | Value |
|---|---|
| `ListItem.Label`, `ListItem.Label2` | The focused item's `Label`. |
| `ListItem.Property(dbid)` | The `id` it was read for. With `Label`, it tells a skin whose metadata the container holds while the next item's is still loading. |
| `ListItem.Director` | All directors, or one at random with `random_pick=true`, whole, as the library names them. |
| `ListItem.Genre` | All genres, or one at random with `random_pick=true`, cleaned for display (below). |
| `ListItem.Property(genre_query)` | With `random_pick=true`: the same pick, whole, as the library names it (`Action & Adventure`, `R&B`). Pass this, not `ListItem.Genre`, to [`genre_credits`](library.md). |
| `ListItem.Studio` | The first studio, as the library names it (`Disney+`). Kodi sets have no studio: with `type=set` it is read from `ListItem(-1).Studio` of the container, and with `target=item` (a set's own info dialog) it is the first studio of the set's earliest movie. |
| `ListItem.Writer` | The first writer. |
| `ListItem.Plot`, `ListItem.PlotOutline` | As on the focused item. |
| `ListItem.Trailer` | The library trailer. With TMDb, the TMDb trailer is used only when the library has none. |
| `ListItem.Property(truncated_label)` | The cut-down text, when `truncate_width` is passed. |
| `ListItem.Property(albumartist_id)`, `ListItem.Property(albumartist)` | With `type=album` or `type=song` and `id`: the first album artist's music library id and name, for `musicdb://albums/?artistid=` paths and [`artist_credits`](library.md#actor_credits-director_credits-writer_credits-genre_credits-studio_credits-artist_credits). Empty for other types. |

The random pick is fixed per item (`type`, `id` and label) for the Kodi session, so a
refire, for example after closing an info dialog, gives the same director and genre.
The helper keeps a random seed for the session in the Home window property
`session_salt`. Don't set or clear it from the skin.

With `random_pick=true`, a compound genre such as `Action & Adventure` is split on
`&` and one part is kept for `ListItem.Genre`; `genre_aliases` and full stops (which
become spaces) apply there too. `Property(genre_query)` keeps the whole pick.

With `enrich_with_tmdb=true`, the TMDb fields listed under
[`tmdb_details`](#tmdb_details) are added too (artwork is not).

The guard is checked before reading, after the TMDb lookup and before the item is
returned.

---

## `tmdb_details`

Returns the item's details from TMDb. It needs a TMDb token in the add-on settings.

```xml
<control type="list" id="9150"><!-- hidden helper container; id is an example -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=tmdb_details&amp;target=50&amp;focus_guard=$INFO[Container(50).CurrentItem]&amp;multiart=true</content>
</control>
```

### Parameters

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `target` | container id, or `item` | — | Container whose focused item is looked up; `item` is the window's own item. |
| `multiart` | `true`, `false` | `false` | Also fetch TMDb's image lists (see below). |
| `type`, `id`, `tmdb_id`, `tvshowid`, `season`, `language` | | | See [TMDb lookups](#tmdb-lookups). |
| `truncate_*` | | | See [Cutting the plot to fit](#cutting-the-plot-to-fit). |
| `focus_guard`, `focus_ids`, `identity_labels`, `identity_container` | | | Focus guard. |

### What you get back

| Infolabel | Movies | TV shows (and episodes) | Seasons |
|---|---|---|---|
| `ListItem.Title` | title | name | — |
| `ListItem.OriginalTitle` | original title | original name | — |
| `ListItem.Plot` | overview | overview | season overview |
| `ListItem.TagLine` | tagline | tagline | — |
| `ListItem.Year` | release year | first air year | — |
| `ListItem.Duration` | runtime | — | — |
| `ListItem.Writer` | — | creators | — |
| `ListItem.Trailer` | best YouTube trailer, as a `plugin://plugin.video.youtube/…` path | same | — |
| `ListItem.Property(tmdb_budget)` | budget | — | — |
| `ListItem.Property(tmdb_revenue)` | revenue | — | — |
| `ListItem.Property(tmdb_next_air_date)` | — | next episode air date | — |
| `ListItem.Art(poster)`, `ListItem.Art(fanart)` | main poster and backdrop | same | — |

`ListItem.Label` is empty; use `ListItem.Title`.

With `multiart=true`, TMDb's image lists are added as numbered art keys:

| Art keys | Source | Most |
|---|---|---|
| `poster1…` | posters in your language | 10 |
| `keyart`, `keyart1…` | posters with no language | 10 |
| `fanart1…` | backdrops with no language | 10 |
| `landscape`, `landscape1…` | backdrops in your language | 10 |
| `clearlogo`, `clearlogo1…` | logos in your language, else logos with no language | 5 |

Results are cached for 7 days, an id TMDb doesn't know for a day, and a failed
request (offline, timeout, server error) for 5 minutes; until the retry, the last
details fetched are still returned. *Clear addon cache* empties it. A `multiart=true` call, or `metadata` with `tmdb_art=true`, also
makes the art available to the artwork helper's `get_extra_multiart` (see
[Artwork](artwork.md#multiart)).

---

## TMDb lookups

Both paths find the TMDb id like this. Each value comes from the parameter when
passed, else from the focused item.

| Param | Falls back to | Notes |
|---|---|---|
| `type` | `ListItem.DBType` | |
| `id` | `ListItem.DBID` | |
| `tmdb_id` | `ListItem.UniqueID(tmdb)` | Used directly when set. Otherwise looked up from the library with `id`. |
| `tvshowid` | `ListItem.TvShowDBID`, then `ListItem.Property(tvshowid)` | For seasons and episodes: the show to look up. |
| `season` | `ListItem.Season` | For seasons. A season with no number (the "All seasons" item) is skipped. |
| `language` | add-on setting `tmdb_language`, else `en-US` | TMDb language, for example `de-DE`. |

Episodes return their show's details, as TMDb has no episode lookup here.

**Add-on settings needed:** `tmdb_access` must be on and `tmdb_access_token` must hold
a TMDb token. Without them, nothing is fetched and `tmdb_details` returns no item.

---

## Cutting the plot to fit

Both paths can return a version of a text cut to fit a number of lines in a given
width and font. It is cut at the end of the last full sentence that fits. If no
sentence fits, the last word that fits gets an ellipsis. The text is returned in
`ListItem.Property(truncated_label)`, with a `[CR]` at the end of each line, so Kodi
breaks the lines exactly where the helper measured them.

The width is measured the way Kodi draws the font at the current screen resolution,
with sizes in 1920×1080 skin pixels. Results are cached.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `truncate_width` | whole number (skin pixels) | `0` | Width of the label. `0` turns cutting off. |
| `truncate_font` | font file path (`special://`, `resource://` or absolute) | — | Font of the label. Required with `truncate_width`. |
| `truncate_size` | whole number | `0` | Font size as in your `Font.xml`. Required with `truncate_width`. |
| `truncate_lines` | whole number | `3` | Most lines to keep. |
| `truncate_label` | any text | — | Text to cut. |
| `truncate_label_id` | control id | — | Read the text from this label control instead (`Control.GetLabel`). |

The text used is the first that is not empty: `truncate_label`, the label of
`truncate_label_id`, the returned plot, then `ListItem.Plot` of the focused item.

```xml
<content>plugin://script.copacetic.helper/?info=metadata&amp;target=50&amp;truncate_width=720&amp;truncate_lines=3&amp;truncate_font=special://skin/fonts/MyFont-Regular.ttf&amp;truncate_size=30</content>
```
