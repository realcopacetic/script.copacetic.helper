# author: realcopacetic

from pathlib import Path

import xbmc

from resources.lib.builders.build_elements import BuildElements
from resources.lib.builders.builder_config import BUILDER_CONFIG
from resources.lib.service.player import PlayerMonitor
from resources.lib.service.settings import SettingsMonitor
from resources.lib.shared.art import SlideshowMonitor
from resources.lib.shared.hash import HashManager
from resources.lib.shared.json import JSONHandler
from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import (
    BLURS,
    CONFIGS,
    CROPS,
    TEMPS,
    condition,
    create_dir,
    get_cache_size,
    infolabel,
    log,
    log_and_execute,
    skin_string,
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
        self._ensure_skinsettings_defaults()

    def _ensure_directories_exist(self):
        """Ensures required directories for blur, crop, and temp exist at startup."""
        if not validate_path(self.blur_folder):
            create_dir(self.blur_folder)
        if not validate_path(self.crop_folder):
            create_dir(self.crop_folder)
        if not validate_path(self.temp_folder):
            create_dir(self.temp_folder)

    def _builder_elements(self):
        """
        Regenerates missing or outdated builder output files for 'prep' and 'buildtime'
        run contexts.
        """
        elements_processor = BuildElements()
        hash_manager = HashManager()
        developer_mode = False

        for context in ["prep", "build"]:
            needs_to_run = any(
                (write_path := config.get("write_path"))
                and context in config.get("run_contexts", [])
                and (
                    developer_mode
                    or not validate_path(write_path)
                    #or not hash_manager.validate_hash(write_path)
                )
                for config in BUILDER_CONFIG.values()
            )

            if needs_to_run:
                elements_processor.process(run_contexts=context)

    def _ensure_skinsettings_defaults(self):
        """Ensures default skinsettings are set at startup if not already defined."""
        json_handler = JSONHandler(CONFIGS)
        skinsettings_data = json_handler.data.get(Path(CONFIGS))

        if not skinsettings_data:
            log(
                f"{self.__class__.__name__}: Skinsettings file missing or empty at {CONFIGS}",
                force=True,
            )
            return

        for setting_key, setting_data in skinsettings_data.items():
            default_value = setting_data.get("default")
            if not default_value:
                continue

            if not condition(f"Skin.String({setting_key})"):
                skin_string(setting_key, default_value)

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
