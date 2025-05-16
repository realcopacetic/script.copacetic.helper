# author: realcopacetic

from pathlib import Path

import xbmc

from resources.lib.builders.build_elements import BuildElements
from resources.lib.builders.builder_config import BUILDER_CONFIG
from resources.lib.service.player import PlayerMonitor
from resources.lib.service.settings import SettingsMonitor
from resources.lib.shared.art import SlideshowMonitor
from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import (
    ADDON,
    BLURS,
    CROPS,
    TEMPS,
    condition,
    create_dir,
    get_cache_size,
    infolabel,
    log,
    log_and_execute,
    validate_path,
)


class Monitor(xbmc.Monitor):
    """
    Background service monitor for handling slideshow, player, and skin setup.
    Manages lifecycle events, directory setup, file regeneration, and idle polling.
    """

    DEFAULT_SLIDESHOW_INTERVAL = 10

    def __init__(self):
        """Initializes the monitor, sets up handlers, and begins polling."""
        # Poller
        self.start = True
        self.idle = False
        self.check_settings, self.check_cache = True, True
        # Setup
        self.blur_folder = BLURS
        self.crop_folder = CROPS
        self.temp_folder = TEMPS
        # Monitors
        self.sqlite = SQLiteHandler()
        self.settings = SettingsMonitor()
        self.slideshow = SlideshowMonitor(self.sqlite)
        self.slideshow_wait = 0
        self.slideshow_interval = self._get_slideshow_interval()
        self.player_monitor = None
        # Run
        self._create()
        self._on_start()

    def _get_slideshow_interval(self):
        """
        Gets the slideshow interval from skin settings or defaults to 10.

        :returns: Integer value in seconds.
        """
        return int(
            infolabel("Skin.String(slideshow_interval)")
            or self.DEFAULT_SLIDESHOW_INTERVAL
        )

    def _create(self):
        """Handles full startup initialization (directories + skin files)."""
        self._ensure_directories_exist()
        self._builder_elements()

    def _ensure_directories_exist(self):
        """Ensures required directories for blur, crop, and temp exist at startup."""
        for folder in [
            self.blur_folder,
            self.crop_folder,
            self.temp_folder,
        ]:
            if not validate_path(folder):
                create_dir(folder)

    def _builder_elements(self):
        """
        Regenerates missing or outdated builder output files for 'prep' and 'buildtime'
        run contexts.
        """
        dev_mode = ADDON.getSettingBool("dev_mode")

        for context in ["prep", "build"]:
            builders = None
            if not dev_mode:
                builders = [
                    builder
                    for builder, config in BUILDER_CONFIG.items()
                    if context in config.get("run_contexts", [])
                    and (write_path := config.get("write_path"))
                    and not validate_path(write_path)
                ]

            BuildElements(
                run_context=context,
                builders_to_run=builders,
                force_rebuild=dev_mode,
            )

    def _on_start(self):
        """Begins the monitor loop and attaches the player monitor."""
        if self.start:
            log(f"{self.__class__.__name__}: Started", force=True)
            self.start = False
            self.player_monitor = PlayerMonitor(self.sqlite)
        else:
            (
                log(f"{self.__class__.__name__}: Resumed", force=True)
                if self._conditions_met()
                else None
            )
        while not self.abortRequested() and self._conditions_met():
            self.poller()
        self._on_stop()

    def _conditions_met(self):
        """
        Checks whether polling should continue (not idle + valid skin).

        :returns: Boolean
        """
        return self._get_skindir() and not self.idle

    def _on_stop(self):
        """Called when monitor loop exits. Waits for restart or exits cleanly."""
        log(f"{self.__class__.__name__}: Idle, waiting...", force=True)
        while not self.abortRequested() and not self._conditions_met():
            self.waitForAbort(2)
        if not self.abortRequested():
            self._on_start()
        else:
            del self.player_monitor
            del self.settings
            del self.slideshow
            log(f"{self.__class__.__name__}: Stopped", force=True)

    def onScreensaverActivated(self):
        """Kodi event hook: Pause monitoring when screensaver starts."""
        self.idle = True

    def onScreensaverDeactivated(self):
        """Kodi event hook: Resume monitoring when screensaver ends."""
        self.idle = False

    def poller(self):
        """Polling loop that runs background tasks for different windows."""
        if condition("Window.IsVisible(home)"):
            # Run slideshow whenever wait is 0
            if self.slideshow_wait == 0:
                self.slideshow.background_slideshow(
                    infolabel("Skin.String(slideshow_type)")
                )
            # Account for interval changes ahead of next pass
            new_slideshow_interval = self._get_slideshow_interval()
            if self.slideshow_interval != new_slideshow_interval:
                self.slideshow_interval = new_slideshow_interval
                self.slideshow_wait = min(self.slideshow_wait, self.slideshow_interval)
            # Reset countdown if interval reached, otherwise increment
            self.slideshow_wait = (self.slideshow_wait + 1) % self.slideshow_interval
        elif condition("Window.IsVisible(skinsettings)"):
            if self.check_cache:
                get_cache_size()
                self.check_cache = False
            if self.check_settings:
                self.settings.get_defaults()
                self.check_settings = False
            if condition("Skin.HasSetting(set_skin_defaults)"):
                self.settings.set_defaults()
                self.check_settings = True
                log_and_execute("Skin.ToggleSetting(set_skin_defaults)")
        else:
            self.check_cache = True
            self.check_settings = True
        self.waitForAbort(1)

    @staticmethod
    def _get_skindir():
        """
        Validates that the active skin is part of the Copacetic skin family.

        :returns: True if active skin matches expected ID, else False.
        """
        return "skin.copacetic" in xbmc.getSkinDir()
