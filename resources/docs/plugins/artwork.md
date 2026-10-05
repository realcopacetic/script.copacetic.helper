# Artwork Plugin Handler

The artwork helper prepares artwork for the focused item and returns the results on a
single list item. It can:

- **crop** a clearlogo to its visible area and report its size;
- **blur** a background image (and a second image, the icon);
- **analyse** each image's colours (dominant, accent, contrast, brightness);
- work out how much to **darken** an image so that text on top stays readable;
- collect a family of numbered artwork (`fanart`, `fanart1`, `fanart2` …) under one
  set of keys, and optionally load it into a FadeLabel for a slideshow.

Processed images and values are cached. When the source image changes, it is
processed again; otherwise the cached result returns straight away.

---

## Plugin path

```xml
<control type="list" id="9300"><!-- hidden helper container; id is an example -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=artwork&amp;target=50&amp;focus_guard=$INFO[Container(50).CurrentItem]&amp;clearlogo_url=$INFO[Container(50).ListItem.Art(clearlogo)]&amp;clearlogo_crop=true&amp;clearlogo_analyze=true&amp;background_url=$INFO[Container(50).ListItem.Art(fanart)]&amp;background_blur=true&amp;background_analyze=true</content>
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

| Image | Prefix | Processes it can run |
|---|---|---|
| Clearlogo | `clearlogo_` | crop, analyse |
| Background | `background_` | blur, analyse, darken |
| Icon | `icon_` | blur, analyse, darken |

An image is only processed when you pass its URL (`clearlogo_url`, `background_url`,
`icon_url`). With no URL at all, the call returns nothing, not even multiart. Processes are off unless
you turn them on. The images are processed in the order above, so the background and
icon can use the clearlogo's colour.

"Icon" is just a name for a second image. Use it for anything: a poster, a thumbnail,
or a second copy of the background with a lighter blur.

---

## Parameters

### Per image

Replace `<prefix>` with `clearlogo`, `background` or `icon`.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `<prefix>_url` | image path or URL | — | The image to process. Required for anything to happen to this image. |
| `<prefix>_analyze` | `true`, `false` | `false` | Analyse the image's colours. |
| `clearlogo_crop` | `true`, `false` | `false` | Crop the clearlogo to its visible (non-transparent) area. |
| `background_blur`, `icon_blur` | `true`, `false` | `false` | Blur the image. |
| `background_blur_radius`, `icon_blur_radius` | whole number | `50` | Blur strength. Applied after the image is scaled down to cover 480×270. |
| `background_edge_trim`, `icon_edge_trim` | decimal (percent) | `0` | Cut this percentage from each side before blurring. Hides black bars and dark edges. |

Booleans accept `true`, `1`, `yes` or `on` (any case). Anything else is false.

### Darken (background and icon)

Replace `<prefix>` with `background` or `icon`. See [Darken](#darken) for what the
values mean.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `<prefix>_darken` | `artwork`, `all` | off | `artwork`: work out how much to darken the image. `all`: also work out how much to darken each text element. Any other value turns darken off. |
| `<prefix>_darken_rects` | `x,y,w,h` or `(x,y,w,h),(x,y,w,h),…` | — | Where your text sits, in frame coordinates. Required: with no value, no darken value is returned. |
| `<prefix>_darken_frame` | `w,h` | `1920,1080` | Size of the frame the rectangles are measured in. The image is scaled to cover this frame and centred, like `<aspectratio>scale</aspectratio>`. |
| `<prefix>_darken_source` | ARGB or RGB hex (`fff0efef`, `#f0efef`), or `clearlogo` | `fff0efef` | Colour of the text on top. `clearlogo` uses the clearlogo's dominant colour; this needs `clearlogo_url` and `clearlogo_analyze=true` in the same call, else the default is used. A value that is not a valid colour stops all results for that image. |
| `<prefix>_darken_strength` | decimal, `0.0`–`2.0` | `1.0` | Multiplies the result. Values outside the range are clamped. |
| `<prefix>_darken_label`, `<prefix>_darken_label1`, `<prefix>_darken_label2` | any text | — | The text in the first, second and third rectangle. Each rectangle is narrowed to the text's estimated width (left edge kept). |
| `<prefix>_darken_label_px` | decimal | `14` | Estimated width of one character, in frame pixels, for the labels above. |

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
| `visit` | any text | — | A value that changes once per focus change. See the same section. |
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
| `<prefix>_color` | `<prefix>_analyze=true` | Dominant colour, as ARGB hex (`ffrrggbb`). Near-white and near-black are skipped unless they cover more than 70% of the image. |
| `<prefix>_accent` | `<prefix>_analyze=true` | A second colour, different enough from the dominant one. |
| `<prefix>_contrast` | `<prefix>_analyze=true` | The dominant colour made lighter (if dark) or darker (if light). |
| `<prefix>_luminosity` | `<prefix>_analyze=true` | Brightness of the dominant colour, `0`–`1000`. |
| `<prefix>_darken` | `<prefix>_darken=artwork` or `all` | How much to darken the image, `0`–`100`. |
| `<prefix>_darken_element`, `…_element1`, `…_element2` | `<prefix>_darken=all` | How much to darken the text in the first, second and third rectangle, `0`–`100`, or `-1` when the area behind it is too busy to judge. |
| `<prefix>_darken_element_mean`, `…_mean1`, `…_mean2` | `<prefix>_darken=all` | Average brightness behind each rectangle, `0`–`100`, not affected by strength. |
| `<prefix>_darken_label_width`, `…_width1`, `…_width2` | a matching `_darken_label` is passed | The estimated text width used for that rectangle. |
| `multiart`, `multiart1`, `multiart2` … | `multiart` is passed | The collected family, numbered without gaps. |

The list item also carries some properties; see
[Is this result for the focused item?](#is-this-result-for-the-focused-item).

## Window properties

The helper also sets these on the home window. With `prop_key`, each name ends in
`_<prop_key>` (for example `background_blur_9300`).

| Property | Value |
|---|---|
| `background_blur` | Path of the blurred background. Only set when there is one; the last value is kept otherwise. |
| `background_darken` | The background darken value. Cleared when there is none or it is `0`. |
| `icon_darken` | The icon darken value. Cleared when there is none or it is `0`. |

Use them when something outside the helper container's window needs the values, or
to keep the last background on screen while the next one is processed.

---

## Darken

Darken tells you how much to dim an image so light text on it stays readable. It
measures the image itself; nothing is changed in the image. You apply the value in
the skin, for example with a `fadediffuse` animation or a semi-transparent black
image.

The image is scaled to cover the frame (`_darken_frame`) and centred. Your rectangles
are then measured on it.

- **`<prefix>_darken`** — the brightest of your rectangles decides. Its brightness is
  mapped to `0`–`100` and multiplied by the strength. If the text colour is itself dark
  (luminance below 0.2), the value is `0`: dark text does not need a darker
  background.
- **`<prefix>_darken_element*`** (`all` only) — each of the first three rectangles is
  judged on its own, as if your text needs a backing behind it. Areas darker than
  luminance 0.18 return `0`. Busy areas (lots of detail) return `-1`.

```xml
<include name="DarkenBackground">
  <animation effect="fadediffuse" end="ffbcbcbc" time="300" condition="Integer.IsGreaterOrEqual(Container(9300).ListItem.Art(background_darken),30) + Integer.IsLess(Container(9300).ListItem.Art(background_darken),60)">Conditional</animation>
  <animation effect="fadediffuse" end="ff939393" time="300" condition="Integer.IsGreaterOrEqual(Container(9300).ListItem.Art(background_darken),60)">Conditional</animation>
</include>
```

```xml
<content>plugin://script.copacetic.helper/?info=artwork&amp;target=50&amp;background_url=$INFO[Container(50).ListItem.Art(fanart)]&amp;background_blur=true&amp;background_darken=artwork&amp;background_darken_source=fff0efef&amp;background_darken_rects=(120,660,960,300),(1710,960,90,60)&amp;background_darken_strength=0.8</content>
```

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
- Refiring for the same item with the same images leaves a running FadeLabel alone.
  A new item always starts again from its main image.

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
segment of `Window(home).Property(artwork_cursor_<cursor_key>)`.

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

Set `visit` from a window property that changes once per focus change, like
`artwork_visit` in the example. Do not put a live clock straight into the path: the
path would change all the time and the helper would keep firing.

---

## Skin contract

The helper reads these when you use the matching parameters:

| What | Used with | Set by |
|---|---|---|
| `Window(home).Property(artwork_cursor_<cursor_key>)` | `cursor_key` | The skin, at focus time. The helper may also write it (see above). |
| A FadeLabel control with id `multiart_fadelabel` in the current window | `multiart_fadelabel` | The skin. |
| A window property that changes once per focus change, passed as `visit` | `visit` | The skin. |
