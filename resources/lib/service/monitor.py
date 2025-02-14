# author: realcopacetic

import xbmc

from resources.lib.service.player import PlayerMonitor
from resources.lib.service.settings import SettingsMonitor
from resources.lib.shared.art import SlideshowMonitor
from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import (BLUR_FOLDERPATH, CROP_FOLDERPATH,
                                            TEMP_FOLDERPATH, condition,
                                            create_dir, get_cache_size,
                                            infolabel, log, log_and_execute,
                                            validate_path)


class Monitor(xbmc.Monitor):
    DEFAULT_SLIDESHOW_INTERVAL = 10

    def __init__(self):
        # Poller
        self.start = True
        self.idle = False
        self.check_settings, self.check_cache = True, True
        # Setup
        self.blur_folder = BLUR_FOLDERPATH
        self.crop_folder = CROP_FOLDERPATH
        self.temp_folder = TEMP_FOLDERPATH
        # Monitors
        self.sqlite = SQLiteHandler()
        self.settings = SettingsMonitor()
        self.slideshow = SlideshowMonitor(self.sqlite)
        self.slideshow_wait = 0
        self.slideshow_interval = self.get_slideshow_interval()
        self.player_monitor = None
        # Run
        self.create_dirs()
        self.on_start()

    def get_slideshow_interval(self):
        # Fetches user-defined slideshow interval or defaults to 10 seconds
        return int(infolabel("Skin.String(slideshow_interval)")
                       or self.DEFAULT_SLIDESHOW_INTERVAL)

    def create_dirs(self):
        # Ensures necessary directories exist at startup
        if not validate_path(self.blur_folder):
            create_dir(self.blur_folder)
        if not validate_path(self.crop_folder):
            create_dir(self.crop_folder)
        if not validate_path(self.temp_folder):
            create_dir(self.temp_folder)

    def on_start(self):
        # Handles monitor startup and polling loop
        if self.start:
            log("Monitor started", force=True)
            self.start = False
            self.player_monitor = PlayerMonitor(self.sqlite)
        else:
            log("Monitor resumed", force=True) if self._conditions_met() else None
        while not self.abortRequested() and self._conditions_met():
            self.poller()
        self._on_stop()

    def _conditions_met(self):
        # Checks if monitor should continue running
        return (self._get_skindir() and not self.idle)

    def _get_skindir(self):
        # Checks if skin.copacetic or skin.copacetic2 is active skin
        return "skin.copacetic" in xbmc.getSkinDir()

    def _on_stop(self):
        # Handles shutdown behaviour
        log(f"Monitor idle, waiting...", force=True)
        while not self.abortRequested() and not self._conditions_met():
            self.waitForAbort(2)
        if not self.abortRequested():
            self._on_start()
        else:
            del self.player_monitor
            del self.settings
            del self.slideshow
            log(f"Monitor stopped", force=True)

    def onScreensaverActivated(self):
        # Pauses monitoring when screensaver activates
        self.idle = True

    def onScreensaverDeactivated(self):
        # Resumes monitoring when screensaver deactivates
        self.idle = False
    
    def poller(self):
        # Loop for background task
        if condition("Window.IsVisible(home)"):
            # Run slideshow whenever wait is 0
            if self.slideshow_wait == 0:
                self.slideshow.background_slideshow(
                    infolabel("Skin.String(slideshow_type)"))
            # Account for interval changes ahead of next pass
            new_slideshow_interval = self.get_slideshow_interval()
            if self.slideshow_interval != new_slideshow_interval:
                self.slideshow_interval = new_slideshow_interval
                self.slideshow_wait = min(self.slideshow_wait, self.slideshow_interval)
            # Reset countdown if interval reached, otherwise increment
            self.slideshow_wait = 0 if self.slideshow_wait + \
                1 == self.slideshow_interval else self.slideshow_wait + 1
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
