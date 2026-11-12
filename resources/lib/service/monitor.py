# author: realcopacetic

import json
import sqlite3
import sys
import time

import xbmc

from resources.lib.art.slideshow import Slideshow
from resources.lib.builders.build_elements import BuildElements, output_digests
from resources.lib.builders.builder_config import BUILDER_CONFIG
from resources.lib.builders.templates import cache_is_current
from resources.lib.service.player import PlayerMonitor
from resources.lib.shared import logger as log
from resources.lib.shared.speed_dial import release_refresh, skin_uses_speed_dial
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import (
    ADDON,
    adopt_shared_state,
    condition,
    dev_reset_due,
    infolabel,
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
# Edits to a queue: Kodi's list providers refresh on play, resume and stop, not on these
# (nor on a shuffle, a Player.OnPropertyChanged; a move announces nothing).
PLAYLIST_EDITS = {"Playlist.OnAdd", "Playlist.OnRemove", "Playlist.OnClear"}


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
        log.info(f"{self.__class__.__name__} → Started, Python {sys.version}")
        self._run()

    def _run(self) -> None:
        """
        Service loop: follow every change of the loaded skin's folder, and a new version
        in the same folder unless it's empty (Kodi unregisters a skin it is installing);
        poll each second while it opts in and the screensaver is off, else every 2 s.
        """
        while not self.abortRequested():
            skin = skin_path()
            version = skin_version(skin)
            if skin != self.skin[0] or version and version != self.skin[1]:
                self._follow(skin, version)
            if self.player_monitor and not self.idle:
                self.poller()
            else:
                self.waitForAbort(2)
        # A profile switch keeps Home's properties: release the active state too.
        if self.player_monitor:
            self._deactivate()
        log.info(f"{self.__class__.__name__} → Stopped")

    def _follow(self, skin: str, version: str) -> None:
        """
        Take a new (folder, version) key. A new folder (a switch) drops any due reload
        and releases the active state; a new version in the same folder (an update)
        keeps it, so a trailer plays on. Activates only with a readable version.

        :param skin: Loaded skin's folder.
        :param version: Its registered version, "" when unreadable.
        """
        if skin != self.skin[0]:
            self.reload_due = False
            if self.player_monitor:
                self._deactivate()
        self.skin = skin, version
        if self.player_monitor:
            log.info(f"{self.__class__.__name__} → Skin updated to version {version}")
            self._builder_elements()
            # An update may add or drop speed dial.
            window_property(SPEED_DIAL_PROPERTY, value=skin_uses_speed_dial())
        elif version and skin_uses_builder():
            self._activate()

    def _activate(self) -> None:
        """
        Entering an opted-in skin: check the builder outputs (reloading if any
        changed), start the player monitor and slideshow, then show the context items.
        """
        path, version = self.skin
        log.info(f"{self.__class__.__name__} → Active in {path}, version {version}")
        self._builder_elements()
        self.player_monitor = PlayerMonitor()
        self.slideshow = Slideshow()
        window_property(SPEED_DIAL_PROPERTY, value=skin_uses_speed_dial())
        window_property(ACTIVE_PROPERTY, value="true")

    def _deactivate(self) -> None:
        """Leaving the skin: hide the context items, release the monitors."""
        window_property(ACTIVE_PROPERTY)
        window_property(SPEED_DIAL_PROPERTY)
        self.player_monitor.release()
        self.slideshow.clear()
        self.player_monitor = self.slideshow = None
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
        Build, then reload if an output changed. Production: missing outputs, or all
        when ids are fresh or the resolver cache is missing or stale (other skin, new
        skin or helper version, an output another profile wrote). Dev: clear state if
        requested, rebuild, reload.
        """
        adopt_shared_state()  # first, so a dev reset clears what it adopts
        pin_dev_reset()  # one turned on outside a builder skin, or before this helper
        dev_mode = ADDON.getSettingBool("dev_mode")

        if dev_mode and dev_reset_due():
            reset_dev_state()
            log.info(
                f"{self.__class__.__name__} → Dev reset consumed — "
                f"outputs and runtime_state cleared"
            )

        if dev_mode:
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
        Kodi event hook: a new playlist_revision on each music queue edit while
        active (a shuffle too), which the skin's queue rail puts in its path.

        :param sender: Announcement sender.
        :param method: Announcement name, e.g. "Playlist.OnAdd".
        :param data: Its data as JSON.
        """
        if not self.player_monitor or infolabel(
            "Window(home).Property(playlist_replacing)"
        ):
            return  # play_files is filling the queue: its play refetches the lists
        if method in PLAYLIST_EDITS:
            edited = json.loads(data).get("playlistid") == 0
        elif method == "Player.OnPropertyChanged":
            data = json.loads(data)
            edited = "shuffled" in data["property"] and data["player"]["playerid"] == 0
        else:
            return
        if edited:
            window_property("playlist_revision", value=str(time.monotonic_ns()))

    def onSettingsChanged(self) -> None:
        """Kodi event hook: re-read debug_logging, pin a new reset to this skin."""
        log.debug_logging.cache_clear()
        pin_dev_reset()

    def poller(self) -> None:
        """
        Polling loop: trailer session watchdog, seek offset expiry, Play next's
        switch-off, global slideshow and held speed dial refreshes, plus a daily API
        cache prune.
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
        self.slideshow.tick()
        release_refresh()
        self.waitForAbort(1)
