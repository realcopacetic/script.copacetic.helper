#!/usr/bin/python
# coding: utf-8


import xbmc
import random
from resources.lib.utilities import *
from resources.lib.actions import clean_filename


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
            DIALOG.notification(ADDON_ID, ADDON.getLocalizedString(32200))
            self.__init__()


    def keep_alive(self):
        log('Monitor: Disabled', force=True)

        while not self.abortRequested() and not self.restart:

            self.waitForAbort(5)

        self.stop()


    def start(self):
        log('Monitor: Started', force=True)

        service_interval = 1
        try:
            background_interval = int(infolabel('Skin.String(Background_Interval)'))
        except ValueError:
            background_interval = 10
        
        background_get_count = background_interval * 30
        background_refresh_count = background_interval

        while not self.abortRequested() and not self.restart:

            # Only run timed tasks screensaver is inactive (to avoid keeping NAS/servers awake)
            if not self.screensaver:

                # Check if skin.copacetic is selected
                skindir = xbmc.getSkinDir()
                if skindir == 'skin.copacetic':

                    #Check if skin string has changed
                    try:
                        if background_interval != int(infolabel('Skin.String(Background_Interval)')):
                            log('Monitor: Restarting due to change in background refresh interval', force=True)
                            self.__init__()
                    except ValueError:
                        pass

                    # Get fanarts every (background_interval * 30) seconds
                    if background_get_count >= (background_interval * 30):
                        log('Monitor: Get fanart', force=True)
                        arts = self.get_fanart()
                        background_get_count = 0
                    else:
                        background_get_count += service_interval

                    # Set background properties every (background_interval) seconds
                    if background_refresh_count >= background_interval:
                        if arts.get('all'):
                            self.setfanart('Background_Global', arts['all'])
                        if arts.get('movies'):
                            self.setfanart('Background_Movies', arts['movies'])
                        if arts.get('tvshows'):
                            self.setfanart('Background_TVShows', arts['tvshows'])
                        if arts.get('videos'):
                            self.setfanart('Background_Videos', arts['videos'])
                        if arts.get('artists'):
                            self.setfanart('Background_Artists', arts['artists'])
                        background_refresh_count = 0
                    else:
                        background_refresh_count += service_interval

            # Wait for time equal to service_interval in seconds before next loop
            self.waitForAbort(service_interval)

        self.stop()


    def get_fanart(self):
        arts = {}
        arts['movies'] = []
        arts['tvshows'] = []
        arts['artists'] = []
        arts['musicvideos'] = []
        arts['all'] = []
        arts['videos'] = []

        for item in ['movies', 'tvshows', 'artists', 'musicvideos']:
            dbtype = 'Video' if item != 'artists' else 'Audio'
            query = json_call(f'{dbtype}Library.Get{item}',
                              properties=['art'],
                              sort={'method': 'random'}, limit=40,
                              parent='grab_fanart'
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
        window_property(key + '_Fanart', set_property = arts.get('fanart', ''))
        if arts.get('clearlogo', False):
            window_property(key + '_Clearlogo', set_property= arts.get('clearlogo', ''))
        else:
            window_property(key + '_Clearlogo', clear_property = True)


class Player(xbmc.Player):

    def __init__(self):
        xbmc.Player.__init__(self)


    def onAVStarted(self):
        if self.isPlayingVideo():
            item  = self.getPlayingItem()
            label = item.getLabel()
            if label:
                clean_filename(label=label)
            else:
                window_property('Return_Label', clear_property=True)
        
        if self.isPlayingAudio():
            tag = self.getMusicInfoTag()
            user_rating = tag.getUserRating()
            album_artist = tag.getAlbumArtist()
            window_property('MusicPlayer_UserRating', set_property=user_rating)
            window_property('MusicPlayer_AlbumArtist', set_property=album_artist)


    def onPlayBackStopped(self):
        window_property('MusicPlayer_UserRating', clear_property=True)
        window_property('MusicPlayer_AlbumArtist', clear_property=True)
        window_property('Return_Label', clear_property=True)