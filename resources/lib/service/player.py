# author: realcopacetic

from xbmc import Player

from resources.lib.script.actions import clean_filename
from resources.lib.service.art import ImageEditor
from resources.lib.utilities import condition, json_call, log, window_property


class PlayerMonitor(Player):
    def __init__(self):
        Player.__init__(self)
        self.clearlogo_cropper = ImageEditor().clearlogo_cropper

    def onAVStarted(self):
        if self.isPlayingVideo() and condition('String.IsEmpty(Window(home).Property(Trailer_Autoplay))'):
            # Crop clearlogo for use on fullscreen info or pause
            self.clearlogo_cropper(source='VideoPlayer',
                                   reporting=window_property)

            # Clean filename
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
            artist = tag.getArtist()
            album_artist = tag.getAlbumArtist()
            window_property('MusicPlayer_UserRating', set=user_rating)
            window_property('MusicPlayer_AlbumArtist', set=album_artist)

            # Get artist multiart for visualisation background
            filter_artist = {'field': 'artist', 'operator': 'is', 'value': artist}
            multiart = []
            query = json_call(
                'AudioLibrary.GetArtists', properties=['art'], 
                sort={'method': 'random'}, limit=15, 
                query_filter={'and': filter_artist},
                parent='get_visualisation_art'
            )
            try:
                for result in query['result']['artist']:
                    if result['art'].get('fanart'):
                        data = {'title': result.get('label', '')}
                        data.update(result['art'])
                        multiart.append(data)
            except KeyError:
                pass
            log(f'FUCK_{multiart}',force=True)
            '''
                    json_query = json_call('VideoLibrary.GetTVShows',
                               properties=['title', 'lastplayed',
                                           'studio', 'mpaa'],
                               sort=self.sort_lastplayed, limit=25,
                               query_filter={'and': filters},
                               parent='next_up'
                               )

                    self.filter_actor = {'field': 'actor',
                             'operator': 'is', 'value': self.label}

            '''

    def onPlayBackStopped(self):
        # Clean properties
        window_property('MusicPlayer_UserRating', clear=True)
        window_property('MusicPlayer_AlbumArtist', clear=True)
        window_property('Return_Label', clear=True)
