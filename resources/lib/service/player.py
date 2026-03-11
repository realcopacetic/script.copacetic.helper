# author: realcopacetic

from xbmc import Player

from resources.lib.service.trailer import TrailerZoomController
from resources.lib.art.editor import ImageEditor
from resources.lib.shared import logger as log
from resources.lib.shared.sqlite import ArtworkCacheHandler
from resources.lib.shared.utilities import (
    condition,
    json_call,
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
        """
        if self.isPlayingVideo():
            if condition("String.IsEmpty(Window(home).Property(Trailer_Autoplay))"):
                self._handle_video_start()

            self.zoom.apply_zoom_if_needed()
            return

        if self.isPlayingAudio():
            self._handle_audio_start()

    def onPlayBackStopped(self):
        """
        Cleanup managed window properties when playback is stopped by the user.
        """
        self._cleanup()

    def onPlayBackEnded(self):
        """
        Cleanup managed window properties when playback ends naturally.
        """
        self._cleanup()

    def _cleanup(self):
        """
        Clear all managed window properties and reset the cleanup registry.
        """
        for key, window_id in self._cleanup_registry:
            window_property(key, window_id=window_id)
        self._cleanup_registry.clear()

    def _handle_video_start(self) -> None:
        """
        Set video-related window properties on playback start.
        Resolves parent identifiers (tvshowid, setid) via JSON-RPC where needed.
        """
        tag = self.getVideoInfoTag()
        dbid = tag.getDbId()
        media_type = tag.getMediaType()

        if media_type == "episode":
            self._set_managed_property("player_tvshowtitle", value=tag.getTVShowTitle())
            self._set_managed_property("player_season", value=str(tag.getSeason()))
            if dbid:
                query = json_call(
                    "VideoLibrary.GetEpisodeDetails",
                    params={"properties": ["tvshowid"], "episodeid": dbid},
                    parent="now_playing_episode",
                )
                details = query.get("result", {}).get("episodedetails", {})
                if tvshowid := details.get("tvshowid"):
                    self._set_managed_property("player_tvshowid", value=str(tvshowid))

        elif media_type == "movie" and dbid:
            query = json_call(
                "VideoLibrary.GetMovieDetails",
                params={"properties": ["setid"], "movieid": dbid},
                parent="now_playing_movie",
            )
            details = query.get("result", {}).get("moviedetails", {})
            if setid := details.get("setid"):
                self._set_managed_property("player_setid", value=str(setid))

    def _handle_audio_start(self) -> None:
        """
        Set music-related window properties on audio start.
        """
        tag = self.getMusicInfoTag()
        self._set_managed_property("player_userrating", value=str(tag.getUserRating()))
        self._set_managed_property("player_artist", value=tag.getArtist())
        self._set_managed_property("player_albumartist", value=tag.getAlbumArtist())
        self._set_managed_property("player_album", value=tag.getAlbum())

    def _set_managed_property(
        self, key: str, value: str = "", window_id: int = 10000
    ) -> None:
        """
        Set a window property and register it for cleanup on playback stop.

        :param key: Property name.
        :param value: Property value.
        :param window_id: ID of the Kodi window, defaults to 10000 for home.
        """
        window_property(key, value=value, window_id=window_id)
        self._cleanup_registry.add((key, window_id))
