# Clean Name

Turns a file name such as `Batman.Begins.2005.1080p.BluRay.x264.mkv` into something
readable, with Kodi's own clean-up (`xbmc.getCleanMovieTitle`, which follows the user's
`cleanstrings` in `advancedsettings.xml`). Use it for files outside the library, whose
labels are their file names. The name is read from the path as Kodi reads it: a web or
DAV path's `?` options and URL-encoding don't get in the way, and a `stack://` path
gives the stack's name (Kodi's own stacking rules).

Pass the path with `$INFO`, not URL-encoded: Kodi hands the plugin URL's values over
raw and the helper reads `path` as it comes. One limit: a `|` in the path (a file name
with one, or `|User-Agent=…` options) ends the plugin query there, so `label` is lost
and a skin matching on it shows nothing.

```xml
<content>plugin://script.copacetic.helper/?info=clean_name&amp;path=$INFO[ListItem.FileNameAndPath]&amp;label=$INFO[ListItem.Label]</content>
```

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `path` | a file's path | required | The file to name |
| `label` | any text | empty | Echoed as the item's label, so you can check it still matches the focused item |

It returns one item, with these properties (each only when found):

| Property | Value |
|---|---|
| `clean_title` | A film's title, or an episode's title |
| `clean_year` | A film's year |
| `clean_tvshowtitle` | For a file named like an episode (`S01E07` or `1x07`): the show |
| `clean_episode` | The episode's code, as `1x07` |

The playing file gets the same names as `player_clean_*` properties, from the service
(see [Player properties](../service/player.md#identity-and-clean-names)).
