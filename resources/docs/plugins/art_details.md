# Art Details

Looks up a picture file on [Wikidata](https://www.wikidata.org) as a painting and
returns its standard fields: artist, year, medium, genre, collection, dimensions, what
it depicts and the English Wikipedia summary. It is for folders of paintings named
`Artist - Title (Year)`, the user's own choice of folders, and runs only on demand: for
the item you serve it for, never as a walk through a folder.

Three things must be true before anything is sent:

1. **Look up details on Wikidata** is on in the helper's settings (setting
   `wikidata`, on by default; your skin can test
   `Addon.SettingBool(script.copacetic.helper,wikidata)`).
2. The picture is in a folder the user marked, or under one: the context menu's
   **Look up art details** on a folder in Pictures (see
   [Items the helper adds to the context menu](../script/actions.md#items-the-helper-adds-to-the-context-menu)).
   The marks are kept in `art_details_folders.json` in the helper's profile folder.
   A folder inside an archive (`zip://`, `rar://`, `archive://`) can't be marked.
3. Your skin asks, by serving `info=art_details` for the focused item. Only pictures
   are looked up: a file whose extension Kodi lists as a picture
   (`xbmc.getSupportedMedia("picture")`), not `.cbz`, `.cbr`, `.zip`, `.rar` or `.rss`.

The setting and the mark are tested again before every request, so nothing is sent
once either is undone, even for a picture already waiting its turn.

```xml
<content>plugin://script.copacetic.helper/?info=art_details&amp;folder=$INFO[Container.FolderPath]&amp;path=$INFO[ListItem.FileNameAndPath]</content>
```

Served, it is a row of a details list's probe ([served lists](../service/serve.md)): the
same params without the `plugin://…?` prefix. Pass `folder` and `path` last, with
`$INFO` and not URL-encoded, as [`clean_name`](clean_name.md)'s `path`.

## The match

The file name is read as `Artist - Title (Year)`: quotes around the title are optional,
the year may be a range (`(1894-1895)`, `(1894-95)`), and words after a quoted title's
`from` are dropped (`'Behind the Great Wave at Kanagawa' from Cycle '36 Views…'`).

The artist is the first painter (occupation *painter*) Wikidata's search finds for the
name, else, in a second request, for each word searched fuzzily, so a typo such as
`Kandinksy` still finds Wassily Kandinsky. Its works come in a request of their own,
kept by the painter's id, so two spellings of one name share them. Each work is
scored against the title, on its labels and aliases in English, German, French,
Spanish, Italian, Russian, Japanese, Dutch and Norwegian, accents, case, punctuation
and small words (*the*, *of*, *off* …) aside, numbers to twenty as Roman numerals
(`Composition Seven` is *Composition VII*):

- how alike the two titles are; but a label whose words are only some of the title's
  scores by the share of the title it covers: at three words or more covering half of
  it, at least 0.75, more the more it covers; else that share, 0.6 at most, which no
  year bonus lifts to a match. So *The Great Wave off Kanagawa*
  matches `Behind the Great Wave at Kanagawa`, while *Green Forest* doesn't match
  `Yellow and Green Forest`, nor *Self-Portrait* `Self-Portrait with Bandaged Ear and
  Pipe`;
- plus 0.15 for an inception year in the file's years, 0.05 for one a year off, less
  0.1 for one further off;
- equal scores go to the work with the most Wikipedia sitelinks, the famous version.

A score of 0.8 or more is a match; anything less shows nothing.

## When it asks

Each file's verdict, a match or a miss, is kept by its path and modification time for
a year: a file is looked up once, and again only when it changes, is refreshed
([`art_details_refresh`](../script/actions.md#art_details_refresh)) or a year has
passed (so a moved or deleted file's verdict goes in time). The answers it came from
(an artist's works, a painting, a summary) are kept 30 days.

Look-ups run in the service only. A served call reads the verdict from the cache; a
file not looked up yet is looked up on a thread of its own, one file at a time, and its
list is served again when the verdict lands, as long as that arrival is still the
window's last; meanwhile the item has no `art_*` properties. A plugin call reads kept
verdicts only and starts no look-up.

Every request waits its turn, a second apart. The Wikidata query service limits clients
hard when it is busy: a `429` holds every Wikidata request for its `Retry-After`. A
look-up waits a busy queue out, a second at a time while its list is still wanted, and
asks once more after a short `429`; one stopped, or refused, keeps no verdict, so the
next visit asks again. A [refresh](../script/actions.md#art_details_refresh) waits for
nothing: pressed while the queue is busy, it leaves the verdict as it is. Requests carry
the helper's contact User-Agent; no key is needed.

## Params

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `folder` | the listing's folder | none | Published as `art_details_checked`, and as `art_details_folder` while it is marked; leave it out where there is no listing (picture info over the slideshow), and both stay as they are |
| `path` | a picture's or folder's path | required | The file to look up; a folder (its path ends in a separator) publishes its mark state |
| `chip_row` | pixels | none | Fit the chips to a row this wide: `art_chip1` … hold only the chips that fit, from the first |
| `chip_font` | a font in your `Font.xml` | none | The chips' font, measured as Kodi lays it out |
| `chip_padding` | pixels | `0` | A chip's `textoffsetx`: its text is this far in from each end |
| `chip_gap` | pixels | `0` | The row's `itemgap` |
| `chip_max` | pixels | none | A chip's widest (`<width max="…">auto</width>`) |
| `chip_upper` | `true` | — | The chips' font draws capitals (`<style>uppercase</style>`) |
| `summary_lines` | lines | none | Cut `art_summary` to fit this many lines, at a sentence where one ends in them, else with `...` |
| `summary_width` | pixels | — | The summary's width |
| `summary_font` | a font in your `Font.xml` | — | The summary's font |

## The item

One item. On a match it carries these properties; with none (no match, not looked up
yet, an unmarked folder, the setting off) it carries none.

| Property | Value |
|---|---|
| `art_title` | The painting's English title |
| `art_artist` | The artist's English name |
| `art_year` | The earliest inception year, else the file's |
| `art_medium` | Paint on its surface, as `Oil on canvas` from *oil paint* and *canvas* (the painting surface, or a support such as canvas, panel, wood or paper); else the materials in turn |
| `art_genre` | The first genre, as Wikidata names it (`landscape art`) |
| `art_collection` | The current collection with an English name; *Private collection* where Wikidata knows only that every one is unknown |
| `art_dimensions` | Height by width, as `73.7 × 92.1 cm` |
| `art_depicts` | Up to three things it depicts, comma-separated |
| `art_summary` | The English Wikipedia summary (cut to `summary_lines`) |
| `art_chip1` … `art_chip4` | Medium, genre, collection and dimensions, empty ones left out (with `chip_row`, those that fit) |
| `art_qid`, `art_artist_qid` | The painting's and the artist's Wikidata ids |
| `art_enwiki` | The English Wikipedia article's title |

### Mark state

While the setting is on, the serve also sets Home window properties, which the
context menu's two items and your skin compare with paths:

| Property | Value |
|---|---|
| `art_details_checked` | The `folder` param: the last listing served |
| `art_details_folder` | The `folder` param while it is marked or under a marked folder; else cleared |
| `art_details_marked` | The served folder's path while it is marked itself |
| `art_details_unmarked` | The served folder's path while neither it nor a folder above it is marked |

So **Look up art details** shows on a folder only once your skin has served it, and
neither item shows on a folder inside a marked one: it follows its parent.

A skin can hold a picture's text until the serve answers where it may match, so its
own labels never show first and change: while `art_details_checked` isn't the
listing (a listing not served yet) or `art_details_folder` is.

## Search

`info=art_search&query=…` finds pictures for a search rail, from what is already kept
and nothing else: each looked-up picture's verdict, in folders marked now. It never
sends a request and lists no folder, so a picture shows only once a serve has looked
it up.

```xml
<content>plugin://script.copacetic.helper/?info=art_search&amp;limit=30&amp;query=$INFO[Window(home).Property(search_query)]</content>
```

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `limit` | a number | `30` | The most pictures listed, the best first |
| `query` | search text, last | none | The words to find; none lists every match, and text with no word in it (emoji alone) nothing |

Kodi passes a plugin URL's options as written, still percent-encoded, so `query` is
decoded once, then its JSON escapes are read (`ô`), as
[`set_search_query`](../script/actions.md#set_search_query) writes them; plain text
works too. Two things plain text can't carry: a `|` ends a plugin URL's options in Kodi,
and text such as `&limit=` inside the query starts a param of its own. Both pass
percent-encoded, as `set_search_query` writes them. Pass the query last.

Every word of the query (case, accents and punctuation aside) must be in one of these,
tried in turn; the first that holds them all ranks the picture:

1. the painting's title;
2. its artist;
3. its details: title, artist, collection, what it depicts, and the artist's movements
   where the [artist page](#the-artist-page) has been kept;
4. the file's name (a picture with no match too).

Within a rank, matches come before misses, then by artist, year and title. With no
query, every match, by artist, year and title. Each item's path is the picture, so
Kodi's own select shows it full screen; it is labelled with the title (else the file
name), `label2` the artist, the picture as `thumb`, and the [item's](#the-item)
`art_*` properties but `art_summary`. Only pictures are listed (as the look-ups), and
nothing while the `wikidata` setting is off.

The best `limit` matches are checked against the disk, and no others: one moved or
deleted is left out, and the list isn't filled up past it, so it may hold fewer than
`limit`. Its verdict is kept until it ages out (a year); a visit to its new place looks
it up there.

## The artist page

A matched painting's `art_artist_qid` opens its artist: `info=art_artist` for the
details and biography, `info=art_rail` for three rails of pictures. Both take the
artist's `qid` and ask only while the `wikidata` setting is on; no folder needs
marking, as the artist comes from a match.

```xml
<label>info=art_artist&amp;qid=$INFO[Window(home).Property(art_artist)]</label>
<label>info=art_rail&amp;kind=gallery&amp;qid=$INFO[Window(home).Property(art_artist)]</label>
```

Served, each reads the answers kept for it, whatever their age; one missing or older
than 30 days is asked on a thread of its own, one request at a time with the look-ups,
and its list is served again when the answer differs. A plugin call reads kept answers
only. The setting is tested again before each request.

[`art_artist`](../script/actions.md#art_artist) moves the page to another artist (a
Similar artists or Influenced tile) and keeps a short Back history.

### info=art_artist

One item, labelled with the artist's English name, its portrait (Wikidata's image,
1280 pixels wide from Wikimedia Commons) as `thumb`. Until its answer lands, a blank
item with no properties.

| Property | Value |
|---|---|
| `art_name` | The artist's English name |
| `art_occupation` | *Painter* where Wikidata lists it, else the first occupation |
| `art_life` | Birth and death years, as `1775–1851` (a decade or century where Wikidata knows no more: `1650s–1688`); the birth year alone for a living artist, `–1851` with only the death known |
| `art_born`, `art_died` | The date to Wikidata's precision (`23 April 1775`, `April 1775`, `1775`, `1770s`, `18th century`; `15 March 44 BC`, `5th century BC` before year 1), a date entered as Julian in its own calendar (`6 March 1475`), then the place |
| `art_teacher`, `art_teacher_more` | The first two teachers (*student of*), and how many more |
| `art_movement`, `art_movement_more` | The first movement, and how many more |
| `art_nationality` | The first country of citizenship's English demonym (the one with no start date, else the earliest: `Russian` for Kandinsky), the adjective (`British`) where Wikidata lists a noun (`Briton`) too |
| `art_paintings` | How many paintings Wikidata credits to the artist |
| `art_influence`, `art_influence_more` | The first two the artist was influenced by, and how many more |
| `art_biography` | The English Wikipedia summary, whole: pass it to [`text`](text.md) to draw it as a page |

An item with no English label, and an unknown value, is left out; an empty field is
an empty property.

### info=art_rail

| Param | Accepted values | What it does |
|---|---|---|
| `qid` | an artist's Wikidata id | The artist |
| `kind` | `gallery`, `similar`, `influenced` | Which rail |

- `gallery`: the artist's works with a picture, its notable works (*notable work* on the
  artist) first, then by Wikipedia sitelinks;
- `similar`: painters of the artist's movements born within 35 years of it, the 60
  with the most sitelinks, of whom those with five paintings or more on Wikidata (an
  occupation and a painting let in a writer who also painted), by sitelinks;
- `influenced`: those whose *influenced by* names the artist, by sitelinks.

Up to 30 items, each labelled with its English name (a work may have none; an artist
always has one), `label2` a
work's earliest inception year, its picture 1280 pixels wide as `thumb`, and:

| Property | Value |
|---|---|
| `qid` | The work's or artist's Wikidata id |
| `full` | The picture 1920 pixels wide, for `ShowPicture` |

`ShowPicture` takes the URL as a path: Kodi asks the server for its type, then loads
it as any picture, in a slideshow of one that replaces the one running. The slideshow
opens as a dialog over what is open, so close your own dialogs first, at once
(`Dialog.Close(…,true)`), keeping the URL in a property for the call after them.

[`art_details_refresh`](../script/actions.md#art_details_refresh) marks the artist's
page stale too: its next serve asks again.
