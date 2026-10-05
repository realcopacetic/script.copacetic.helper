# Progress Bar Helper

Works out how much of the focused item has been watched, returns it on a list item,
and moves and sizes a progress bar group to fit your layout.

It handles movies, episodes, TV shows, seasons and movie sets. For a set it counts the
watched movies in the set.

## Plugin path

```xml
<control type="list" id="9500"><!-- hidden helper container; id is an example -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=progressbar&amp;target=50&amp;focus_guard=$INFO[Container(50).CurrentItem]&amp;target_id=4010&amp;anchor_id=4000&amp;valign=bottom&amp;track_h=4</content>
</control>
```

## Controls the skin provides

`target_id` is the id of a group. The helper finds the other controls by adding to it:

| Control | Id | Required | What the helper does |
|---|---|---|---|
| Group | `target_id` | yes | Moved to the rectangle's x and y. Grown (never shrunk) to at least the rectangle's size. |
| Progress control | `target_id + 1`, or `progress_id` | yes | Set to the rectangle's width and height. |
| Button | `target_id + 2`, or `btn_id` | no | Centred in the unwatched part of the bar (between the played point and the end), kept inside the bar, and centred vertically. Needs an explicit `<width>` and `<height>`. |
| Image | `target_id + 3`, or `img_id` | no | Set to the rectangle's width and `img_h` tall, centred vertically on the bar. |
| Extra control | `target_id + 4` | no | Set to the rectangle's width and height. |

Put the other controls inside the group. Their positions are relative to the group.

## Parameters

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `target_id` | control id | — | **Required.** The group id. |
| `target` | container id, or `item` | — | Container whose focused item is measured. Omit to use `Container` (the current container); `item` measures the window's own item. |
| `progress_id` | control id | `target_id + 1` | Progress control id. |
| `btn_id` | control id | `target_id + 2` | Button id. |
| `img_id` | control id | `target_id + 3` | Image id. |
| `img_h` | whole number | the bar height | Height of the image. |
| `focus_guard`, `focus_ids`, `identity_labels`, `identity_container` | | | Focus guard. See [Plugin Helpers](plugin_helpers.md#3-guarding-against-fast-scrolls-and-container-moves). |

Placement parameters (`coords`, `anchor_id`, `inset`, `track_w`, `track_h`,
`halign`, `valign`, `hpad`, `vpad`, `outside`) set the rectangle. See
[Placement Options](placement.md). With no `coords` or `anchor_id`, the item is
still returned but nothing moves.

## How the value is worked out

The first rule that matches wins:

1. The first of `ListItem.PercentPlayed`, `ListItem.Property(WatchedEpisodePercent)`
   and `ListItem.Property(WatchedProgress)` that is a whole number above 0.
2. If the item is watched (`ListItem.Overlay` is `OverlayWatched.png` or
   `ListItem.PlayCount` is above 0): 100.
3. For a movie set: the share of movies in the set with a play count, from
   `VideoLibrary.GetMovieSetDetails`.
4. Otherwise: 0.

## What you get back

One list item in the helper container:

| Infolabel | Value |
|---|---|
| `ListItem.PercentPlayed` | The value above, 0–100 (set as the resume point out of 100). |
| `ListItem.Property(unwatchedepisodes)` | `ListItem.Property(UnwatchedEpisodes)` of the focused item. For a set, the number of unwatched movies. Empty when the item is watched. |

## Focus guard

The guard is checked before the value is worked out and again before any control
moves. If focus moved on in between, the list item is still returned but no control
moves.
