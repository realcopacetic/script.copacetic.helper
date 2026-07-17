# author: realcopacetic

import sys

import xbmc

from resources.lib.builders.build_elements import BuildElements
from resources.lib.builders.builder_config import BUILDER_CONFIG
from resources.lib.builders.templates import cache_is_current
from resources.lib.service.player import PlayerMonitor
from resources.lib.shared import logger as log
from resources.lib.shared.sqlite import ArtworkCacheHandler
from resources.lib.shared.utilities import (
    ADDON,
    BLURS,
    CROPS,
    TEMPS,
    reset_dev_state,
    skin_uses_builder,
    validate_path,
)


class Monitor(xbmc.Monitor):
    """
    Background service monitor. Owns one-time setup (artwork directories,
    builder outputs) and a lightweight poller for the trailer watchdog.
    All work is gated on the active skin opting into the helper.
    """

    def __init__(self):
        """Initializes the monitor, sets up handlers, and begins polling."""
        # Poller
        self.start = True
        self.idle = False
        self._build_done = False
        self._skindir = None
        self._supported = False
        # Setup
        self.blur_folder = BLURS
        self.crop_folder = CROPS
        self.temp_folder = TEMPS
        # Monitors
        self.sqlite = ArtworkCacheHandler()
        self.player_monitor = None
        # Run
        self._on_start()

    def _build_optin_check(self):
        """
        Run the build pipeline once, when the active skin provides builder
        inputs. Presence of the builder folder structure is the opt-in:
        Copacetic qualifies automatically; any skin opts in by adding it.
        """
        if self._build_done or not self._skin_supported():
            return
        self._builder_elements()
        self._build_done = True

    def _builder_elements(self):
        """
        Run the build pipeline.
        Production: only rebuild outputs that are missing.
        Dev: clear state if requested, rebuild everything, reload skin.
        """
        dev_mode = ADDON.getSettingBool("dev_mode")
        dev_reset = ADDON.getSettingBool("dev_reset")

        if dev_mode and dev_reset:
            reset_dev_state()
            ADDON.setSettingBool("dev_reset", False)
            log.info(
                f"{self.__class__.__name__}: Dev reset consumed — "
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
            and not validate_path(write_path)
        ]
        if seeded or not cache_is_current():
            # Fresh ids or changed templates: full rebuild so every output
            # bakes the same state generation (partial rebuilds mix ids).
            build.run()
        elif builders:
            BuildElements(builders_to_run=builders).run()

    def _on_start(self):
        """Begins the monitor loop and attaches the player monitor."""
        log.info(f"{self.__class__.__name__} → Python version: {sys.version}")
        self._build_optin_check()
        if self.start:
            log.info(f"{self.__class__.__name__}: Started")
            self.start = False
            self.player_monitor = PlayerMonitor(self.sqlite)
        elif self._conditions_met():
            log.info(f"{self.__class__.__name__}: Resumed")
        while not self.abortRequested() and self._conditions_met():
            self.poller()
        self._on_stop()

    def _skin_supported(self):
        """
        True when the active skin opts into the helper. Re-evaluates the
        capability check only when the skin changes; cached otherwise.

        :return: Boolean
        """
        skindir = xbmc.getSkinDir()
        if skindir != self._skindir:
            self._skindir = skindir
            self._supported = skin_uses_builder()

        return self._supported

    def _conditions_met(self):
        """
        Polling continues while the skin opts in and the service isn't idle.

        :return: Boolean
        """
        return self._skin_supported() and not self.idle

    def _on_stop(self):
        """Called when monitor loop exits. Waits for restart or exits cleanly."""
        log.info(f"{self.__class__.__name__}: Idle, waiting...")
        while not self.abortRequested() and not self._conditions_met():
            self.waitForAbort(10)
        if not self.abortRequested():
            self._on_start()
        else:
            del self.player_monitor
            log.info(f"{self.__class__.__name__}: Stopped")

    def onScreensaverActivated(self):
        """Kodi event hook: Pause monitoring when screensaver starts."""
        self.idle = True

    def onScreensaverDeactivated(self):
        """Kodi event hook: Resume monitoring when screensaver ends."""
        self.idle = False

    def poller(self):
        """
        Polling loop: trailer session watchdog and global slideshow,
        plus per-window tasks.
        """
        self.player_monitor.watch_trailer_session()
        # Slideshow reinstatement: own cadence + enable-gate inside
        # SlideshowMonitor and call a single tick() here, e.g.
        #   if condition("Window.IsVisible(home)"):
        #       self.slideshow.tick()
        # Instantiate it behind the capability gate like player_monitor,
        # passing self.sqlite; gate the work on Skin.String(slideshow_type).
        self.waitForAbort(1)
