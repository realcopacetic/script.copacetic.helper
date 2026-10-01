# Play Next

Keeps a TV show playing. When an episode from the library starts and it is the last
item in Kodi's video playlist, the service adds the show's next episode to the end of
the playlist. Kodi then plays it when the current episode ends.

## Enabling it

Play next is off until your skin turns on the skin setting `playnext_enabled`:

```xml
<control type="radiobutton" id="100">
  <label>Play next episode</label>
  <selected>Skin.HasSetting(playnext_enabled)</selected>
  <onclick>Skin.ToggleSetting(playnext_enabled)</onclick>
</control>
```

## When it runs

Once per episode, when playback of a library episode starts and the service can find
the episode's TV show. It runs for any skin, whether or not it opts in to the
[poll loop](index.md#opting-in).

It does nothing when:

- `Skin.HasSetting(playnext_enabled)` is false;
- the episode is not playing from Kodi's video playlist;
- the playlist already has an item after the current one;
- the episode is the last one of the show.

## Which episode is queued

The service lists the show's episodes in season and episode order and takes the one
after the episode that is playing. Episodes that share the playing episode's file are
skipped, so the other parts of a multi-part episode are not queued again.

## What your skin sees

The service sets no window properties for this feature. The queued episode appears in
the video playlist, so Kodi's own infolabels show it, for example
`$INFO[VideoPlayer.NextTitle]` and `$INFO[Playlist.Length(video)]`.
