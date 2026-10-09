# Slideshow

A background slideshow for your skin. Every few seconds the service picks a random
piece of fanart from the library or from a path the user chooses. It blurs it, crops
the item's clearlogo, works out an optional darken value, and stores the results in
window properties. Your skin shows them and owns every transition.

All properties on this page are on the Home window (`10000`).

## When it runs

- The slideshow runs inside the service's [poll loop](index.md#the-poll-loop), so only
  for a skin that opts in, and not while the screensaver is active.
- The first slide is published as soon as the loop starts, including right after the
  user switches to your skin. After that, a new slide is published each time the
  interval passes.
- Whenever the active skin changes, and when the service stops, every property below
  is cleared. If the new skin opts in, its first slide follows at once.
- When the source settings change, the next slide is published at once from the new
  source.
- The slideshow pauses while `fullscreenvideo` or `visualisation` is visible.

There is no setting to turn it off. If your skin doesn't show the properties, they
have no visible effect.

## Window properties set

| Property | Value | Notes |
|---|---|---|
| `slideshow_fanart` | Path to the original fanart | Replaced by each slide. |
| `slideshow_blur` | Path to the blurred fanart (JPEG) | Replaced by each slide. |
| `slideshow_darken` | Darken percentage, `0`–`100` | Cleared when the slide has no darken value. Only set when `background_darken` is declared (see [Processing options](#processing-options)). |
| `slideshow_clearlogo` | Path to the cropped clearlogo (PNG) | Cleared when the item has no clearlogo. Uses `clearlogo-billboard` art first, then `clearlogo`. |
| `slideshow_title` | The item's label | Cleared when the item has no label. |

All five are written together for each slide. If the source returns nothing, no new
slide is published and the last slide stays.

## Skin settings read

| Name | Kind | Accepted values | Default | What it does |
|---|---|---|---|---|
| `slideshow_source` | Skin string | `global`, `videos`, `movies`, `tvshows`, `artists`, `music`, `custom` | `global` | Where the fanart comes from. |
| `slideshow_path` | Skin string | Any path Kodi can list: folder, playlist, library node, plugin | empty | Used when `slideshow_source` is `custom`. Empty means no slides. |
| `slideshow_interval` | Skin string | Whole number of seconds | `5` | Time between slides. |
| `slideshow2` | Skin setting (bool) | — | off | Turns on a second schedule with its own source. |
| `slideshow2_source` | Skin string | As `slideshow_source` | `global` | Source for the second schedule. |
| `slideshow2_path` | Skin string | As `slideshow_path` | empty | Path for the second schedule. |
| `slideshow_start` | Skin string | Hour `0`–`23`, or `HH:MM` | `6` | Hour the first schedule takes over. Only read when `slideshow2` is on. |
| `slideshow2_start` | Skin string | Hour `0`–`23`, or `HH:MM` | `20` | Hour the second schedule takes over. Only read when `slideshow2` is on. |

Only the hour of `slideshow_start` and `slideshow2_start` is used.

### Sources

| Value | Fanart from |
|---|---|
| `global` | Movies, TV shows and music artists |
| `videos` | Movies and TV shows |
| `movies` | Movies |
| `tvshows` | TV shows |
| `artists`, `music` | Music artists |
| `custom` | The path in `slideshow_path` (or `slideshow2_path`) |

Library sources skip any library that has no content. Items without fanart are
skipped. An item's fanart is picked at random from all its fanart art types, so
extra fanart (`fanart1`, `fanart2` …) is included. For `custom`, an item's `thumb`
is used when it has no fanart.

The service fetches up to 20 random items at a time and doesn't repeat a fanart until
every fetched item has been shown.

### Two schedules

With `slideshow2` on, the second schedule runs from `slideshow2_start` until
`slideshow_start`, and the first schedule runs for the rest of the day. The times can
wrap past midnight. If both hours are the same, only the first schedule runs.

## Processing options

Your skin chooses how the fanart is processed by setting the window property
`slideshow_artwork_params` on the Home window. It is a query string of `background_*`
parameters, the same ones the [artwork plugin](../plugins/artwork.md) takes. It is read
before each slide, so you can change it at any time.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `background_blur` | `true` / `false` | `true` | Blur the fanart. With `false` no slides are published, because `slideshow_blur` is the processed image. |
| `background_blur_radius` | Whole number of pixels | `50` | Blur strength. |
| `background_edge_trim` | Percent per side | `0` | Border to cut away before blurring, to drop black bars. |
| `background_darken` | `true` / `false` | `false` | Work out a darken value. |
| `background_darken_source` | ARGB hex, e.g. `fff0efef`, one per rectangle | `fff0efef` | Colour of the text that sits on the fanart. |
| `background_darken_rects` | One or more `x,y,w,h` rectangles | the whole frame | Areas where text sits. |
| `background_darken_surface` | `art` / `blur` | `art` | Which image the darken is measured on: the fanart or its blur. |
| `background_ratio` | decimal | `3` | Contrast ratio the darken aims for. |

`background_darken_frame`, `background_darken_max`, `background_darken_label`,
`background_darken_label1`, `background_darken_label2` and `background_darken_label_px`
work too, as in the [artwork plugin](../plugins/artwork.md#darken-background-and-icon).
Only the blur and the darken value are published, so `background_element_colors` and
`background_palette` have no effect here.

`background_url` is always set by the service and can't be overridden. The clearlogo
is always cropped; `clearlogo_*` parameters are ignored. `background_darken_source`
can't be `clearlogo` here: use an ARGB colour.

Example (from Copacetic, in the Home window):

```xml
<onload>SetProperty(slideshow_artwork_params,"background_blur=true&amp;background_blur_radius=20&amp;background_edge_trim=2&amp;background_darken=true",home)</onload>
```

Copacetic draws `slideshow_darken` on both the sharp fanart and its blur, so it leaves
`background_darken_surface` at `art`: the sharp image has the brighter highlights, and a
darken that carries the text there carries it on the blur too.

If the property is empty, the fanart is blurred with the default radius and no darken
value is worked out.

## Showing the slideshow

A blurred background with a crossfade between slides. The first image fills in at
once when the window opens. The second, with `background="true"` and a fade time,
handles the crossfade:

```xml
<control type="group">
  <control type="image">
    <visible>!String.IsEmpty(Window(home).Property(slideshow_blur))</visible>
    <aspectratio>scale</aspectratio>
    <texture>$INFO[Window(home).Property(slideshow_blur)]</texture>
  </control>
  <control type="image">
    <visible>!String.IsEmpty(Window(home).Property(slideshow_blur))</visible>
    <aspectratio>scale</aspectratio>
    <texture background="true">$INFO[Window(home).Property(slideshow_blur)]</texture>
    <fadetime>900</fadetime>
  </control>
</control>
```

The sharp fanart, with a clearlogo on top:

```xml
<control type="image">
  <visible>!String.IsEmpty(Window(home).Property(slideshow_fanart))</visible>
  <aspectratio>scale</aspectratio>
  <texture background="true">$INFO[Window(home).Property(slideshow_fanart)]</texture>
  <fadetime>900</fadetime>
</control>
<control type="image">
  <left>120</left>
  <top>860</top>
  <width>600</width>
  <height>160</height>
  <aspectratio aligny="bottom">keep</aspectratio>
  <texture background="true">$INFO[Window(home).Property(slideshow_clearlogo)]</texture>
  <fadetime>900</fadetime>
</control>
```

Use `slideshow_darken` to darken the image behind text, for example as the alpha of a
black overlay, or in a `$VAR[]` that picks an overlay texture by range.

A variable that prefers the slideshow fanart:

```xml
<variable name="background_fanart">
  <value condition="!String.IsEmpty(Window(home).Property(slideshow_fanart))">$INFO[Window(home).Property(slideshow_fanart)]</value>
</variable>
```
