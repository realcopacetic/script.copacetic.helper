# Favourite Helper

A favourite list item carries little more than its label, its thumb and the command
it runs. It has no plot, no year, no watched state and no fanart. This plugin path
finds the library item a favourite points to and returns that item, with all its
library details. Point your metadata, progress bar or artwork calls at the container
that holds it, and a favourite gets the same details as the library item would.

## Plugin path

```xml
<control type="list" id="9040"><!-- hidden helper container; ids are examples -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=favourite&amp;target=50&amp;focus_guard=$INFO[Container(50).CurrentItem]&amp;path=$INFO[Container(50).ListItem.FileNameAndPath]</content>
</control>
```

Here 50 is the list showing the favourites. Then read the item from 9040, or pass
`target=9040` to another helper. Keep that helper's focus guard on the favourites list
with `identity_labels`, so it stops when you move to another favourite:

```xml
<content>plugin://script.copacetic.helper/?info=metadata&amp;target=9040&amp;identity_labels=Container(50).CurrentItem&amp;focus_guard=$INFO[Container(50).CurrentItem]&amp;id=$INFO[Container(9040).ListItem.DBID]&amp;type=$INFO[Container(9040).ListItem.DBType]</content>
```

Wait for 9040 to finish before you read it: add `!Container(9040).IsUpdating` to the
other helper's `<visible>` condition.

## Parameters

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `path` | the favourite's `ListItem.FileNameAndPath` | — | **Required.** The favourite to look up. Nothing is returned without it. |
| `index` | any text | — | Returned on the item as `ListItem.Property(favourite.index)`. Pass the favourite's own `ListItem.Property(favourite.index)`. To check that 9040 holds the focused favourite, match `favourite.path` instead (below): an index is a position in the list. |
| `target` | container id | — | Container used by the focus guard. |
| `focus_guard`, `focus_ids`, `identity_labels`, `identity_container`, `dialog` | | | Focus guard. See [Plugin Helpers](plugin_helpers.md#3-guarding-against-fast-scrolls-and-container-moves). |

## Which favourites are found

The helper reads the command the favourite runs: the media path in
`PlayMedia(...)`, or the path (second parameter) in `ActivateWindow(...)`. Any other
command finds nothing. It then looks the path up:

| The path is | The item returned |
|---|---|
| A TV show folder: `videodb://tvshows/titles/<id>/`, or under one filter node such as `videodb://tvshows/genres/3/<id>/` (also with `-1/`, all seasons) | The TV show |
| A season folder: `videodb://tvshows/titles/<id>/<season>/` (or under one filter node) | That season of the show |
| A movie set: `videodb://movies/sets/<id>/` | The set |
| An artist: `musicdb://artists/<id>/` (also with `-1/`, all albums) | The artist |
| An album: `musicdb://albums/<id>/`, `musicdb://artists/<artist>/<id>/`, `musicdb://recentlyaddedalbums/<id>/` or `musicdb://recentlyplayedalbums/<id>/` | The album |
| A media file | The movie, episode, music video or song in your library with that exact file |

Plugin paths, other library folders and files that are not in the library find
nothing. A file is found from the library database only: the helper never opens the
file or its share.

## What the item carries

- **Videos** (movie, set, TV show, season, episode, music video): the library details
  as `ListItem.*` infolabels, such as `ListItem.Title`, `ListItem.Plot`,
  `ListItem.DBID`, `ListItem.DBType` and `ListItem.PlayCount`, and the library
  artwork as `ListItem.Art(...)`. Each type has the details the library keeps for it:
  a movie has its year, rating and resume point; a set or season has few (a season
  has no plot). A TV show or season also has the episode counts Kodi's own library
  items carry: `ListItem.Property(TotalEpisodes)`, `WatchedEpisodes`,
  `UnWatchedEpisodes` and `WatchedEpisodePercent`, and a TV show
  `ListItem.Property(TotalSeasons)`.
- **Music** (artist, album, song): the library details and artwork. An artist has
  Kodi's artist description and dates: `ListItem.Property(Artist_Description)`,
  `Artist_Born`, `Artist_Formed`, `Artist_YearsActive`, `Artist_Disbanded` and
  `Artist_Died`. An album has `ListItem.Property(Album_Description)`.
- `ListItem.Property(favourite.index)`: the `index` you passed.
- `ListItem.Property(favourite.path)`: the favourite's `ListItem.FileNameAndPath`, as
  Kodi lists it, so
  `String.IsEqual(Container(9040).ListItem.Property(favourite.path),Container(50).ListItem.FileNameAndPath)`
  is true while 9040 holds the focused favourite. It stays true while Kodi refreshes
  9040 in place (after a library update), as Kodi keeps the old item until the new
  one arrives.

The item is for reading only. Its path is the helper's own, so selecting it does not
play or open anything: keep your `<onclick>` on the favourite itself.

## When nothing is returned

The container is left empty when the favourite points to no library item, when
`path` is missing, when the focus guard fails, or when the library no longer has the
item.

Each favourite's answer is kept until Kodi restarts, the "no library item" answer
too, so moving back to a favourite costs nothing. A favourite you add to the library
later is found after a restart. If a lookup fails with an error, nothing is kept and
the next call tries again. If the library loses a file's item, the next call looks the
file up again; a folder's item stays not found until Kodi restarts.

See [Plugin Helpers](plugin_helpers.md) for how plugin paths work.
