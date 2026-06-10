# author: realcopacetic

import time

from xbmc import Player

from resources.lib.service.trailer import TrailerZoomController
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
        self.zoom = TrailerZoomController()
        self._cleanup_registry: set[tuple[str, int]] = set()

    def onAVStarted(self):
        """Handle playback start events for video and audio."""
        if self.isPlayingVideo():
            state = infolabel("Window(home).Property(trailer_state)")
            if state == "pending":
                if self._trailer_is_stale():
                    self._orphan_trailer()
                else:
                    window_property("trailer_state", value="playing")
                    self.zoom.apply_zoom_if_needed()
                return
            # No pending request: any leftover trailer state was superseded
            # by a real video — clear it and take the normal video path.
            self._clear_trailer_props()
            self._handle_video_start()
            return
        if self.isPlayingAudio():
            self._handle_audio_start()

    def onPlayBackStopped(self):
        """Clean up managed properties when playback is stopped by the user."""
        self._cleanup()

    def onPlayBackEnded(self):
        """Cleanup managed window properties when playback ends naturally."""
        self._cleanup()

    def onPlayBackError(self):
        """
        Clean up when requested playback fails and clear the refire stamp
        so the item can retry on its next focus.
        """
        self._cleanup()
        window_property("trailer_played_item")

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

    def _trailer_is_stale(self) -> bool:
        """
        True when focus has left the item this trailer was requested for.
        Fails open on unreadable labels — never on certainty that the
        source container lost focus.
        """
        expected = infolabel("Window(home).Property(trailer_item)")
        source = self.zoom._get_trailer_source()
        if not expected or not source:
            return False
        raw = infolabel("Window(home).Property(trailer_source)")
        if raw.isdigit() and not condition(
            f"Control.HasFocus({raw}) | Control.HasFocus({raw}0)"
        ):
            return True
        current = infolabel(f"{source}.Label")
        if not current:
            return False
        return current != expected

    def _orphan_trailer(self) -> None:
        """
        Demote a stale trailer to a paused, hidden orphan instead of stopping
        mid-scroll; the watchdog reaps it once the user has settled.
        """
        self._pause_session()
        window_property("trailer_state", value="orphaned")

    def _clear_trailer_props(self) -> None:
        """Reset the trailer session to idle."""
        for key in (
            "trailer_state",
            "trailer_item",
            "trailer_source",
            "trailer_viewport",
            "trailer_pending_since",
        ):
            window_property(key)

    def _pause_session(self) -> None:
        """
        Pause the trailer: silent and frozen, with no teardown and no global
        side-effect (unlike mute). Absolute (play=False), so idempotent — a
        session never resumes, only plays through or is reaped.
        """
        json_call(
            method="Player.PlayPause",
            params={"playerid": 1, "play": False},  # 1 = video player
            parent="trailer_pause",
        )

    def watch_trailer_session(self) -> None:
        """
        Poller hook: reap a wedged pending request; demote a playing session
        whose source container lost focus; reap a demoted session once the
        user has settled.
        """
        state = infolabel("Window(home).Property(trailer_state)")
        if state == "pending":
            self._reap_stale_pending()
            return
        if state == "playing" and self._source_lost_focus():
            self._orphan_trailer()
            return
        # If a swallowed skin pause ever leaves an audible zombie, reinstate the
        # backstop here: if !Player.Paused -> self._pause_session()
        if state in ("interrupted", "orphaned") and condition(
            "Player.HasVideo + System.IdleTime(2)"
        ):
            log.execute("PlayerControl(Stop)")

    def _reap_stale_pending(self, max_age: float = 5.0) -> None:
        """
        Clear a pending request whose playback never started or errored
        (e.g. a hung plugin URL), but only when nothing is playing — a
        trailer that has since arrived is left for onAVStarted to confirm.

        :param max_age: Seconds a pending request may sit before reaping.
        """
        if condition("Player.HasMedia"):
            return
        since = to_float(infolabel("Window(home).Property(trailer_pending_since)"))
        if since <= 0.0 or time.time() - since < max_age:
            return
        log.debug("PlayerMonitor: Reaping stale pending trailer request")
        self._clear_trailer_props()

    def _source_lost_focus(self) -> bool:
        """
        True when a container-id trailer_source no longer holds focus.

        :return: False for non-container sources (bare ListItem in videos).
        """
        raw = infolabel("Window(home).Property(trailer_source)")
        if not raw.isdigit():
            return False
        return not condition(f"Control.HasFocus({raw}) | Control.HasFocus({raw}0)")

    def _cleanup(self):
        """Clear managed properties, the registry, and the trailer session."""
        for key, window_id in self._cleanup_registry:
            window_property(key, window_id=window_id)
        self._cleanup_registry.clear()
        # A pending state belongs to a newer request that superseded the
        # playback this stop event is for — leave its props intact.
        if condition("String.IsEqual(Window(home).Property(trailer_state),pending)"):
            return
        self._clear_trailer_props()