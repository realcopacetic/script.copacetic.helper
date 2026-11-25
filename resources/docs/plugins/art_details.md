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
3. Your skin asks, by serving `info=art_details` for the focused item.

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
name, else for each word searched fuzzily, so a typo such as `Kandinksy` still finds
Wassily Kandinsky. Each of the artist's works is scored against the title, on its
labels and aliases in English, German, French, Spanish, Italian, Russian, Japanese,
Dutch and Norwegian, accents, case, punctuation and small words (*the*, *of*, *off* …)
aside, numbers to twenty as Roman numerals (`Composition Seven` is *Composition VII*):

- how alike the two titles are, or, for a label of two words or more whose words all
  appear in the file's title, at least 0.75, more the more of the title it covers;
- plus 0.15 for an inception year in the file's years, 0.05 for one a year off, less
  0.1 for one further off;
- equal scores go to the work with the most Wikipedia sitelinks, the famous version.

A score of 0.8 or more is a match; anything less shows nothing.

## When it asks

Each file's verdict, a match or a miss, is kept by its path and modification time with
no expiry: a file is looked up once, and again only when it changes or is refreshed
([`art_details_refresh`](../script/actions.md#art_details_refresh)). The answers it came
from (an artist's works, a painting, a summary) are kept 30 days.

A served call reads the verdict from the cache only. A file not looked up yet is looked
up on a thread of its own, one file at a time, and its list is served again when the
verdict lands, as long as that arrival is still the window's last; meanwhile the item
has no `art_*` properties. A plugin call looks it up there and then.

Every request waits its turn, a second apart. The Wikidata query service limits clients
hard when it is busy: a `429` holds every Wikidata request for its `Retry-After`, and a
look-up that couldn't ask keeps no verdict, so the next visit asks again. Requests carry
the helper's contact User-Agent; no key is needed.

## Params

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `folder` | the listing's folder | empty | Published as `art_details_folder` while it is marked |
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
| `art_medium` | Paint on its surface, as `Oil on canvas` from *oil paint* and *canvas* (the painting surface); else the materials in turn |
| `art_genre` | The first genre, as Wikidata names it (`landscape art`) |
| `art_collection` | The current collection; *Private collection* where Wikidata knows only that it is unknown |
| `art_dimensions` | Height by width, as `73.7 × 92.1 cm` |
| `art_depicts` | Up to three things it depicts, comma-separated |
| `art_summary` | The English Wikipedia summary (cut to `summary_lines`) |
| `art_chip1` … `art_chip4` | Medium, genre, collection and dimensions, empty ones left out (with `chip_row`, those that fit) |
| `art_qid`, `art_artist_qid` | The painting's and the artist's Wikidata ids |
| `art_enwiki` | The English Wikipedia article's title |

### Mark state

The serve also sets Home window properties, which the context menu's two items
compare with the focused folder's path:

| Property | Value |
|---|---|
| `art_details_folder` | The `folder` param while it is marked or under a marked folder; else cleared |
| `art_details_marked` | The served folder's path while it is marked itself |
| `art_details_covered` | The served folder's path while it, or a folder above it, is marked |
| `art_details_unmarked` | The served folder's path while neither is |

So **Look up art details** shows on a folder only once your skin has served it, and
neither item shows on a folder inside a marked one: it follows its parent.
`art_details_folder` lets a skin hold a picture's text until the serve answers in a
marked folder, so its own labels never show first and change.
