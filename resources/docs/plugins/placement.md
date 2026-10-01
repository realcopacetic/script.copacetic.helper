# Placement Options

Three plugin paths move controls on screen: `jumpbutton`, `progressbar` and
`typewriter`. They share one set of placement parameters. This page describes them.

Each of these helpers first works out a rectangle (x, y, width, height). What it then
does with the rectangle depends on the helper:

- `jumpbutton` slides a button along it.
- `progressbar` moves and sizes the progress bar to fill it.
- `typewriter` moves and sizes a textbox inside it.

---

## How the rectangle is found

1. If `coords` is passed, it is used as the rectangle.
2. Otherwise the rectangle of the control in `anchor_id` is read (its position, width
   and height).
3. If neither gives a rectangle, a warning is logged and nothing moves.

Then:

4. `inset` shrinks the rectangle on each side.
5. If `track_w` or `track_h` is passed, a box of that size is placed inside the
   rectangle, using `halign`/`valign` and `hpad`/`vpad`. The box becomes the new
   rectangle. A box larger than the rectangle is not used on that axis; the
   rectangle keeps its size.
6. If `outside` is passed (and `anchor_id` is used), the box is placed next to the
   anchor instead of inside it. See [Outside placement](#outside-placement).

## Parameters

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `coords` | `x,y,w,h` (four whole numbers) | — | The rectangle to use. Takes priority over `anchor_id`. A value that is not four numbers is ignored and `anchor_id` is tried instead. |
| `anchor_id` | control id | — | Control whose position and size give the rectangle. |
| `inset` | `N`, `H,V` or `L,T,R,B` | `0` | Shrinks the rectangle. `N` shrinks every side by N. `H,V` shrinks left and right by H, top and bottom by V. `L,T,R,B` sets each side. Three values are treated as `0`. |
| `track_w` | whole number | — | Width of the box placed inside the rectangle. |
| `track_h` | whole number | — | Height of the box placed inside the rectangle. For `typewriter` this is the line height (see the typewriter page). |
| `halign` | `left`, `center`, `right` | `center` | Horizontal alignment inside the rectangle. Any other value acts as `center`. |
| `valign` | `top`, `center`, `bottom` | `center` | Vertical alignment inside the rectangle. Any other value acts as `center`. |
| `hpad` | whole number | `0` | With `left` or `right`: the gap from that edge. With `center`: a nudge (positive moves right). |
| `vpad` | whole number | `0` | With `top` or `bottom`: the gap from that edge. With `center`: a nudge (positive moves down). |
| `outside` | `below`, `above`, `left`, `right` | — | Places the box next to the anchor instead of inside it. Needs `anchor_id`. |
| `relative` | `true`, `false` | `false` | `jumpbutton` only. Keeps the button's current position across the track instead of aligning it. |

Booleans accept `true`, `1`, `yes` or `on` (any case). Anything else is false.

## Outside placement

With `outside`, the box sits against the anchor's edge. `inset` is ignored. The box
size is `track_w`/`track_h`, or the anchor's size where these are not passed.

| `outside` | x | y |
|---|---|---|
| `below` | aligned along the anchor with `halign` and `hpad` | anchor bottom + `vpad` |
| `above` | aligned along the anchor with `halign` and `hpad` | anchor top − `vpad` − box height |
| `right` | anchor right + `hpad` | aligned along the anchor with `valign` and `vpad` |
| `left` | anchor left − `hpad` − box width | aligned along the anchor with `valign` and `vpad` |

## Coordinate rules

Kodi's Python API uses positions relative to each control's parent. The anchor's
position is measured from the anchor's parent. The moved control's position is
measured from its own parent. So:

- **The anchor and the moved control must share a parent** (or both sit at window
  level). Then `anchor_id` works as expected.
- **If the moved control is inside the anchor group**, use `coords=0,0,W,H` with the
  group's size instead of `anchor_id`.

Give the anchor an explicit `<width>` and `<height>`. Kodi's Python API cannot see a
size that comes from `<left>` and `<right>` together.

## Example

```xml
<content>plugin://script.copacetic.helper/?info=progressbar&amp;target_id=4010&amp;anchor_id=4000&amp;inset=20&amp;track_h=4&amp;valign=bottom</content>
```

Control 4000 is shrunk by 20 pixels on every side. The progress bar is 4 pixels tall
and sits along the bottom of that smaller rectangle. (Ids are examples.)
