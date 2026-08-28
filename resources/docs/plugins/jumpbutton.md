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

Every run reads the list fresh; there is no state between runs, so refire it whenever
the label or position should change (typically when the sort letter changes).

## Coordinate contract

Kodi's Python API is parent-relative: `getX/getY` on the anchor are measured from the
anchor's parent, and `setPosition` on the button is measured from the button's parent.
The helper adds the anchor's origin to the travel axis, so **the anchor and the button
must share a coordinate space**:

- **Siblings** (same parent group, or both at window root): use `anchor_id`.
- **Button inside the anchor group**: use `coords=0,0,W,H` with the group's size —
  the rect expressed in the button's own space.

Anchors nested deeper than the button's parent yield rect values in the wrong space.
Keep the anchor and the button flat relative to each other.

Give the anchor explicit `width`/`height`; dimensions derived from edge pairs
(`left`+`right`) are not visible to `getWidth/getHeight`.

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

| Param | Type | Default | Notes |
|---|---|---|---|
| `info` | str | — | `jumpbutton` |
| `sortletter` | str | `ListItem.SortLetter` of the list | Label to display. Pass your own for digit sorts (SortLetter is the first character only). |
| `target` | int | — | Container id for CurrentItem/NumItems/SortLetter. Omit on media windows to use the view container. |
| `target_id` | int | — | Required. Button control to position. |
| `anchor_id` | int | — | Control whose rect is the track. |
| `coords` | str | — | `x,y,w,h`; overrides `anchor_id`. |
| `inset` | str | `0` | `N` / `L,T` / `L,T,R,B` shrink applied to the rect. |
| `halign` | str | `center` | `left` / `center` / `right` — cross-axis for vertical tracks. |
| `valign` | str | `center` | `top` / `center` / `bottom` — cross-axis for horizontal tracks. |
| `hpad` / `vpad` | int | `0` | Edge inset for left/right/top/bottom alignment; nudge for center. |
| `relative` | bool | `false` | Keep the button's current cross-axis coordinate instead of aligning. |

## Notes

- The button's size is read from its XML; set `width`/`height` explicitly.
- If the anchor or button can't be found the run logs and returns; nothing is moved.
- `fraction` is 0 when the list has fewer than two items.

See [`placement.md`](placement.md) for the options shared by all placement helpers.
