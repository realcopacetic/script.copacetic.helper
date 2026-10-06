# author: realcopacetic

import random
import time
from operator import itemgetter

import xbmc
import xbmcgui

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import (
    ADDON,
    SKINXML,
)
from resources.lib.shared.speed_dial import SpeedDial
from resources.lib.shared.speed_dial import entry as dial_entry
from resources.lib.shared.speed_dial import mark_source
from resources.lib.shared.utilities import clear_cache as _clear_cache_util
from resources.lib.shared.utilities import clear_label as _clear_label_util
from resources.lib.shared.utilities import (
    clear_playlists,
    condition,
    container_position,
    focused_control_id,
    infolabel,
    json_call,
    play_files,
    reset_dev_state,
    to_int,
    topmost_window_id,
    window_property,
)

REGISTRY = {}

_LIBRARY_ITEMS = {"album": "albumid", "artist": "artistid", "genre": "genreid"}
_INFO_DIALOGS = ("songinformation", "musicinformation", "movieinformation")
_INFO_DETAILS = {
    "episode": "VideoLibrary.GetEpisodeDetails",
    "movie": "VideoLibrary.GetMovieDetails",
    "musicvideo": "VideoLibrary.GetMusicVideoDetails",
    "set": "VideoLibrary.GetMovieSetDetails",
    "song": "AudioLibrary.GetSongDetails",
    "tvshow": "VideoLibrary.GetTVShowDetails",
}
MIX_SIZE = 50
MIX_ARTIST_SHARE = 0.15


def action(fn):
    """Decorator to auto-register actions to whitelist"""
    REGISTRY[fn.__name__] = fn
    return fn


@action
def clear_cache(**kwargs: str) -> None:
    """Action: clear processed artwork cache."""
    _clear_cache_util(**kwargs)


@action
def clear_label(id: int | str, **kwargs: str) -> None:
    """
    Clear a fadelabel register. Sanctioned for window load only (the arriving
    window owns the register); mid-session skin-side clears violate the
    single-writer doctrine.
    """
    _clear_label_util(id)


@action
def container_move(offset: str, **kwargs: str) -> None:
    """
    Move a container by an offset, clamping at the list ends when wrap is
    false. Targets the id param, else the focused control.

    :param id: Container id; falls back to focused control when absent.
    :param offset: Signed move distance (default 1).
    :param wrap: 'false' to clamp at both ends; otherwise Kodi's native wrap.
    """
    container = kwargs.get("id") or focused_control_id()
    if not container:
        return

    offset = to_int(kwargs.get("offset"), 1)
    if kwargs.get("wrap") == "false":
        pos = to_int(infolabel(f"Container({container}).CurrentItem"), 0)
        total = to_int(infolabel(f"Container({container}).NumItems"), 0)
        if not (1 <= pos + offset <= total):
            return

    log.execute(f"Control.Move({container},{offset})")


@action
def container_reset(id: str, **kwargs: str) -> None:
    """
    Select a container's first item in the topmost dialog or window, without
    focusing it: a kept-in-memory window reopens on each list's last selection.

    :param id: Container id.
    """
    window = xbmcgui.Window(topmost_window_id())
    window.getControl(int(id)).selectItem(0)


@action
def delete_orphans(**kwargs: str) -> None:
    """
    Remove child entries whose parent is missing or ineligible, then
    rebuild outputs and reload the skin if anything was removed.
    """
    child_mapping = kwargs.get("child_mapping")
    if not child_mapping:
        log.error("delete_orphans: 'child_mapping' kwarg is required")
        return

    from resources.lib.builders.runtime import RuntimeStateManager

    removed = RuntimeStateManager.from_templates().delete_orphans(
        child_mapping,
        require_parent=kwargs.get("require_parent", "").lower() == "true",
    )
    log.info(
        f"delete_orphans: removed {removed} entr"
        f"{'y' if removed == 1 else 'ies'} from '{child_mapping}'"
    )
    if removed:
        if infolabel("Window(home).Property(active_editor_name)"):
            # Editor session live: its close-time snapshot diff sees these
            # deletions and rebuilds once — a reload here lands under the modal.
            log.info("delete_orphans: editor session live — rebuild deferred")
        else:
            from resources.lib.builders.build_elements import BuildElements

            BuildElements().run()
            log.execute("ReloadSkin()")


@action
def dialog_yesno(heading: str, message: str, **kwargs: str) -> None:
    """
    Opens a yes/no dialog and runs a set of Kodi actions based on the result.

    :param heading: Dialog heading.
    :param message: Dialog body text.
    :param yes_actions: Pipe-separated string of built-in actions if "Yes" selected.
    :param no_actions: Pipe-separated string of actions if "No" selected.
    """
    yes_actions = kwargs.get("yes_actions", "").split("|")
    no_actions = kwargs.get("no_actions", "Null").split("|")

    if xbmcgui.Dialog().yesno(heading, message):
        for action in yes_actions:
            log.execute(action)
    else:
        for action in no_actions:
            log.execute(action)


@action
def dynamic_settings_window(**kwargs: str) -> None:
    """
    Opens a dynamic settings window as a modal dialog and collects
    any static and dynamic controls that have been expanded from
    skinner templates and tagged with this window's name.
    """
    from resources.lib.windows.dynamiceditor import DynamicEditor

    if not (mapping := kwargs.get("mapping")):
        log.error("dynamic_settings_window: 'mapping' kwarg is required")
        return

    controls_from_raw = kwargs.get("controls_from", "")
    controls_from = (
        [m.strip() for m in controls_from_raw.split(",") if m.strip()]
        if controls_from_raw
        else []
    )
    name = kwargs.get("name", "dynamic_window")
    host = kwargs.get("host")
    host_focus = kwargs.get("host_focus")
    focus_item = kwargs.get("focus_item")
    parent_filter = kwargs.get("parent")
    suffix = f"_{parent_filter}" if parent_filter else ""
    mapping_slot = f"current_mapping{suffix}"

    previous_editor = infolabel("Window(home).Property(active_editor_name)")
    previous_label = infolabel("Window(home).Property(editor_label)")
    window_property("active_editor_name", value=name)
    window_property(mapping_slot, value=mapping)

    myWindow = DynamicEditor(f"{name}.xml", SKINXML, "Default", "")
    myWindow.parent_filter = parent_filter
    myWindow.mapping = mapping
    myWindow.host = host
    myWindow.host_focus = host_focus
    myWindow.focus_item = focus_item
    myWindow.controls_from = controls_from
    rebuilt = False
    try:
        myWindow.doModal()

        # Host exit router: recorded exit target ⇒ forward to it; none +
        # host still active ⇒ back-exit, before the rebuild reload can
        # re-fire the host's forwarding onload.
        if not previous_editor and host:
            target = infolabel("Window(home).Property(host_exit_target)")
            # doModal returns ~200ms before GUI deinit; while any dialog
            # lives, builtins/infolabels address the corpse — wait it out.
            monitor = xbmc.Monitor()
            for _ in range(50):
                if xbmcgui.getCurrentWindowDialogId() == 9999:
                    break
                if monitor.waitForAbort(0.02):
                    return
            window_property("host_exit_target")
            log.debug(f"dynamic_settings_window: host exit — target='{target}'")
            if target:
                # Arriving window must not see a live editor_label; a Back exit
                # keeps it until the finally so the shell strip stays hidden.
                window_property("editor_label", value=previous_label)
                log.execute(f"ReplaceWindow({target})")
            elif condition(f"Window.IsActive({host})"):
                log.execute("Action(Back)")

        # Rebuild if state changed during the session. Outermost editor only;
        # nested editors defer the rebuild to the enclosing editor's close.
        if not previous_editor:
            myWindow.runtime_manager.reload_state()
            if (
                myWindow.runtime_manager.runtime_state
                != myWindow._runtime_state_snapshot
            ):
                from resources.lib.builders.build_elements import BuildElements

                BuildElements().run()
                rebuilt = True
    finally:
        # Always restore properties — a stuck active_editor_name makes every
        # later top-level session look nested and silently skip rebuilds.
        # active_editor_name goes last: it reopens the host's onload gate, so
        # no new session can start (and be clobbered here) before this point.
        window_property(mapping_slot)
        window_property("editor_label", value=previous_label)
        window_property("active_editor_name", value=previous_editor)
        del myWindow

    # Posted after the restores: the reload re-inits the host, whose onload
    # starts the next session.
    if rebuilt:
        log.execute("ReloadSkin()")


@action
def play_album(**kwargs: str) -> None:
    """
    Starts playback of an album by ID.

    :param id: Album ID.
    """
    if dbid := to_int(kwargs.get("id")):
        clear_playlists()
        json_call(
            "Player.Open",
            item={"albumid": dbid},
            options={"shuffled": False},
            parent="play_album",
        )


@action
def play_album_from_track(id: str, **kwargs: str) -> None:
    """
    Plays a song's album starting from that song, in disc and track order.

    :param id: Song ID.
    """
    songid = to_int(id)
    details = json_call(
        "AudioLibrary.GetSongDetails",
        params={"properties": ["albumid"], "songid": songid},
        parent="play_album_from_track",
    )
    if not (song := details.get("result", {}).get("songdetails")):
        return

    # Sort by track is disc-aware: Kodi stores the track as (disc << 16) | track.
    songs = json_call(
        "AudioLibrary.GetSongs",
        properties=["file"],
        sort={"method": "track"},
        query_filter={"albumid": song["albumid"]},
        parent="play_album_from_track",
    )["result"].get("songs", [])
    play_files(
        [s["file"] for s in songs],
        position=[s["songid"] for s in songs].index(songid),
    )


@action
def play_items(id: str, **kwargs: str) -> None:
    """
    Plays all media items in a container by index.

    :param id: Container ID.
    :param method: "from_here" or "shuffle" for behavior control.
    :param type: "music" or "video".
    """
    method = kwargs.get("method", "")
    scope = "NoWrap" if method == "from_here" else "Absolute"
    prefix = f"Container({id}).ListItem{scope}"
    indices = range(to_int(infolabel(f"Container({id}).NumItems")))

    if kwargs.get("type", "") == "music":
        play_files(
            [
                url
                for i in indices
                if (url := infolabel(f"{prefix}({i}).FileNameAndPath"))
            ],
            shuffled=method == "shuffle",
        )
        return

    clear_playlists()
    items = []
    for i in indices:
        dbtype = infolabel(f"{prefix}({i}).DBType")
        dbid = to_int(infolabel(f"{prefix}({i}).DBID"))
        if dbid and dbtype in ("movie", "episode", "musicvideo"):
            items.append({f"{dbtype}id": dbid})
        elif url := infolabel(f"{prefix}({i}).FileNameAndPath"):
            items.append({"file": url})

    json_call(
        "Playlist.Add",
        item=items,
        params={"playlistid": 1},
        parent="play_items",
    )
    json_call(
        "Player.Open",
        item={"playlistid": 1, "position": 0},
        options={"shuffled": method == "shuffle"},
        parent="play_items",
    )


@action
def play_trailer(trailer: str, **kwargs: str) -> None:
    """
    Play a trailer, flagging it so PlayerMonitor applies trailer zoom and
    stamping the requested item so stale starts can be cancelled.

    :param trailer: Player path or plugin URL to play.
    :param item: Item label captured skin-side, atomic with the trailer URL.
    :param focus_ids: Optional comma-separated control ids that must keep focus.
    :param viewport: Optional "WxH" trailer region; enables aspect zoom.
    :param source_prefix: Optional container id or infolabel prefix of the item.
    :param window: Optional name of the window or page the trailer plays in.
    """
    if not trailer:
        return

    window_property("trailer_state", value="pending")
    window_property("trailer_pending_since", value=str(time.time()))
    window_property("trailer_viewport", value=kwargs.get("viewport", ""))
    window_property("trailer_source", value=kwargs.get("source_prefix", ""))
    window_property("trailer_item", value=kwargs.get("item", ""))
    window_property("trailer_focus_ids", value=kwargs.get("focus_ids", ""))
    window_property("trailer_window", value=kwargs.get("window", ""))
    log.execute(f'PlayMedia("{trailer}",1,noresume)')


@action
def focus(target: str, **kwargs: str) -> None:
    """
    Focuses a control, retrying until focus lands or a timeout expires.
    Optionally first moves a container's selection to the item whose
    property matches a value, probed live by absolute position.

    :param target: Control ID to focus.
    :param select_container: Container whose selection to move first.
    :param select_property: Item property to match in the container.
    :param select_value: Property value identifying the item.
    :param timeout: Retry window in milliseconds, defaults to 500.
    """
    container = kwargs.get("select_container")
    prop = kwargs.get("select_property")
    value = kwargs.get("select_value")
    if container and prop and value:
        position = container_position(container, prop, value)
        if position is None:
            log.debug(f"focus → no item with {prop}={value} in {container}")
            return
        log.execute(f"SetFocus({container},{position},absolute)")
    monitor = xbmc.Monitor()
    remaining = max(to_int(kwargs.get("timeout", "500"), 500) // 20, 1)
    while remaining:
        log.execute(f"SetFocus({target})")
        if monitor.waitForAbort(0.02):
            return
        if condition(f"Control.HasFocus({target})"):
            return
        remaining -= 1


def _info_item(key: str) -> xbmcgui.ListItem | None:
    """
    Build the ListItem Dialog().info() resolves to the library item a trail key
    names. Seasons are left out: Python can't set a tag's show or season id.

    :param key: "dbtype:dbid".
    :return: ListItem, or None for another type or an item not in the library.
    """
    dbtype, _, dbid = key.partition(":")
    dbid = to_int(dbid)
    if dbtype in ("album", "artist"):
        item = xbmcgui.ListItem(path=f"musicdb://{dbtype}s/{dbid}/")
        item.setIsFolder(True)
        item.getMusicInfoTag().setDbId(dbid, dbtype)
        return item
    if dbtype not in _INFO_DETAILS:
        return None
    details = json_call(
        _INFO_DETAILS[dbtype],
        properties=["title", "plot" if dbtype == "set" else "file"],
        params={f"{dbtype}id": dbid},
        parent="info",
    )
    if not (found := details.get("result", {}).get(f"{dbtype}details")):
        return None
    if dbtype == "song":
        item = xbmcgui.ListItem(found["title"], path=found["file"])
        item.getMusicInfoTag().setDbId(dbid, dbtype)
        return item
    # Kodi reads movies, shows and episodes back by dbid and music videos by
    # file; a set shows this tag as built, art from the library by dbid.
    path = f"videodb://movies/sets/{dbid}/" if dbtype == "set" else found["file"]
    item = xbmcgui.ListItem(found["title"], path=path)
    item.setIsFolder(dbtype in ("set", "tvshow"))
    tag = item.getVideoInfoTag()
    tag.setDbId(dbid)
    tag.setMediaType(dbtype)
    tag.setTitle(found["title"])
    if dbtype == "set":
        tag.setPlot(found["plot"])
        tag.setSetId(dbid)
    return item


def _show_info(item: xbmcgui.ListItem | None, key: str = "") -> None:
    """
    Force-close the open info dialogs, then show info for item (None only closes).
    Dialog().info() blocks until that dialog closes; if Kodi never opened it,
    the hop ends here.

    :param item: ListItem from _info_item, or None.
    :param key: The item's trail key, which the dialog's onload records.
    """
    for dialog in _INFO_DIALOGS:
        if condition(f"Window.IsVisible({dialog})"):
            log.execute(f"Dialog.Close({dialog},true)", wait=True)
    if item:
        xbmcgui.Dialog().info(item)
        # no onload recorded the key: Kodi declined the item, so uncover the window
        if infolabel("Window(home).Property(info_current)") != key:
            window_property("info_hop")


@action
def info(dbtype: str, dbid: str, **kwargs: str) -> None:
    """
    Replace the open info dialog with a library item's info (an infoscreen hop).
    An item that can't be opened clears info_hop and leaves the dialog open.

    :param dbtype: Library media type (not season).
    :param dbid: Library id.
    """
    key = f"{dbtype}:{dbid}"
    if item := _info_item(key):
        _show_info(item, key)
    else:
        window_property("info_hop")


@action
def info_back(**kwargs: str) -> None:
    """
    Pop the infoscreen trail to its newest openable item and show it. With none,
    clear info_hop and close, so the dialog's unload clears the trail.
    """
    current = infolabel("Window(home).Property(info_current)")
    trail = infolabel("Window(home).Property(info_trail)").split("|")
    for i, key in enumerate(trail):
        if key != current and (item := _info_item(key)):
            window_property("info_trail", "|".join(trail[i + 1 :]))
            _show_info(item, key)
            return
    window_property("info_hop")
    _show_info(None)


@action
def rate_song(id: str = "", rating: str = "", **kwargs: str) -> None:
    """
    Sets a song's user rating; Kodi updates the playing song's tag itself. Then
    bumps liked_songs_version, which liked songs lists carry in their URL, since
    an empty list ignores the library's own update announcement.

    :param id: Song ID (defaults to ListItem.DBID).
    :param rating: 0-10, 0 clears it (defaults to Skin.String(like_threshold)).
    """
    json_call(
        "AudioLibrary.SetSongDetails",
        params={
            "songid": to_int(id or infolabel("ListItem.DBID")),
            "userrating": to_int(rating or infolabel("Skin.String(like_threshold)")),
        },
        parent="rate_song",
    )
    window_property("liked_songs_version", value=str(time.time_ns()))


@action
def roll_seed(prop: str, window_id: int | str = 10000, **kwargs: str) -> None:
    """
    Set a fresh random seed into the named window property.

    :param prop: Window property name to write the seed into.
    :param window_id: ID of the Kodi window, defaults to 10000 for home.
    """
    if not prop:
        log.debug("roll_seed → 'prop' kwarg is required")
        return
    window_property(
        prop, value=str(random.randrange(2**31)), window_id=to_int(window_id, 10000)
    )


@action
def seed_keyboard_layout(layout: str | None = None, **kwargs: str) -> None:
    """
    Reseed the keyboard mapping from a Kodi keyboardlayout, chosen via
    dialog when not passed. The editor's close-time snapshot comparison
    handles rebuild and reload.

    :param layout: Kodi layout identifier; prompts with a picker when absent.
    """
    from resources.lib.builders.runtime import RuntimeStateManager
    from resources.lib.shared.keyboard import keyboard_layout_trees, layout_characters

    trees = keyboard_layout_trees()
    if layout is None:
        choices = [
            f"{element.get('language')} {element.get('layout')}"
            for _, tree in sorted(trees.items())
            for element in tree.getroot().findall("layout")
            if not element.get("codingtable")
        ]
        picked = xbmcgui.Dialog().select(ADDON.getLocalizedString(32400), choices)
        if picked < 0:
            return
        layout = choices[picked]

    manager = RuntimeStateManager.from_templates()
    manager.reseed_entries("keyboard", layout_characters(layout, trees))


@action
def set_edit(id: str, **kwargs: str) -> None:
    """
    Focuses a Kodi edit control and sets its text via Input.SendText.

    :param id: Control ID to write to.
    :param return_id: Optional control to refocus after the write.
    :param text: Text payload for set/append modes.
    :param mode: set (default) | append | backspace | space | clear.
    """
    mode = kwargs.get("mode", "set")
    text = str(kwargs.get("text", ""))
    current = infolabel(f"Control.GetLabel({id}).index(1)")
    if mode == "append":
        text = current + text
    elif mode == "backspace":
        text = current[:-1]
    elif mode == "space":
        text = current + " "
    elif mode == "clear":
        text = ""
    window_property("edit_scripted_write", value="true")
    log.execute(f"SetFocus({id})", wait=True)
    json_call("Input.SendText", params={"text": text, "done": True}, parent="set_edit")
    return_id = kwargs.get("return_id")
    if return_id:
        log.execute(f"SetFocus({return_id})", wait=True)
    window_property("edit_scripted_write")


@action
def set_search_query(id: str, **kwargs: str) -> None:
    """
    Mirror an edit control's text into the search_query property, cleared
    below min_length. Sole writer for the search rails' path values.

    :param id: Edit control id to read.
    :param min_length: Minimum characters before the query is published.
    """
    min_length = to_int(kwargs.get("min_length"), 3)
    text = infolabel(f"Control.GetLabel({id}).index(1)")
    window_property("search_query", value=text if len(text) >= min_length else False)


def _year_rule(year: str) -> dict:
    """
    Smart playlist rule for one year's songs.

    :param year: Year, as a string.
    :return: Smart playlist rule for songs from that year.
    """
    return {"field": "year", "operator": "is", "value": year}


def _random_songs(query_filter: dict, limit: int | None = None) -> list[dict]:
    """
    Fetches songs in random order, with their files, artists and genres.

    :param query_filter: AudioLibrary.GetSongs filter.
    :param limit: Maximum number of songs; None for all.
    :return: Song dicts with songid, file, artist and genre.
    """
    return json_call(
        "AudioLibrary.GetSongs",
        properties=["file", "artist", "genre"],
        sort={"method": "random"},
        limit=limit,
        query_filter=query_filter,
        parent="music",
    )["result"].get("songs", [])


def _play_songs(songs: list[dict]) -> None:
    """
    Replaces whatever is playing: queues the songs in order and plays from the
    first. Call it once the songs are fetched.

    :param songs: Song dicts with file.
    """
    play_files([s["file"] for s in songs])


def _mix_seed(type: str, dbid: int) -> dict | None:
    """
    The song a mix starts from: the song itself, or one of the five most
    played songs of the album or artist.

    :param type: song, album or artist.
    :param dbid: Library ID of the item.
    :return: Song dict with songid, file, artist and genre, or None.
    """
    if type == "song":
        return (
            json_call(
                "AudioLibrary.GetSongDetails",
                properties=["file", "artist", "genre"],
                params={"songid": dbid},
                parent="start_mix",
            )
            .get("result", {})
            .get("songdetails")
        )
    top = json_call(
        "AudioLibrary.GetSongs",
        properties=["file", "artist", "genre"],
        sort={"method": "playcount", "order": "descending"},
        limit=5,
        query_filter={_LIBRARY_ITEMS[type]: dbid},
        parent="start_mix",
    )["result"].get("songs")
    return random.choice(top) if top else None


def _spread(own: list, others: list) -> list:
    """
    Spreads own evenly through others, keeping the order of each.

    :param own: Items to spread.
    :param others: Items to spread them through.
    :return: Merged list.
    """
    step = (len(others) + 1) / (len(own) + 1)
    keyed = [*enumerate(others), *((n * step - 0.5, s) for n, s in enumerate(own, 1))]
    return [s for _, s in sorted(keyed, key=itemgetter(0))]


@action
def move_pin(
    id: str = "", type: str = "", path: str = "", offset: str = "1", **kwargs: str
) -> None:
    """
    Moves a pinned speed dial entry up (negative offset) or down.

    :param id: Library ID.
    :param type: album, artist or song; anything else is a playlist.
    :param path: Playlist path.
    :param offset: Positions to move.
    """
    SpeedDial().move(dial_entry(type, id, path), to_int(offset))


@action
def pin(id: str = "", type: str = "", path: str = "", **kwargs: str) -> None:
    """
    Pins an artist, album, song or music playlist to the front of speed dial.

    :param id: Library ID.
    :param type: album, artist or song; anything else is a playlist.
    :param path: Playlist path.
    """
    SpeedDial().pin(dial_entry(type, id, path))


@action
def shuffle(id: str = "", type: str = "artist", path: str = "", **kwargs: str) -> None:
    """
    Plays an artist, album, genre, year or music playlist in random order.

    :param id: Library ID; the year itself for type year.
    :param type: artist, album, genre or year; anything else plays path.
    :param path: Playlist path, for types without a library ID.
    """
    mark_source(None if type in ("genre", "year") else dial_entry(type, id, path))
    if type == "year":
        _play_songs(_random_songs(_year_rule(id)))
        return
    clear_playlists()
    item = (
        {_LIBRARY_ITEMS[type]: to_int(id)}
        if type in _LIBRARY_ITEMS
        else {"directory": path, "media": "music"}
    )
    json_call("Player.Open", item=item, options={"shuffled": True}, parent="shuffle")


@action
def shuffle_artist(id: str = "", **kwargs: str) -> None:
    """
    Starts shuffled playback for an artist; kept for skins that call it.

    :param id: Artist ID.
    """
    shuffle(id=id, type="artist")


@action
def start_mix(id: str = "", type: str = "song", **kwargs: str) -> None:
    """
    Plays a random mix. A genre or year mix is its own songs; a song, album or
    artist mix starts from a seed song, then songs sharing its genres, about
    MIX_ARTIST_SHARE of them by the seed's artists, spread through the list.

    :param id: Library ID (defaults to ListItem.DBID); the year itself for year.
    :param type: song, album, artist, genre or year.
    """
    if type in ("genre", "year"):
        mark_source(None)
        rule = {"genreid": to_int(id)} if type == "genre" else _year_rule(id)
        _play_songs(_random_songs(rule, MIX_SIZE))
        return
    dbid = to_int(id or infolabel("ListItem.DBID"))
    if not (seed := _mix_seed(type, dbid)):
        return
    mark_source(dial_entry(type, dbid))

    genres = seed["genre"]
    by_artist = {"field": "artist", "operator": "is", "value": seed["artist"]}
    own_size = round(MIX_SIZE * MIX_ARTIST_SHARE) if genres else MIX_SIZE
    own = [
        s for s in _random_songs(by_artist, own_size) if s["songid"] != seed["songid"]
    ][: own_size - 1]
    others = (
        _random_songs(
            {
                "and": [
                    {"field": "genre", "operator": "is", "value": genres},
                    {**by_artist, "operator": "isnot"},
                ]
            },
            MIX_SIZE - 1 - len(own),
        )
        if genres
        else []
    )
    _play_songs([seed, *_spread(own, others)])


REGISTRY["play_radio"] = start_mix  # former name, kept for skins that call it


@action
def subtitle_limiter(lang: str, user_trigger: bool | str = True, **kwargs: str) -> None:
    """
    Switches to preferred subtitle stream or toggles through them.

    :param lang: Preferred language (e.g., "en").
    :param user_trigger: If True, toggles on/off if already active.
    """
    if condition("VideoPlayer.HasSubtitles"):
        player = xbmc.Player()
        subtitles = []
        current_subtitle = player.getSubtitles()
        subtitles = player.getAvailableSubtitleStreams()
        if lang not in current_subtitle or (
            user_trigger and condition("!VideoPlayer.SubtitlesEnabled")
        ):
            try:
                index = subtitles.index(lang)
            except ValueError as error:
                log.debug(
                    f"subtitle_limiter: Error - Preferred subtitle stream ({lang}) not "
                    f"available, toggling through available streams instead → {error}",
                )
                log.execute("Action(NextSubtitle)")
            else:
                player.setSubtitleStream(index)
                log.debug(
                    f"subtitle_limiter: Switching to subtitle stream {index} in "
                    f"preferred language: {lang}"
                )
        elif condition("VideoPlayer.SubtitlesEnabled") and user_trigger:
            log.execute("Action(ShowSubtitles)")
    else:
        log.debug("subtitle_limiter: Error - Playing video has no subtitles")


@action
def tmdb_test(**kwargs: str) -> None:
    """
    Verify the configured TMDb token by making a test request.
    Reports success or failure via notification.
    """
    from resources.lib.apis.tmdb.client import get_tmdb_client

    client = get_tmdb_client()
    if not client:
        xbmcgui.Dialog().notification(
            ADDON.getLocalizedString(32000),
            ADDON.getLocalizedString(32208),
            time=4000,
        )
        return

    result = client.get_json("/configuration")
    if result and "images" in result:
        xbmcgui.Dialog().notification(
            ADDON.getLocalizedString(32000),
            ADDON.getLocalizedString(32209),
            time=4000,
        )
    else:
        xbmcgui.Dialog().notification(
            ADDON.getLocalizedString(32000),
            ADDON.getLocalizedString(32210),
            time=4000,
        )


@action
def toggle_addon(id: str, **kwargs: str) -> None:
    """
    Enables or disables an addon and shows a notification.

    :param id: Addon ID.
    """
    if condition(f"System.AddonIsEnabled({id})"):
        json_call(
            "Addons.SetAddonEnabled",
            params={"addonid": id, "enabled": False},
            parent="toggle_addon",
        )
        xbmcgui.Dialog().notification(id, ADDON.getLocalizedString(32205))
    else:
        json_call(
            "Addons.SetAddonEnabled",
            params={"addonid": id, "enabled": True},
            parent="toggle_addon",
        )
        xbmcgui.Dialog().notification(id, ADDON.getLocalizedString(32206))


@action
def unpin(id: str = "", type: str = "", path: str = "", **kwargs: str) -> None:
    """
    Unpins a speed dial entry.

    :param id: Library ID.
    :param type: album, artist or song; anything else is a playlist.
    :param path: Playlist path.
    """
    SpeedDial().unpin(dial_entry(type, id, path))


@action
def rebuild(**kwargs: str) -> None:
    """
    Rebuild builder outputs and reload the skin. Regenerates output XML,
    seeds missing runtime state mappings, and refreshes the resolver cache;
    existing runtime state is preserved unless reset is requested.

    :param reset: 'true' to delete runtime state and outputs, then rebuild fresh.
    """
    from resources.lib.builders.build_elements import BuildElements

    reset = kwargs.get("reset") == "true"
    if reset:
        reset_dev_state()
        ADDON.setSettingBool("dev_reset", False)

    BuildElements().run()

    log.execute("ReloadSkin()")
    xbmcgui.Dialog().notification(
        ADDON.getLocalizedString(32000),
        ADDON.getLocalizedString(32207 if reset else 32211),
        time=4000,
    )
