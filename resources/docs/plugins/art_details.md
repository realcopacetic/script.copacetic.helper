# Art Details

Looks up a picture file on [Wikidata](https://www.wikidata.org) as a painting and
returns its standard fields: artist, year, medium, genre, collection, dimensions, what
it depicts and the English Wikipedia summary. It is for folders of paintings named
`Artist - Title (Year)`, the user's own choice of folders, and runs only on demand: for
the item you serve it for, never as a walk through a folder.

Three things must be true before anything is sent:

1. The user turned on **Look up paintings on Wikidata** in the helper's settings
   (setting `wikidata`, off by default; your skin can test
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
hard when it is busy: a `429` holds every Wikidata request for its `Retry-After`, and a
look-up that couldn't ask keeps no verdict, so the next visit asks again. Requests carry
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
| `art_life` | Birth and death years, as `1775–1851`; the birth year alone for a living artist, `–1851` with only the death known |
| `art_born`, `art_died` | The date to Wikidata's precision (`23 April 1775`, `April 1775`, `1775`), then the place |
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
- `similar`: painters of the artist's movements born within 35 years of it, with a
  painting of their own on Wikidata (an occupation alone lets in a writer who also
  painted), by sitelinks;
- `influenced`: those whose *influenced by* names the artist, by sitelinks.

Up to 30 items, each labelled with its English name (empty for none), `label2` a
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
