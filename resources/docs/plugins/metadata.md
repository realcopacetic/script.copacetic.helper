# Metadata Helpers

The `metadata` plugin path returns a cleaned-up copy of the focused item's details on a
single list item. It reads the item's infolabels, tidies them, can add details from
TMDB, and can cut a long plot to fit a set number of lines.

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

**Served.** As a [served list](../service/serve.md) (Copacetic's `9000` with probe
`6900`, `9100` with `6901`, or an info dialog's own), the probe holds these params without
the `plugin://…?` prefix. TMDb is then read from the cache only and fetched on a thread
of its own; the list is served again once the answer lands, if the item is still the
one served.

### Parameters

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `target` | container id, or `item` | — | Container whose focused item is read. Omit to use `Container` (the current container); `item` reads the window's own item (an info dialog's). |
| `type` | `movie`, `tvshow`, `season`, `episode`, `set`, … | — | The item's `DBType`. Used for TMDB lookups and for sets (see Studio below). |
| `id` | number | — | The item's `DBID`. Used for TMDB lookups, for album artists and set studios and years (see below), and to keep the `random_pick` choice. |
| `random_pick` | `true`, `false`, `genre`, `director` | `false` | Return one director and one genre picked at random, instead of all of them. `genre` picks the genre alone and keeps every director (for a rail that follows them all, as [`director_credits`](library.md#actor_credits-director_credits-writer_credits-genre_credits-studio_credits-artist_credits) can); `director` the director alone. The same item gets the same pick until Kodi restarts, and `genre` picks the same genre as `true`. |
| `genre_aliases` | `text:name,text:name,…` | — | With `random_pick=true` or `genre`: if the picked genre contains `text`, it becomes `name`. URL-encode spaces (`Hip-Hop:Hip%20Hop`). |
| `genre_chips` | number | — | Also return the genres as chips in `genre_first`, `genre_second` and `genre_more` (below): two chips while the two names, and the second's ` +N` when more are left, hold this many characters together, else one. For a monospaced chip font, the characters that fit the space two chips get. An episode with no genre (a served one: Kodi's library episodes carry their show's) takes its show's. |
| `album_format` | `true`, `false` | `false` | With `type=album` and `id`: also return the album's most common audio format across its songs, in `format_codec` and `format_samplerate` or `format_bitrate` (below). |
| `most_played` | `true`, `false` | `false` | With `type=album` or `type=artist` and `id`: also return the song of the album, or of the artist, with the most plays, in `most_played` (below). From Kodi's own play counts, in one library call that returns two songs however many the artist has. |
| `compilation_artists` | `true`, `false` | `false` | With `type=album` and `id`: for a compilation, also return its main track artists in `compilation_artists` (below), from your library alone. |
| `wikidata` | `true`, `false` | `false` | With the helper's `wikidata` setting on: also return Wikidata details of a movie or TV show (found by its TMDB id, else its IMDb id), an artist (its MusicBrainz id) or an album (its MusicBrainz release group), in the `wikidata_*` properties (below). An item with none of those ids is never looked up. Only answers already saved are returned; in a served list a missing or stale one is asked for on a thread of its own, and the list is served again when it lands. |
| `place_chips` | number | — | With `wikidata=true` on an artist: the characters its date chip and its `wikidata_place` chip hold together; a longer place is cut to the rest and ends with `…`. The date is a person's or character's Born (else Formed), any other type's Formed (else Born), as MusicBrainz's type (`ListItem.Property(artist_type)`) has it. As `genre_chips`, for a monospaced chip font. |
| `based_on_font`, `based_on_width` | a font name from your `Font.xml`, number (skin pixels) | — | With `wikidata=true` on a movie or TV show: `wikidata_based_on` cut to one line of that width, at a word, ending `...`, measured as Kodi draws the font (as `truncate_font`). Without both, or with a name not in `Font.xml`, it is returned whole. |
| `story_width` | number (skin pixels) | — | With `wikidata=true` and `story_chip_font` on a movie or TV show: return its story band, chips in columns (Set in, About, Universe, Part of; see `wikidata_set_in_1` below), fitted to this width as Kodi sizes the chips. While they overflow, the universe goes first, then the About chips from the last, then the second place, then the period. With no width (or `0`) there is no band. |
| `story_gap`, `story_chip_gap` | number (skin pixels) | `0` | With `story_width`: the gap between two columns, and between two chips of a column. |
| `story_caption_font`, `story_caption_set_in`, `story_caption_about`, `story_caption_universe`, `story_caption_part_of` | a font name from your `Font.xml`, text | — | With `story_width`: the columns' captions as you draw them over the chips, so a column whose caption is wider than its chips is fitted at the caption's width. Without the font, columns are as wide as their chips. |
| `story_chip_font`, `story_chip_padding`, `story_chip_max`, `story_chip_upper` | font name, number, number, `true` | —, `0`, none, `false` | With `story_width`: the chips' font (required), their text offset on each side, their widest, and whether the font draws capitals (a `Font.xml` style of `uppercase`). |
| `heading_font`, `heading_width` | a font name from your `Font.xml`, number (skin pixels) | — | Return in `heading_lines` how many lines, 1 or 2, the item's tagline (else its title) takes in a textbox of that font and width, as Kodi wraps it. For a skin that sizes what sits under a heading of up to two lines. |
| `set_suffix` | text | — | Return a movie's collection (`ListItem.Set`) without that last word in `set_name`: `Collection` turns `Planet of the Apes (Reboot) Collection` into `Planet of the Apes (Reboot)`. Case aside; a name that is the word alone, or doesn't end with it, is returned whole. |
| `years_present` | text | — | With `type=artist`: return its years active in `artist_years` (below), this word ending a span with no end yet. |
| `tagline_quotes` | `single` | — | Also return the tagline ready to sit inside your own double quote marks, in `ListItem.Property(clean_tagline)`: its double quotes become curly single ones (`"criminal"` and `“criminal”` both read `‘criminal’`), and a pair that wraps the whole tagline (its only double quotes) is dropped. Off by default, and `ListItem.TagLine` is never changed. |
| `enrich_with_tmdb` | `true`, `false` | `false` | Add details from TMDB. TMDB values replace the library values, except the plot, title, tagline and trailer, which TMDB only fills when the item has none (a season takes TMDB's plot where it has one: Kodi gives seasons their show's). See [TMDB lookups](#tmdb-lookups). |
| `prefer_tmdb_trailer` | `true`, `false` | `false` | With `enrich_with_tmdb`: TMDB's trailer replaces a library trailer that is a link (`plugin://`, `http://`, `https://`), such as the one Kodi's TMDB scraper saves. A library trailer that is a file always stays. |
| `random_trailer` | `true`, `false` | `false` | With `enrich_with_tmdb`: when TMDB's trailer is used, pick one at random from its best-ranked trailers instead of the newest. The same item gets the same pick until Kodi restarts. |
| `tmdb_trailer_only` | `true`, `false` | `false` | With `enrich_with_tmdb`: take only the trailer from TMDB, by the rules above; every other field stays the library's. For a view that wants TMDB's trailer without TMDB's plot, title or details. |
| `tmdb_art` | `true`, `false` | `false` | With `enrich_with_tmdb`: fetch TMDB's image lists too, so the artwork helper's `get_extra_multiart` can read them from the cache. The returned item still carries no TMDB artwork. |
| `show_creators` | `true`, `false` | `false` | With `type=season`: `ListItem.Writer` is its show's TMDB creators, as a TV show's is with `enrich_with_tmdb` (Kodi keeps no writer for a show or season). Read from the show's cached TMDB entry, so a season opened from its show asks TMDB nothing; else fetched as `enrich_with_tmdb` is. It changes nothing else of the season. |
| `tmdb_id`, `tvshowid`, `season`, `language` | | | TMDB lookup inputs. See [TMDB lookups](#tmdb-lookups). |
| `truncate_*` | | | See [Cutting the plot to fit](#cutting-the-plot-to-fit). |
| `focus_guard`, `focus_ids`, `identity_labels`, `identity_container` | | | Focus guard. See [Plugin Helpers](plugin_helpers.md#3-guarding-against-fast-scrolls-and-container-moves). |

### What you get back

| Infolabel | Value |
|---|---|
| `ListItem.Label`, `ListItem.Label2` | The focused item's `Label`. |
| `ListItem.Title` | The focused item's `Title`, which a list's label may not be (a search node, Files with library titles off): use it where a library title is compared, such as the `exclude_value` of [`genre_credits`](library.md). With TMDB, the TMDB title is used only when the item has none. |
| `ListItem.TVShowTitle` | The focused item's show title (a show, season or episode), to leave its show out of a TV rail, such as `genre_credits` with `type=tvshow`. |
| `ListItem.Property(dbid)` | The `id` it was read for. With `Label`, it tells a skin whose metadata the container holds while the next item's is still loading. |
| `ListItem.Director` | All directors, or one at random with `random_pick=true` or `director`, whole, as the library names them. |
| `ListItem.Genre` | All genres, or one at random with `random_pick=true` or `genre`, cleaned for display (below). |
| `ListItem.Property(genre_query)` | With `random_pick=true` or `genre`: the same pick, whole, as the library names it (`Action & Adventure`, `R&B`). Pass this, not `ListItem.Genre`, to [`genre_credits`](library.md). |
| `ListItem.Studio` | The first studio, as the library names it (`Disney+`). Kodi sets have no studio: with `type=set` it is the first studio of the set's earliest movie, in a list and in the set's own info dialog alike. |
| `ListItem.Property(set_first_year)`, `ListItem.Property(set_last_year)` | With `type=set` and `id`: the years of the set's earliest and latest movies (those with a year), for a year span; `set_last_year` is empty when both are the same year. Empty for other types. Reading `Container(id).ListItem(0)` and `ListItem(-1)` of a set's movies instead gives the years around the list's cursor, not the span. |
| `ListItem.Writer` | The first writer. |
| `ListItem.Plot`, `ListItem.PlotOutline`, `ListItem.TagLine` | As on the focused item. With TMDB, the TMDB plot and tagline are used only when the library has none; a season takes the TMDB season overview where it has one, as Kodi gives seasons their show's plot. |
| `ListItem.Trailer` | The library trailer. With TMDB, the TMDB trailer is used when the library has none, or with `prefer_tmdb_trailer=true` when the library's is a link. |
| `ListItem.Property(truncated_label)` | The cut-down text, when `truncate_width` is passed. |
| `ListItem.Property(truncated_title)` | The cut-down title, when `truncate_title_width` is passed and the title overflows; empty when it fits. |
| `ListItem.Property(clean_tagline)` | With `tagline_quotes=single`: the tagline (the returned `ListItem.TagLine`) with its double quotes single, for a skin that adds its own: `Putting the "criminal" in "criminal lawyer."` becomes `Putting the ‘criminal’ in ‘criminal lawyer.’`, and `"Winter is coming."` becomes `Winter is coming.`. A straight quote opens at the start or after a space, bracket or dash, and closes anywhere else. Empty when there is no tagline. |
| `ListItem.Property(genre_first)`, `ListItem.Property(genre_second)`, `ListItem.Property(genre_more)` | With `genre_chips`: the first genre; the second, only when the two fit as two chips; and how many genres neither chip names, for a `+N` (empty for none). With `genre_second` empty, put `+N` on the first chip: `$INFO[ListItem.Property(genre_more), +]`. |
| `ListItem.Property(format_codec)`, `ListItem.Property(format_samplerate)`, `ListItem.Property(format_bitrate)` | With `album_format=true` on an album: the most common file extension (`flac`, `mp3`) with, for a lossless format, the sample rate in kHz as `ListItem.SampleRate` gives it (`44.1`), or for a lossy one the bitrate in kbps (`320`). An `.m4a` (ALAC or AAC) counts as lossless above 320 kbps. Empty for other types, or an album with no rates. |
| `ListItem.Property(most_played)`, `ListItem.Property(most_played_artist)` | With `most_played=true` on an album or artist: the title of its song with the most plays, when that is two or more (one play isn't a favourite) and no other song has as many (an album played through twice has no favourite). An artist's songs are those Kodi lists under them: songs they are an artist of, and songs on their albums. On an album, `most_played_artist` is the song's artists when none of them is an album artist (a compilation's song), for `$INFO[ListItem.Property(most_played_artist), • ]`; else empty. Both empty for other types. |
| `ListItem.Property(tagline)` | With `enrich_with_tmdb` on a TV show the library has no tagline for: TMDB's tagline. Kodi Omega keeps no TV show tagline; a skin can read `$INFO[ListItem.TagLine]$INFO[Container(id).ListItem.Property(tagline)]`, which stays right where Kodi has its own. |
| `ListItem.Property(tmdb_pending)` | With `enrich_with_tmdb` in a served list, on a TV show: `true` while its TMDB entry is missing or stale and being asked for, as `wikidata_pending` is for the Wikidata details. When TMDB's answer brings news the list is served again without it, so its tagline, writers (the creators), genres and studio (the network) may change on the frame it goes empty. |
| `ListItem.Property(compilation_artists)` | With `compilation_artists=true` on a compilation (Kodi's compilation flag, or an album by MusicBrainz's Various Artists): its track artists, those on the most tracks first, two named and the rest counted (`Glorilla, Travis Scott +18`). Empty for other albums. |
| `ListItem.Property(wikidata_music_by)` | With `wikidata=true` on a movie: its composers (P86), ` / ` between them. Not returned for a TV show. |
| `ListItem.Property(wikidata_based_on)` | With `wikidata=true` on a movie or TV show: the written work it is based on (P144: a novel or novel series, novella, short story, poem, play, book or book series, biography, comic or manga; never a game, toy, character or film), as the work alone: `Slow Horses, novel by Mick Herron`, `American Prometheus, biography by Kai Bird and Martin J. Sherwin`; its authors with ` and `, none named when Wikidata has none. The first such work only; cut to a line with `based_on_font`. |
| `ListItem.Property(wikidata_set_in_1)` … `_3` | With `story_width`: the story band's Set in column. Where it is set (P840): its first two places, in Wikidata's order; then when (P2408), told by its label: a named period (`World War II`) before a year (`1940`), a year before a decade (`1940s`), a decade before a century (`20th century`, `20. century`, `XX century`), after leaving out any year or decade within 5 years of the item's year (its own time): a 2023 film set in `2023` and the `1940s` shows `1940s`. The band asks Wikidata nothing of its own: its values' labels come with the look-up's other labels. |
| `ListItem.Property(wikidata_about_1)` … `_3` | With `story_width`: what it is about (P921), in Wikidata's order, by label: leaving out a subject that its title holds or that holds its title (word by word, case and punctuation aside: `J. Robert Oppenheimer` on Oppenheimer), and a year, decade or century. |
| `ListItem.Property(wikidata_universe_1)` | With `story_width`: its fictional universe (P1434), else its media franchise (P8345), unless the name, without words such as `universe` or `collection`, holds or is held by its title or a movie's collection (`Despicable Me universe` on Despicable Me 4). |
| `ListItem.Property(wikidata_part_of_1)` | With `story_width` on a movie: its collection (`ListItem.Set`), only when the band would otherwise hold one chip or none. |
| `ListItem.Property(heading_lines)` | With `heading_font` and `heading_width`: `1` or `2`; empty with no tagline or title. |
| `ListItem.Property(set_name)` | With `set_suffix` on an item with a collection: the collection's name without that word. |
| `ListItem.Property(artist_years)` | With `years_present` on an artist: Kodi's years active (`ListItem.Property(artist_yearsactive)`, which only AllMusic fills). Else, for any type but a person or character (MusicBrainz's type: a lifespan isn't years active), its formation (else birth) to its disbanding (else death), or to `years_present`; the year alone from a full date (`1997–2019`, `2003–present`). Empty for a person or character without Kodi's, or with no first year. |
| `ListItem.Property(wikidata_instruments)` | With `wikidata=true` on a person or character (MusicBrainz's type) Kodi lists no instruments for (`ListItem.Property(artist_instrument)` empty): the instruments it plays (P1303), capitalised, two named and the rest counted (`Guitar, Voice +3`). None for a group or an artist of no type. Details saved before this was added have none until they are asked again. |
| `ListItem.Property(wikidata_created_by)` | With `wikidata=true` on a TV show the returned `ListItem.Writer` names no creators for (TMDB has none, or isn't asked): its creators on Wikidata (P170), ` / ` between them. Details saved before this was added have none until they are asked again. |
| `ListItem.Property(wikidata_labels)` | With `wikidata=true` on an artist: its record labels (P264), two named and the rest counted (`Ed Banger Records, Because Music +2`). |
| `ListItem.Property(wikidata_place)` | With `wikidata=true` on an artist: where a group formed (P740), else where a person was born (P19), `Paris`; cut to fit with `place_chips`. |
| `ListItem.Property(wikidata_producer)` | With `wikidata=true` on an album: its producers (P162), ` / ` between them. |
| `ListItem.Property(wikidata_pending)` | With `wikidata=true` in a served list: `true` while the item's details are missing or stale and being asked for. When they land with news the list is served again without it, so the frame it goes empty is the frame the `wikidata_*` values may change: hide what shows them for that frame to mask the change. Empty when the kept details are fresh, and on a plugin call. |
| `ListItem.Property(albumartist_id)`, `ListItem.Property(albumartist)` | With `type=album` or `type=song` and `id`: the first album artist's music library id and name, for `musicdb://albums/?artistid=` paths and [`artist_credits`](library.md#actor_credits-director_credits-writer_credits-genre_credits-studio_credits-artist_credits). Empty for other types. |

Wikidata names a label in English, else in its multilingual label, else in any
language it has. Each `wikidata_*` property is empty when Wikidata has no such value;
the details are kept for 30 days (an item Wikidata lacks, 7).

The random pick is fixed per item (`type`, `id` and label) for the Kodi session, so a
refire, for example after closing an info dialog, gives the same director and genre.
The helper keeps a random seed for the session in the Home window property
`session_salt`. Don't set or clear it from the skin.

With a genre pick, a compound genre such as `Action & Adventure` is split on
` & ` (spaced, so `R&B` stays whole) and one part is kept for `ListItem.Genre`. Music
types (`album`, `artist`, `song`, `musicvideo`) are not split: their genres are single
names (`Drum & Bass`). `genre_aliases` and full stops (which become spaces) apply to
`ListItem.Genre` for every type.
`Property(genre_query)` keeps the whole pick.

With `enrich_with_tmdb=true`, the [TMDB fields](#tmdb-fields) are added too (artwork is not); the item's own title,
plot, tagline and trailer are kept where it has them (the trailer only if it is a file,
with `prefer_tmdb_trailer=true`).

The guard is checked before reading, after the TMDB lookup and before the item is
returned.

### In an info dialog (`target=item`)

Kodi's own **Information** item in a context menu can swap the item an open info
dialog shows, without opening the dialog again. The dialog's `<onload>` does not run,
so the skin never records the new item. `metadata` with `target=item` catches this.
When all of these are true, it returns no item and runs the helper's `info_swap`
action, which reopens the dialog on the new item as if the user had clicked it in a
list (see [`info_swap`](../script/actions.md#info_swap)):

- `Window(home).Property(info_current)` is not empty.
- It is not this item's `<DBType>:<DBID>`.
- `Window(home).Property(info_hop)` is empty.

The helper sets `info_hop` to `forward` first. Skins that don't set `info_current`
never see this.

| What | Set by |
|---|---|
| `Window(home).Property(info_current)` | The skin, in the info dialogs' `<onload>` (see [`info`](../script/actions.md#info)). |
| `Window(home).Property(info_hop)` | The skin before `info` or `info_back`, and the helper here. Cleared by the skin's `<onload>`. |

---

## TMDB lookups

`metadata` finds the TMDB id like this. Each value comes from the parameter when
passed, else from the focused item.

| Param | Falls back to | Notes |
|---|---|---|
| `type` | `ListItem.DBType` | |
| `id` | `ListItem.DBID` | |
| `tmdb_id` | `ListItem.UniqueID(tmdb)` | Used directly when set. Otherwise looked up from the library with `id` (a season's or episode's show with `tvshowid`): one `GetMovieDetails` or `GetTVShowDetails` call, kept once found until Kodi restarts or this Kodi's next library update of the item (a rescrape can change it; another device's, on a shared library, announces nothing here), so the progress bar and later focuses don't ask again. |
| `tvshowid` | `ListItem.TvShowDBID`, then `ListItem.Property(tvshowid)` | For seasons and episodes: the show to look up. |
| `season` | `ListItem.Season` | For seasons. A season with no number (the "All seasons" item) is skipped, `show_creators` too. |
| `language` | add-on setting **TMDB language**, else `en-US` | TMDB language, for example `de-DE`. |

A season with `enrich_with_tmdb` also reads its show's entry (asked on a thread of its
own in a served list when missing or stale), so the show's next airing stays current
for its [progress bar](progressbar.md#how-the-context-values-are-worked-out).

Episodes look up their show, as TMDB has no episode lookup here, and take only what
fits an episode: the show's trailer, artwork and `tmdb_*` properties. The episode's
own title, plot and year are kept.

### TMDB fields

With `enrich_with_tmdb=true`, these come from TMDB:

| Infolabel | Movies | TV shows (and episodes) | Seasons |
|---|---|---|---|
| `ListItem.Title` | title | name | — |
| `ListItem.Plot` | overview | overview | season overview |
| `ListItem.TagLine` | tagline | tagline | — |
| `ListItem.Writer` | — | creators | — (its show's creators with `show_creators`) |
| `ListItem.Property(tmdb_creator_ids)` | — | the creators' TMDB person ids, joined by `,`, for [`creator_credits`](library.md#creator_credits) | — |
| `ListItem.Trailer` | best YouTube trailer, as a `plugin://plugin.video.youtube/…` path: trailers, then teasers, then other video types; official over unofficial; then the newest | same | — |
| `ListItem.Property(tmdb_next_air_date)` | — | next episode air date | — |
| `ListItem.Property(tmdb_next_air_season)`, `ListItem.Property(tmdb_next_air_episode)` | — | next episode's season and episode number | — |
| `ListItem.Property(tmdb_last_air_date)` | — | last aired episode air date | — |
| `ListItem.Property(tmdb_last_air_season)`, `ListItem.Property(tmdb_last_air_episode)` | — | last aired episode's season and episode number | — |
| `ListItem.Property(tmdb_status)` | — | status as TMDB writes it, e.g. `Returning Series`, `Ended`, `Canceled` | — |

With `tmdb_art=true`, TMDB's image lists are cached with these numbered art keys:

| Art keys | Source | Most |
|---|---|---|
| `poster`, `poster1…` | posters in your language | 10 |
| `keyart`, `keyart1…` | posters with no language | 10 |
| `fanart`, `fanart1…` | backdrops with no language | 10 |
| `landscape`, `landscape1…` | backdrops in your language | 10 |
| `clearlogo`, `clearlogo1…` | logos in your language, else logos with no language | 5 |

Backdrops must be exactly 16:9 at 1920×1080 or larger and posters exactly 2:3 at
1000×1500 or larger; others are left out. TMDB's main poster and backdrop follow the
same rule when they are in the lists, and stay first when they aren't (so `poster` or
`fanart` can then lead 10 more).

Results are cached for 7 days, an id TMDB doesn't know for a day, a "too many
requests" answer for as long as TMDB asks, and any other failed request (offline,
timeout, server error, a refused token) for 5 minutes; until the retry, the last
details fetched are still returned. A TV show's entry is also stale once the next
episode's air date it names is past (from the day after), however young it is, so the
episode after is fetched; asked once a day, as TMDB can still name the past airing a
day on, or the request fails. *Clear add-on cache* empties it. The art is then
available to the artwork helper's `get_extra_multiart`
(see [Artwork](artwork.md#multiart)).

**Add-on settings needed:** the user pastes their own TMDB v3 API key or v4 read access
token into **TMDB access token** (setting id `tmdb_access_token`, empty by
default). There is no separate on/off setting: the token is the user's consent.
Without it, nothing is fetched or read from the cache, nothing is logged above debug,
and `metadata` adds nothing from TMDB. **Test TMDB access** checks the token.
**TMDB language** (`tmdb_language`) sets the default `language`.

This product uses the TMDB API but is not endorsed or certified by TMDB.

---

## Cutting the plot to fit

`metadata` can return a version of a text cut to fit a number of lines in a given
width and font. It is cut at the end of the last full sentence that fits. If no
sentence fits, the last word that fits gets an ellipsis. The text is returned in
`ListItem.Property(truncated_label)`, with a `[CR]` at the end of each line, so Kodi
breaks the lines exactly where the helper measured them.

The width is measured the way Kodi draws the font at the current screen resolution,
with sizes in 1920×1080 skin pixels, and lines break where Kodi breaks them: at plain
spaces (a no-break space holds), with a word wider than the label cut after the last
letter that fits. Results are cached by the font's name, so after changing the font in `Font.xml` run
[`clear_cache`](../script/actions.md#clear_cache).

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `truncate_width` | whole number (skin pixels) | `0` | Width of the label. `0` turns cutting off. |
| `truncate_font` | a font name from your `Font.xml`, e.g. `description_l` | — | Font of the label. The helper reads its file and size from the first fontset in `16x9/Font.xml`. Required with `truncate_width`. A name that is not in `Font.xml` logs a warning and the text is returned uncut. |
| `truncate_lines` | whole number | `3` | Most lines to keep. |
| `truncate_label` | any text | — | Text to cut. |
| `truncate_label_id` | control id | — | Read the text from this label control instead (`Control.GetLabel`). It is read when the call starts, before any TMDB wait, so a label that follows the focus still gives this item's text. |
| `truncate_probe` | `true`, `false`, a `DBType` such as `season` | `true` | `false`: every type but `album`, `artist` and `song` ignores `truncate_label_id` (below); a `DBType`: items of that type ignore it. |

The text used is the first that is not empty: `truncate_label`, the label of
`truncate_label_id`, the returned plot, then `ListItem.Plot` of the focused item.
`truncate_probe` skips `truncate_label_id` where that label reads something else:
`season` for a season, whose Kodi plot is its show's, so the returned plot (TMDB's
season overview when there is one) is cut; `false` for a favourite read with `target=`,
whose caption may be its action text, so the returned plot (the library's, else TMDB's)
is cut. Music keeps the label: an album's or artist's caption is its description.
An item with no plot of its own skips the label whenever TMDB returned one, so TMDB's
plot is cut directly. This matters when your label falls back to the last returned
plot, which can be another item's.

```xml
<content>plugin://script.copacetic.helper/?info=metadata&amp;target=50&amp;truncate_width=720&amp;truncate_lines=3&amp;truncate_font=font_plot</content>
```

A title is cut the same way, separately, from these params. It always ends in an
ellipsis, never at a sentence, and `truncated_title` is set only when the title
overflows, so a title that fits stays the skin's own label and doesn't change.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `truncate_title_width` | whole number (skin pixels) | `0` | Width of the title. `0` turns it off. |
| `truncate_title_font` | a font name from your `Font.xml` | — | Font of the title. Required with `truncate_title_width`. |
| `truncate_title_lines` | whole number | `3` | Most lines to keep. |
| `truncate_title_id` | control id | — | The label control to read the title from, when the call starts. Required with `truncate_title_width`. |
