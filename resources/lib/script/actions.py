# author: realcopacetic

import random
import time

import xbmc
import xbmcgui

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import (
    ADDON,
    SKINXML,
)
from resources.lib.shared.utilities import clear_cache as _clear_cache_util
from resources.lib.shared.utilities import clear_label as _clear_label_util
from resources.lib.shared.utilities import (
    clear_playlists,
    condition,
    container_position,
    focused_control_id,
    infolabel,
    json_call,
    reset_dev_state,
    to_int,
    window_property,
)

REGISTRY = {}


def action(fn):
    """Decorator to auto-register actions to whitelist"""
    REGISTRY[fn.__name__] = fn
    return fn


@action
def clear_cache(**kwargs: str) -> None:
    """Action: clear processed artwork cache."""
    _clear_cache_util(**kwargs)


@action
def clean_filename(label: str | bool = False, **kwargs: str) -> None:
    """
    Cleans a filename by removing extensions and formatting characters.

    :param label: Optional input string. If not provided, uses ListItem.Label.
    :return: Sets the result to "Return_Label" window property.
    """
    json_response = json_call(
        "Settings.GetSettingValue",
        params={"setting": "filelists.showextensions"},
        parent="clean_filename",
    )

    subtraction = 1 if json_response["result"]["value"] is True else 0
    if not label:
        label = infolabel("$INFO[ListItem.Label]")
    count = label.count(".") - subtraction
    label = label.replace(".", " ", count).replace("_", " ").strip()

    window_property("Return_Label", value=label)


@action
def clear_label(id: int | str, **kwargs: str) -> None:
    """
    Clear a fadelabel register. Sanctioned for window-unload only —
    mid-session skin-side clears violate the single-writer doctrine.
    """
    _clear_label_util(id, hide=False)


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
            # Clear eagerly: leaving it set until the finally gates quick
            # re-entry to the host while the rebuild is still running.
            window_property("active_editor_name", value=previous_editor)

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
                log.execute("ReloadSkin()")
    finally:
        # Always restore properties — a stuck active_editor_name makes every
        # later top-level session look nested and silently skip rebuilds.
        window_property(mapping_slot)
        window_property("active_editor_name", value=previous_editor)
        window_property("editor_label", value=previous_label)
        del myWindow


@action
def play_album(**kwargs: str) -> None:
    """
    Starts playback of an album by ID.

    :param id: Album ID.
    """
    clear_playlists()

    dbid = int(kwargs.get("id", False))
    if dbid:
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
    clear_playlists()

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
        sort={"method": "track"},
        query_filter={"albumid": song["albumid"]},
        parent="play_album_from_track",
    )["result"].get("songs", [])
    songids = [s["songid"] for s in songs]
    json_call(
        "Playlist.Add",
        item=[{"songid": s} for s in songids],
        params={"playlistid": 0},
        parent="play_album_from_track",
    )
    json_call(
        "Player.Open",
        item={"playlistid": 0, "position": songids.index(songid)},
        parent="play_album_from_track",
    )


@action
def play_items(id: str, **kwargs: str) -> None:
    """
    Plays all media items in a container by index.

    :param id: Container ID.
    :param method: "from_here" or "shuffle" for behavior control.
    :param type: "music" or "video".
    """
    clear_playlists()

    method = kwargs.get("method", "")
    playlistid = 0 if kwargs.get("type", "") == "music" else 1
    scope = "NoWrap" if method == "from_here" else "Absolute"
    prefix = f"Container({id}).ListItem{scope}"

    items = []
    for i in range(to_int(infolabel(f"Container({id}).NumItems"))):
        dbtype = infolabel(f"{prefix}({i}).DBType")
        dbid = to_int(infolabel(f"{prefix}({i}).DBID"))
        if dbid and dbtype in ("movie", "episode", "musicvideo", "song"):
            items.append({f"{dbtype}id": dbid})
        elif url := infolabel(f"{prefix}({i}).FileNameAndPath"):
            items.append({"file": url})

    json_call(
        "Playlist.Add",
        item=items,
        params={"playlistid": playlistid},
        parent="play_items",
    )
    json_call(
        "Player.Open",
        item={"playlistid": playlistid, "position": 0},
        options={"shuffled": method == "shuffle"},
        parent="play_items",
    )


@action
def play_radio(**kwargs: str) -> None:
    """
    Builds a randomized genre-based playlist based on current song ID.

    :param id: Optional song ID (defaults to ListItem.DBID).
    """
    clear_playlists()

    songid = to_int(kwargs.get("id") or infolabel("ListItem.DBID"))
    details = json_call(
        "AudioLibrary.GetSongDetails",
        params={"properties": ["genre"], "songid": songid},
        parent="play_radio",
    )
    if not (genres := details.get("result", {}).get("songdetails", {}).get("genre")):
        return

    songs = json_call(
        "AudioLibrary.GetSongs",
        sort={"method": "random"},
        limit=24,
        query_filter={"genre": random.choice(genres)},
        parent="play_radio",
    )["result"].get("songs", [])
    songids = [songid, *(s["songid"] for s in songs)]
    json_call(
        "Playlist.Add",
        item=[{"songid": s} for s in songids],
        params={"playlistid": 0},
        parent="play_radio",
    )
    json_call("Player.Open", item={"playlistid": 0, "position": 0}, parent="play_radio")


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
    """
    if not trailer:
        return

    window_property("trailer_state", value="pending")
    window_property("trailer_pending_since", value=str(time.time()))
    window_property("trailer_viewport", value=kwargs.get("viewport", ""))
    window_property("trailer_source", value=kwargs.get("source_prefix", ""))
    window_property("trailer_item", value=kwargs.get("item", ""))
    window_property("trailer_focus_ids", value=kwargs.get("focus_ids", ""))
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


@action
def rate_song(**kwargs: str) -> None:
    """
    Sets the user rating for a song and updates skin string for MusicPlayer.

    :param id: Song ID.
    :param rating: Rating threshold value.
    """
    dbid = int(kwargs.get("id", xbmc.getInfoLabel("ListItem.DBID")))
    rating_threshold = int(
        kwargs.get(
            "rating", xbmc.getInfoLabel("Skin.String(Music_Rating_Like_Threshold)")
        )
    )

    json_call(
        "AudioLibrary.SetSongDetails",
        params={"songid": dbid, "userrating": rating_threshold},
        parent="rate_song",
    )

    player = xbmc.Player()
    player_dbid = (
        int(xbmc.getInfoLabel("MusicPlayer.DBID")) if player.isPlayingAudio() else None
    )

    if dbid == player_dbid:
        if rating_threshold != 0:
            window_property("MusicPlayer_UserRating", value=rating_threshold)
        else:
            window_property("MusicPlayer_UserRating")
        """
        player_path = player.getPlayingFile()
        item = xbmcgui.ListItem(path=player_path)
        musicInfoTag = item.getMusicInfoTag()
        musicInfoTag.setUserRating(rating_threshold)
        player.updateInfoTag(item)
        """


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
        picked = xbmcgui.Dialog().select("Keyboard layout", choices)
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


@action
def shuffle_artist(**kwargs: str) -> None:
    """
    Starts shuffled playback for a given artist.

    :param id: Artist ID.
    """
    clear_playlists()

    dbid = int(kwargs.get("id", False))
    json_call(
        "Player.Open",
        item={"artistid": dbid},
        options={"shuffled": True},
        parent="shuffle_artist",
    )


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
