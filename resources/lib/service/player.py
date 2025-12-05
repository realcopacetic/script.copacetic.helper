# author: realcopacetic

from xbmc import Player
import xbmc

from resources.lib.art.editor import ImageEditor
from resources.lib.script.actions import clean_filename, subtitle_limiter
from resources.lib.shared import logger as log
from resources.lib.shared.sqlite import ArtworkCacheHandler
from resources.lib.shared.utilities import (
    condition,
    infolabel,
    json_call,
    to_float,
    window_property,
)


class PlayerMonitor(Player):
    def __init__(self, sqlite_handler=None):
        Player.__init__(self)
        self.sqlite = sqlite_handler or ArtworkCacheHandler()
        self.image_processor = ImageEditor(self.sqlite).image_processor

    def onAVStarted(self):
        log.debug(f"FUCK DEBUG video playing")
        if self.isPlayingVideo() and condition(
            "String.IsEmpty(Window(home).Property(Trailer_Autoplay))"
        ):
            ...
            # # Crop clearlogo for use on fullscreen info or pause
            # self.image_processor(processes={"clearlogo": "crop"}, source="VideoPlayer")
            # # Clean filename
            # item = self.getPlayingItem()
            # label = item.getLabel()
            # if label:
            #     clean_filename(label=label)
            # else:
            #     window_property("Return_Label")

            # # Get set id
            # tag = self.getVideoInfoTag()
            # dbid = tag.getDbId()
            # if dbid and condition("VideoPlayer.Content(movie)"):
            #     query = json_call(
            #         "VideoLibrary.GetMovieDetails",
            #         params={"properties": ["setid"], "movieid": dbid},
            #         parent="get_set_id",
            #     )
            #     if query["result"].get("moviedetails", None):
            #         setid = int(query["result"]["moviedetails"]["setid"])
            #         window_property("VideoPlayer_SetID", value=setid)

            # # Switch subtitles to lang if set in skin settings
            # lang = infolabel("Skin.String(Subtitle_Limiter)")
            # if lang and condition("VideoPlayer.SubtitlesEnabled"):
            #     subtitle_limiter(lang, user_trigger=False)

        elif self.isPlayingVideo():
            content_ar = 0.0
            ar_window = 1088.0 / 612.0
            zoom = 1.0
            json_call(
                method="Player.SetViewMode",
                params={"viewmode": {"zoom": zoom}},
                parent="reset_viewmode",
            )
            test = infolabel('ListItem.Label')
            log.debug(f'FUCK DEBUG {test=}')
            trailer_ar = to_float(infolabel("Player.Process(VideoDAR)"))
            movie_ar = to_float(infolabel("ListItem.VideoAspect"))
            if trailer_ar and abs(trailer_ar - 1.78) > 0.05:
                content_ar = trailer_ar
            elif movie_ar:
                content_ar = movie_ar

            if content_ar > 0.0:
                zoom = content_ar / ar_window
                zoom = round(zoom, 3)
            if zoom > 1.0:
                json_call(
                    method="Player.SetViewMode",
                    params={"viewmode": {"zoom": zoom}},
                    parent="PlayerMonitor_apply_zoom",
                )
            log.debug(f"FUCK DEBUG {trailer_ar=}, {movie_ar=}, {content_ar=}, {ar_window=}, {zoom=}")

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
