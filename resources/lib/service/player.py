#!/usr/bin/python
# coding: utf-8
from xbmc import Player

from resources.lib.script.actions import clean_filename
from resources.lib.utilities import window_property


class PlayerMonitor(Player):
    def __init__(self):
        Player.__init__(self)

    def onAVStarted(self):
        # clean filename on video playback
        if self.isPlayingVideo():
            item = self.getPlayingItem()
            label = item.getLabel()
            if label:
                clean_filename(label=label)
            else:
                window_property('Return_Label', clear_property=True)

        # Get user rating on music playback
        if self.isPlayingAudio():
            tag = self.getMusicInfoTag()
            user_rating = tag.getUserRating()
            album_artist = tag.getAlbumArtist()
            window_property('MusicPlayer_UserRating', set_property=user_rating)
            window_property('MusicPlayer_AlbumArtist',
                            set_property=album_artist)

    def onPlayBackStopped(self):
        window_property('MusicPlayer_UserRating', clear_property=True)
        window_property('MusicPlayer_AlbumArtist', clear_property=True)
        window_property('Return_Label', clear_property=True)
