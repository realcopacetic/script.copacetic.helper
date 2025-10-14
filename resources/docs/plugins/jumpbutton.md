# JumpButton Helper

The **JumpButton helper** allows you to implement a jump-to button that follows the sort letter while scrolling a list. It automatically moves a button control within the bounds of a scrollbar, displaying the current sort letter (e.g. *M* for movies starting with “M”).

## Purpose & Use Cases

1. **Scroll-following overlay**  
   - As you scroll through a list, the helper calculates the scrollbar fraction (`cur/total`) and moves the button to the correct position along the scrollbar track.  
   - For example: if letter *M* begins at item 300 of 600 movies, the helper places the button at 50% of the scrollbar.

2. **Jump navigation button**  
   - When the button itself has focus, the user can press **left/right** (horizontal lists) or **up/down** (vertical lists) to jump to the next available sort letter.  
   - After each jump, the helper repositions the button automatically.

⚠️ **Kodi limitation:** Python cannot directly move `<scrollbar>` or `<progress>` controls. Instead, the button must live inside a **group** with a base ID. The helper manipulates the button inside this group to simulate a proper jump overlay.

---

## Placement & Geometry

The JumpButton uses the same placement logic as other helpers, but with rules tailored for scrollbars:
- **Coords or Anchor** → The helper resolves a bounding rectangle from either `coords` (`x,y,w,h`) or `anchor_id` (the rect of another control).  
- **Insets** → Padding is applied inside that rect (`inset=left,top,right,bottom`).  
- **Aspect ratio check** → If the rect is wider than tall, we treat it as **horizontal**; if taller than wide, as **vertical**.  
- **Relative axis option** → If `relative=true`, the helper keeps the button’s original coordinate along the axis that does not travel.

For a generic overview of all placement options, see [`placement.md`](placement.md).

---

## XML Example

Here’s a simple example of a scrollbar and jump button wrapped in a group:

```xml
<control type="group" id="4000">
  <control type="scrollbar" id="60">
    <orientation>horizontal</orientation>
    <visible>true</visible>
  </control>

  <control type="button" id="62">
    <label>A</label>
    <width>30</width>
    <height>30</height>
    <font>font20</font>
  </control>
</control>
```

- The scrollbar (`id=60`) reports its position as `cur/total`.  
- The button (`id=62`) is repositioned by the helper.  
- The group (`id=4000`) acts as the base container.

---

## Plugin Path Example

Call the JumpButton helper from your container using `RunPlugin`:

```xml
<onclick>RunPlugin(plugin://script.copacetic.helper?action=jumpbutton&amp;scroll_id=60&amp;sortletter=$INFO[ListItem.SortLetter]&amp;anchor_id=4000&amp;inset=12,4)</onclick>
```

This moves the button according to the scrollbar fraction and updates its label with the sort letter.

---

## Parameters

| Param        | Type   | Default | Allowed Values | Notes |
|--------------|--------|---------|----------------|-------|
| `action`     | str    | —       | `jumpbutton`   | Must be set to `jumpbutton`. |
| `scroll_id`  | int    | 60      | Any valid control ID | The ID of the scrollbar control to read `cur/total` from. |
| `sortletter` | str    | `$INFO[ListItem.SortLetter]` | Any label string | The text to display on the button. |
| `anchor_id`  | int    | —       | Any valid control ID | ID of a control whose rect defines placement bounds. |
| `coords`     | str    | —       | `x,y,w,h` CSV  | Explicit rect (overrides `anchor_id`). |
| `inset`      | str    | `0`     | `N` / `L,T` / `L,T,R,B` | Padding inside the bounding rect. |
| `halign`     | str    | `center`| `left`, `center`, `right` | Horizontal alignment of button if not `relative`. |
| `valign`     | str    | `center`| `top`, `center`, `bottom` | Vertical alignment of button if not `relative`. |
| `relative`   | bool   | `false` | `true` / `false` | Keep original non-travel axis position. |
| `hpad`/`vpad`| int    | 0       | Any px value   | Additional pixel padding. |

---

## Notes for Skinners

- Always wrap the jump button and scrollbar in a **group**. Python cannot move the scrollbar itself.  
- The button width/height defaults to **30px** if unset. Define sizes explicitly for predictable positioning.  
- For vertical scrollbars, make sure the resolved rect is taller than wide; otherwise it will be treated as horizontal.  
- If the helper cannot find the target controls, it fails silently and logs a warning.

