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
from resources.lib.shared.sqlite import ApiCacheHandler, ArtworkCacheHandler
from resources.lib.shared.utilities import (
    ADDON,
    reset_dev_state,
    skin_path,
    skin_uses_builder,
    validate_path,
)


class Monitor(xbmc.Monitor):
    """
    Background service monitor. Owns one-time setup (artwork directories,
    builder outputs) and a lightweight poller for the trailer watchdog and
    global slideshow. All work is gated on the active skin opting in.
    """

    def __init__(self) -> None:
        """Initializes the monitor, sets up handlers, and begins polling."""
        # Poller
        self.start = True
        self.idle = False
        self._build_done = False
        self._skindir = None
        self._supported = False
        # Monitors
        self.sqlite = ArtworkCacheHandler()
        self.player_monitor = None
        self.slideshow = None
        # Run
        self._run()

    def _run(self) -> None:
        """
        Top-level service loop: alternate active polling and idle waiting.
        Flat by design — the previous _on_start/_on_stop mutual recursion
        grew the call stack by two frames per idle/resume cycle.
        """
        while not self.abortRequested():
            self._on_start()
            self._on_stop()
        del self.player_monitor
        log.info(f"{self.__class__.__name__} → Stopped")

    def _build_optin_check(self) -> None:
        """
        Run the build pipeline once, when the active skin provides builder
        inputs. Presence of the builder folder structure is the opt-in:
        Copacetic qualifies automatically; any skin opts in by adding it.
        """
        if self._build_done or not self._skin_supported():
            return
        self._builder_elements()
        self._build_done = True

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

    def _on_start(self) -> None:
        """Begins the monitor loop and attaches the player monitor."""
        log.info(f"{self.__class__.__name__} → Python version: {sys.version}")
        self._build_optin_check()
        if self.start:
            log.info(f"{self.__class__.__name__} → Started")
            self.start = False
            ApiCacheHandler().prune()
            self.player_monitor = PlayerMonitor()
            self.slideshow = Slideshow(self.sqlite)
        elif self._conditions_met():
            log.info(f"{self.__class__.__name__} → Resumed")
        while not self.abortRequested() and self._conditions_met():
            self.poller()

    def _skin_supported(self) -> bool:
        """
        True when the active skin opts into the helper. Re-evaluates the
        capability check only when the skin changes; cached otherwise.

        :return: True when the skin opts in.
        """
        skindir = xbmc.getSkinDir()
        if skindir != self._skindir:
            self._skindir = skindir
            self._supported = skin_uses_builder()

        return self._supported

    def _conditions_met(self) -> bool:
        """
        Polling continues while the skin opts in and the service isn't idle.

        :return: True while the polling loop should keep running.
        """
        return self._skin_supported() and not self.idle

    def _on_stop(self) -> None:
        """Called when the polling loop exits. Waits until conditions return."""
        if self.abortRequested():
            return

        log.info(f"{self.__class__.__name__} → Idle, waiting...")
        while not self.abortRequested() and not self._conditions_met():
            self.waitForAbort(10)

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
