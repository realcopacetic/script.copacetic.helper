#!/usr/bin/python
# coding: utf-8
import xbmc

from resources.lib.service.art import ImageEditor, SlideshowMonitor
from resources.lib.service.player import PlayerMonitor
from resources.lib.utilities import (condition, get_folder_size, infolabel,
                                     log, window_property)


class Monitor(xbmc.Monitor):
    def __init__(self):
        self.start = True
        self.idle = False
        self.player_monitor = None
        self.media_monitor = None
        self.art_monitor = SlideshowMonitor()
        self.position = False
        self._on_start()

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

    def _conditions_met(self):
        return (
            self._get_skindir() and not self.idle and
            (
                condition('!Skin.HasSetting(Background_Disabled)') or
                condition('Skin.HasSetting(Crop_Clearlogos)')
            )
        )

    def _get_skindir(self):
        skindir = xbmc.getSkinDir()
        if skindir == 'skin.copacetic':
            return True

    def poller(self):
        # Tasks to perform each cycle

        # video playing fullscreen
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
            self._on_scroll(key='3100', return_color=False)

        # clearlogo view visible
        elif condition(
            'Skin.HasSetting(Crop_Clearlogos) + ['
            'Control.IsVisible(501) | '
            'Control.IsVisible(502) | '
            'Control.IsVisible(504)]'
        ):
            self._on_scroll()

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
            size = get_folder_size()
            self.art_monitor.background_slideshow()
            self.waitForAbort(1)

        # else wait for next poll
        else:
            self.waitForAbort(1)

    def _on_scroll(self, key='ListItem', return_color=True):
        current_item = self._current_item(key)
        if current_item != self.position:
            self._clearlogo_cropper = ImageEditor().clearlogo_cropper
            self._clearlogo_cropper(
                source=key, return_height=True, return_color=return_color, reporting=window_property)
        self.waitForAbort(0.2)
        self.position = current_item

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

    def _current_item(self, key='ListItem'):
        if key == 'ListItem':
            container = 'Container.CurrentItem'
        else:
            container = f'Container({key}).CurrentItem'
        current_item = infolabel(container)
        return current_item

    def onScreensaverActivated(self):
        self.idle = True

    def onScreensaverDeactivated(self):
        self.idle = False
