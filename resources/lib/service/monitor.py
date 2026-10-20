# author: realcopacetic

import sys
import time

import xbmc

from resources.lib.art.slideshow import Slideshow
from resources.lib.builders.build_elements import BuildElements
from resources.lib.builders.builder_config import BUILDER_CONFIG
from resources.lib.builders.templates import cache_is_current
from resources.lib.service.player import PlayerMonitor
from resources.lib.shared import logger as log
from resources.lib.shared.speed_dial import release_refresh
from resources.lib.shared.sqlite import ApiCacheHandler
from resources.lib.shared.utilities import (
    ADDON,
    condition,
    infolabel,
    reset_dev_state,
    skin_path,
    skin_uses_builder,
    skin_version,
    validate_path,
    window_property,
)

# Set while an opted-in skin is active; addon.xml's context items test it.
ACTIVE_PROPERTY = "helper_active"
# Token _settle posts through Kodi's builtin queue to see when the queue has run.
SETTLE_PROPERTY = "helper_settle"


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
        elif version and skin_uses_builder():
            self._activate()

    def _activate(self) -> None:
        """
        Entering an opted-in skin: check the builder outputs (reloading if any
        changed), prune the API cache, start the player monitor and slideshow, then
        show the context items.
        """
        path, version = self.skin
        log.info(f"{self.__class__.__name__} → Active in {path}, version {version}")
        self._builder_elements()
        ApiCacheHandler().prune()
        self.player_monitor = PlayerMonitor()
        self.slideshow = Slideshow()
        window_property(ACTIVE_PROPERTY, value="true")

    def _deactivate(self) -> None:
        """Leaving the skin: hide the context items, release the monitors."""
        window_property(ACTIVE_PROPERTY)
        self.player_monitor.release()
        self.slideshow.clear()
        self.player_monitor = self.slideshow = None
        log.info(f"{self.__class__.__name__} → Inactive, skin left")

    def _builder_elements(self) -> None:
        """
        Build, then reload if an output changed. Production: missing outputs, or all
        when ids are fresh or the resolver cache is missing or stale (other skin, new
        skin or helper version). Dev: clear state if requested, rebuild, reload.
        """
        dev_mode = ADDON.getSettingBool("dev_mode")
        dev_reset = ADDON.getSettingBool("dev_reset")

        if dev_mode and dev_reset:
            reset_dev_state()
            ADDON.setSettingBool("dev_reset", False)
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
        if seeded or not cache_is_current(build.stamp):
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
        resets Kodi to the default one).
        """
        if not self._settle():
            return
        path, version = self.skin
        if skin_path() != path:
            self.reload_due = False
            log.info(f"{self.__class__.__name__} → Reload dropped, skin switched")
            return
        self.reload_due = skin_version(path) != version
        if self.reload_due:
            log.info(f"{self.__class__.__name__} → Reload deferred, skin updating")
        else:
            xbmc.executebuiltin("ReloadSkin()")

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
                return True
            if self.waitForAbort(0.2):
                return False
        return True

    def onScreensaverActivated(self) -> None:
        """Kodi event hook: Pause monitoring when screensaver starts."""
        self.idle = True

    def onScreensaverDeactivated(self) -> None:
        """Kodi event hook: Resume monitoring when screensaver ends."""
        self.idle = False

    def onSettingsChanged(self) -> None:
        """Kodi event hook: re-read the add-on's debug_logging setting."""
        log.debug_logging.cache_clear()

    def poller(self) -> None:
        """
        Polling loop: trailer session watchdog, global slideshow and held
        speed dial refreshes, plus per-window tasks.
        """
        self.player_monitor.watch_trailer_session()
        self.slideshow.tick()
        release_refresh()
        self.waitForAbort(1)
