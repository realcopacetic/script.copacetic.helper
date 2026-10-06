# Reposition Helper

Sets the position or size of one or more controls from values in the plugin path.
Use it when a size depends on an infolabel, for example sizing a clearlogo to its real
aspect ratio, or an image to the height of rendered text.

It works on the topmost dialog when one is open, else on the current window.

## Plugin path

```xml
<control type="list" id="9700"><!-- hidden helper container; id is an example -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=reposition&amp;target_id=4040,4041&amp;fit=520,174&amp;src=$INFO[Container(9300).ListItem.Art(clearlogo_width)],$INFO[Container(9300).ListItem.Art(clearlogo_height)]</content>
</control>
```

This sets the height of controls 4040 and 4041 so that a logo of the given size,
scaled to fit a 520×174 box, keeps its shape. (Ids are examples; the clearlogo size
comes from the [artwork](artwork.md) helper.)

Once the controls are set, the path returns one list item with
`ListItem.Property(src_w)` and `ListItem.Property(src_h)`: the two values of `src`, as
passed (empty without `src`). Compare them with the current size to tell that the
controls are set for it. When `target_id` is missing, or `fit` cannot be used, nothing
is returned.

```xml
<expression name="LogoSized">String.IsEqual(Container(9700).ListItem.Property(src_h),Container(9300).ListItem.Art(clearlogo_height))</expression>
```

## Parameters

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `target_id` | control id, or ids separated by commas | — | **Required.** The controls to change. |
| `x` | whole number | — | New left position. Needs `y` too. |
| `y` | whole number | — | New top position. Needs `x` too. |
| `w` | whole number | — | New width. |
| `h` | whole number | — | New height. |
| `fit` | `W,H` | — | A box to fit into. With `src`, sets the height (see below). Overrides `h`. |
| `src` | `w,h` | — | The real size of the content. Required with `fit`. |

Anything not passed is left as it is. A position needs both `x` and `y`; one on its
own is ignored.

With `fit=W,H` and `src=w,h`, the height becomes `round(W × h ÷ w)`, but never more
than `H`. The width is not changed. If `src` is missing or zero, a warning is logged
and nothing changes.

Positions are relative to each control's parent. There is no focus guard.
