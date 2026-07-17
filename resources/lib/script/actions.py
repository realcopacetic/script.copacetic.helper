# author: realcopacetic

import random
import time

import xbmc

from resources.lib.shared import logger as log
from resources.lib.shared.utilities import ADDON, DIALOG, SKINXML
from resources.lib.shared.utilities import clear_cache as _clear_cache_util
from resources.lib.shared.utilities import (
    clear_playlists,
    condition,
    container_position,
    focused_control_id,
    infolabel,
    json_call,
    reset_dev_state,
    skin_string,
    to_int,
    window_property,
)

REGISTRY = {}


def action(fn):
    """Decorator to auto-register actions to whitelist"""
    REGISTRY[fn.__name__] = fn
    return fn


@action
def clear_cache(**kwargs):
    """Action: clear processed artwork cache."""
    _clear_cache_util(**kwargs)


@action
def clean_filename(label=False, **kwargs):
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
def clear_label(id, **kwargs):
    """
    Clear a fadelabel register. Sanctioned for window-unload only —
    mid-session skin-side clears violate the single-writer doctrine.
    """
    from resources.lib.shared.utilities import clear_label

    clear_label(id, hide=False)


@action
def container_move(offset: str, **kwargs: dict) -> None:
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
def delete_orphans(**kwargs):
    """
    Remove child entries whose parent is missing or ineligible, then
    rebuild outputs and reload the skin if anything was removed.
    """
    child_mapping = kwargs.get("child_mapping")
    if not child_mapping:
        log.error("delete_orphans: 'child_mapping' kwarg is required")
        return

    from resources.lib.builders.build_elements import BuildElements

    build = BuildElements()
    removed = build.runtime_manager.delete_orphans(
        child_mapping,
        require_parent=kwargs.get("require_parent", "").lower() == "true",
    )
    log.info(
        f"delete_orphans: removed {removed} entr"
        f"{'y' if removed == 1 else 'ies'} from '{child_mapping}'"
    )
    if removed:
        build.run()
        log.execute("ReloadSkin()")


@action
def dialog_yesno(heading, message, **kwargs):
    """
    Opens a yes/no dialog and runs a set of Kodi actions based on the result.

    :param heading: Dialog heading.
    :param message: Dialog body text.
    :param yes_actions: Pipe-separated string of built-in actions if "Yes" selected.
    :param no_actions: Pipe-separated string of actions if "No" selected.
    """
    yes_actions = kwargs.get("yes_actions", "").split("|")
    no_actions = kwargs.get("no_actions", "Null").split("|")

    if DIALOG.yesno(heading, message):
        for action in yes_actions:
            log.execute(action)
    else:
        for action in no_actions:
            log.execute(action)


@action
def dynamic_settings_window(**kwargs):
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
    parent_filter = kwargs.get("parent")
    suffix = f"_{parent_filter}" if parent_filter else ""
    mapping_slot = f"current_mapping{suffix}"

    previous_editor = infolabel("Window(home).Property(active_editor_name)")
    window_property("active_editor_name", value=name)
    window_property(mapping_slot, value=mapping)

    myWindow = DynamicEditor(f"{name}.xml", SKINXML, "Default", "")
    myWindow.parent_filter = parent_filter
    myWindow.mapping = mapping
    myWindow.controls_from = controls_from
    try:
        myWindow.doModal()

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
        del myWindow


@action
def globalsearch_input(**kwargs):
    """
    Prompts the user for a global search query and activates the search window.
    Stores the result in Skin String 'globalsearch'.
    """
    kb = xbmc.Keyboard(
        infolabel("$INFO[Skin.String(globalsearch)]"), infolabel("$LOCALIZE[137]")
    )
    kb.doModal()
    if kb.isConfirmed():
        text = kb.getText()
        skin_string("globalsearch", value=text)
        log.execute("ActivateWindow(1180)")


@action
def hex_contrast_check(**kwargs):
    """
    Calculates contrast for a hex color and sets Skin.String(Accent_Color_Contrast).

    :param hex: Hex string (e.g., "#ffffff" or "ffffffff").
    :return: "light" or "dark" contrast hint.
    """
    from resources.lib.art.editor import ImageEditor

    image = ImageEditor()
    hex = kwargs.get("hex", "")

    if hex:
        r = int(hex[2:-4], 16)
        g = int(hex[4:-2], 16)
        b = int(hex[6:], 16)
        rgb = (r, g, b)
        luminosity = image.return_luminosity(rgb)
        best_contrast = "dark" if luminosity > 0.179 else "light"

        log.execute(f"Skin.SetString(Accent_Color_Contrast,{best_contrast})")


@action
def jumpbutton(**kwargs):
    """Updates the position of the jump scrollbar indicator."""
    from resources.lib.plugin.geometry import PlacementOpts
    from resources.lib.plugin.helpers import JumpButton

    jump = JumpButton()
    jump.update(
        sortletter=kwargs.get("sortletter", ""),
        scroll_id=kwargs.get("scroll_id", ""),
        opts=PlacementOpts.from_params(kwargs),
    )


@action
def play_album(**kwargs):
    """
    Starts playback of an album by ID.

    :param id: Album ID (int).
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
def play_album_from_track(**kwargs):
    """
    Plays an album starting from a specific track.

    :param id: Song ID to look up album.
    :param track: Track number to start from (1-based).
    """
    clear_playlists()

    dbid = int(kwargs.get("id", False))
    track = int(kwargs.get("track", False)) - 1

    if dbid:
        json_response = json_call(
            "AudioLibrary.GetSongDetails",
            params={"properties": ["albumid"], "songid": dbid},
            parent="play_album_from_track",
        )

    if json_response["result"].get("songdetails", None):
        albumid = json_response["result"]["songdetails"]["albumid"]

    json_call(
        "Player.Open",
        item={"albumid": albumid},
        options={"shuffled": False},
        parent="play_album_from_track",
    )

    if track > 0:
        json_call("Player.GoTo", params={"playerid": 0, "to": track})


@action
def play_items(id, **kwargs):
    """
    Plays all media items in a container by index.

    :param id: Container ID.
    :param method: "from_here" or "shuffle" for behavior control.
    :param type: "music" or "video".
    """
    clear_playlists()

    method = kwargs.get("method", "")
    shuffled = True if method == "shuffle" else False
    playlistid = 0 if kwargs.get("type", "") == "music" else 1

    if method == "from_here":
        method = f"Container({id}).ListItemNoWrap"
    else:
        method = f"Container({id}).ListItemAbsolute"

    for count in range(int(infolabel(f"Container({id}).NumItems"))):
        try:
            dbid = int(xbmc.getInfoLabel(f"{method}({count}).DBID"))
            url = xbmc.getInfoLabel(f"{method}({count}).Filenameandpath")
        except ValueError:
            break
        else:
            if condition(f"String.IsEqual({method}({count}).DBType,movie)"):
                media_type = "movie"
            elif condition(f"String.IsEqual({method}({count}).DBType,episode)"):
                media_type = "episode"
            elif condition(f"String.IsEqual({method}({count}).DBType,song)"):
                media_type = "song"
            elif condition(f"String.IsEqual({method}({count}).DBType,musicvideo)"):
                media_type = "musicvideo"

            if media_type and dbid:
                json_call(
                    "Playlist.Add",
                    item={f"{media_type}id": dbid},
                    params={"playlistid": playlistid},
                    parent="play_items",
                )
            elif url:
                json_call(
                    "Playlist.Add",
                    item={"file": url},
                    params={"playlistid": playlistid},
                    parent="play_items",
                )

    json_call(
        "Playlist.GetItems", params={"playlistid": playlistid}, parent="play_items"
    )

    json_call(
        "Player.Open",
        item={"playlistid": playlistid, "position": 0},
        options={"shuffled": shuffled},
        parent="play_items",
    )


@action
def play_radio(**kwargs):
    """
    Builds a randomized genre-based playlist based on current song ID.

    :param id: Optional song ID (defaults to ListItem.DBID).
    """
    import random

    clear_playlists()

    dbid = int(kwargs.get("id", xbmc.getInfoLabel("ListItem.DBID")))

    json_response = json_call(
        "AudioLibrary.GetSongDetails",
        params={"properties": ["genre"], "songid": dbid},
        parent="play_radio",
    )

    if json_response["result"]["songdetails"].get("genre", None):
        genre = json_response["result"]["songdetails"]["genre"]
        genre = random.choice(genre)

    if genre:
        json_call(
            "Playlist.Add",
            item={"songid": dbid},
            params={"playlistid": 0},
            parent="play_radio",
        )

        json_response = json_call(
            "AudioLibrary.GetSongs",
            params={"properties": ["genre"]},
            sort={"method": "random"},
            limit=24,
            query_filter={"genre": genre},
            parent="play_radio",
        )

        for count in json_response["result"]["songs"]:
            if count.get("songid", None):
                songid = int(count["songid"])

                json_call(
                    "Playlist.Add",
                    item={"songid": songid},
                    params={"playlistid": 0},
                    parent="play_radio",
                )

        json_call("Playlist.GetItems", params={"playlistid": 0}, parent="play_radio")

        json_call(
            "Player.Open", item={"playlistid": 0, "position": 0}, parent="play_radio"
        )


@action
def play_trailer(trailer, **kwargs):
    """
    Play a trailer, flagging it so PlayerMonitor applies trailer zoom and
    stamping the requested item so stale starts can be cancelled.

    :param trailer: Player path or plugin URL to play.
    :param item: Item label captured skin-side, atomic with the trailer URL.
    :param item: Item label captured skin-side, atomic with the trailer URL.
    :param viewport: Optional "WxH" trailer region; enables aspect zoom.
    :param source_prefix: Optional infolabel prefix for AR lookup.
    """
    if not trailer:
        return

    source = (kwargs.get("source_prefix") or "").strip()
    prefix = f"Container({source}).ListItem" if source.isdigit() else source
    item = kwargs.get("item") or (infolabel(f"{prefix}.Label") if prefix else "")
    window_property("trailer_state", value="pending")
    window_property("trailer_pending_since", value=str(time.time()))
    window_property("trailer_viewport", value=kwargs.get("viewport", ""))
    window_property("trailer_source", value=source)
    window_property("trailer_item", value=item)
    log.execute(f"PlayMedia({trailer},1,noresume)")


@action
def focus(target, **kwargs):
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
def rate_song(**kwargs):
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
def roll_seed(prop, window_id=10000, **kwargs):
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
def set_edit(id, **kwargs):
    """
    Focuses a Kodi control, sends text, and confirms it.

    :param id: Control ID to focus.
    :param return_id: Unused, reserved for future use.
    :param text: Text to send.
    """
    text = str(kwargs.get("text", ""))
    log.execute(f"SetFocus({id})")
    xbmc.Monitor().waitForAbort(0.05)
    json_call("Input.SendText", params={"text": text, "done": True}, parent="set_edit")


@action
def shuffle_artist(**kwargs):
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
def subtitle_limiter(lang, user_trigger=True, **kwargs):
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
                    f"subtitle_limiter: Error - Preferred subtitle stream ({lang}) not available, toggling through available streams instead → {error}",
                )
                log.execute("Action(NextSubtitle)")
            else:
                player.setSubtitleStream(index)
                log.debug(
                    f"subtitle_limiter: Switching to subtitle stream {index} in preferred language: {lang}"
                )
        elif condition("VideoPlayer.SubtitlesEnabled") and user_trigger:
            log.execute("Action(ShowSubtitles)")
    else:
        log.debug("subtitle_limiter: Error - Playing video has no subtitles")


@action
def tmdb_test(**kwargs):
    """
    Verify the configured TMDb token by making a test request.
    Reports success or failure via notification.
    """
    from resources.lib.apis.tmdb.client import get_tmdb_client

    client = get_tmdb_client()
    if not client:
        DIALOG.notification(
            ADDON.getLocalizedString(32000),
            ADDON.getLocalizedString(32208),
            time=4000,
        )
        return

    result = client.get_json("/configuration")
    if result and "images" in result:
        DIALOG.notification(
            ADDON.getLocalizedString(32000),
            ADDON.getLocalizedString(32209),
            time=4000,
        )
    else:
        DIALOG.notification(
            ADDON.getLocalizedString(32000),
            ADDON.getLocalizedString(32210),
            time=4000,
        )


@action
def toggle_addon(id, **kwargs):
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
        DIALOG.notification(id, ADDON.getLocalizedString(32205))
    else:
        json_call(
            "Addons.SetAddonEnabled",
            params={"addonid": id, "enabled": True},
            parent="toggle_addon",
        )
        DIALOG.notification(id, ADDON.getLocalizedString(32206))


@action
def rebuild(**kwargs):
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
    DIALOG.notification(
        ADDON.getLocalizedString(32000),
        ADDON.getLocalizedString(32207 if reset else 32211),
        time=4000,
    )
