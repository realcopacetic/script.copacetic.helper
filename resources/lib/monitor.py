#!/usr/bin/python
# coding: utf-8


import xbmc
import random
from resources.lib.helper import *


NOTIFICATION_METHOD = ['VideoLibrary.OnUpdate',
                       'VideoLibrary.OnScanFinished',
                       'VideoLibrary.OnCleanFinished',
                       'AudioLibrary.OnUpdate',
                       'AudioLibrary.OnScanFinished'
                       ]


class Monitor(xbmc.Monitor):
    def __init__(self):
        self.restart = False
        self.screensaver = False
        self.service_enabled = True

        if self.service_enabled:
            self.start()
        else:
            self.keep_alive()

    def onNotification(self, sender, method, data):
        if ADDON_ID in sender and 'restart' in method:
            self.restart = True

    def onSettingsChanged(self):
        log('Monitor: Addon setting changed', force=True)
        self.restart = True

    def onScreensaverActivated(self):
        self.screensaver = True

    def onScreensaverDeactivated(self):
        self.screensaver = False

    def stop(self):
        if self.service_enabled:
            log('Monitor: Stopped', force=True)

        if self.restart:
            log('Monitor: Applying changes', force=True)
            # Give Kodi time to set possible changed skin settings. Just to be sure to bypass race conditions on slower systems.
            xbmc.sleep(500)
            DIALOG.notification(ADDON_ID, ADDON.getLocalizedString(32006))
            self.__init__()

    def keep_alive(self):
        log('Monitor: Disabled', force=True)

        while not self.abortRequested() and not self.restart:
            self.waitForAbort(5)

        self.stop()

    def start(self):
        log('Monitor: Started', force=True)

        service_interval = 0.5
        background_interval = 7
        get_backgrounds = 300

        while not self.abortRequested() and not self.restart:

            ''' Only run timed tasks if screensaver is inactive to avoid keeping NAS/servers awake
            '''
            if not self.screensaver:

                ''' Get fanarts
                '''
                if get_backgrounds >= 300:
                    log('Monitor: Get fanart', force=True)
                    arts = self.grabfanart()
                    get_backgrounds = 0

                else:
                    get_backgrounds += service_interval

                ''' Set background properties
                '''
                if background_interval >= 7:
                    if arts.get('all'):
                        self.setfanart('Fanart_Slideshow_Global', arts['all'])
                    if arts.get('movies'):
                        self.setfanart('Fanart_Slideshow_Movies', arts['movies'])
                    if arts.get('tvshows'):
                        self.setfanart('Fanart_Slideshow_TVShows', arts['tvshows'])
                    if arts.get('videos'):
                        self.setfanart('Fanart_Slideshow_Videos', arts['videos'])
                    if arts.get('artists'):
                        self.setfanart('Fanart_Slideshow_Artists', arts['artists'])
                    if arts.get('musicvideos'):
                        self.setfanart('Fanart_Slideshow_MusicVideos', arts['musicvideos'])

                    background_interval = 0

                else:
                    
                    background_interval += service_interval

            self.waitForAbort(service_interval)

        self.stop()


    def grabfanart(self):
        arts = {}
        arts['movies'] = []
        arts['tvshows'] = []
        arts['artists'] = []
        arts['musicvideos'] = []
        arts['all'] = []
        arts['videos'] = []

        for item in ['movies', 'tvshows', 'artists', 'musicvideos']:
            dbtype = 'Video' if item != 'artists' else 'Audio'
            query = json_call('%sLibrary.Get%s' % (dbtype, item),
                              properties=['art'],
                              sort={'method': 'random'}, limit=40
                              )

            try:
                for result in query['result'][item]:
                    if result['art'].get('fanart'):
                        data = {'title': result.get('label', '')}
                        data.update(result['art'])
                        arts[item].append(data)

            except KeyError:
                pass

        arts['videos'] = arts['movies'] + arts['tvshows']

        for cat in arts:
            if arts[cat]:
                arts['all'] = arts['all'] + arts[cat]

        return arts


    def setfanart(self, key, items):
        arts = random.choice(items)
        window_property(key, arts.get('fanart', ''))