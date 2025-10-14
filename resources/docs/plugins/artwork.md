# Artwork Plugin Handler

The artwork helper processes **clearlogos** and **fanart**, extracts a colour set (dominant, accent, contrast, luminosity), computes an optional **darken** value for overlays, and supports **multiart** families (e.g., `fanart1…fanartN`). Results are returned via **ListItem infolabels** and cached.

- **Caching & DB:** processed paths and static analysis values are saved in a lightweight DB saved in the userdata folder. If the source art changes, the hash changes and the item is **reprocessed**; otherwise values are loaded from DB and files from cache (fast path). Runtime-only values like `fanart_darken` are computed on demand.

---

## Example plugin calls

```xml
<content>plugin://script.copacetic.helper/?info=artwork&amp;logo_crop=true&amp;multiart=fanart&amp;multiart_max=10</content>
```
This will crop the artwork at path `Container.ListItem.Art(clearlogo)` and expose multiart slots for the `fanart` family starting at `Container.ListItem.Art(fanart).

```xml
<content>plugin://script.copacetic.helper/?info=artwork&amp;target=3100&amp;bg_blur=true&amp;multiart=fanart&amp;multiart_max=10&amp;overlay_enable=true&amp;overlay_source=ffd1cece&amp;overlay_rect=120,660,1680,360</content>
```
This will blur the fanart for the Container with id matching `target` (`Container(3100).ListItem.Art(fanart)`), and compute a darken value for the provided overlay rectangle of the fanart to ensure readability against the provided ARGB hex code.

## Plugin path parameters

> Pass these as query params on the plugin path.

| Param | Type | Allowed / Range | Description | Default |
|---|---:|---|---|---|
| `info` | str | `artwork` | Selects this helper. |  |
| `logo_crop` | bool | `true` / `false` | Crop clearlogo to tight bounds and export as PNG. |  |
| `bg_blur` | bool | `true` / `false` | Blur fanart and export as JPEG. |  |
| `multiart` | str | e.g. `fanart`, `poster`, `keyart`, `tvshow.poster`, `square` | Returns `multiart`, `multiart1..N` for that art family. |  |
| `multiart_max` | int | 1–50, defaults to 15 | Max number of multiart slots to expose. |  |
| `overlay_enable` | bool | `true` / `false` | Enable darken/contrast analysis in a rectangle on the blurred fanart. |  |
| `overlay_source` | str | `clearlogo` **or** ARGB hex (e.g. `ffabcdef`) | Text/foreground colour to check contrast against. |  |
| `overlay_rect` | str | `x,y,w,h` (ints ≥ 0) | Rectangle (pixels) for readability analysis. |  |
| `overlay_target` | float | 3.0–7.0 | Target contrast ratio (WCAG-style; 4.5 typical for normal text). |  |
| `target` | int | Kodi control id | Bind helper to a specific container (pairs with `focus_guard`). |  |
| `focus_guard` | str | any | Early-abort if focus moved (usually `Container(id).CurrentItem`). |  |

> **Important:** To compute `fanart_darken` with `overlay_source=clearlogo`, include **both** `logo_crop=true` and `bg_blur=true` in the same call so the helper can analyse the fresh clearlogo colour *and* the blurred fanart in the overlay rectangle.

---

## Returns (ListItem.Art)

- `ListItem.Art(clearlogo)` → path to cropped clearlogo (PNG)
- `ListItem.Art(clearlogo_color)` → dominant logo colour (ARGB hex)
- `ListItem.Art(clearlogo_accent)` → accent logo colour (ARGB hex)
- `ListItem.Art(clearlogo_contrast)` → contrasting logo colour (ARGB hex)
- `ListItem.Art(clearlogo_luminosity)` → logo brightness (0–1000)

- `ListItem.Art(fanart)` → path to blurred fanart (JPEG)
- `ListItem.Art(fanart_color)` → dominant fanart colour (ARGB hex)
- `ListItem.Art(fanart_accent)` → accent fanart colour (ARGB hex)
- `ListItem.Art(fanart_contrast)` → contrasting fanart colour (ARGB hex)
- `ListItem.Art(fanart_luminosity)` → fanart brightness (0–1000)
- `ListItem.Art(fanart_darken)` → darken percent (0–85), when overlay analysis is enabled

- `ListItem.Art(multiart)` → first item of selected art family (if any)
- `ListItem.Art(multiart1)` … `ListItem.Art(multiartN)` → subsequent items up to `multiart_max`

---

## Processes 

### 1) Crop (clearlogo)
- Tight bounding-box crop (alpha-aware), exported as **PNG**.
- Colour set computed: **dominant**, **accent**, **contrast**, **luminosity**.
- Stored in DB + cache for reuse until the source file or path hash changes.

### 2) Blur (fanart) + Darken (optional)
- Downsample + Gaussian blur, exported as **JPEG**.
- Same colour set computed for fanart.
- **Darken** (WCAG-informed): in `overlay_rect`, sample brightness using a **grid**, take the **brightest cell**, estimate background luminance, and compare to the **overlay_source**. Returns a darken percentage (capped) to help reach the target ratio.
- **Red allowance (hue-aware leniency):** red-heavy scenes can appear perceptually darker than WCAG formulae suggest. A hue window around red relaxes the target ratio within guard rails to avoid over-darkening.

> You can **use fadediffuse animations** inside Kodi to darken an image control using the the 0-100 value returned by `ListItem.Art(fanart_darken)`

**Example XML animations:**
```xml

  <control type="list" id="9998">
    <itemlayout />
    <focusedlayout />
    <content>plugin://script.copacetic.helper/?info=artwork&amp;logo_crop=true&amp;bg_blur=true&amp;overlay_enable=true&amp;overlay_source=ffd1cece&amp;overlay_rect=120,660,1680,360</content>
  </control>

	<include name="darken_artwork_under_text_animation">
		<animation effect="fadediffuse" end="ffe6e6e6" time="360" condition="Integer.IsGreaterOrEqual(Container(9998).ListItem.Art(fanart_darken),10) + Integer.IsLess(Container(9998).ListItem.Art(fanart_darken),20)">Conditional</animation>
		<animation effect="fadediffuse" end="ffd1d1d1" time="360" condition="Integer.IsGreaterOrEqual(Container(9998).ListItem.Art(fanart_darken),20) + Integer.IsLess(Container(9998).ListItem.Art(fanart_darken),30)">Conditional</animation>
		<animation effect="fadediffuse" end="ffbcbcbc" time="360" condition="Integer.IsGreaterOrEqual(Container(9998).ListItem.Art(fanart_darken),30) + Integer.IsLess(Container(9998).ListItem.Art(fanart_darken),40)">Conditional</animation>
		<animation effect="fadediffuse" end="ffadadad" time="360" condition="Integer.IsGreaterOrEqual(Container(9998).ListItem.Art(fanart_darken),40) + Integer.IsLess(Container(9998).ListItem.Art(fanart_darken),50)">Conditional</animation>
		<animation effect="fadediffuse" end="ff9f9f9f" time="360" condition="Integer.IsGreaterOrEqual(Container(9998).ListItem.Art(fanart_darken),50) + Integer.IsLess(Container(9998).ListItem.Art(fanart_darken),60)">Conditional</animation>
		<animation effect="fadediffuse" end="ff939393" time="360" condition="Integer.IsGreaterOrEqual(Container(9998).ListItem.Art(fanart_darken),60) + Integer.IsLess(Container(9998).ListItem.Art(fanart_darken),70)">Conditional</animation>
		<animation effect="fadediffuse" end="ff898989" time="360" condition="Integer.IsGreaterOrEqual(Container(9998).ListItem.Art(fanart_darken),70) + Integer.IsLess(Container(9998).ListItem.Art(fanart_darken),80)">Conditional</animation>
		<animation effect="fadediffuse" end="ff838383" time="360" condition="Integer.IsGreaterOrEqual(Container(9998).ListItem.Art(fanart_darken),80) + Integer.IsLess(Container(9998).ListItem.Art(fanart_darken),90)">Conditional</animation>
		<animation effect="fadediffuse" end="ff808080" time="360" condition="Integer.IsGreaterOrEqual(Container(9998).ListItem.Art(fanart_darken),90) + Integer.IsLess(Container(9998).ListItem.Art(fanart_darken),100)">Conditional</animation>
		<animation effect="fadediffuse" end="ff666666" time="360" condition="Integer.IsGreaterOrEqual(Container(9998).ListItem.Art(fanart_darken),100)">Conditional</animation>
	</include>

  <control type="image">
    <include content="darken_artwork_under_text_animation" />
    <texture>$INFO[ListItem.Art(fanart)]</>

```
 
### 3) Multiart
- Resolves and returns a family of artwork keys for the item (e.g. `fanart`, `poster`, `tvshow.fanart`), exposing them as `multiart`, `multiart1..N` up to `multiart_max`.
- Useful for slideshows, cycling backgrounds, or layout-specific art families.


> You can **switch which art type is exposed** using a single variable, and multiart will always be returned to the same `multiart`, `multiart1..N` range, meaning there is no need to juggle dozens or hundreds of window properties and fetch unused multiart paths each time.

**Example XML variable:**
```xml
<variable name="multiart_type">
    <value condition="!String.IsEmpty(ListItem.Art(keyart1)) + $EXP[layouts_poster_visible] + $EXP[art_keyart_visible]">keyart</value>
    <value condition="!String.IsEmpty(ListItem.Art(poster1)) + $EXP[layouts_poster_visible] + [!$EXP[art_keyart_visible] | String.IsEmpty(ListItem.Art(keyart))]">poster</value>
    <value condition="!String.IsEmpty(ListItem.Art(tvshow.keyart1)) + $EXP[layouts_poster_visible] + $EXP[art_keyart_visible]">tvshow.keyart</value>
    <value condition="!String.IsEmpty(ListItem.Art(tvshow.poster1)) + $EXP[layouts_poster_visible] + [!$EXP[art_keyart_visible] | String.IsEmpty(ListItem.Art(tvshow.keyart))]">tvshow.poster</value>
    <value condition="!String.IsEmpty(ListItem.Art(landscape1)) + $EXP[layouts_fanart_visible] + $EXP[art_landscape_visible]">landscape</value>
    <value condition="!String.IsEmpty(ListItem.Art(fanart1)) + $EXP[layouts_fanart_visible] + [!$EXP[art_landscape_visible] | String.IsEmpty(ListItem.Art(landscape))]">fanart</value>
    <value condition="!String.IsEmpty(ListItem.Art(tvshow.landscape1)) + $EXP[layouts_fanart_visible] + $EXP[art_landscape_visible]">tvshow.landscape</value>
    <value condition="!String.IsEmpty(ListItem.Art(tvshow.fanart1)) + $EXP[layouts_fanart_visible] + [!$EXP[art_landscape_visible] | String.IsEmpty(ListItem.Art(landscape))]">tvshow.fanart</value>
    <value condition="!String.IsEmpty(ListItem.Art(square1)) + $EXP[layouts_square_visible]">square</value>
    <value condition="!String.IsEmpty(ListItem.Art(tvshow.square1)) + $EXP[layouts_square_visible]">tvshow.square</value>
</variable>

<content>plugin://script.copacetic.helper/?info=artwork&amp;multiart=$VAR[multiart_type]$&amp;multiart_max=30</content>

```

---

## Benchmarks

**Per-operation (fresh processing):**
- `ImageProcessor.crop` (clearlogo): **~0.01–0.09 s**
- `ImageProcessor.blur` (fanart): **~0.06–0.09 s**
- `ColorAnalyzer.analyze`: **~0.003–0.075 s**

**End-to-end handler (fresh, including I/O):**
- `PluginHandlers → artwork`: **~0.15–0.44 s**

**Fast paths:**
- Reading previously processed data from cache/DB tends to land in **tens of milliseconds**, depending on I/O.

---

## Tunables

> Internal analyser settings that shape palette/contrast/readability. Listed here for reference; defaults intentionally omitted.

**Sampling & Palette**
- `palette_size` — number of colours in adaptive palette.
- `sample_size` — downsample size when building the palette (square).
- `avg_downsample` — downsample size for averaging RGB in a patch.
- `avg_grid` — grid resolution (G×G) to locate the brightest cell prior to averaging.

**Filtering thresholds**
- `skip_whites` — ignore near-white swatches unless overwhelmingly dominant.
- `skip_blacks` — ignore near-black swatches unless overwhelmingly dominant.
- `dominance_allow_threshold` — allow extremes if they exceed this fraction of pixels.
- `alpha_thresholded_mask` — binary alpha masking for opacity decisions.
- `alpha_opaque_min` — alpha cutoff (0–255) treated as opaque.
- `near_white` — per-channel threshold for “near white”.
- `near_black` — per-channel threshold for “near black”.

**Accent extraction**
- `freq_distance_norm` — normalisation factor for RGB distance.
- `accent_weight` — weights for accent scoring: frequency, saturation, distance.
- `accent_freq_exponent` — gamma to flatten dominance.
- `accent_freq_floor` — ignore swatches contributing below this fraction.
- `accent_min_dist` — minimum RGB distance from dominant to qualify as accent.

**Contrast & Lightness**
- `contrast_shift` — lightness delta for contrast colour.
- `contrast_midpoint` — HLS pivot; lighten if L < pivot else darken.
- `min_lightness` — lower clamp for HLS lightness.
- `max_lightness` — upper clamp for HLS lightness.

**Readability (overlay)**
- `text_overlay_colour` — ARGB colour to use when evaluating readability (if not provided via `overlay_source`).
- `text_overlay_rect` — default rectangle `(x, y, w, h)` for overlay analysis.
- `target_contrast_ratio` — target WCAG contrast ratio (normal text ≈ 4.5, large text ≈ 3.0).

**Red leniency / guard rails**
- `red_relax_enable` — enable hue-aware leniency for reds on dark backgrounds.
- `red_hue_center` — hue centre for reds (0.0 in [0..1]).
- `red_hue_window` — ± hue window around red (about ±22°).
- `red_min_target` — never demand higher ratio when red rule applies.
- `red_relax_cap` — max target when relaxing reds on dark backgrounds.
- `red_bg_floor` — treat as “already dark” if background L is below this.
- `max_darken_cap` — cap on darken percent to avoid over-darkening.

---

## Notes on standards

- **Contrast** is evaluated in the spirit of **WCAG** contrast ratios for readability.  
  Typical targets: **4.5** for normal text and **3.0** for large text. Red leniency exists to reflect perceptual limits with saturated reds on very dark scenes.

---







Multiart scans the current item’s artwork fields for a family (e.g. `fanart`, `poster`, `keyart`, `tvshow.poster`, etc.). If it finds `arttype`, `arttype1`, `arttype2`, … it will return them neatly as `multiart`, `multiart1`, `multiart2`, … on the item. You can then **switch which family is exposed** using a single variable, without juggling hundreds of window properties.

**Example (your real Copacetic code):**
```xml
<variable name="multiart_type_videos">
    <value condition="Control.HasFocus(3100) + !String.IsEmpty(Container(3100).ListItem.Art(thumb1)) + [String.IsEqual(Container(3100).ListItem.DBType,episode) | String.IsEqual(Container(3100).ListItem.DBType,album) | String.IsEqual(Container(3100).ListItem.DBType,song)]">thumb</value>
    <value condition="Control.HasFocus(3100) + !String.IsEmpty(Container(3100).ListItem.Art(keyart1)) + $EXP[layouts_poster_videos_visible] + $EXP[art_keyart_visible]">keyart</value>
    <value condition="Control.HasFocus(3100) + !String.IsEmpty(Container(3100).ListItem.Art(poster1)) + $EXP[layouts_poster_videos_visible] + [!$EXP[art_keyart_visible] | String.IsEmpty(Container(3100).ListItem.Art(keyart))]">poster</value>
    <value condition="Control.HasFocus(3100) + !String.IsEmpty(Container(3100).ListItem.Art(tvshow.keyart1)) + $EXP[layouts_poster_videos_visible] + $EXP[art_keyart_visible]">tvshow.keyart</value>
    <value condition="Control.HasFocus(3100) + !String.IsEmpty(Container(3100).ListItem.Art(tvshow.poster1)) + $EXP[layouts_poster_videos_visible] + [!$EXP[art_keyart_visible] | String.IsEmpty(Container(3100).ListItem.Art(tvshow.keyart))]">tvshow.poster</value>
    <value condition="Control.HasFocus(3100) + !String.IsEmpty(Container(3100).ListItem.Art(landscape1)) + $EXP[layouts_fanart_videos_visible] + $EXP[art_landscape_visible]">landscape</value>
    <value condition="Control.HasFocus(3100) + !String.IsEmpty(Container(3100).ListItem.Art(fanart1)) + $EXP[layouts_fanart_videos_visible] + [!$EXP[art_landscape_visible] | String.IsEmpty(Container(3100).ListItem.Art(landscape))]">fanart</value>
    <value condition="Control.HasFocus(3100) + !String.IsEmpty(Container(3100).ListItem.Art(tvshow.landscape1)) + $EXP[layouts_fanart_videos_visible] + $EXP[art_landscape_visible]">tvshow.landscape</value>
    <value condition="Control.HasFocus(3100) + !String.IsEmpty(Container(3100).ListItem.Art(tvshow.fanart1)) + $EXP[layouts_fanart_videos_visible] + [!$EXP[art_landscape_visible] | String.IsEmpty(Container(3100).ListItem.Art(landscape))]">tvshow.fanart</value>
    <value condition="Control.HasFocus(3100) + !String.IsEmpty(Container(3100).ListItem.Art(square1)) + $EXP[layouts_square_videos_visible]">square</value>
    <value condition="Control.HasFocus(3100) + !String.IsEmpty(Container(3100).ListItem.Art(tvshow.square1)) + $EXP[layouts_square_videos_visible]">tvshow.square</value>
    <value condition="!String.IsEmpty(ListItem.Art(thumb1)) + [String.IsEqual(ListItem.DBType,episode) | String.IsEqual(ListItem.DBType,album) | String.IsEqual(ListItem.DBType,song)]">thumb</value>
    <value condition="!String.IsEmpty(ListItem.Art(keyart1)) + $EXP[layouts_poster_videos_visible] + $EXP[art_keyart_visible]">keyart</value>
    <value condition="!String.IsEmpty(ListItem.Art(poster1)) + $EXP[layouts_poster_videos_visible] + [!$EXP[art_keyart_visible] | String.IsEmpty(ListItem.Art(keyart))]">poster</value>
    <value condition="!String.IsEmpty(ListItem.Art(tvshow.keyart1)) + $EXP[layouts_poster_videos_visible] + $EXP[art_keyart_visible]">tvshow.keyart</value>
    <value condition="!String.IsEmpty(ListItem.Art(tvshow.poster1)) + $EXP[layouts_poster_videos_visible] + [!$EXP[art_keyart_visible] | String.IsEmpty(ListItem.Art(tvshow.keyart))]">tvshow.poster</value>
    <value condition="!String.IsEmpty(ListItem.Art(landscape1)) + $EXP[layouts_fanart_videos_visible] + $EXP[art_landscape_visible]">landscape</value>
    <value condition="!String.IsEmpty(ListItem.Art(fanart1)) + $EXP[layouts_fanart_videos_visible] + [!$EXP[art_landscape_visible] | String.IsEmpty(ListItem.Art(landscape))]">fanart</value>
    <value condition="!String.IsEmpty(ListItem.Art(tvshow.landscape1)) + $EXP[layouts_fanart_videos_visible] + $EXP[art_landscape_visible]">tvshow.landscape</value>
    <value condition="!String.IsEmpty(ListItem.Art(tvshow.fanart1)) + $EXP[layouts_fanart_videos_visible] + [!$EXP[art_landscape_visible] | String.IsEmpty(ListItem.Art(landscape))]">tvshow.fanart</value>
    <value condition="!String.IsEmpty(ListItem.Art(square1)) + $EXP[layouts_square_videos_visible]">square</value>
    <value condition="!String.IsEmpty(ListItem.Art(tvshow.square1)) + $EXP[layouts_square_videos_visible]">tvshow.square</value>
</variable>
```

**Why it helps**
- One variable selects the art family.
- The plugin returns `multiart`, `multiart1..N` for that family.
- Your views use the same labels/conditions regardless of which family is active.

---

## 4) Clearlogo — crop + colour set

**What happens**
- Tight bounding-box crop, size-capped → **PNG**.
- Extracts a **dominant** colour (alpha-aware, filters near-white/black unless dominant).
- Picks an **accent** distinct enough from dominant (distance + frequency + saturation).
- Computes a **contrast** colour via HLS lightness shift around a midpoint.
- Estimates **luminosity** using a **brightest-patch** scan then averaging that patch.

**Why it’s useful**
- Logos become visually consistent.
- You get a compact palette (`*_color`, `*_accent`, `*_contrast`) for styling text, badges, and focus rings.

---

## 5) Fanart — blur + colour set + optional darken

**What happens**
- Downsample + heavy Gaussian blur → **JPEG** (renders fast; hides noise).
- Same colour set as clearlogo.
- **Optional darken**: ensures your overlay text/logo meets a target contrast **inside a rectangle**.

**How darken works (overview)**
- We sample a grid across the rect, find the **brightest patch**, estimate background luminance there, then compare with your text colour. The helper returns a **darken %** (0–85) to hit your contrast target.
- **Red-leniency** guard rails prevent over-darkening in red-heavy scenes that look visually dark but read as “not dark enough” to pure maths.

---

## 6) Overlay requirements (important)

To get `fanart_darken`:
- `overlay_enable=true` must be set.
- A **text colour** must be known:
  - `overlay_source=clearlogo` → include `logo_crop=true` in the same call (we need the freshly computed dominant colour from the logo).
  - or pass an explicit ARGB hex colour in `overlay_source`.
- A **fanart image** must be produced/analysed → include `bg_blur=true`.

Rationale: darken compares **text (logo) vs background (fanart)** within your rectangle.

---

## 7) Parameters

| Param | Type | Allowed / Range | Default | Purpose | Notes |
|---|---:|---|---|---|---|
| `overlay_enable` | str | `true` to enable | off | Toggle darken | Requires `bg_blur=true` |
| `overlay_source` | str | `clearlogo` **or** ARGB hex | analyser default | Text colour to test | If `clearlogo`, also set `logo_crop=true` |
| `overlay_rect` | str | `x,y,w,h` (ints ≥0) | analyser default | Region to analyse | Parses CSV; ignored if invalid |
| `overlay_target` | float | > 0 (e.g. 3.0–7.0) | 4.5 | Target contrast ratio | Higher → potentially more darken |
| `multiart` | str | any art key family | — | Export multiart slots | e.g. `fanart`, `poster`, `tvshow.poster` |
| `multiart_max` | int | 1–50 | 15 | How many slots to expose | Stops early if gaps |
| `target` | int | Kodi control ID | — | Bind to specific container | Use with `focus_guard` |
| `focus_guard` | str | any | — | Abort if identity changes | Usually `Container(id).CurrentItem` |

---

## 8) Returns (what you get back)

- **Images**
  - `clearlogo` → PNG (cropped).
  - `fanart` → JPEG (blurred).
- **Colour analysis**
  - `*_color` (dominant), `*_accent` (accent), `*_contrast` (contrasting), `*_luminosity` (0–1000 scale).
- **Overlay**
  - `fanart_darken` (0–85) when overlay is enabled and inputs are valid.
- **Multiart (optional)**
  - `multiart`, `multiart1..N` for the requested family.

---

## 9) Artwork readiness guard (recommended)

Sometimes the image library lags behind other metadata at window load. The plugin path may fire before art is ready, then re-fire once art arrives. Guard against this:
```xml
<variable name="artwork_helper">
  <value condition="$EXP[artwork_guard] + Control.HasFocus(3100) + !Container(3100).IsUpdating">
    plugin://script.copacetic.helper/?info=artwork&amp;target=3100&amp;focus_guard=$INFO[Container(3100).CurrentItem]&amp;logo_crop=true&amp;bg_blur=true&amp;multiart=$VAR[multiart_type_videos]&amp;multiart_max=15&amp;overlay_enable=true&amp;overlay_source=clearlogo&amp;overlay_rect=120,660,1680,360
  </value>
  <value condition="$EXP[artwork_guard] + !$EXP[primary_switching]">
    plugin://script.copacetic.helper/?info=artwork&amp;focus_guard=$INFO[Container.CurrentItem]&amp;logo_crop=true&amp;bg_blur=true&amp;multiart=$VAR[multiart_type_videos]&amp;multiart_max=15&amp;overlay_enable=true&amp;overlay_source=clearlogo&amp;overlay_rect=120,660,1680,360
  </value>
</variable>

<variable name="artwork_ready_checker">
  <value condition="!String.IsEmpty(Container(3100).ListItem.Art(clearlogo)) + Control.HasFocus(3100)">$INFO[Container(3100).ListItem.Art(clearlogo)]</value>
  <value condition="!String.IsEmpty(Container(3100).ListItem.Art(fanart)) + Control.HasFocus(3100)">$INFO[Container(3100).ListItem.Art(fanart)]</value>
  <value condition="!String.IsEmpty(Container(3100).ListItem.Art(poster)) + Control.HasFocus(3100)">$INFO[Container(3100).ListItem.Art(poster)]</value>
  <value condition="!String.IsEmpty(Container(3100).ListItem.Art(thumb)) + Control.HasFocus(3100)">$INFO[Container(3100).ListItem.Art(thumb)]</value>
  <value condition="!String.IsEmpty(ListItem.Art(clearlogo))">$INFO[ListItem.Art(clearlogo)]</value>
  <value condition="!String.IsEmpty(ListItem.Art(fanart))">$INFO[ListItem.Art(fanart)]</value>
  <value condition="!String.IsEmpty(ListItem.Art(poster))">$INFO[ListItem.Art(poster)]</value>
  <value condition="!String.IsEmpty(ListItem.Art(thumb))">$INFO[ListItem.Art(thumb)]</value>
  <value />
</variable>

<expression name="artwork_guard">!String.IsEmpty(Control.GetLabel(6301))</expression>

<control type="label" id="6301">
  <label>$VAR[artwork_ready_checker]</label>
</control>
```

---




