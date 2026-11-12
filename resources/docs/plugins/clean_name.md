# Clean Name

Turns a file name such as `Batman.Begins.2005.1080p.BluRay.x264.mkv` into something
readable, with Kodi's own clean-up (`xbmc.getCleanMovieTitle`, which follows the user's
`cleanstrings` in `advancedsettings.xml`). Use it for files outside the library, whose
labels are their file names.

```xml
<content>plugin://script.copacetic.helper/?info=clean_name&amp;path=$ESCINFO[ListItem.FileNameAndPath]&amp;label=$ESCINFO[ListItem.Label]</content>
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
