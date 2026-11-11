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
- When `slideshow_artwork_params` changes, the current slide's darken is published
  again at once (see [Processing options](#processing-options)).
- The slideshow pauses while `fullscreenvideo` or `visualisation` is visible.

There is no setting to turn it off. If your skin doesn't show the properties, they
have no visible effect.

## Window properties set

| Property | Value | Notes |
|---|---|---|
| `slideshow_fanart` | Path to the original fanart; a typed wrapper (`image://music@…/`, `image://video_…@…/`) stays wrapped | Replaced by each slide. |
| `slideshow_blur` | Path to the blurred fanart (JPEG) | Replaced by each slide. |
| `slideshow_darken` | Darken percentage, `0`–`100` | Cleared when the slide has no darken value. Written again on its own when `slideshow_artwork_params` changes. Only set when `slideshow_artwork_params` has `background_darken=true` (see [Processing options](#processing-options)). |
| `slideshow_clearlogo` | Path to the cropped clearlogo (PNG) | Cleared when the item has no `clearlogo` art. |
| `slideshow_title` | The item's label | Cleared when the item has no label. |
| `slideshow_clearlogo_a`, `slideshow_clearlogo_b` | As `slideshow_clearlogo`, in alternating slots | Each slide writes one slot and leaves the other holding the slide before. |
| `slideshow_title_a`, `slideshow_title_b` | As `slideshow_title`, in alternating slots | As above. |
| `slideshow_slot` | `a` or `b`: the slot the current slide wrote | Written last, after the slot. |

All of them are written together for each slide. If the source returns nothing, no new
slide is published and the last slide stays.

If a slide fails (its fanart can't be opened, or the blur gives nothing), nothing is
published for it and the service tries another fetched item a second later, one item a
second, instead of waiting for the interval. When the last fetched item fails, it waits
for the interval before it fetches again, so a source whose items all fail is tried at
most 20 items per interval. A slide that took a second or more to fail waits a whole
interval from when it failed: a network share that doesn't answer holds each try for
Kodi's network timeout (30 seconds by default), and the service does nothing else
meanwhile. The interval also counts from when a fetch of new items ends, so a slow
fetch doesn't shorten the slide, and a fetch that finds nothing is tried again an
interval after it, not at once.

The slots are for a skin that animates the logo out and the next one in: a property a
skin reads can't keep its old value, so the outgoing logo needs its own. Show each
slot while `slideshow_slot` names it, and its `Visible` and `Hidden` animations play
on every slide, with no other trigger (see [Showing the slideshow](#showing-the-slideshow)).

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
extra fanart (`fanart1`, `fanart2` …) and a parent show's or artist's fanart are
included. A movie's set fanart (`set.fanart`) is not. For `custom`, an item's `thumb`
is used when it has no fanart, and a picture file with no art at all, such as one in a
plain folder of pictures, is shown itself. A picture file is one whose name ends in one
of Kodi's picture extensions, less its archive and feed types: `.png`, `.jpg`, `.jpeg`,
`.bmp`, `.gif`, `.ico`, `.tif`, `.tiff`, `.tga`, `.pcx`, `.webp`, `.jp2`, `.apng`,
`.avif`. Pictures in subfolders aren't included.

The service fetches up to 20 random items at a time and doesn't repeat a fanart until
every fetched item has been shown. For a `custom` folder or plugin, it lists 200 random
entries of the path and picks 20 of those that have art, so a folder that also holds
videos, subfolders or other files still fills a batch. A library path (`videodb://`,
`musicdb://`, `library://` or a `.xsp` smart playlist) lists 20, as Kodi looks up each
listed item's art in the library.

### Two schedules

With `slideshow2` on, the second schedule runs from `slideshow2_start` until
`slideshow_start`, and the first schedule runs for the rest of the day. The times can
wrap past midnight. If both hours are the same, only the first schedule runs.

## Processing options

Your skin chooses how the fanart is processed by setting the window property
`slideshow_artwork_params` on the Home window. It is a query string of `background_*`
parameters, the same ones the [artwork plugin](../plugins/artwork.md) takes. It is read
before each slide, so you can change it at any time.

The service also checks it every second. When it has changed, the current slide's
`slideshow_darken` is worked out again by the new params and written on its own,
without waiting for the interval. The fanart, blur, clearlogo, title and
`slideshow_slot` stay as they are, so a slot's animations don't play. Copacetic uses
this to measure for its menu while the menu shows and for the slide's clearlogo in
its idle mode.

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `background_blur` | `true` / `false` | `true` | Blur the fanart. With `false` no slides are published, because `slideshow_blur` is the processed image. |
| `background_blur_radius` | Whole number of pixels | `50` | Blur strength, in pixels of a 480×270 cover (see the artwork plugin). |
| `background_edge_trim` | Percent per side | `0` | Border to cut away before blurring, to drop black bars. |
| `background_darken` | `true` / `false` | `false` | Work out a darken value. |
| `background_darken_source` | ARGB hex, e.g. `fff0efef`, or `clearlogo`, one per rectangle | `fff0efef` | Colour of the text that sits on the fanart. |
| `background_darken_rects` | One or more `x,y,w,h` rectangles | the whole frame | Areas where text sits. |
| `background_darken_surface` | `art` / `blur` | `art` | Which image the darken is measured on: the fanart or its blur. |
| `background_ratio` | decimal | `3` | Contrast ratio the darken aims for. |

`background_darken_frame`, `background_darken_max`, `background_darken_label`,
`background_darken_label_font` and `background_darken_label_pitch` work too, as in the
[artwork plugin](../plugins/artwork.md#darken-background-and-icon).
Only the blur and the darken value are published, so `background_element_colors` and
`background_palette` have no effect here.

`background_url` is always set by the service and can't be overridden. The clearlogo
is always cropped and measured; `clearlogo_*` parameters are ignored. A
`background_darken_source` of `clearlogo` uses the colour of the slide's clearlogo;
when the slide has none, that rectangle uses `fff0efef` at `background_ratio`.

Example (from Copacetic, in the Home window):

```xml
<onload>SetProperty(slideshow_artwork_params,"background_blur=true&amp;background_blur_radius=20&amp;background_edge_trim=2&amp;background_darken=true&amp;background_darken_rects=0,480,1920,120&amp;background_ratio=5",home)</onload>
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

A clearlogo that animates out as the next one comes in, one group per slot (the
other slot is the same with `b`):

```xml
<control type="group">
  <visible>String.IsEqual(Window(home).Property(slideshow_slot),a)</visible>
  <animation effect="fade" end="0" time="300">Hidden</animation>
  <animation type="Visible">
    <effect type="fade" start="0" end="100" time="600" delay="300" />
    <effect type="slide" start="0,-10" end="0,0" time="225" delay="375" />
  </animation>
  <left>120</left>
  <top>860</top>
  <control type="image">
    <width>600</width>
    <height>160</height>
    <aspectratio aligny="bottom">keep</aspectratio>
    <texture>$INFO[Window(home).Property(slideshow_clearlogo_a)]</texture>
  </control>
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
