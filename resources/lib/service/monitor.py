# author: realcopacetic

import json
import sqlite3
import sys
import time
from threading import Thread, Timer

import xbmc

from resources.lib.apis.tmdb.context import forget_tmdb_id
from resources.lib.art.slideshow import Slideshow
from resources.lib.art.splash import bake_profiles
from resources.lib.builders.build_elements import BuildElements, output_digests
from resources.lib.builders.builder_config import BUILDER_CONFIG
from resources.lib.builders.templates import cache_is_current
from resources.lib.service import clashes
from resources.lib.service.player import PlayerMonitor
from resources.lib.service.serve import Server
from resources.lib.shared import logger as log
from resources.lib.shared.helpers import REWATCH_STOPPED
from resources.lib.shared.speed_dial import release_refresh, skin_uses_speed_dial
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.text import load_font
from resources.lib.shared.utilities import (
    ADDON,
    adopt_shared_state,
    condition,
    dev_reset_due,
    infolabel,
    json_call,
    notify_build_failed,
    pin_dev_reset,
    reset_dev_state,
    skin_path,
    skin_uses_builder,
    skin_version,
    validate_path,
    window_property,
)

# Set while an opted-in skin is active; addon.xml's context items test it.
ACTIVE_PROPERTY = "helper_active"
# Set with it while that skin names speed dial; addon.xml's Pin/Unpin test it instead.
SPEED_DIAL_PROPERTY = "helper_speed_dial"
# Token _settle posts through Kodi's builtin queue to see when the queue has run.
SETTLE_PROPERTY = "helper_settle"
# Time for the skin to draw helper_reloading's dots before ReloadSkin freezes the frame.
RELOAD_COVER_SECS = 0.2
# A plugin progress bar's container, the id its page asks a skin to give it for the skip
PLUGIN_BAR = 9010
# Wait after a video update's burst: the listing it rebuilds rings in the landing's
# second, so a re-serve this late reads the rebuilt item, past a ring dropped as repeat
VIDEO_UPDATE_SECS = 1.0
# Edits to a queue: Kodi's list providers refresh on play, resume and stop, not on these
# (nor on a shuffle, a Player.OnPropertyChanged; a move announces nothing).
PLAYLIST_EDITS = {"Playlist.OnAdd", "Playlist.OnRemove", "Playlist.OnClear"}


def _play_count(songid: int) -> int | None:
    """
    A library song's play count, as Kodi has it now.

    :param songid: Library song id.
    :return: Its play count; None if unread.
    """
    response = json_call(
        "AudioLibrary.GetSongDetails",
        params={"properties": ["playcount"], "songid": songid},
        parent="song_closed",
    )
    return response.get("result", {}).get("songdetails", {}).get("playcount")


class Monitor(xbmc.Monitor):
    """
    Background service monitor. All work is gated on the active skin opting in
    (shipping the builder folders): entering such a skin activates the build
    check, player monitor and slideshow; leaving it releases them.
    """

    def __init__(self) -> None:
        """Initialise the service state, then run the loop until Kodi exits."""
        self.idle = False
        self.skin = None, None
        self.reload_due = False
        self.prune_due = 0.0  # wall-clock time of the next API cache prune
        self.player_monitor = None
        self.slideshow = None
        self.server = None  # served focus calls (serve.py)
        self.song_bump = None  # a pending album bar re-serve
        self.video_bump = None  # a pending bar and details re-serve
        self.closed = {}  # songs closed since the last bump: id → start play count
        self.clash_features = ()  # clashes.features() after the last apply
        log.info(f"{self.__class__.__name__} → Started, Python {sys.version}")
        self._run()

    def _run(self) -> None:
        """
        Service loop: follow the loaded skin's folder, and a new version in it unless
        empty (Kodi unregisters a skin it is installing); while it opts in, poll at
        most 1 s apart (lyrics only under the screensaver), else every 2 s.
        """
        while not self.abortRequested():
            skin = skin_path()
            version = skin_version(skin)
            if skin != self.skin[0] or version and version != self.skin[1]:
                self._follow(skin, version)
            if self.player_monitor and not self.idle:
                self.poller()
            elif self.player_monitor and self.player_monitor.isPlayingAudio():
                # A dim screensaver leaves the visualisation's lyrics in view
                self.waitForAbort(self.player_monitor.watch_lyrics())
            else:
                self.waitForAbort(2)
        # A profile switch keeps Home's properties: release the active state too.
        if self.player_monitor:
            self._deactivate()
        log.info(f"{self.__class__.__name__} → Stopped")

    def _follow(self, skin: str, version: str) -> None:
        """
        Take a new (folder, version) key. A switch drops any due reload and releases the
        active state; an update keeps it, so a trailer plays on. Activates only with a
        readable version; a skin that doesn't opt in gets back add-ons switched off.

        :param skin: Loaded skin's folder.
        :param version: Its registered version, "" when unreadable.
        """
        load_font.cache_clear()  # keyed by special://skin, which follows the skin
        if skin != self.skin[0]:
            self.reload_due = False
            if self.player_monitor:
                self._deactivate()
        self.skin = skin, version
        if self.player_monitor:
            log.info(f"{self.__class__.__name__} → Skin updated to version {version}")
            self._builder_elements()
            # An update may add or drop speed dial.
            window_property(
                SPEED_DIAL_PROPERTY, value=skin_uses_speed_dial() and "true"
            )
        elif version and skin_uses_builder():
            self._activate()
        elif version:
            clashes.restore()

    def _activate(self) -> None:
        """
        Entering an opted-in skin: check the builder outputs (reloading if any
        changed), start the player monitor and slideshow, bake the login blurs, show
        the context items, then check add-ons that clash, queued behind any reload.
        """
        path, version = self.skin
        log.info(f"{self.__class__.__name__} → Active in {path}, version {version}")
        self._builder_elements()
        self.player_monitor = PlayerMonitor(song_closed=self._song_closed)
        self.slideshow = Slideshow()
        self.server = Server()
        Thread(target=bake_profiles, daemon=True).start()
        window_property(SPEED_DIAL_PROPERTY, value=skin_uses_speed_dial() and "true")
        window_property(ACTIVE_PROPERTY, value="true")
        window_property(clashes.ASKING)  # a check killed mid-run would block the rest
        self._check_clashes()

    def _check_clashes(self, answers: dict | None = None) -> None:
        """
        Apply the answers about add-ons that clash, here alone so no two writes
        overlap, then note what it leaves; queue the question about any not asked yet.

        :param answers: Answers just clicked, handed over by check_clashes.
        """
        unasked = clashes.apply(answers)
        self.clash_features = clashes.features()  # after: its own switches aren't news
        if unasked and not answers:  # the check handing answers over asked the rest
            log.execute("RunScript(script.copacetic.helper,action=check_clashes)")

    def _deactivate(self) -> None:
        """Leaving the skin: hide the context items, release the monitors."""
        window_property(ACTIVE_PROPERTY)
        window_property(SPEED_DIAL_PROPERTY)
        for bump in (self.song_bump, self.video_bump):
            if bump:
                bump.cancel()
        self.player_monitor.release()
        self.slideshow.clear()
        self.server.stop()
        self.player_monitor = self.slideshow = self.server = None
        log.info(f"{self.__class__.__name__} → Inactive, skin left")

    def _builder_elements(self) -> None:
        """Check the outputs; a failed build is logged, shown and skips the reload."""
        try:
            self._check_outputs()
        except Exception:
            log.exception(f"{self.__class__.__name__} → Build failed, no reload")
            notify_build_failed()

    def _check_outputs(self) -> None:
        """
        Build, then reload if an output changed. Dev: clear state if asked, rebuild.
        Else the missing outputs, or all when ids are fresh or the resolver cache is
        missing or stale (other skin or version, an edited template, a profile's write).
        """
        adopt_shared_state()  # first, so a dev reset clears what it adopts

        if ADDON.getSettingBool("dev_mode"):
            # One turned on outside a builder skin, or before this helper: only a
            # check that can use it claims it.
            pin_dev_reset()
            if dev_reset_due():
                reset_dev_state()
                log.info(
                    f"{self.__class__.__name__} → Dev reset consumed — "
                    f"outputs and runtime_state cleared"
                )
            BuildElements().run()
            self._reload()
            return

        build = BuildElements()
        seeded = build.runtime_manager.initialize_runtime_state()
        builders = [
            builder
            for builder, config in BUILDER_CONFIG.items()
            if (write_path := config.get("write_path"))
            and not validate_path(skin_path(write_path))
        ]
        if seeded or not cache_is_current(build.stamp, output_digests()):
            # Fresh ids, or a resolver cache that is missing or stale: full
            # rebuild so every output bakes the same state generation.
            written = build.run()
        elif builders:
            build.selected = builders
            written = build.run()
        else:
            written = False
        if written or self.reload_due:
            # The skin loaded before this build; reload so it reads the new outputs.
            self._reload()

    def _reload(self) -> None:
        """
        Once Kodi has settled, ReloadSkin unless the skin switched since the check
        began (dropped) or started updating (deferred: reloading an unregistered skin
        resets Kodi to the default one). A skin update raises the splash's dots first.
        """
        # No monitors: a start, a switch in or a helper restart, each left as it was.
        # Nor over a film. The dots need a frame drawn: ReloadSkin holds the last one.
        covered = self.player_monitor and not condition(
            "Window.IsActive(fullscreenvideo)"
        )
        if covered:
            window_property("helper_reloading", value="reload")
            if self.waitForAbort(RELOAD_COVER_SECS):
                return
        if not self._settle():
            return
        path, version = self.skin
        if skin_path() != path:
            self.reload_due = False
            log.info(f"{self.__class__.__name__} → Reload dropped, skin switched")
        elif skin_version(path) != version:
            self.reload_due = True
            log.info(f"{self.__class__.__name__} → Reload deferred, skin updating")
        else:
            self.reload_due = False
            load_font.cache_clear()  # a dev rebuild may have changed a font in place
            xbmc.executebuiltin("ReloadSkin()")
            return
        if covered:
            window_property("helper_reloading")

    def _settle(self) -> bool:
        """
        Post tokens through Kodi's builtin queue until one lands with no yes/no dialog
        seen (a YES queues "Keep this skin?", which runs queued builtins; a reload there
        answers no). Polled: executebuiltin(wait=True) holds the GIL a stop needs.

        :return: False when Kodi is exiting.
        """
        deadline = time.monotonic() + 60  # a dropped Home property or a stuck dialog
        while time.monotonic() < deadline:
            token = str(time.monotonic_ns())
            xbmc.executebuiltin(f"SetProperty({SETTLE_PROPERTY},{token},home)")
            seen = False
            while True:
                seen |= condition("Window.IsVisible(yesnodialog)")
                if infolabel(f"Window(home).Property({SETTLE_PROPERTY})") == token:
                    break
                if self.waitForAbort(0.2):
                    return False
                if time.monotonic() >= deadline:
                    return True
            if not seen:
                break
            if self.waitForAbort(0.2):
                return False
        window_property(SETTLE_PROPERTY)  # the last token landed: none pending
        return True

    def onScreensaverActivated(self) -> None:
        """Kodi event hook: Pause monitoring when screensaver starts."""
        self.idle = True

    def onScreensaverDeactivated(self) -> None:
        """Kodi event hook: Resume monitoring when screensaver ends."""
        self.idle = False

    def onNotification(self, sender: str, method: str, data: str) -> None:
        """
        Kodi event hook, on the service's thread: the clashes writes scripts hand over,
        a video update's kept TMDb id; while active, playlist_revision on music queue
        edits (a shuffle too), the bar after Stop rewatch or library updates (no scan).

        :param sender: Announcement sender.
        :param method: Announcement name, e.g. "Playlist.OnAdd".
        :param data: Its data as JSON.
        """
        mine = sender == log.ADDON_ID
        if mine and method == f"Other.{clashes.ANSWERS}":
            if self.player_monitor:  # the skin left meanwhile: asked again on return
                self._check_clashes(json.loads(data))
            return
        if mine and method == f"Other.{clashes.RESET}":
            clashes.restore(forget=True)
            self.clash_features = ()  # checked next pass: reads this frame are cached
            return
        if mine and method == f"Other.{REWATCH_STOPPED}":  # the action's mark is down
            server = self.server  # None once the skin has left
            self._serve_bar(server, server.served("progressbar") if server else 0)
            return
        if method == "AudioLibrary.OnUpdate":
            # Music updates don't reach 9010's video-tagged item (DirectoryProvider.cpp
            # Announce): re-serve an album's bar once per burst, as Kodi queues them
            data = json.loads(data)
            if (
                self.player_monitor
                and data.get("type") == "song"
                and "transaction" not in data
                and not self.closed  # a close's wait, for its write, bumps them too
            ):
                self._song_update()
            return
        if method == "VideoLibrary.OnUpdate":
            data = json.loads(data)
            item = data.get("item", data)  # an announced item's, or AnnounceUpdate's
            forget_tmdb_id(item.get("type"), item.get("id"))  # a rescrape's new id
            # A plugin list refetches itself; a served one is rebound only on an
            # arrival, and the rebuilt listing's ring repeats its visit (same second).
            # A library item's only: a file's saved state announces id -1
            if (
                self.player_monitor
                and item.get("id", 0) > 0
                and "transaction" not in data
            ):
                self._video_update()
            return
        shuffle = method == "Player.OnPropertyChanged"
        if not (shuffle or method in PLAYLIST_EDITS) or not self.player_monitor:
            return
        if infolabel("Window(home).Property(playlist_replacing)"):
            return  # play_files is filling the queue: its play refetches the lists
        data = json.loads(data)
        if shuffle:
            edited = "shuffled" in data["property"] and data["player"]["playerid"] == 0
        else:
            edited = data.get("playlistid") == 0
        if edited:
            window_property("playlist_revision", value=str(time.monotonic_ns()))

    def _song_closed(self, songid: int, playcount: int | None) -> None:
        """
        A library song closed: PAPlayer saves its play count in a job once its stream
        has drained (PAPlayer.cpp CloseFileCB), so wait out a crossfade, and 2 s more.

        :param songid: Its library id.
        :param playcount: Its play count when it started; None if unread.
        """
        self.closed.setdefault(songid, playcount)
        response = json_call(
            "Settings.GetSettingValue",
            params={"setting": "musicplayer.crossfade"},
            parent="song_closed",
        )
        self._song_update(response.get("result", {}).get("value", 0) + 2)

    def _song_update(self, delay: float = 0.5) -> None:
        """
        One album bar re-serve (_album_bump) after the last of a burst of song updates
        and closes; an update doesn't cut a pending close's longer wait (its write).

        :param delay: Seconds to wait.
        """
        if self.song_bump:
            self.song_bump.cancel()
        self.song_bump = Timer(delay, self._album_bump)
        self.song_bump.daemon = True
        self.song_bump.start()

    def _album_bump(self) -> None:
        """
        Timer: the topmost window's served bar again, a plugin bar's progress_version,
        unless the bar on top shows a film's or show's (no blink); then a new
        played_version if a closed song's play counted (unannounced by real path).
        """
        server = self.server  # None once the skin has left
        served = server.served("progressbar") if server else 0
        bar = served or PLUGIN_BAR
        if condition(
            f"!String.StartsWith(Container({bar}).ListItem.FileNameAndPath,plugin://)"
            f" | String.IsEqual(Container({bar}).ListItem.Property(album),true)"
        ):
            self._serve_bar(server, served)
        closed, self.closed = self.closed, {}  # a started Timer can't be cancelled
        if any(_play_count(songid) != count for songid, count in closed.items()):
            window_property("played_version", value=str(time.monotonic_ns()))

    def _video_update(self) -> None:
        """One bar and details re-serve (_video_bump) after the last of a burst."""
        if self.video_bump:
            self.video_bump.cancel()
        self.video_bump = Timer(VIDEO_UPDATE_SECS, self._video_bump)
        self.video_bump.daemon = True
        self.video_bump.start()

    def _video_bump(self) -> None:
        """Timer: the lists the topmost window served its bar and details in, again."""
        if server := self.server:  # None once the skin has left
            for info in ("metadata", "progressbar"):  # a bar follows metadata's fetch
                if served := server.served(info):
                    server.again(served)

    @staticmethod
    def _serve_bar(server: Server | None, served: int) -> None:
        """
        The progress bar again: the topmost window's served list, and a plugin bar
        by a new progress_version in its URL.

        :param server: The server, read once by the caller; None once the skin left.
        :param served: The list the bar was served in (Server.served); 0 for none.
        """
        if served:
            server.again(served)
        window_property("progress_version", value=str(time.monotonic_ns()))

    def onSettingsChanged(self) -> None:
        """Kodi event hook: re-read debug_logging, pin a new reset to this skin."""
        log.debug_logging.cache_clear()
        pin_dev_reset()

    def poller(self) -> None:
        """
        Polling loop: trailer session watchdog, seek offset expiry, Play next's
        switch-off, skip segments, the game OSD's blur, slideshow, held speed dial
        refreshes, clashes on a feature or add-on change, lyrics, a daily cache prune.
        """
        if (now := time.time()) >= self.prune_due:  # runs on through suspend
            try:
                ApiCacheHandler().prune()
            except sqlite3.OperationalError as e:  # locked past its timeout
                log.warning(f"{self.__class__.__name__} → API cache prune: {e}")
                self.prune_due = now + 3600
            else:
                self.prune_due = now + 86400
        self.player_monitor.watch_trailer_session()
        self.player_monitor.expire_seek_offset()
        self.player_monitor.watch_playnext()
        self.player_monitor.watch_segments()
        self.player_monitor.watch_game_osd()
        self.slideshow.tick()
        release_refresh()
        if clashes.features() != self.clash_features:
            self._check_clashes()
        self.waitForAbort(self.player_monitor.watch_lyrics())  # last: it times the wait
