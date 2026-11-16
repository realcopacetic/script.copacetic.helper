# Broadcasts

`info=broadcasts` fills a container with one PVR channel's programmes, from the one on
air onward. Kodi's own channel guide dialog (`DialogPVRChannelGuide.xml`) lists only the
playing channel's when a skin opens it, so this lets a skin show any channel's guide
beside its channel list.

```xml
<control type="list" id="4719"><!-- id is an example -->
  <itemlayout />
  <focusedlayout />
  <content>plugin://script.copacetic.helper/?info=broadcasts&amp;channelid=$INFO[Container(11).ListItem.Property(channelid)]&amp;limit=48</content>
</control>
```

| Param | |
|---|---|
| `channelid` | The channel's id. A Kodi channel item carries it as `ListItem.Property(channelid)` (`FileItem.cpp`, `SetProperty("channelid", channel->ChannelID())`). Required. |
| `limit` | The most programmes to return. |

It makes two JSON-RPC calls: `PVR.GetBroadcasts` (every guide entry Kodi holds for the
channel) and `PVR.GetChannelDetails` (its logo, skipped when there are no programmes).

## The items

| | |
|---|---|
| `ListItem.Label` | The title as Kodi shows it: "Parental locked" (19266) for a locked programme (`FileItem.cpp:125-135`). |
| `ListItem.Art(thumb)` | The programme's own image (empty when it has none, or is parental locked). |
| `ListItem.Icon` | The channel's logo, else `DefaultTVShows.png`. |
| `ListItem.Property(broadcastid)` | The programme's id, for JSON-RPC's `PVR.*` timer methods and [`pvr_smart_select`](../script/actions.md#pvr_smart_select). |
| `ListItem.Property(channelid)` | The `channelid` asked for, so a skin can tell whose programmes it holds. |
| `ListItem.Property(start)`, `(end)` | Start and end as local clock times in Kodi's time format, without seconds (as `ListItem.StartTime`). |
| `ListItem.Property(runtime)` | Minutes. |
| `ListItem.Property(on_air)` | `true` for the programme on air. |
| `ListItem.Property(time_left)` | On air only, to the programme's end by the clock: `1h 23m`, `1h` or `48m`; empty once it has ended. |
| `ListItem.Property(state)` | `reminder`, `recording`, `timer`, `recorded` or empty: the first true wins, as the TV guide's icon. |
| `ListItem.Property(series)` | `true` when a timer rule made its timer or reminder. |
| `ListItem.Property(hide_add_remove_favourite)` | `true`: the context menu offers no Add to favourites (`ContextMenus.cpp:79-82`), since the item's path is no real item. |

- **On air** runs on the channel's playing time, as Kodi's own does (`isactive` and
  `wasactive` use `GetCurrentPlayingTime`, `EpgInfoTag.cpp:207-223`), so a timeshifted
  channel's programme stays on air as it plays. **Time left** counts to the end by the
  clock, as the TV guide's: Kodi's `progresspercentage` uses the wall clock
  (`EpgInfoTag.cpp:231-247`), not the playing time, so the two never mixed. A timeshifted
  programme past its end by the clock reads on air with no time left.
- **`recording`** is a timer that isn't a reminder on the programme on air: JSON-RPC has
  no recording flag for a guide entry.
- **Not available** through JSON-RPC: a timer's error or conflict, and the broadcaster's
  flags (new, premiere, finale, live).
- Each item's path is unique to its programme, so a refetch keeps the selected one.
- The items are not playable and carry no info tag: give the container an `onclick`
  (for a later programme, [`pvr_smart_select`](../script/actions.md#pvr_smart_select)).
  Kodi's programme info can't be opened for them: its info dialogs take only items Kodi
  holds (`GUIContentUtils.cpp` `ShowInfoForItem`; `PVRGUIActionsUtils.cpp`
  `HasInfoForItem` has no guide-entry case).
