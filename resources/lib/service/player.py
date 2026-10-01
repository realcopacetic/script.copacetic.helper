# author: realcopacetic

import time

from xbmc import PLAYLIST_MUSIC, Player, PlayList
from xbmcgui import getCurrentWindowDialogId

from resources.lib.service import playnext
from resources.lib.service.trailer import TrailerZoomController, trailer_source
from resources.lib.shared import logger as log
from resources.lib.shared.speed_dial import SpeedDial, queue_source, take_source
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

    def __init__(self) -> None:
        """Initialise player monitor and helpers."""
        super().__init__()
        self.zoom = TrailerZoomController()
        self._cleanup_registry = set()
        self._dial_queue = None

    def onAVStarted(self) -> None:
        """Handle playback start events for video and audio."""
        if self.isPlayingVideo():
            state = infolabel("Window(home).Property(trailer_state)")
            if state == "pending":
                window_property(
                    "trailer_file", value=infolabel("Player.Filenameandpath")
                )
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

    def onPlayBackStopped(self) -> None:
        """Clean up managed properties when playback is stopped by the user."""
        self._cleanup()

    def onPlayBackEnded(self) -> None:
        """Cleanup managed window properties when playback ends naturally."""
        self._cleanup()

    def onPlayBackError(self) -> None:
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
                    playnext.ensure_successor(dbid, tvshowid)

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
        Splits the player's artist list into player_artist_1..3 for exact matching.
        """
        tag = self.getMusicInfoTag()
        self._set_managed_property("player_artist", value=tag.getArtist())
        self._set_managed_property("player_albumartist", value=tag.getAlbumArtist())
        self._set_managed_property("player_album", value=tag.getAlbum())
        self._set_managed_property("player_disc", value=str(tag.getDisc()))

        query = json_call(
            "Player.GetItem",
            params={"playerid": 0, "properties": ["artist"]},
            parent="now_playing_song",
        )
        artists = query.get("result", {}).get("item", {}).get("artist", [])
        for index in range(3):
            artist = artists[index] if index < len(artists) else ""
            self._set_managed_property(f"player_artist_{index + 1}", value=artist)
        self._record_speed_dial(tag.getDbId())

    def _record_speed_dial(self, songid: int) -> None:
        """
        Records what playback started from: the source a helper action marked,
        else one inferred from the queue when a queue starts (not per track).

        :param songid: Library ID of the playing song; 0 or less if none.
        """
        source = take_source()
        playlist = PlayList(PLAYLIST_MUSIC)
        queue = (playlist.size(), playlist[0].getPath()) if playlist.size() else songid
        if source is False:
            advanced = queue == self._dial_queue and playlist.getposition() > 0
            if advanced or songid <= 0:
                return
            source = queue_source(songid)
        self._dial_queue = queue
        if source:
            SpeedDial().played(source)

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
        True when focus has left the controls or the item the trailer was
        requested for. The label check fails open on an unreadable label or
        under a modal dialog, which Python info lookups read first.
        """
        ids = infolabel("Window(home).Property(trailer_focus_ids)")
        if ids and not condition(
            " | ".join(f"Control.HasFocus({i})" for i in ids.split(","))
        ):
            return True
        source = trailer_source()
        expected = infolabel("Window(home).Property(trailer_item)")
        if not (source and expected) or getCurrentWindowDialogId() != 9999:
            return False
        current = infolabel(f"{source}.Label")
        return bool(current) and current != expected

    def _orphan_trailer(self) -> None:
        """
        Demote a stale or ending trailer to a paused, hidden orphan instead of
        stopping it; the watchdog rewinds it, then reaps it once the user settles.
        """
        self._pause_session()
        window_property("trailer_state", value="orphaned")

    def _clear_trailer_props(self) -> None:
        """Reset the trailer session to idle."""
        for key in (
            "trailer_state",
            "trailer_item",
            "trailer_source",
            "trailer_focus_ids",
            "trailer_viewport",
            "trailer_pending_since",
            "trailer_file",
        ):
            window_property(key)

    def _pause_session(self) -> None:
        """
        Pause the trailer: silent and frozen, with no teardown and no global
        side-effect. Absolute (play=False), so idempotent — a session never
        resumes, only plays through or is reaped.
        """
        json_call(
            method="Player.PlayPause",
            params={"playerid": 1, "play": False},  # 1 = video player
            parent="trailer_pause",
        )

    def watch_trailer_session(self) -> None:
        """
        Poller hook: reap a wedged pending request; demote a playing session
        whose item lost focus or whose end is near; rewind a demoted session at
        once, so no close counts it as watched, and reap it once the user settles.
        """
        state = infolabel("Window(home).Property(trailer_state)")
        if state == "pending":
            self._reap_stale_pending()
            return
        if state == "playing" and (self._trailer_is_stale() or self._trailer_ending()):
            self._orphan_trailer()
            return
        if state in ("interrupted", "orphaned") and self._is_trailer_playback():
            if condition("!Player.Paused"):
                # Swallowed skin pause (queued toggles cancelling out)
                self._pause_session()
                return
            if self.getTime() > 1 and condition("Player.SeekEnabled"):
                self.seekTime(0)  # a reap or a replacing trailer closes it here
                return
            if condition("System.IdleTime(10)"):
                log.execute("PlayerControl(Stop)")

    def _reap_stale_pending(self, max_age: float = 5.0) -> None:
        """
        Retire a pending request that never started (e.g. a failed plugin
        resolve): the paused trailer it was to replace goes back to the reaper,
        else clear to idle. A video that has since arrived is left for onAVStarted.

        :param max_age: Seconds a pending request may sit before reaping.
        """
        since = to_float(infolabel("Window(home).Property(trailer_pending_since)"))
        if since <= 0.0 or time.time() - since < max_age:
            return
        zombie = self._is_trailer_playback()
        if not zombie and condition("Player.HasMedia"):
            return
        log.debug("PlayerMonitor: Reaping stale pending trailer request")
        window_property("trailer_played_item")
        if zombie:
            window_property("trailer_state", value="orphaned")
        else:
            self._clear_trailer_props()

    def _trailer_ending(self, margin: float = 2.0) -> bool:
        """
        True when our trailer is within ``margin`` seconds of its end, so it can
        be demoted and rewound before a natural end marks it watched.

        :param margin: Seconds before the end; covers one poll and the pause.
        :return: True when the trailer should end now.
        """
        if not self._is_trailer_playback():
            return False
        return 0 < self.getTotalTime() - self.getTime() <= margin

    def _is_trailer_playback(self) -> bool:
        """
        True when the playing video is the trailer this session stamped.
        Fails closed on a missing stamp — never acts on someone's film.
        """
        stamped = infolabel("Window(home).Property(trailer_file)")
        if not stamped or not condition("Player.HasVideo"):
            return False
        return infolabel("Player.Filenameandpath") == stamped

    def _cleanup(self) -> None:
        """Clear managed properties, the registry, and the trailer session."""
        for key, window_id in self._cleanup_registry:
            window_property(key, window_id=window_id)
        self._cleanup_registry.clear()
        # A pending state belongs to a newer request that superseded the
        # playback this stop event is for — leave its props intact.
        if condition("String.IsEqual(Window(home).Property(trailer_state),pending)"):
            return
        self._clear_trailer_props()
