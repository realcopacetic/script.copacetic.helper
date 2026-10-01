# JumpButton Helper

Positions a button along a scrollbar track in proportion to the list's cursor and
labels it with the current sort letter (or any label you pass). The scrollbar itself
is never touched — Python cannot move or reorient `<scrollbar>` controls — the button
is an overlay that travels the same span.

## How it works

1. A rect is resolved from `anchor_id` (the scrollbar, or a group the scrollbar fills)
   or from explicit `coords`.
2. Axis is inferred from the rect: wider than tall → horizontal travel; taller than
   wide → vertical.
3. The button is placed at `fraction × (span − button size)` along the travel axis,
   where `fraction = (CurrentItem − 1) / (NumItems − 1)` of the list, and aligned on
   the cross axis with `halign`/`valign` (+ `hpad`/`vpad`), or left where it is with
   `relative=true`.
4. `setLabel` and `setPosition` are applied to the button. Both work on hidden controls.

The button only moves when its label or the list size changes. After each move the
helper stores `<label>|<NumItems>` in `Window(home).Property(jumpbutton_seen)`. A
later run with the same label in a list of the same size does nothing, so the button
stays at the first item of that letter while you scroll through it. Refire the path
whenever the label should change (typically when the sort letter changes).

The helper works on the current window (`getCurrentWindowId()`), not on dialogs.

## Coordinate rules

The anchor and the button must share a parent group, or the button must use
`coords=0,0,W,H` when it sits inside the anchor group. Give the anchor an explicit
`width` and `height`. See [Coordinate rules](placement.md#coordinate-rules).

## Duplicate ids

`Window.getControl(id)` returns the first control with that id whose own state is
visible, else the first registered. If your skin has several controls sharing the
button id (for example one per orientation) the helper will write to whichever wins
that lookup, which at rest is the first in the file. Use one button and let the helper
position it for either orientation; the anchor may be duplicated as long as exactly one
copy is visible per layout (an orientation gate on each is enough).

## XML

```xml
<control type="group"><!-- one parent for the track(s) and the button -->
  <control type="scrollbar" id="60">
    <orientation>horizontal</orientation>
    <left>120</left><top>1050</top><width>1680</width><height>4</height>
    <pagecontrol>50</pagecontrol>
  </control>
  <control type="button" id="62">
    <width>45</width><height>30</height>
    <align>center</align><aligny>center</aligny>
  </control>
</control>
```

## Plugin path

```xml
plugin://script.copacetic.helper/?info=jumpbutton&amp;sortletter=$INFO[ListItem.SortLetter]&amp;anchor_id=60&amp;target_id=62
```

Use it as `<content>` of a hidden list container so it refires when the URL changes,
or via `RunPlugin` from an action.

## Parameters

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `target_id` | control id | — | **Required.** The button to label and move. |
| `sortletter` | any text | `ListItem.SortLetter` of the list | Label for the button. Pass your own for digit sorts (SortLetter is the first character only). |
| `target` | container id | — | Container to read `CurrentItem`, `NumItems` and `SortLetter` from. Omit on media windows to use the view container. |
| `anchor_id` | control id | — | Control whose rectangle is the track. |
| `coords` | `x,y,w,h` | — | The track rectangle. Overrides `anchor_id`. |
| `inset` | `N`, `H,V` or `L,T,R,B` | `0` | Shrinks the track. |
| `halign` | `left`, `center`, `right` | `center` | Position across a vertical track. |
| `valign` | `top`, `center`, `bottom` | `center` | Position across a horizontal track. |
| `hpad` / `vpad` | whole number | `0` | Gap from the edge for `left`/`right`/`top`/`bottom`; a nudge for `center`. |
| `relative` | `true`, `false` | `false` | Keep the button's current position across the track instead of aligning it. |

`track_w`, `track_h` and `outside` are also read. They change the track rectangle as
described in [Placement Options](placement.md).

The path returns no list items.

## Notes

- The button's size is read from its XML; set `width`/`height` explicitly.
- If the anchor or button can't be found the run logs and returns; nothing is moved.
- `fraction` is 0 when the list has fewer than two items.
- There is no focus guard. The button must stay responsive while you scroll.

See [Placement Options](placement.md) for the options shared by all placement helpers.
