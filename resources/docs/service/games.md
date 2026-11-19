# Games

Tells your skin which emulator and system the playing game uses, and gives the game
OSD's dialogs a blurred picture of the game to sit on. Kodi has no infolabel for
either.

All properties are on the Home window (`10000`). They are set only while a skin that
[opts in](index.md#opting-in) is active, and cleared whenever the active skin changes or
the service stops.

## When a game starts

When a game starts (Kodi's AV started event), and at once when the user switches to a skin that opts in while a game plays, the service sets
`player_emulator` and `player_system`.

A game takes this path alone. Kodi reports a game as video and audio too, but none of
the [video player properties](player.md#video) are set for it: no subtitle or stream
counts, no `player_start`, no clean name from the file name, no skip segments. Lyrics
left from a song are cleared, and so is any trailer state.

| Property | Value |
|---|---|
| `player_emulator` | The game add-on's emulator name. Kodi names libretro add-ons `Platforms (Emulator)`, so this is the text inside the first brackets; a name without brackets is used whole. For example `Nestopia UE`. |
| `player_system` | The system, from your skin's emulators mapping (below). Empty when the skin has no mapping, or the mapping has no system for this add-on and file. |

Both are cleared when playback stops, ends or fails and nothing else starts. The next
file replaces them.

### The emulators mapping

The service reads `player_system` from a JSON file in your skin, read again at each
game start:

`extras/templates/mappings/mappings_emulators.json`

It looks for the top-level key `emulators`, and in it a `metadata` object keyed by game
add-on id. Each add-on gives either one `system`, or an `extensions` object that maps a
file extension (lower case, no dot) to a system, for an emulator that plays several:

```json
{
  "emulators": {
    "mode": "static",
    "items": ["game.libretro.bnes", "game.libretro.beetle-pce"],
    "metadata": {
      "game.libretro.bnes": { "system": "NES" },
      "game.libretro.beetle-pce": { "extensions": { "pce": "PC Engine", "sgx": "SuperGrafx" } }
    }
  }
}
```

The playing file's extension is looked up first; if it isn't listed, `system` is used;
with neither, `player_system` is empty. The file is a normal
[builder mapping](../builders/02-mappings.md), so the builders can use it too. Leave it
out and only `player_emulator` is set.

## When the game OSD opens

Each poll (once a second), the service checks `Window.IsActive(gameosd)`. When the game
OSD opens, it sets `player_game_blur`; when it closes, it clears it, so the next opening
never shows the last one's picture before its own blur is ready.

| Property | Value |
|---|---|
| `player_game_blur` | The game's newest save picture, blurred as a background is. Empty when the game has no picture yet, or Kodi is still writing it. |

Kodi saves the game every 10 seconds of play and writes a picture beside each save, in
`special://home/saves/<game file name>/`. The service blurs the newest one, so a manual
save made since the last autosave counts too. Each blur is a new file, named after the
picture's time, because Kodi won't load a changed picture at a path it has already
shown. The last blur, and Kodi's cached copy of it, are deleted. If the OSD opens again
before the next autosave, the same file is reused.

A dialog opened over the game OSD leaves it open, so `player_game_blur` stays set while
the dialog shows. Open the OSD's dialogs (saves, settings, controllers) with
`ActivateWindow` over it, without closing it first, or the property is cleared.

`player_game_blur` is also cleared when playback stops, ends or fails, and at the next
game's start. An OSD already open when a game starts counts as opening for that game.

## Example

Show the system under the emulator, or the emulator alone when there is no system:

```xml
<control type="label">
  <label>$INFO[Window(home).Property(player_emulator)]</label>
</control>
<control type="label">
  <visible>!String.IsEmpty(Window(home).Property(player_system))</visible>
  <label>$INFO[Window(home).Property(player_system)]</label>
</control>
```

Use the blur as a dialog background, with the game's fanart as a fallback:

```xml
<variable name="game_dialog_background">
  <value condition="!String.IsEmpty(Window(home).Property(player_game_blur))">$INFO[Window(home).Property(player_game_blur)]</value>
  <value>$INFO[Player.Art(fanart)]</value>
</variable>
```
