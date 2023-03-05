#!/usr/bin/python
# coding: utf-8
from xbmc import Player

from resources.lib.script.actions import clean_filename
from resources.lib.service.art import ImageEditor
from resources.lib.utilities import window_property


class PlayerMonitor(Player):
    def __init__(self):
        Player.__init__(self)
        self.clearlogo_cropper = ImageEditor().clearlogo_cropper

    def onAVStarted(self):
        if self.isPlayingVideo():
            self.clearlogo_cropper(source='VideoPlayer', reporting=window_property)

        # Clean filename on video playback
            item = self.getPlayingItem()
            label = item.getLabel()
            if label:
                clean_filename(label=label)
            else:
                window_property('Return_Label', clear=True)

        # Get user rating on music playback
        if self.isPlayingAudio():
            tag = self.getMusicInfoTag()
            user_rating = tag.getUserRating()
            album_artist = tag.getAlbumArtist()
            window_property('MusicPlayer_UserRating', set=user_rating)
            window_property('MusicPlayer_AlbumArtist',
                            set=album_artist)

    def onPlayBackStopped(self):
        # Clean properties
        window_property('clearlogo_cropped', clear=True)
        window_property('clearlogo-alt_cropped', clear=True)
        window_property('clearlogo_cropped', clear=True)
        window_property('MusicPlayer_UserRating', clear=True)
        window_property('MusicPlayer_AlbumArtist', clear=True)
        window_property('Return_Label', clear=True)
