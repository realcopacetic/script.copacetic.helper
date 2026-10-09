# author: realcopacetic

import sys
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
    reset_dev_state,
    skin_path,
    skin_uses_builder,
    validate_path,
    window_property,
)

# Set while an opted-in skin is active; addon.xml's context items test it.
ACTIVE_PROPERTY = "helper_active"


class Monitor(xbmc.Monitor):
    """
    Background service monitor. All work is gated on the active skin opting in
    (shipping the builder folders): entering such a skin activates the build
    check, player monitor and slideshow; leaving it releases them.
    """

    def __init__(self) -> None:
        """Initialise the service state, then run the loop until Kodi exits."""
        self.idle = False
        self.skin = None
        self.player_monitor = None
        self.slideshow = None
        log.info(f"{self.__class__.__name__} → Started, Python {sys.version}")
        self._run()

    def _run(self) -> None:
        """
        Flat service loop: follow the active skin's folder (special://skin moves
        once the new skin loads), poll each second while it opts in and the
        screensaver is off, else look again in 2 s (only a path check). Stopping
        releases the active state too: a profile switch keeps Home's properties.
        """
        while not self.abortRequested():
            if (skin := skin_path()) != self.skin:
                self.skin = skin
                if self.player_monitor:
                    self._deactivate()
                if skin_uses_builder():
                    self._activate()
            if self.player_monitor and not self.idle:
                self.poller()
            else:
                self.waitForAbort(2)
        if self.player_monitor:
            self._deactivate()
        log.info(f"{self.__class__.__name__} → Stopped")

    def _activate(self) -> None:
        """
        Entering an opted-in skin: check the builder outputs (reloading if any were
        built), prune the API cache, start the player monitor and slideshow, then
        show the context items.
        """
        log.info(f"{self.__class__.__name__} → Active in {self.skin}")
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
        Run the build pipeline, then reload the skin if anything was built.
        Production: rebuild missing outputs, or all when ids are fresh or the
        resolver cache is missing or from another skin.
        Dev: clear state if requested, rebuild everything.
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
            xbmc.executebuiltin("ReloadSkin()")
            return

        build = BuildElements()
        seeded = build.runtime_manager.initialize_runtime_state()
        builders = [
            builder
            for builder, config in BUILDER_CONFIG.items()
            if (write_path := config.get("write_path"))
            and not validate_path(skin_path(write_path))
        ]
        if seeded or not cache_is_current():
            # Fresh ids, or a resolver cache that is missing or from another skin:
            # full rebuild so every output bakes the same state generation.
            build.run()
        elif builders:
            BuildElements(builders_to_run=builders).run()
        else:
            return
        # The skin loaded before this build; reload so it reads the new outputs.
        xbmc.executebuiltin("ReloadSkin()")

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
