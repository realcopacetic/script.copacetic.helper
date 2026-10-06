# Typewriter Helper

Types a label into a textbox one character at a time. The textbox grows one line at a
time as the text wraps, up to a line limit. The run stops at once if focus moves on.

## Plugin path

```xml
<control type="list" id="9600"><!-- hidden helper container; id is an example -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=typewriter&amp;target=50&amp;focus_guard=$INFO[Container(50).CurrentItem]&amp;label=$INFO[Container(50).ListItem.Label]&amp;target_id=4020&amp;anchor_id=4030&amp;valign=bottom&amp;track_h=37&amp;max_lines=3</content>
</control>

<control type="textbox" id="4020">
  <width>800</width>
  <height>37</height>
  <font>font30</font>
</control>
```

The path returns no list items. It drives the textbox directly.

## Controls the skin provides

- A **textbox** with id `target_id`, in the current window (with `dialog=true` or
  `target=item`, in the topmost dialog). It must be a textbox: the helper reads
  `Container(<target_id>).HasNext` to know when the text has wrapped. The helper sets
  its position, width, height and text, and makes it visible when typing starts.

## Parameters

| Param | Accepted values | Default | What it does |
|---|---|---|---|
| `target_id` | control id | — | **Required.** The textbox. |
| `label` | any text | — | **Required** unless `reset=true`. The text to type. |
| `reset` | `true`, `false` | `false` | Stop any run on this textbox and hide it. See [Resetting](#resetting). |
| `max_lines` | whole number | `3` | Most lines the textbox may grow to. |
| `start_delay` | seconds (decimal) | `0` | Wait before typing starts. Focus is checked again after the wait. |
| `visit` | any text | — | If passed, the run only goes ahead when it equals `Window(home).Property(artwork_visit)`. |
| `target` | container id, or `item` | — | Container the label belongs to. Used by the focus guard and the window properties below. `item` means the window's own item (an info dialog's); `typewriter_container` is then empty. |
| `dialog` | `true`, `false` | `false` | The controls are in the topmost dialog, not the current window. `target=item` implies it. See [Plugin Helpers](plugin_helpers.md#the-focus-guard). |
| `focus_guard`, `focus_ids`, `identity_labels`, `identity_container` | | | Focus guard. See [Plugin Helpers](plugin_helpers.md#3-guarding-against-fast-scrolls-and-container-moves). |

Placement parameters (`coords`, `anchor_id`, `inset`, `track_w`, `track_h`, `halign`,
`valign`, `hpad`, `vpad`, `outside`) set where the textbox goes. See
[Placement Options](placement.md). Two of them work differently here:

- **`track_h` is the line height.** It must match the font's line pitch, or the
  text is clipped. Without it, the line height is 30 and the box used for alignment
  is `30 × max_lines` tall.
- **`valign` also sets the growth direction.** `top` grows downwards, `bottom` grows
  upwards, `center` grows both ways.

The textbox width is the rectangle's width.

## What happens on each run

1. With `visit` passed: if it does not equal `Window(home).Property(artwork_visit)`,
   the run stops. This drops replays of old cached paths (for example after
   `ReloadSkin()`), as the live path fires again anyway.
2. The focus guard is checked.
3. `Window(home).Property(typewriter_container)` is set to the container id
   (`identity_container`, else `target`; empty when neither is passed), and
   `Window(home).Property(typewriter_pos)` to that container's `CurrentItem`.
4. The run claims `Window(home).Property(typewriter_current_<target_id>)` with a unique
   value.
5. After `start_delay`, the textbox is cleared, placed one line tall and made visible.
6. One character is added every 25 ms. When `Container(<target_id>).HasNext` becomes
   true, the textbox grows by one line, up to `max_lines`.

Before every character the run checks the focus guard and the claimed property. If
focus moved on, or another value is now in
`typewriter_current_<target_id>`, the textbox is cleared and the run stops.

## Resetting

A newer run always takes over from an older one on the same textbox. To stop a run
without starting another, either:

- write any other value into the property from the skin, for example
  `SetProperty(typewriter_current_4020,scroll,home)` in an `<onfocus>`; or
- call the path with `reset=true`:

```xml
<content>plugin://script.copacetic.helper/?info=typewriter&amp;reset=true&amp;target_id=4020</content>
```

`reset=true` writes `scroll` into `typewriter_current_<target_id>`, hides the textbox
and clears `typewriter_container` and `typewriter_pos`.

Use the skin side for anything that must vanish at once. A plugin run can take a
moment to start.

## Window properties

| Property (home window) | Set by | Value |
|---|---|---|
| `typewriter_container` | each run; cleared by `reset=true` | Container id the label belongs to. |
| `typewriter_pos` | each run; cleared by `reset=true` | `CurrentItem` of that container. |
| `typewriter_current_<target_id>` | each run, `reset=true`, or the skin | The value of the run allowed to type. |

Compare `typewriter_container` and `typewriter_pos` with the live container to tell
whether the text on screen still belongs to the focused item.

## Skin contract

- `Window(home).Property(artwork_visit)` must be set by the skin when you pass
  `visit`. Set it once per focus change, then pass the same value in `visit`.
