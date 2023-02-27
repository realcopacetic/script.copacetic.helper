#!/usr/bin/python
# coding: utf-8
import xbmc

from resources.lib.service.art import SlideshowMonitor
from resources.lib.service.player import PlayerMonitor
from resources.lib.utilities import condition, log, get_cropped_clearlogo


class Monitor(xbmc.Monitor):
    def __init__(self):
        self.start = True
        self.idle = False
        self.player_monitor = None
        self.media_monitor = None
        self.art_monitor = SlideshowMonitor()
        self._on_start()

    def onScreensaverActivated(self):
        self.idle = True

    def onScreensaverDeactivated(self):
        self.idle = False

    def _get_skindir(self):
        skindir = xbmc.getSkinDir()
        if skindir == 'skin.copacetic':
            return True

    def _conditions_met(self):
        return (
            self._get_skindir() and not self.idle and
            (
                condition('!Skin.HasSetting(Background_Disabled)') or
                condition('Skin.HasSetting(Crop_Clearlogos)')
            )
        )

    def _on_start(self):
        if self.start:
            log('Monitor started', force=True)
            self.start = False
            self.player_monitor = PlayerMonitor()
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
            del self.media_monitor
            del self.art_monitor
            log(f'Monitor stopped', force=True)

    def poller(self):

        #video playing fullscreen
        if condition(
            'VideoPlayer.IsFullscreen'
        ):
            self.waitForAbort(1)

        # secondary list has focus and clearlogo view visible
        elif condition(
            'Skin.HasSetting(Crop_Clearlogos) + ['
            'Control.HasFocus(3100) + ['
            'Control.IsVisible(501) | Control.IsVisible(502) | Control.IsVisible(504)]]'
        ):
            get_cropped_clearlogo(key='3100')
            self.waitForAbort(0.2)

        # clearlogo view visible
        elif condition(
            'Skin.HasSetting(Crop_Clearlogos) + ['
            'Control.IsVisible(501) | '
            'Control.IsVisible(502) | '
            'Control.IsVisible(504)]'
        ):
            get_cropped_clearlogo()
            self.waitForAbort(0.2)

        # slideshow window is visible run SlideshowMonitor()
        elif condition(
            '!Skin.HasSetting(Background_Disabled) + ['
            'Window.IsVisible(home) | '
            'Window.IsVisible(settings) | '
            'Window.IsVisible(skinsettings) | '
            'Window.IsVisible(appearancesettings) | '
            'Window.IsVisible(mediasettings) | '
            'Window.IsVisible(playersettings) | '
            'Window.IsVisible(servicesettings) | '
            'Window.IsVisible(systemsettings) | '
            'Window.IsVisible(pvrsettings) | '
            'Window.IsVisible(gamesettings) | '
            'Window.IsVisible(profiles) | '
            'Window.IsVisible(systeminfo) | '
            'Window.IsVisible(filemanager) | '
            'Window.IsVisible(addonsettings) + !String.IsEmpty(ListItem.Art(fanart)) | '
            'Window.IsVisible(addonbrowser) + !Container.Content(addons) | '
            'Window.IsVisible(mediasource) | '
            'Window.IsVisible(smartplaylisteditor) | '
            'Window.IsVisible(musicplaylisteditor) | '
            'Window.IsVisible(mediasource) | '
            'Container.Content(genres) | '
            'Container.Content(years) | '
            'Container.Content(playlists) | '
            'Container.Content(sources) | '
            'Container.Content(studios) | '
            'Container.Content(directors) | '
            'Container.Content(tags) | '
            'Container.Content(countries) | '
            'Container.Content(roles) | '
            'Container.Content() + [Window.Is(videos) | Window.Is(music)]]'
        ):
            self.art_monitor.background_slideshow()
            self.waitForAbort(1)

        # else wait for next poll
        else:
            self.waitForAbort(1)
