# author: realcopacetic

import xbmc

from resources.lib.service.player import PlayerMonitor
from resources.lib.service.settings import SettingsMonitor
from resources.lib.shared.art import SlideshowMonitor
from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.utilities import (BLUR_FOLDERPATH, CROP_FOLDERPATH,
                                     TEMP_FOLDERPATH, condition, create_dir,
                                     get_cache_size, infolabel, log,
                                     log_and_execute, validate_path)


class Monitor(xbmc.Monitor):
    DEFAULT_REFRESH_INTERVAL = 10

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
        self.player_monitor = None
        self.settings_monitor = SettingsMonitor()
        self.art_monitor = SlideshowMonitor(self.sqlite)
        # Run
        self._create_dirs()
        self._on_start()

    def _conditions_met(self):
        return (
            self._get_skindir() and not self.idle
        )

    def _create_dirs(self):
        if not validate_path(self.blur_folder):
            create_dir(self.blur_folder)
        if not validate_path(self.crop_folder):
            create_dir(self.crop_folder)
        if not validate_path(self.temp_folder):
            create_dir(self.temp_folder)

    def _get_refresh_interval(self):
        try:
            refresh_interval = int(
                infolabel('Skin.String(Background_Interval)')
            )
        except ValueError:
            refresh_interval = self.DEFAULT_REFRESH_INTERVAL
        return refresh_interval

    def _get_skindir(self):
        skindir = xbmc.getSkinDir()
        if 'skin.copacetic' in skindir:
            return True

    def _on_recommendedsettings(self):
        if condition('Window.Is(skinsettings)') and self.check_settings:
            self.settings_monitor.get_default()
            self.check_settings = False
        elif not condition('Window.Is(skinsettings)'):
            self.check_settings = True
        if condition('Skin.HasSetting(run_set_default)'):
            self.settings_monitor.set_default()
            self.check_settings = True
            log_and_execute('Skin.ToggleSetting(run_set_default)')

    def _on_skinsettings(self):
        if condition('Window.Is(skinsettings)') and self.check_cache:
            get_cache_size()
            self.check_cache = False
        elif condition('!Window.Is(skinsettings)'):
            self.check_cach = True

    def _on_start(self):
        if self.start:
            log('Monitor started', force=True)
            self.start = False
            self.player_monitor = PlayerMonitor(self.sqlite)
        else:
            log('Monitor resumed', force=True) if self._conditions_met() else None
        while not self.abortRequested() and self._conditions_met():
            self.poller()
        self._on_stop()

    def _on_stop(self):
        log(f'Monitor idle', force=True)
        while not self.abortRequested() and not self._conditions_met():
            self.waitForAbort(2)
        if not self.abortRequested():
            self._on_start()
        else:
            del self.player_monitor
            del self.settings_monitor
            del self.art_monitor
            log(f'Monitor stopped', force=True)

    def poller(self):
        if condition(
            'Window.IsVisible(home)'
        ):
            self.art_monitor.background_slideshow()
            self._on_skinsettings()
            self._on_recommendedsettings()
            self.waitForAbort(0.5)
        # else wait for next poll
        else:
            self.check_cache = True
            self.check_settings = True
            self.waitForAbort(0.5)

    def onScreensaverActivated(self):
        self.idle = True

    def onScreensaverDeactivated(self):
        self.idle = False
