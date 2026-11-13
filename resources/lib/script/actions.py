# author: realcopacetic

import json
import random
import time
from collections.abc import Iterable
from functools import reduce
from urllib.parse import quote

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.lib.service.trailer import (
    TrailerZoomController,
    enter_fullscreen,
    start_flight,
)
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import (
    ADDON,
    DETAILS,
    INFO_DIALOGS,
    SKINXML,
)
from resources.lib.shared.mix import (
    DAILY_ARTIST_SHARE,
    DAILY_WINDOW,
    MIX_SIZE,
    SEED_SHARE,
    artist_genres,
    mix_songs,
    random_songs,
    todays_mixes,
)
from resources.lib.shared.speed_dial import SpeedDial
from resources.lib.shared.speed_dial import entry as dial_entry
from resources.lib.shared.speed_dial import mark_source, take_source
from resources.lib.shared.streams import (
    player_streams,
    preferred_subtitle,
    subtitle_status,
)
from resources.lib.shared.utilities import clear_cache as _clear_cache_util
from resources.lib.shared.utilities import clear_label as _clear_label_util
from resources.lib.shared.utilities import (
    clear_playlists,
    condition,
    container_position,
    infolabel,
    json_call,
    notify_build_failed,
    parse_bool,
    play_files,
    reset_dev_state,
    skin_path,
    skin_string,
    to_float,
    to_int,
    topmost_window_id,
    url_decode_path,
    window_property,
)

REGISTRY = {}

_LIBRARY_ITEMS = {"album": "albumid", "artist": "artistid", "genre": "genreid"}
API_SOURCES = {
    "tmdb": ("TMDb", 32033),
    "listenbrainz": ("ListenBrainz", 32034),
    "deezer": ("Deezer", 32036),
    "theintrodb": ("TheIntroDB", 32041),
}
WAVEFORM = "visualization.waveform"
# 250 points a line (the fewest: calmer than 0, no resampling), lines in the skin's
# ghosted (Waveform draws without blending; the skin's veil of blur dims them), no
# fill (an all-zero background)
WAVEFORM_LOOK = {
    "points-per-line": 250,
    "line-thickness": 2,
    "line-red": 0.941,
    "line-green": 0.937,
    "line-blue": 0.937,
    "bg-red": 0.0,
    "bg-green": 0.0,
    "bg-blue": 0.0,
}


def action(fn):
    """Decorator to auto-register actions to whitelist"""
    REGISTRY[fn.__name__] = fn
    return fn


def _rebuild() -> bool:
    """
    Rebuild builder outputs under Window(home).Property(helper_reloading)=rebuild,
    so the skin can cover the rebuild and the reload after it, then clear it. A failed
    build clears it here (toast, raise); a caller that sends no reload clears it.

    :return: True when any output file was written.
    """
    from resources.lib.builders.build_elements import BuildElements

    window_property("helper_reloading", value="rebuild")
    try:
        return BuildElements().run()
    except Exception:
        window_property("helper_reloading")
        notify_build_failed()
        raise


def _reload_skin() -> None:
    """ReloadSkin, with helper_reloading moved on to reload."""
    window_property("helper_reloading", value="reload")
    log.execute("ReloadSkin()")


@action
def clean_image_cache(**kwargs: str) -> None:
    """
    After a yes/no on what was found, remove this device's cached images that no
    library item uses and that haven't been shown for 30 days.
    """
    from datetime import datetime, timedelta, timezone

    from resources.lib.script.library import EVERYTHING, LIBRARY, library_art

    heading = ADDON.getLocalizedString(32028)
    progress = xbmcgui.DialogProgress()
    progress.create(heading, ADDON.getLocalizedString(32224))
    used = {
        url_decode_path(url)
        for kind in LIBRARY
        for _, _, art in library_art(kind, EVERYTHING.get(kind))
        for url in art.values()
    }
    textures = json_call(
        "Textures.GetTextures",
        properties=["url", "cachedurl", "sizes"],
        parent="clean_image_cache",
    )["result"].get("textures", [])
    # lastused is sqlite's CURRENT_TIMESTAMP: UTC, "YYYY-MM-DD HH:MM:SS"
    cutoff = f"{datetime.now(timezone.utc) - timedelta(days=30):%Y-%m-%d %H:%M:%S}"
    stale = [
        texture
        for texture in textures
        if url_decode_path(texture["url"]) not in used
        and max((size["lastused"] for size in texture["sizes"]), default="") < cutoff
    ]
    files = (f"special://thumbnails/{texture['cachedurl']}" for texture in stale)
    size = sum(xbmcvfs.Stat(file).st_size() for file in files if xbmcvfs.exists(file))
    progress.close()
    if not stale:
        xbmcgui.Dialog().notification(heading, ADDON.getLocalizedString(32226))
        return
    message = ADDON.getLocalizedString(32222) % (len(stale), size / 1e6)
    if not xbmcgui.Dialog().yesno(heading, message):
        return
    progress = xbmcgui.DialogProgressBG()
    progress.create(heading)
    for index, texture in enumerate(stale):
        progress.update(100 * index // len(stale))
        json_call(
            "Textures.RemoveTexture",
            params={"textureid": texture["textureid"]},
            parent="clean_image_cache",
        )
    progress.close()
    xbmcgui.Dialog().notification(heading, ADDON.getLocalizedString(32223) % len(stale))


@action
def clear_api_cache(source: str, **kwargs: str) -> None:
    """
    After a yes/no, forget every saved answer from one web API, so each is fetched
    again when next needed.

    :param source: tmdb, listenbrainz, deezer or theintrodb.
    """
    from resources.lib.shared.sqlite import ApiCacheHandler

    name, label = API_SOURCES[source]
    heading = ADDON.getLocalizedString(label)
    if xbmcgui.Dialog().yesno(heading, ADDON.getLocalizedString(32035) % name):
        ApiCacheHandler().clear(f"{source}:%")
        xbmcgui.Dialog().notification(heading, ADDON.getLocalizedString(32230))


@action
def clear_art(type: str = "", online_only: str = "", **kwargs: str) -> None:
    """
    After a yes/no, remove the current art of every artist or album in Kodi's list,
    so refreshing them all fills it again: Kodi's scan only fills missing types.

    :param type: artists or albums; asks when empty.
    :param online_only: true to remove only web art, so local files take its place.
    """
    from resources.lib.script.library import library_art

    kinds = {
        "artists": xbmc.getLocalizedString(133),
        "albums": xbmc.getLocalizedString(132),
    }
    heading = ADDON.getLocalizedString(32025)
    if not type:
        choice = xbmcgui.Dialog().select(heading, list(kinds.values()))
        if choice < 0:
            return
        type = list(kinds)[choice]
    if not online_only:
        sources = [ADDON.getLocalizedString(32029), ADDON.getLocalizedString(32030)]
        choice = xbmcgui.Dialog().select(heading, sources)
        if choice < 0:
            return
        online_only = str(choice == 0)
    online_only = parse_bool(online_only)
    which = ADDON.getLocalizedString(32031 if online_only else 32032)
    if not xbmcgui.Dialog().yesno(
        heading, ADDON.getLocalizedString(32026) % (which, kinds[type])
    ):
        return
    # the items Kodi's Artists or Albums node lists, which its refresh-all fills again
    targets = [
        (type, item_id, label, art_types)
        for item_id, label, art in library_art(type)
        if (
            art_types := [
                art_type
                for art_type, url in art.items()
                if _removable(url, online_only)
            ]
        )
    ]
    _remove_art(heading, targets)
    xbmcgui.Dialog().notification(
        heading, ADDON.getLocalizedString(32216) % len(targets)
    )


def _removable(url: str, online_only: bool) -> bool:
    """
    Whether clear_art removes an art URL: web images, or with online_only off all
    but embedded art (image://music@…), which a refresh never extracts again.

    :param url: Art URL as Kodi returns it.
    :param online_only: Only web images.
    :return: True to remove it.
    """
    path = url_decode_path(url)
    if online_only:
        return path.startswith(("http://", "https://"))
    return not path.startswith("image://")


def _remove_art(
    heading: str, targets: list[tuple[str, int, str, Iterable[str]]]
) -> None:
    """
    Remove art from library items under a background progress bar.

    :param heading: Progress heading.
    :param targets: (kind, id, label, art types) per item.
    """
    from resources.lib.script.library import remove_art

    progress = xbmcgui.DialogProgressBG()
    progress.create(heading)
    for index, (kind, item_id, label, art_types) in enumerate(targets):
        progress.update(100 * index // len(targets), message=label)
        remove_art(kind, item_id, art_types)
    progress.close()


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
def container_reset(id: str, item: str = "1", **kwargs: str) -> None:
    """
    Select a container's item in the topmost dialog or window, without focusing
    it: a kept-in-memory window reopens on each list's last selection.

    :param id: Container id.
    :param item: The item to select, from 1 (MusicPlayer.PlaylistPosition reads so).
    """
    window = xbmcgui.Window(topmost_window_id())
    window.getControl(int(id)).selectItem(max(to_int(item) - 1, 0))


@action
def delete_orphans(**kwargs: str) -> None:
    """
    Remove child entries whose parent is missing or ineligible, then rebuild
    outputs if anything was removed, and reload the skin if a file changed.
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
        elif _rebuild():
            _reload_skin()
        else:
            window_property("helper_reloading")


@action
def dialog_textviewer(heading: str, label: str, **kwargs: str) -> None:
    """
    Opens Kodi's text viewer on an infolabel's text, read here so the skin passes
    no text through RunScript's arguments (an add-on's changelog has commas).

    :param heading: Dialog heading.
    :param label: InfoLabel whose text the viewer shows, e.g. ListItem.AddonNews.
    """
    # empty once the dialog has closed: the viewer would keep its last text
    if text := infolabel(label):
        xbmcgui.Dialog().textviewer(heading, text)


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

    controls_from = [
        m.strip() for m in kwargs.get("controls_from", "").split(",") if m.strip()
    ]
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

    myWindow = DynamicEditor(f"{name}.xml", skin_path(SKINXML), "Default", "")
    myWindow.parent_filter = parent_filter
    myWindow.mapping = mapping
    myWindow.host = host
    myWindow.host_focus = host_focus
    myWindow.focus_item = focus_item
    myWindow.controls_from = controls_from
    rebuilt = written = False
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
                rebuilt = True
                written = _rebuild()
    finally:
        # Always restore properties — a stuck active_editor_name makes every
        # later top-level session look nested and silently skip rebuilds.
        # active_editor_name goes last: it reopens the host's onload gate, so
        # no new session can start (and be clobbered here) before this point.
        window_property(mapping_slot)
        window_property("editor_label", value=previous_label)
        window_property("active_editor_name", value=previous_editor)
        del myWindow

    # Decided after the restores: an active host may have skipped its onload while
    # the gate was closed, and the reload's re-init of it starts the next session.
    if rebuilt:
        if written or host and condition(f"Window.IsActive({host})"):
            _reload_skin()
        else:
            window_property("helper_reloading")


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
    position = [s["songid"] for s in songs].index(songid)  # raises before the mark
    mark_source(dial_entry("album", song["albumid"]))
    play_files(songs, position=position)


@action
def play_item(type: str, id: str, **kwargs: str) -> None:
    """
    Plays one library video from where it was left, in place of what plays: Kodi
    makes it the video playlist's only item and stays full screen.

    :param type: movie, episode or musicvideo.
    :param id: Its library id.
    """
    json_call(
        "Player.Open",
        item={f"{type}id": int(id)},
        options={"resume": True},
        parent="play_item",
    )


def _select_first(id: str, path: str) -> None:
    """
    Select a queue list's first song once its refetch lists the new queue, for up
    to 3 s: a refetch keeps the old selection by path, maybe a later song.

    :param id: Container id of the queue list.
    :param path: The new queue's first file.
    """
    monitor = xbmc.Monitor()
    for _ in range(30):
        if not condition(f"Container({id}).IsUpdating") and path == infolabel(
            f"Container({id}).ListItemAbsolute(0).FileNameAndPath"
        ):
            container_reset(id)
            return
        if monitor.waitForAbort(0.1):
            return


@action
def play_items(id: str, **kwargs: str) -> None:
    """
    Plays all media items in a container by index.

    :param id: Container ID.
    :param method: "from_here" or "shuffle" for behavior control.
    :param type: "music" or "video".
    :param select: Music: a queue list to select the first song in, once it shows.
    """
    method = kwargs.get("method", "")
    scope = "NoWrap" if method == "from_here" else "Absolute"
    prefix = f"Container({id}).ListItem{scope}"
    indices = range(to_int(infolabel(f"Container({id}).NumItems")))

    if kwargs.get("type", "") == "music":
        songs = []
        for i in indices:
            if url := infolabel(f"{prefix}({i}).FileNameAndPath"):
                song = {"file": url}
                if infolabel(f"{prefix}({i}).DBType") == "song" and (
                    (songid := to_int(infolabel(f"{prefix}({i}).DBID"))) > 0
                ):
                    song["songid"] = songid
                songs.append(song)
        play_files(songs, shuffled=method == "shuffle")
        if (select := kwargs.get("select")) and songs:
            _select_first(select, songs[0]["file"])
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
def playlist_goto(position: str, **kwargs: str) -> None:
    """
    Plays the music queue from one of its songs, keeping the queue: a list's own
    click on a queue item plays the song on its own.

    :param position: The song's place in the queue, from 1 (Container.CurrentItem).
    """
    json_call(
        "Player.GoTo",
        params={"playerid": 0, "to": to_int(position) - 1},
        parent="playlist_goto",
    )


@action
def play_trailer(trailer: str, **kwargs: str) -> None:
    """
    Request a trailer, stamping the item it is for so a stale start is parked.
    It plays at once, or when the trailer still resolving ahead of it lands; one
    already playing for the same item and window plays on.

    :param trailer: Player path or plugin URL to play.
    :param item: Item label captured skin-side, atomic with the trailer URL.
    :param focus_ids: Optional comma-separated control ids that must keep focus.
    :param viewport: Optional "WxH" trailer region; enables aspect zoom.
    :param source_prefix: Optional container id or infolabel prefix of the item.
    :param window: Optional name of the window or page the trailer plays in.
    :param fullscreen: "true" to take the trailer full screen as soon as it starts.
    """
    if not trailer:
        return
    playing = ("playing", trailer, kwargs.get("item", ""), kwargs.get("window", ""))
    if playing == tuple(
        infolabel(f"Window(home).Property(trailer_{key})")
        for key in ("state", "request", "item", "window")
    ):
        return  # landed after a quick away-and-back: the return's rest asks again

    window_property("trailer_state", value="pending")
    window_property("trailer_request", value=trailer)
    window_property("trailer_viewport", value=kwargs.get("viewport", ""))
    window_property("trailer_source", value=kwargs.get("source_prefix", ""))
    window_property("trailer_item", value=kwargs.get("item", ""))
    window_property("trailer_focus_ids", value=kwargs.get("focus_ids", ""))
    window_property("trailer_window", value=kwargs.get("window", ""))
    window_property("trailer_fullscreen", value=kwargs.get("fullscreen", ""))
    start_flight(trailer)


@action
def trailer_fullscreen(trailer: str, **kwargs: str) -> None:
    """
    Take a window's trailer full screen: at once while it plays there, else as
    soon as it starts, requesting it first when it isn't already on its way.

    :param trailer: Player path or plugin URL; the other params as play_trailer.
    :param window: Window the trailer plays in; required, or each press restarts it.
    """
    ours = infolabel("Window(home).Property(trailer_window)") == kwargs.get("window")
    state = infolabel("Window(home).Property(trailer_state)") if ours else ""
    if state == "playing":
        enter_fullscreen()
    elif state == "pending":
        window_property("trailer_fullscreen", value="true")
    else:
        play_trailer(trailer, **kwargs | {"fullscreen": "true"})


@action
def trailer_return(**kwargs: str) -> None:
    """
    Full screen has closed on the info dialog's trailer: reopen that dialog,
    which takes a still-playing trailer back into its tab. With none to reopen,
    end the hop and stop the trailer.
    """
    key = infolabel("Window(home).Property(trailer_return)")
    window_property("trailer_return")
    playing = infolabel("Window(home).Property(trailer_state)") == "fullscreen"
    if not (item := _info_item(key)):
        window_property("info_hop")
        if playing:
            log.execute("PlayerControl(Stop)")
        return
    if playing:
        TrailerZoomController().apply_zoom_if_needed()
    _show_info(item, key)


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
    if dbtype == "season" or dbtype not in DETAILS:
        return None
    details = json_call(
        DETAILS[dbtype],
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
    for dialog in INFO_DIALOGS:
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
    The skin handles the dialog's own item; a call for it anyway, or for an item
    that can't be opened, clears info_hop and leaves the dialog open.

    :param dbtype: Library media type (not season).
    :param dbid: Library id.
    """
    key = f"{dbtype}:{dbid}"
    if key != infolabel("Window(home).Property(info_current)") and (
        item := _info_item(key)
    ):
        _show_info(item, key)
        return
    window_property("info_hop")


@action
def info_swap(key: str, **kwargs: str) -> None:
    """
    Kodi's own Information swapped the dialog's item with no onload (metadata
    caught it): reopen on it as a hop, or on the last item if it can't be opened.

    :param key: The swapped-in item's "dbtype:dbid".
    """
    if not (item := _info_item(key)):
        key = infolabel("Window(home).Property(info_current)")
        item = _info_item(key)
        window_property("info_hop", value="back" if item else False)
    _show_info(item, key)


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
def refresh_cached(id: str, type: str, **kwargs: str) -> None:
    """
    Mark one library item's saved web answers stale and forget its processed art and
    cached images, then refresh the list, so each is made again when next shown.

    :param id: The item's library id.
    :param type: Its DBType.
    """
    from resources.lib.script.library import refresh_cached as refresh

    changed = refresh(type, int(id))
    xbmc.executebuiltin("Container.Refresh")
    xbmcgui.Dialog().notification(
        ADDON.getLocalizedString(32835),
        ADDON.getLocalizedString(32231 if changed else 32232),
    )


@action
def remove_broken_art(**kwargs: str) -> None:
    """
    Check every art link of artists, albums, films, sets, shows and seasons, then,
    after a yes/no on what was found, remove the dead ones.
    """
    from resources.lib.script.library import CHECKED, broken_urls, library_art, online

    heading = ADDON.getLocalizedString(32027)
    if not online():
        xbmcgui.Dialog().notification(heading, ADDON.getLocalizedString(32220))
        return
    progress = xbmcgui.DialogProgress()
    progress.create(heading, ADDON.getLocalizedString(32224))
    items = [
        (kind, item_id, label, art)
        # shows before seasons: a show's save rewrites its seasons' art as it was
        for kind in ("artists", "albums", "movies", "sets", "tvshows", "seasons")
        for item_id, label, art in library_art(kind, CHECKED.get(kind))
    ]
    urls = {url for *_, art in items for url in art.values()}
    checking = ADDON.getLocalizedString(32225) % len(urls)

    monitor = xbmc.Monitor()

    def report(done: int) -> bool:
        progress.update(100 * done // len(urls), checking)
        return progress.iscanceled() or monitor.abortRequested()

    result = broken_urls(urls, report)
    cancelled = progress.iscanceled() or monitor.abortRequested()
    progress.close()
    if result is None:  # cancelled, or offline after the check
        if not cancelled:
            xbmcgui.Dialog().notification(heading, ADDON.getLocalizedString(32220))
        return
    broken, dead_hosts, skipped = result
    if skipped:
        log.info(
            f"remove_broken_art: {skipped} links skipped, their server didn't answer"
        )

    def targets_for(wanted: set[str]) -> list[tuple[str, int, str, list[str]]]:
        return [
            (kind, item_id, label, [art for art, url in arts.items() if url in wanted])
            for kind, item_id, label, arts in items
            if not wanted.isdisjoint(arts.values())
        ]

    note = f" {ADDON.getLocalizedString(32228) % skipped}" if skipped else ""

    def with_skipped(message: str) -> str:
        return message + note

    if dead_hosts:  # a name this device alone can't resolve isn't gone: ask
        hosts = sorted(set(dead_hosts.values()))
        named = ", ".join(hosts[:5]) + (" …" if len(hosts) > 5 else "")
        slots = sum(len(art) for *_, art in targets_for(set(dead_hosts)))
        if xbmcgui.Dialog().yesno(
            heading, ADDON.getLocalizedString(32227) % (named, slots)
        ):
            broken.update(dead_hosts)
    if not (targets := targets_for(broken)):  # 32229 after the servers were declined
        message = with_skipped(ADDON.getLocalizedString(32229 if dead_hosts else 32219))
        xbmcgui.Dialog().notification(heading, message)
        return
    count = sum(len(art_types) for *_, art_types in targets)
    message = ADDON.getLocalizedString(32218) % (count, len(targets), note)
    if not xbmcgui.Dialog().yesno(heading, message):
        return
    for kind, _, label, art_types in targets:
        log.info(f"remove_broken_art: {kind} {label}: {', '.join(art_types)}")
    _remove_art(heading, targets)
    message = with_skipped(ADDON.getLocalizedString(32221) % count)
    xbmcgui.Dialog().notification(heading, message)


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
    from resources.lib.shared.keyboard import (
        keyboard_layout_trees,
        layout_characters,
        usable_layouts,
    )

    trees = keyboard_layout_trees()
    if layout is None:
        choices = [
            f"{element.get('language')} {element.get('layout')}"
            for _, tree in sorted(trees.items())
            for element in usable_layouts(tree)
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
    log.execute(f"SetFocus({id})", wait=True)
    json_call("Input.SendText", params={"text": text, "done": True}, parent="set_edit")
    return_id = kwargs.get("return_id")
    if return_id:
        log.execute(f"SetFocus({return_id})", wait=True)


@action
def search_backspace(**kwargs: str) -> None:
    """
    Rewrite search_query from search_log, the on-screen keys' record (← a delete),
    on Kodi's main thread between clicks, until the log is unchanged after the
    write: keys pressed meanwhile and runs in any order end on the log's text.
    """
    home = xbmcgui.Window(10000)
    keys = None
    while (logged := home.getProperty("search_log")) != keys:
        keys = logged
        query = reduce(_key, keys, "")
        log.execute(f'SetProperty(search_query,"{query}",home)', wait=True)


def _key(text: str, key: str) -> str:
    """
    Apply one search_log entry: ← deletes the last character, anything else appends.

    :param text: Query so far.
    :param key: One log character.
    :return: The query after the key.
    """
    return text[:-1] if key == "←" else text + key


@action
def set_search_query(id: str, **kwargs: str) -> None:
    """
    Mirror an edit control's text into the search_query property, encoded
    for the search rails' paths. Keyboard mode's writer; the keys write raw.

    :param id: Edit control id to read.
    :param min_length: Minimum characters before the query is published.
    """
    text = infolabel(f"Control.GetLabel({id}).index(1)")
    _publish_query(text, to_int(kwargs.get("min_length"), 3))


def _publish_query(text: str, min_length: int) -> None:
    """
    Write text to search_query JSON-escaped and URL-encoded, so `&`, `+` and
    `%` survive a library path's xsp option; cleared below min_length.

    :param text: Query text.
    :param min_length: Minimum characters before the query is published.
    """
    window_property(
        "search_query",
        value=quote(json.dumps(text)[1:-1]) if len(text) >= min_length else False,
    )


def _year_rule(year: str) -> dict:
    """
    Smart playlist rule for one year's songs.

    :param year: Year, as a string.
    :return: Smart playlist rule for songs from that year.
    """
    return {"field": "year", "operator": "is", "value": year}


def _mix_seed(type: str, dbid: int) -> dict | None:
    """
    The song a mix starts from: the song itself, or one of the five most
    played songs of the album or artist.

    :param type: song, album or artist.
    :param dbid: Library ID of the item.
    :return: Song dict with songid, file, artist, artistid and genre, or None.
    """
    if type == "song":
        return (
            json_call(
                "AudioLibrary.GetSongDetails",
                properties=["file", "artist", "artistid", "genre"],
                params={"songid": dbid},
                parent="start_mix",
            )
            .get("result", {})
            .get("songdetails")
        )
    top = json_call(
        "AudioLibrary.GetSongs",
        properties=["file", "artist", "artistid", "genre"],
        sort={"method": "playcount", "order": "descending"},
        limit=5,
        query_filter={_LIBRARY_ITEMS[type]: dbid},
        parent="start_mix",
    )["result"].get("songs")
    return random.choice(top) if top else None


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
    if type == "year":
        if songs := random_songs(_year_rule(id)):  # none: Kodi starts nothing
            mark_source(None)
            play_files(songs)
        return
    mark_source(None if type == "genre" else dial_entry(type, id, path))
    clear_playlists()
    item = (
        {_LIBRARY_ITEMS[type]: to_int(id)}
        if type in _LIBRARY_ITEMS
        else {"directory": path, "media": "music"}
    )
    opened = json_call(
        "Player.Open", item=item, options={"shuffled": True}, parent="shuffle"
    )
    if "error" in opened:  # nothing to play, so no start takes the mark
        take_source()


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
    Plays a random mix. A genre or year mix is its own songs, a daily one today's
    mix of a genre; a song, album or artist mix is a seed song, SEED_SHARE by its
    artists, the rest by similar artists, then of its genres (else its artists').

    :param id: Library ID (defaults to ListItem.DBID); the year for year.
    :param type: song, album, artist, genre, year or daily (id a genre ID).
    """
    if type == "daily":
        mix = next((m for m in todays_mixes() if m["genreid"] == to_int(id)), None)
        if not mix:  # the day turned since its card loaded: the genre's own mix
            start_mix(id=id, type="genre")
        elif songs := mix_songs(
            mix["artists"],
            [mix["genre"]],
            MIX_SIZE,
            share=DAILY_ARTIST_SHARE,
            similar=mix["similar"],
            played=DAILY_WINDOW,
        ):
            mark_source(None)
            play_files(songs)
        return
    if type in ("genre", "year"):
        rule = {"genreid": to_int(id)} if type == "genre" else _year_rule(id)
        if songs := random_songs(rule, MIX_SIZE):  # none: Kodi starts nothing
            mark_source(None)
            play_files(songs)
        return
    dbid = to_int(id or infolabel("ListItem.DBID"))
    if not (seed := _mix_seed(type, dbid)):
        return
    from resources.lib.plugin.music import similar_artists

    mark_source(dial_entry(type, dbid))
    genres = seed["genre"] or artist_genres(seed["artist"])
    # an artist's own, as its top song may be another's it features on
    artistid = dbid if type == "artist" else seed["artistid"][0]
    similar = similar_artists(artistid, "start_mix")
    songs = mix_songs(
        seed["artist"],
        genres,
        MIX_SIZE - 1,
        {seed["songid"]},
        SEED_SHARE[type],
        similar,
    )
    play_files([seed, *songs])


REGISTRY["play_radio"] = start_mix  # former name, kept for skins that call it


def _iso639_2(lang: str) -> str:
    """
    A language code or English name as the ISO 639-2/B code streams carry, via
    639-1 as Kodi does, so 639-2/T "deu" gives "ger"; unknown ones stay as given.

    :param lang: Language as the skin passes it (e.g. "en", "deu", "English").
    :return: Its ISO 639-2/B code (e.g. "eng", "ger").
    """
    two = xbmc.convertLanguage(lang, xbmc.ISO_639_1) or lang
    return xbmc.convertLanguage(two, xbmc.ISO_639_2) or lang


def _publish_subtitle(lang: str, kind: str) -> None:
    """
    Writes player_subtitle_kind from the playing video's subtitle; empty with no
    video (a refresh while playback stops).

    :param lang: Preferred ISO 639-2/B language code; empty for none.
    :param kind: Preferred subtitle type.
    """
    status = condition("Player.HasVideo") and subtitle_status(
        *player_streams("subtitle"), lang, kind
    )
    window_property("player_subtitle_kind", value=status)


@action
def chapter_focus(chapter: str, **kwargs: str) -> None:
    """
    Sets player_chapter_focus to the Player.Chapters pair ending where chapter n
    starts, so a ranges control draws that chapter's tick (empty without one), and
    player_chapter_focus_number to n, so the skin can hide a tick that lags focus.

    :param chapter: Kodi's 1-based chapter number, e.g. ListItem.Property(chapter).
    """
    # Kodi drops the pair of a chapter at 0, so the pairs belong to the last chapters
    values = iter(infolabel("Player.Chapters").split(","))
    pairs = [f"{start},{end}" for start, end in zip(values, values)]
    index = to_int(chapter) - to_int(infolabel("Player.ChapterCount")) + len(pairs) - 1
    # The upper bound is for a stop while the script starts: no chapters, n stays
    window_property(
        "player_chapter_focus", value=pairs[index] if 0 <= index < len(pairs) else ""
    )
    window_property("player_chapter_focus_number", value=chapter)


@action
def player_stream(type: str, lang: str = "", kind: str = "", **kwargs: str) -> None:
    """
    Steps the playing video's audio or video stream, wrapping, or its subtitles:
    lang's preferred stream on and off (off when it has none), else each stream in
    turn, then off. Sets streams directly, so Kodi shows no toast.

    :param type: audio, subtitle or video.
    :param lang: Preferred subtitle language: a code or English name (e.g. "en").
    :param kind: Preferred subtitle type: forced, full (default) or impaired.
    """
    player = xbmc.Player()
    lang = _iso639_2(lang)
    streams, current = player_streams(type)
    on = current["index"] if current else -1
    if type != "subtitle":
        if len(streams) < 2:  # Kodi reopens and seeks even for the same stream
            return
        step = player.setAudioStream if type == "audio" else player.setVideoStream
        step((on + 1) % len(streams))
        # A selected forced subtitle, shown or hidden, follows the new audio language
        # unseen (and may show); Kodi caches the subtitle index for 1 s
        if type == "audio" and not xbmc.Monitor().waitForAbort(1.1):
            _publish_subtitle(lang, kind)
        return
    if lang:
        target = preferred_subtitle(streams, lang, kind)
        if target and target["index"] == on:
            target = None
    else:
        target = streams[on + 1] if on + 1 < len(streams) else None
    if target:
        player.setSubtitleStream(target["index"])  # also shows subtitles
    elif current:
        player.showSubtitles(False)
    status = subtitle_status(streams, target, lang, kind)
    window_property("player_subtitle_kind", value=status)


@action
def player_stream_refresh(lang: str = "", kind: str = "", **kwargs: str) -> None:
    """
    Re-reads the playing video's subtitle into player_subtitle_kind, as Kodi
    raises no event when its dialogs or keys change it; empty with no video.

    :param lang: Preferred subtitle language, as for player_stream.
    :param kind: Preferred subtitle type, as for player_stream.
    """
    _publish_subtitle(_iso639_2(lang), kind)


@action
def subtitle_limiter(lang: str, user_trigger: bool | str = True, **kwargs: str) -> None:
    """
    Switches to preferred subtitle stream or toggles through them.

    :param lang: Preferred language as Kodi reports it (e.g., "eng").
    :param user_trigger: True (or "true") also toggles subtitles on/off; see parse_bool.
    """
    user_trigger = parse_bool(user_trigger)
    if condition("VideoPlayer.HasSubtitles"):
        player = xbmc.Player()
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
def size_identity(window: str = "videoosd", **kwargs: str) -> None:
    """
    A window's onload: fit its identity logo to the playing item's, for an open the
    service didn't size (the OSD's first, any after a skin reload).

    :param window: videoosd or seekbar.
    """
    from resources.lib.plugin.helpers import size_identity as fit  # this action only

    fit(window)


@action
def skip_segment(seek: str, **kwargs: str) -> None:
    """
    The skin's skip button: seek to the end of the segment, passed by the skin
    once it has checked that segment is still the one the button opened on.

    :param seek: Seconds, player_skip_seek when pressed.
    """
    if seconds := to_float(seek):
        xbmc.Player().seekTime(seconds)


@action
def listenbrainz_test(**kwargs: str) -> None:
    """
    Verify the configured ListenBrainz token by making a test request.
    Reports success or failure via notification.
    """
    from resources.lib.apis import listenbrainz
    from resources.lib.apis.http import HttpError

    if not listenbrainz.enabled():
        message = 32212
    else:
        try:
            valid = listenbrainz.get_json("validate-token")["valid"]
        except HttpError:
            valid = False
        message = 32213 if valid else 32214
    xbmcgui.Dialog().notification(
        ADDON.getLocalizedString(32000), ADDON.getLocalizedString(message), time=4000
    )


@action
def tmdb_test(**kwargs: str) -> None:
    """
    Verify the configured TMDb token by making a test request.
    Reports success or failure via notification.
    """
    from resources.lib.apis.http import HttpError
    from resources.lib.apis.tmdb.client import get_tmdb_client

    if not (client := get_tmdb_client()):
        message = 32208
    else:
        try:
            valid = "images" in client.get_json("/configuration")
        except HttpError:
            valid = False
        message = 32209 if valid else 32210
    xbmcgui.Dialog().notification(
        ADDON.getLocalizedString(32000), ADDON.getLocalizedString(message), time=4000
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
def waveform_background(enabled: str, **kwargs: str) -> None:
    """
    On: enable Waveform (installing it if asked), style it for the blurred background
    and make it the visualiser, keeping the user's and Waveform's own look. Off: give
    both back; the visualiser only if Waveform is still the one in use.

    :param enabled: 'true' to switch to Waveform, anything else to switch back.
    """
    setting = {"setting": "musicplayer.visualisation"}
    current = json_call(
        "Settings.GetSettingValue", params=setting, parent="waveform_background"
    )["result"]["value"]
    if not parse_bool(enabled):
        if current == WAVEFORM:
            saved = infolabel("Skin.String(waveform_restore)")
            # One removed or disabled since can't run: none, as Kodi would have it
            restore = saved if condition(f"System.AddonIsEnabled({saved})") else ""
            json_call(
                "Settings.SetSettingValue",
                params=setting | {"value": restore},
                parent="waveform_background",
            )
        kept = infolabel("Skin.String(waveform_look)")
        if kept and condition(f"System.AddonIsEnabled({WAVEFORM})"):
            _waveform_look(
                {
                    key: type(value)(text)
                    for (key, value), text in zip(
                        WAVEFORM_LOOK.items(), kept.split(",")
                    )
                }
            )
        skin_string("waveform_look")
        return
    if not condition(f"System.HasAddon({WAVEFORM})"):
        log.execute(f"InstallAddon({WAVEFORM})")  # Kodi asks first
        # Polled, as wait=True holds the GIL through the question: done once it is
        # enabled, or Kodi's questions (a master lock's code first) and download have
        # been gone for 2 s
        asking = (
            "Window.IsActive(yesnodialog) | Window.IsActive(progressdialog)"
            " | Window.IsActive(numericinput) | Window.IsActive(virtualkeyboard)"
            " | Window.IsActive(gamepadinput)"
        )
        monitor, quiet = xbmc.Monitor(), 0
        while quiet < 10 and not condition(f"System.AddonIsEnabled({WAVEFORM})"):
            if monitor.waitForAbort(0.2):
                return
            quiet = 0 if condition(asking) else quiet + 1
    elif not condition(f"System.AddonIsEnabled({WAVEFORM})"):
        json_call(
            "Addons.SetAddonEnabled",
            params={"addonid": WAVEFORM, "enabled": True},
            parent="waveform_background",
        )
    if not condition(f"System.AddonIsEnabled({WAVEFORM})"):
        # Declined or not offered: the skin keeps its usual layers
        xbmcgui.Dialog().notification(
            ADDON.getLocalizedString(32000), ADDON.getLocalizedString(32233)
        )
        return
    waveform = xbmcaddon.Addon(WAVEFORM)
    kept = (
        (
            waveform.getSettingInt(key)
            if isinstance(value, int)
            else waveform.getSettingNumber(key)
        )
        for key, value in WAVEFORM_LOOK.items()
    )
    skin_string("waveform_look", ",".join(map(str, kept)))
    _waveform_look(WAVEFORM_LOOK)
    skin_string("waveform_restore", current)
    json_call(
        "Settings.SetSettingValue",
        params=setting | {"value": WAVEFORM},
        parent="waveform_background",
    )


def _waveform_look(look: dict[str, int | float]) -> None:
    """
    Write Waveform's own settings: whole numbers as integers, colours as numbers.

    :param look: Setting id → value.
    """
    waveform = xbmcaddon.Addon(WAVEFORM)
    for key, value in look.items():
        if isinstance(value, int):
            waveform.setSettingInt(key, value)
        else:
            waveform.setSettingNumber(key, value)


@action
def rebuild(**kwargs: str) -> None:
    """
    Rebuild builder outputs and reload the skin. Regenerates output XML,
    seeds missing runtime state mappings, and refreshes the resolver cache;
    existing runtime state is preserved unless reset is requested.

    :param reset: 'true' to delete runtime state and outputs, then rebuild fresh.
    """
    reset = kwargs.get("reset") == "true"
    if reset:
        reset_dev_state()

    _rebuild()
    _reload_skin()
    xbmcgui.Dialog().notification(
        ADDON.getLocalizedString(32000),
        ADDON.getLocalizedString(32207 if reset else 32211),
        time=4000,
    )
