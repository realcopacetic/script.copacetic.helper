# author: realcopacetic

from xbmc import Player

from resources.lib.service.trailer import TrailerZoomController
from resources.lib.art.editor import ImageEditor
from resources.lib.shared import logger as log
from resources.lib.shared.sqlite import ArtworkCacheHandler
from resources.lib.shared.utilities import (
    condition,
    window_property,
)


class PlayerMonitor(Player):
    """
    Player monitor for operations to be performed on playback start/stop.
    """

    def __init__(self, sqlite_handler: ArtworkCacheHandler | None = None) -> None:
        """
        Initialise player monitor and helpers.

        :param sqlite_handler: Optional SQLite handler instance.
        """
        super().__init__()
        self.sqlite = sqlite_handler or ArtworkCacheHandler()
        self.image_processor = ImageEditor(self.sqlite).image_processor
        self.zoom = TrailerZoomController()
        self._cleanup_registry: set[tuple[str, str]] = set()

    def onAVStarted(self):
        """
        Handle playback start events for video and audio.

        :return: None.
        """
        if self.isPlayingVideo() and condition(
            "String.IsEmpty(Window(home).Property(Trailer_Autoplay))"
        ):
            ...
            return
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

        if self.isPlayingVideo():
            self.zoom.apply_zoom_if_needed()
            return

        if self.isPlayingAudio():
            self._handle_audio_start()

    def onPlayBackStopped(self):
        """
        Cleanup managed window properties on playback stop.

        :return: None.
        """
        for key, window in self._cleanup_registry:
            window_property(key, value="", window=window)

        self._cleanup_registry.clear()

    def _handle_audio_start(self) -> None:
        """
        Set music-related window properties on audio start.

        :return: None.
        """
        tag = self.getMusicInfoTag()
        self._set_managed_property(
            "MusicPlayer_UserRating", value=str(tag.getUserRating())
        )
        self._set_managed_property(
            "MusicPlayer_AlbumArtist", value=tag.getAlbumArtist()
        )

    def _set_managed_property(self, key: str, value: str = "", window: str = "home") -> None:
        """
        Set a window property and register it for cleanup.

        :param key: Property name.
        :param value: Property value.
        :param window: Kodi window id or name.
        """
        window_property(key, value=value, window=window)
        self._cleanup_registry.add((key, window))
