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

# No modal (9999) or a busy dialog (10138, 10160): a trailer resolve shows one.
_NO_MODAL_OR_BUSY = frozenset({9999, 10138, 10160})


class PlayerMonitor(Player):
    """
    Player monitor for operations to be performed on playback start/stop.
    """

    def __init__(self) -> None:
        """Initialise player monitor and helpers; publish the speed dial pins."""
        super().__init__()
        self.zoom = TrailerZoomController()
        self._published = set()
        self._dial_queue = None
        SpeedDial().publish()

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
            # Requested in a window the user has since left; a film the user
            # started goes fullscreen (trailers start windowed).
            if state == "cancelled" and not condition(
                "Window.IsActive(fullscreenvideo)"
            ):
                log.execute("PlayerControl(Stop)")
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
        Publish video-related window properties on playback start.
        Resolves parent identifiers (tvshowid, setid) via JSON-RPC where needed.
        """
        tag = self.getVideoInfoTag()
        dbid = tag.getDbId()
        media_type = tag.getMediaType()
        props = {}

        if media_type == "episode":
            props["player_tvshowtitle"] = tag.getTVShowTitle()
            props["player_season"] = str(tag.getSeason())
            if dbid > 0:
                query = json_call(
                    "VideoLibrary.GetEpisodeDetails",
                    params={"properties": ["tvshowid"], "episodeid": dbid},
                    parent="now_playing_episode",
                )
                details = query.get("result", {}).get("episodedetails", {})
                if tvshowid := details.get("tvshowid"):
                    props["player_tvshowid"] = str(tvshowid)
                    playnext.ensure_successor(dbid, tvshowid)

        elif media_type == "movie" and dbid > 0:
            query = json_call(
                "VideoLibrary.GetMovieDetails",
                params={"properties": ["setid"], "movieid": dbid},
                parent="now_playing_movie",
            )
            details = query.get("result", {}).get("moviedetails", {})
            if setid := details.get("setid"):
                props["player_setid"] = str(setid)
        self._publish(props)

    def _handle_audio_start(self) -> None:
        """
        Publish music-related window properties on audio start.
        Splits the player's artist list into player_artist_1..3 for exact matching.
        """
        tag = self.getMusicInfoTag()
        query = json_call(
            "Player.GetItem",
            params={"playerid": 0, "properties": ["albumid", "artist"]},
            parent="now_playing_song",
        )
        item = query.get("result", {}).get("item", {})
        artists = item.get("artist", [])
        self._publish(
            {
                "player_artist": tag.getArtist(),
                "player_albumartist": tag.getAlbumArtist(),
                "player_album": tag.getAlbum(),
                "player_albumid": str(item.get("albumid", "")),
                "player_disc": str(tag.getDisc()),
            }
            | {f"player_artist_{i}": a for i, a in enumerate(artists[:3], 1)}
        )
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

    def _publish(self, props: dict[str, str]) -> None:
        """
        Write the playing file's properties, then clear any the previous file set
        that this one doesn't, so a skip or playlist advance never blanks them.

        :param props: Property names and values for the playing file.
        """
        stale = self._published.difference(props)
        for key, value in props.items():
            window_property(key, value=value)
        for key in stale:
            window_property(key)
        self._published = set(props)

    def _trailer_is_stale(self) -> bool:
        """
        True when focus has left the controls or the item the trailer was
        requested for, or a modal other than the busy dialog covers it (focus is
        read in the topmost modal, so a dialog holding the focus ids keeps it).
        """
        ids = infolabel("Window(home).Property(trailer_focus_ids)")
        if ids and not condition(
            " | ".join(f"Control.HasFocus({i})" for i in ids.split(","))
        ):
            return True
        dialog = getCurrentWindowDialogId()
        if dialog not in _NO_MODAL_OR_BUSY and not ids:
            return True
        source = trailer_source()
        expected = infolabel("Window(home).Property(trailer_item)")
        if not (source and expected) or dialog != 9999:
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
            "trailer_window",
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
        if state in ("pending", "cancelled"):
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
        """
        Clear the player properties unless the next file already plays (its
        onAVStarted replaces them), then the trailer session.
        """
        if not self.isPlaying():
            self._publish({})
        # A pending state belongs to a newer request that superseded the
        # playback this stop event is for — leave its props intact.
        if condition("String.IsEqual(Window(home).Property(trailer_state),pending)"):
            return
        self._clear_trailer_props()
