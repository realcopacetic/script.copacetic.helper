# Text Image Helper

Draws a piece of text into a PNG image and returns its path. The image is white text
on a transparent background, so you colour it with `<colordiffuse>`. Use it when a
label needs something Kodi's own labels cannot do, such as custom letter spacing or
line height.

Images are cached by their content. The same text and settings return the same file
straight away.

## Plugin path

```xml
<control type="list" id="9360"><!-- hidden helper container; id is an example -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=text&amp;target=50&amp;focus_guard=$INFO[Container(50).CurrentItem]&amp;text=$INFO[Container(50).ListItem.Plot]&amp;text_font=special://skin/fonts/MyFont-SemiBold.ttf&amp;text_size=46&amp;text_line_height=1.1&amp;text_letter_spacing=-1.5&amp;text_width=1280&amp;text_height=660</content>
</control>

<control type="image">
  <width>1280</width>
  <height>660</height>
  <aspectratio aligny="top">keep</aspectratio>
  <texture>$INFO[Container(9360).ListItem.Art(text)]</texture>
  <colordiffuse>FFFFFFFF</colordiffuse>
</control>
```

## Parameters

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `text` | any text | — | The text to draw. Nothing is returned when empty. |
| `text_font` | font file path (`special://` or absolute) | — | The `.ttf` or `.otf` font to draw with. |
| `text_size` | whole number (pixels) | `42` | Font size. |
| `text_width` | whole number (pixels) | `1280` | Wrap width, and the width of the image. |
| `text_height` | whole number (pixels) | `720` | Most height allowed. Text that does not fit is cut at a whole line: at the last full sentence that fits, else with an ellipsis. |
| `text_line_height` | decimal | `1.3` | Line spacing, as a multiple of the font size. |
| `text_letter_spacing` | decimal | `0.0` | Extra space between letters, as a percentage of the font size. Negative values pull letters closer. |
| `target` | container id | — | Container used by the focus guard. |
| `focus_guard`, `focus_ids`, `identity_labels`, `identity_container` | | | Focus guard. See [Plugin Helpers](plugin_helpers.md#3-guarding-against-fast-scrolls-and-container-moves). |

## What you get back

| Infolabel | Value |
|---|---|
| `ListItem.Art(text)` | Path to the PNG image. |
| `ListItem.Property(text_height)` | Height of the image in pixels (only as tall as the lines drawn). |

Use `text_height` to size the image control to the text. The
[reposition](reposition.md) helper can do this:

```xml
<content>plugin://script.copacetic.helper/?info=reposition&amp;target_id=4360&amp;w=1280&amp;h=$INFO[Container(9360).ListItem.Property(text_height)]</content>
```
