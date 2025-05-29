# author: realcopacetic

from xbmc import Player

from resources.lib.art.editor import ImageEditor
from resources.lib.script.actions import clean_filename, subtitle_limiter
from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import (
    condition,
    infolabel,
    json_call,
    window_property,
)


class PlayerMonitor(Player):
    def __init__(self, sqlite_handler=None):
        Player.__init__(self)
        self.sqlite = sqlite_handler or SQLiteHandler()
        self.image_processor = ImageEditor(self.sqlite).image_processor

    def onAVStarted(self):
        if self.isPlayingVideo() and condition(
            "String.IsEmpty(Window(home).Property(Trailer_Autoplay))"
        ):
            # Crop clearlogo for use on fullscreen info or pause
            self.image_processor(source="VideoPlayer", processes={"clearlogo": "crop"})
            # Clean filename
            item = self.getPlayingItem()
            label = item.getLabel()
            if label:
                clean_filename(label=label)
            else:
                window_property("Return_Label")

            # Get set id
            tag = self.getVideoInfoTag()
            dbid = tag.getDbId()
            if dbid and condition("VideoPlayer.Content(movie)"):
                query = json_call(
                    "VideoLibrary.GetMovieDetails",
                    params={"properties": ["setid"], "movieid": dbid},
                    parent="get_set_id",
                )
                if query["result"].get("moviedetails", None):
                    setid = int(query["result"]["moviedetails"]["setid"])
                    window_property("VideoPlayer_SetID", value=setid)

            # Switch subtitles to lang if set in skin settings
            lang = infolabel("Skin.String(Subtitle_Limiter)")
            if lang and condition("VideoPlayer.SubtitlesEnabled"):
                subtitle_limiter(lang, user_trigger=False)

        # Get user rating on music playback
        elif self.isPlayingAudio():
            tag = self.getMusicInfoTag()
            user_rating = tag.getUserRating()
            album_artist = tag.getAlbumArtist()
            window_property("MusicPlayer_UserRating", value=user_rating)
            window_property("MusicPlayer_AlbumArtist", value=album_artist)

    def onPlayBackStopped(self):
        # Clean properties
        window_property("MusicPlayer_UserRating")
        window_property("MusicPlayer_AlbumArtist")
        window_property("VideoPlayer_SetID")
        window_property("Return_Label")
