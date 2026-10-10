# Artwork Plugin Handler

The artwork helper prepares artwork for the focused item and returns the results on a
single list item. It can:

- **crop** a clearlogo to its visible area and report its size;
- **blur** a background image (and a second image, the icon);
- work out how much to **darken** an image so that text on top stays readable;
- make an **element on art** readable (a label over a poster): pick its colour, and
  say whether it needs a band of blur behind it, or a tinted band;
- return a **palette** in the art's own colours, at a fixed light level;
- collect a family of numbered artwork (`fanart`, `fanart1`, `fanart2` …) under one
  set of keys, and optionally load it into a FadeLabel for a slideshow.

The helper works in two passes. **Prepare** crops, blurs and measures each image (its
colours, and how dark and bright it is where your elements sit); this is cached, and
when the source image changes it is processed again. **Compose** then works out the
darken, the element colour and band, and the palette from those measurements, once per
call and never cached, so changing a compose parameter (the ratio, the colours, the
surface) costs nothing.

---

## Plugin path

```xml
<control type="list" id="9300"><!-- hidden helper container; id is an example -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=artwork&amp;target=50&amp;focus_guard=$INFO[Container(50).CurrentItem]&amp;clearlogo_url=$INFO[Container(50).ListItem.Art(clearlogo)]&amp;clearlogo_crop=true&amp;background_url=$INFO[Container(50).ListItem.Art(fanart)]&amp;background_blur=true</content>
</control>

<control type="image">
  <texture>$INFO[Container(9300).ListItem.Art(clearlogo)]</texture>
</control>
<control type="image">
  <texture background="true">$INFO[Container(9300).ListItem.Art(background)]</texture>
</control>
```

## The three images

The helper works on up to three images in one call. Each has its own parameters,
named after it:

| Image | Prefix | What it can do |
|---|---|---|
| Clearlogo | `clearlogo_` | crop; its colour is always measured, for `clearlogo` sources and the palette |
| Background | `background_` | blur, darken, element on art, palette |
| Icon | `icon_` | blur, darken, element on art, palette |

An image is only processed when you pass its URL (`clearlogo_url`, `background_url`,
`icon_url`). With no URL at all, the call returns nothing, not even multiart (with
`target=item` it returns one empty list item, so you can tell it has run). Processes are off unless
you turn them on. Compose runs once every image is prepared, so the background and
icon can use the clearlogo's colour whatever order they come in.

If the background can't be read (a dead remote URL), the helper tries once more with
the item's own fanart, when that is a different image. That is its `fanart`, else its
`tvshow.fanart`, else its `artist.fanart`, else its `thumb`. An item with a `thumb`
whose `fanart` is missing or is the same as its `tvshow.fanart` (most episodes) uses
its `thumb`. The icon has no such second try.

"Icon" is just a name for a second image. Use it for anything: a poster, a thumbnail,
or a second copy of the background with a lighter blur.

---

## Parameters

### Per image

Replace `<prefix>` with `clearlogo`, `background` or `icon`.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `<prefix>_url` | image path or URL | — | The image to process. Required for anything to happen to this image. |
| `clearlogo_crop` | `true`, `false` | `false` | Crop the clearlogo to its visible (non-transparent) area. |
| `background_blur`, `icon_blur` | `true`, `false` | `false` | Blur the image. |
| `background_blur_radius`, `icon_blur_radius` | whole number | `50` | Blur strength. Applied after the image is scaled to cover 480×270, or, when `<prefix>_darken_frame` is passed, scaled to cover that frame and cropped to it (centred). |
| `background_edge_trim`, `icon_edge_trim` | decimal (percent) | `0` | Cut this percentage from each side before blurring. Hides black bars and dark edges. |
| `background_ratio`, `icon_ratio` | decimal | `3` | Contrast ratio the darken, the element on art and the palette aim for (WCAG: 3 for large text and graphics, 4.5 for body text). |

Booleans accept `true`, `1`, `yes` or `on` (any case). Anything else is false.
Transparent art is composited on `ff121217` (Copacetic's `squidink`) before it is
blurred or measured.

A blurred image is cached by its source and radius only. Changing `_edge_trim` or
`_darken_frame` later does not replace a blur that is already cached.

### Darken (background and icon)

Replace `<prefix>` with `background` or `icon`. See [Darken](#darken) for what the
values mean.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `<prefix>_darken` | `true`, `false` | `false` | Work out how much to darken the image. |
| `<prefix>_darken_rects` | `x,y,w,h` or `(x,y,w,h),(x,y,w,h),…` | the whole frame | Where your elements sit, in frame coordinates. The element on art and the palette are measured here too. |
| `<prefix>_darken_frame` | `w,h` | `1920,1080` | Size of the frame the rectangles are measured in: the image is scaled to cover it and centred, like `<aspectratio>scale</aspectratio>`. |
| `<prefix>_darken_source` | ARGB or RGB hex (`fff0efef`, `#f0efef`), or `clearlogo`; comma-separated, one per rectangle | `fff0efef` | Colour of the element in each rectangle, in rectangle order; the last carries on for the rest. `clearlogo` uses the clearlogo's colour (it needs `clearlogo_url` in the same call, else the default is used). |
| `<prefix>_darken_surface` | `art`, `blur` | `art` | The image you draw the darken over: the image itself or its blur. The helper measures that one. |
| `<prefix>_darken_max` | whole number, `0`–`100` | none | A cap on the darken. Bright art may then fall short of the ratio. |
| `<prefix>_darken_label`, `<prefix>_darken_label1`, `<prefix>_darken_label2` | any text | — | The text in the first, second and third rectangle. Each rectangle is narrowed to the text's estimated width (left edge kept). |
| `<prefix>_darken_label_px` | decimal | `14` | Estimated width of one character, in frame pixels, for the labels above. |

### Element on art and palette (background and icon)

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `<prefix>_element_colors` | ARGB or RGB hex, comma-separated, e.g. `fff0efef,ff312124` | none | Candidate colours for an element drawn on the image (a label). Turns on [Element on art](#element-on-art). |
| `<prefix>_palette` | `true`, `false` | `false` | Return the image's [palette](#palette). |

The rectangles, frame and labels in the darken table set where these are measured;
`<prefix>_darken` itself need not be on.

### Multiart

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `multiart` | an art type, e.g. `fanart`, `poster`, `keyart`, `tvshow.fanart` | — | The family to collect. |
| `multiart_max` | whole number, `0`–`50` | `15` | Highest number to look for (`fanart1` … `fanart15`). |
| `get_extra_multiart` | `true`, `false` | `false` | Add TMDb artwork of the same type, after the library artwork. See [Multiart](#multiart). |
| `language` | TMDb language, e.g. `en-US` | add-on setting | Language of the TMDb artwork to add. |
| `type`, `id`, `tmdb_id`, `tvshowid` | | | With `get_extra_multiart`: how the TMDb item is found. See [TMDb lookups](metadata.md#tmdb-lookups). |
| `multiart_fadelabel` | control id | — | A FadeLabel to fill with the family, in display order. See [Multiart in a FadeLabel](#multiart-in-a-fadelabel). |

### Other

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `target` | container id, or `item` | — | Container whose focused item this call is for; `item` is the window's own item (an info dialog's). See [Plugin Helpers](plugin_helpers.md#the-focus-guard). |
| `prop_key` | any text | — | Suffix for the window properties the helper sets (see [Window properties](#window-properties)). |
| `cursor_key` | any text | — | Name of the window property that marks the focused item (`artwork_cursor_<cursor_key>`). See [Is this result for the focused item?](#is-this-result-for-the-focused-item). |
| `visit` | any text | — | A value that changes once per focus change. See the same section. A new value also refills the multiart FadeLabel. If passed and not equal to `Window(home).Property(artwork_visit)`, the call does nothing: a superseded or replayed path, as the live one fires anyway. |
| `focus_guard`, `focus_ids`, `identity_labels`, `identity_container` | | | Focus guard. See [Plugin Helpers](plugin_helpers.md#3-guarding-against-fast-scrolls-and-container-moves). |

---

## What you get back

All values are on the helper container's list item, as `ListItem.Art(...)`.

| Art key | When | Value |
|---|---|---|
| `clearlogo` | `clearlogo_crop=true` | Path to the cropped PNG. |
| `clearlogo_width`, `clearlogo_height` | `clearlogo_crop=true` | Size of the cropped logo in pixels. The logo is first scaled down to fit 1600×620. |
| `background`, `icon` | `<prefix>_blur=true` | Path to the blurred JPEG. |
| `background_blur_radius`, `icon_blur_radius` | `<prefix>_blur=true` | The radius used. |
| `<prefix>_darken` | `<prefix>_darken=true` | How much to darken the image: the exact % black, `0`–`100`. |
| `<prefix>_darken_label_width`, `…_width1`, `…_width2` | a matching `_darken_label` is passed | The estimated text width used for that rectangle. |
| `<prefix>_element_color` | `<prefix>_element_colors` is passed | The candidate colour to draw the element in. |
| `<prefix>_band` | `<prefix>_element_colors` is passed, the image is blurred and a band is needed | Image to draw behind the element: the blur itself, or a copy of it with the clashing pixels tinted. Empty when no band is needed. |
| `<prefix>_palette_primary` | `<prefix>_palette=true` | The palette's main colour. |
| `<prefix>_palette_secondary` | `<prefix>_palette=true`, and the image has a colour | A lighter, softer colour of the same hue. Empty for a neutral image. |
| `<prefix>_palette_darken` | `<prefix>_palette=true` | The % black the darken surface needs for `_palette_primary` to read at the ratio. |
| `<prefix>_palette_logo` | `<prefix>_palette=true`, and the clearlogo has a colour | The clearlogo's hue at the palette's light level. |
| `<prefix>_palette_logo_darken` | as `_palette_logo` | The % black the darken surface needs for `_palette_logo` to read at the ratio. |
| `multiart`, `multiart1`, `multiart2` … | `multiart` is passed | The collected family, numbered without gaps. |

The list item also carries some properties; see
[Is this result for the focused item?](#is-this-result-for-the-focused-item).

## Window properties

The helper also sets these on the home window. With `prop_key`, each name ends in
`_<prop_key>` (for example `background_blur_9300`).

| Property | Value |
|---|---|
| `background_blur` | Path of the blurred background. Only set when there is one; the last value is kept otherwise. |
| `background_darken` | The background darken value, % black. Cleared when there is none or it is `0`. |
| `icon_darken` | The icon darken value, % black. Cleared when there is none or it is `0`. |

Use them when something outside the helper container's window needs the values, or
to keep the last background on screen while the next one is processed.

---

## Darken

Darken tells you how much to dim an image so the elements on it stay readable. It
measures the image; nothing in the image changes. Apply the value in the skin with a
`fadediffuse` animation.

In each rectangle the helper measures the darkest and brightest 10 % of the surface you
darken (`_darken_surface`). For each rectangle it works out the least black that brings
that rectangle's element colour (`_darken_source`) to the ratio (`_ratio`) against its
brightest part. The largest is `<prefix>_darken`, as one value has to carry every
rectangle. An element too dark for any floor to carry (relative luminance below
`0.05 × (ratio − 1)`, `0.1` at 3:1) asks for nothing.

The value is the exact % black for a `fadediffuse` to the grey `255 × (1 − %/100)`.
`fadediffuse` multiplies the encoded colour, so keeping `k` of the grey keeps about
`k^2.2` of the light: pure white art under `fff0efef` needs 47 % at 3:1. Map it to a
ladder of fixed greys in the skin, each row taking the grey of its darker end, so the
ratio still holds:

```xml
<include name="DarkenBackground">
  <animation effect="fadediffuse" end="ffd9d9d9" time="300" condition="Integer.IsGreater(Container(9300).ListItem.Art(background_darken),10) + Integer.IsLessOrEqual(Container(9300).ListItem.Art(background_darken),15)">Conditional</animation>
  <animation effect="fadediffuse" end="ffcccccc" time="300" condition="Integer.IsGreater(Container(9300).ListItem.Art(background_darken),15) + Integer.IsLessOrEqual(Container(9300).ListItem.Art(background_darken),20)">Conditional</animation>
  <!-- … one row per 5 % … -->
</include>
```

```xml
<content>plugin://script.copacetic.helper/?info=artwork&amp;target=50&amp;background_url=$INFO[Container(50).ListItem.Art(fanart)]&amp;background_blur=true&amp;background_darken=true&amp;background_darken_surface=blur&amp;background_darken_rects=(120,660,960,300),(1710,960,90,60)</content>
```

## Element on art

For an element drawn straight on the image (a label over a poster), pass its candidate
colours in `<prefix>_element_colors`. Each candidate is scored against both ends of each
rectangle (its worst ratio), and the first step that works wins:

1. **Nothing.** A candidate reads on the image and the area isn't busy (its own darkest
   and brightest parts are less than the ratio apart). `_band` is empty.
2. **Blur band.** The area is busy, or no candidate reads on the image but one reads on
   its blur. `_band` is the blur, which removes the detail behind the letters.
3. **Tinted band.** No candidate reads on the blur either. For each candidate the helper
   works out how far each pixel of the blur must move toward a colour from the image's
   own band area (its darkest under light text, its lightest under dark text) to read;
   the candidate that changes the area least wins, decided from the area's brightness
   histogram before any image is made. `_band` is a copy of the blur with only the
   clashing pixels moved: full strength inside the rectangles, fading out around them.
   Draw it through your own band mask.

`_element_color` is the winning candidate. The band copy is a file of its own beside
the blur, so the image control sees a new path; it is cached with the blur and replaced
when the ratio or the candidates change.

## Palette

`<prefix>_palette=true` returns colours in the image's own hue at a fixed relative
luminance (`0.45`), so they keep their colour on any art: the accent when it has colour
(HLS chroma at least `0.15`), else the dominant colour. With neither, the image is
neutral: `_palette_primary` is `fff0efef`, `_palette_secondary` is empty and
`_palette_darken` is the image's darken. `_palette_logo` is the clearlogo's hue at the
same level, empty when the logo is white, grey or black.

Each colour comes with the % black it needs (`_palette_darken`, `_palette_logo_darken`).
Compare them in the skin with the darken you apply, for example to colour an element in
the logo's hue only when `Integer.IsLessOrEqual(…palette_logo_darken,…background_darken)`.

---

## Multiart

Kodi stores extra artwork as numbered keys: `fanart`, `fanart1`, `fanart2` …
Multiart reads `Art(<type>)` and `Art(<type>1)` to `Art(<type><multiart_max>)` from
the focused item, skips the empty ones, and returns them as `multiart`, `multiart1`,
`multiart2` … with no gaps.

Because the keys are always the same, your layouts can read `multiart*` and switch
the family with one variable:

```xml
<variable name="MultiartType">
  <value condition="!String.IsEmpty(Container(50).ListItem.Art(keyart1))">keyart</value>
  <value condition="!String.IsEmpty(Container(50).ListItem.Art(poster1))">poster</value>
  <value>fanart</value>
</variable>
```

```xml
<content>plugin://script.copacetic.helper/?info=artwork&amp;target=50&amp;focus_guard=$INFO[Container(50).CurrentItem]&amp;background_url=$INFO[Container(50).ListItem.Art(fanart)]&amp;background_blur=true&amp;multiart=$VAR[MultiartType]&amp;multiart_max=15</content>
```

With `get_extra_multiart=true`, TMDb artwork of the same type is added after the
library artwork:

- Only when the item has its own image of that type, so the first image is always the
  item's.
- Without duplicates: a TMDb image already in the library artwork in another size is
  skipped.
- Backdrops (`fanart`, `landscape`) at width 1280 and posters (`poster`, `keyart`) at
  width 780, not TMDb's original size, as each new image downloads the first time it
  shows.
- From the TMDb cache only, which [`metadata`](metadata.md#metadata) with
  `tmdb_art=true` or [`tmdb_details`](metadata.md#tmdb_details) with `multiart=true`
  fills for the same item and language. An item not cached yet gets its library
  artwork only.
- For movies and TV shows with a TMDb id. Episodes use their show's artwork.
- A `tvshow.` type adds TMDb artwork of the plain type: `tvshow.fanart` adds TMDb
  `fanart`.

### Multiart in a FadeLabel

Pass `multiart_fadelabel=<id>` to load the family into a FadeLabel. Each label is an
image path. Read the label that is showing with `Control.GetLabel(<id>)` and use it
as an image texture to get a slideshow.

- The main image comes first. The rest are shuffled.
- The returned `multiart*` keys stay in library order (library artwork, then TMDb
  artwork). Only the FadeLabel is shuffled.
- A family with fewer than two images is not loaded. The FadeLabel is emptied and no
  `multiart*` keys are returned.
- Refiring for the same item, the same `visit` and the same images leaves a running
  FadeLabel alone. A new item, or a new `visit`, always starts again from its main
  image.

The FadeLabel must be in the current window. The helper also uses these home window
properties, with `<id>` the FadeLabel id:

| Property | What it holds |
|---|---|
| `multiart_frozen_<id>` | The image that was showing when the FadeLabel was refilled, so you can keep it on screen during the change. Cleared when the new item is from a different container or folder. |
| `multiart_seed_scope_<id>` | Which container and folder the FadeLabel was last filled for. |
| `multiart_seed_sig_<id>` | Which item and image set it was last filled with. |

The focus guard is checked just before the FadeLabel is filled. A call for an item
that is no longer focused never refills it.

---

## `multiart_tiles`

Fills several FadeLabels in an info dialog, one per art type, with the dialog item's
artwork. The FadeLabels take turns: only one changes at a time, in the order you list
them, and each starts on the item's main image. Use it for a grid of artwork tiles
that should not all change at once.

```xml
<control type="list" id="9401"><!-- hidden helper container; ids are examples -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=multiart_tiles&amp;tiles=3402:poster,3403:fanart,3404:keyart&amp;multiart_max=15&amp;visit=$INFO[Window(home).Property(infoscreen_gallery_visit)]</content>
</control>
```

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `tiles` | `<id>:<art type>,<id>:<art type>,…` | — | **Required.** Each FadeLabel id and the art family it shows, as for `multiart` above (`fanart`, `poster`, `keyart` …). |
| `multiart_max` | whole number, `0`–`50` | `15` | Highest number to look for in each family. |
| `visit` | any text | — | Must equal `Window(home).Property(infoscreen_gallery_visit)` (see below). |

- The artwork is read from the window's own item (`ListItem.Art(...)`), the item an
  info dialog shows. There is no `target`.
- The FadeLabels must be in the topmost dialog, or in the current window when no dialog
  is open. Give them all the same scroll speed and delay.
- Library artwork only; no TMDb artwork is added. The main image comes first and the
  rest are shuffled.
- An image is shown in one FadeLabel only. When several art types hold the same image
  (the same URL, or the same TMDb file in another size), the FadeLabels take turns
  claiming their shuffled images, and the others leave it out. Main images always stay,
  so two FadeLabels can start on the same image.
- With `k` FadeLabels that have more than one image, each image stays for `k` steps,
  and the FadeLabels change one after another. A FadeLabel with one image stays still.
- A FadeLabel whose art type the item does not have is left as it is.
- After the main images are set, the helper compares `visit` with
  `Window(home).Property(infoscreen_gallery_visit)`. If they differ, the other images
  are not added and nothing is returned. Leave out `visit` and that property, or set
  both to the same value.

When it is done, the path returns one list item with
`ListItem.Property(visit)` set to `visit`. Compare it with the property to tell that
the FadeLabels are filled for this visit.

There is no focus guard.

---

## Is this result for the focused item?

A plugin call can take a moment. While it runs, focus may move on, and the old result
stays on screen until the new one arrives. These list item properties tell you which
item a result is for, so you can hide results that are out of date.

When the container position is known, the list item carries:

| Property | Value |
|---|---|
| `current` | Which item this result is for (see below). |
| `current_pos` | The container position (`CurrentItem`) this result is for. |
| `previous`, `next` | `<container>/<position>` of the items either side. Positions wrap around when the container has more than one item. |
| `previous_pos`, `next_pos` | The positions either side, on their own. |

The container is `target` when passed. Without `target`, it is the first `/`
segment of `Window(home).Property(artwork_cursor_<cursor_key>)`, or the id of the
focused control when that property is empty. With `target=item` there is no position,
so none of these properties are set.

### The value of `current`

It uses one format: `<container>/<position>/<dbid>/<visit>`. The container part is
left out when empty. Other parts keep their `/` even when empty.

1. **With `cursor_key` and `visit`**: the helper builds `<container>/<position>/<dbid>/<visit>`
   from the item it ran for, and `current` is that value. If
   `Window(home).Property(artwork_cursor_<cursor_key>)` held a different value when
   the call started, has not changed during the call, and the focus guard still
   passes, the helper also writes the value into that property.
2. **With `cursor_key` but no `visit`**: `current` is the property's value, or
   `<container>/<position>/<dbid>` when the property is empty.
3. **With no `cursor_key`**: `current` is `<container>/<position>/<dbid>`.

To hide out-of-date results, write the same format into the property from the skin,
at the moment focus changes (for example in an `<onfocus>`), and compare:

```xml
<onfocus>SetProperty(artwork_cursor_main,50/$INFO[Container(50).CurrentItem]/$INFO[Container(50).ListItem.DBID]/$INFO[Window(home).Property(artwork_visit)],home)</onfocus>
```

```xml
<expression name="ArtworkIsCurrent">String.IsEqual(Container(9300).ListItem.Property(current),Window(home).Property(artwork_cursor_main))</expression>
```

Writing the property at focus time matters. It is what makes the old result
out of date at once, while the new call is still running. If the skin writes a value
in a different format, the helper replaces it with its own whenever `visit` is
passed.

Set `visit` from `Window(home).Property(artwork_visit)`, and have the skin change
that property once per focus change. The helper compares the two: a call whose
`visit` is not the property's current value does nothing, so another property here
would stop every call. Do not put a live clock straight into the path: the path would
change all the time and the helper would keep firing.

---

## Skin contract

The helper reads these when you use the matching parameters:

| What | Used with | Set by |
|---|---|---|
| `Window(home).Property(artwork_cursor_<cursor_key>)` | `cursor_key` | The skin, at focus time. The helper may also write it (see above). |
| A FadeLabel control with id `multiart_fadelabel` in the current window | `multiart_fadelabel` | The skin. |
| `Window(home).Property(artwork_visit)`, changed once per focus change and passed as `visit` | `visit` | The skin. |
| `Window(home).Property(infoscreen_gallery_visit)` | `multiart_tiles` with `visit` | The skin, once each time the dialog shows the artwork. |
| FadeLabel controls with the ids in `tiles`, in the topmost dialog | `multiart_tiles` | The skin. |
