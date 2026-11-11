# author: realcopacetic

import json
import random
import time
from urllib.parse import quote

from xbmc import PLAYLIST_MUSIC, InfoTagVideo, Player, PlayList
from xbmcgui import getCurrentWindowDialogId

from resources.lib.service import playnext
from resources.lib.service.trailer import (
    TrailerZoomController,
    enter_fullscreen,
    start_flight,
    trailer_source,
)
from resources.lib.shared import logger as log
from resources.lib.shared.speed_dial import (
    SpeedDial,
    clear_properties,
    queue_source,
    take_source,
)
from resources.lib.shared.streams import player_streams, subtitle_status
from resources.lib.shared.utilities import (
    condition,
    infolabel,
    json_call,
    session_salt,
    split_random,
    to_float,
    window_property,
)

# No modal (9999) or a busy dialog (10138, 10160): a trailer resolve shows one.
_NO_MODAL_OR_BUSY = frozenset({9999, 10138, 10160})


def _set_path(setid: int, title: str) -> str:
    """
    The videodb URL of a movie set's films less one, for a rail of the rest.

    :param setid: Library movie set id.
    :param title: Title of the film to leave out.
    :return: The URL, its filter quoted so a title's "&" or "#" can't cut it.
    """
    rule = {"field": "title", "operator": "isnot", "value": title}
    xsp = json.dumps({"type": "movies", "rules": {"and": [rule]}}, ensure_ascii=False)
    return f"videodb://movies/titles/?setid={setid}&xsp={quote(xsp, safe='')}"


def _queue_key(playlist: PlayList) -> tuple[int, str] | None:
    """
    Tells one music queue from another: its size and first path.

    :param playlist: The music playlist.
    :return: (size, first path), or None while it is empty.
    """
    return (playlist.size(), playlist[0].getPath()) if playlist.size() else None


class PlayerMonitor(Player):
    """
    Player monitor for operations to be performed on playback start/stop.
    """

    def __init__(self) -> None:
        """
        Initialise player monitor and helpers; publish the speed dial pins and,
        when the skin is entered mid-playback, the playing file's properties.
        """
        super().__init__()
        self.zoom = TrailerZoomController()
        self._published = set()
        self._dial_queue = None
        self._dial_source = False  # (queue key, mark) taken at a start, until AV
        self._landed = None  # the flight's path, from its start until its AV start
        self._dropped_flight = False  # the user's media dropped one: full screen it
        self._resume_waiting = False  # a hung flight was cancelled: start the next
        self._seek_at = 0.0  # the last seek's time; 0 clears one left by a restart
        SpeedDial().publish()
        if self.isPlaying():
            self.onAVStarted()

    def release(self) -> None:
        """
        Undo what the monitor published, before the service drops it: stop a
        trailer it still holds, clear player, trailer and speed dial properties.
        """
        if self._is_trailer_playback():
            # Rewind first, as the watchdog does, so the stop saves no watched state
            self._pause_session()
            self.seekTime(0)
            log.execute("PlayerControl(Stop)")
        elif self._landed and infolabel("Player.Filenameandpath") == self._landed:
            log.execute("PlayerControl(Stop)")  # still opening: no video to rewind yet
        if self._landed:  # it will never land now
            window_property("trailer_flight")
        self._publish({})
        window_property("player_seek_offset")
        self._clear_trailer_props()  # a flight still out is stopped when it lands
        clear_properties()

    def onAVStarted(self) -> None:
        """Handle playback start events for video and audio."""
        path = infolabel("Player.Filenameandpath")
        if path == self._landed:
            self._landed = None
            self._land(path)
            return
        if self._dropped_flight:
            # The user's media, started inside the flight's wait (onPlayBackStarted)
            self._dropped_flight = False
            if self.isPlayingVideo() and not condition(
                "Window.IsActive(fullscreenvideo)"
            ):
                log.execute("Action(FullScreen)")  # took the flight's windowed start
        if self.isPlayingVideo():
            # Not a trailer: any leftover trailer state was superseded by a
            # real video — clear it and take the normal video path.
            self._clear_trailer_props()
            self._handle_video_start()
            return
        if self.isPlayingAudio():
            self._handle_audio_start()

    def onPlayBackStarted(self) -> None:
        """
        Hold a new speed dial mark with its queue, for that queue's AV start.
        The trailer flight's own start is ours from its first frame; other media
        started inside its wait drops it, or Kodi plays the trailer in its place.
        """
        window_property("player_seek_offset")  # Next or a new item sends no stop
        if (source := take_source()) is not False:
            self._dial_source = (_queue_key(PlayList(PLAYLIST_MUSIC)), source)
        if not (flight := infolabel("Window(home).Property(trailer_flight)")):
            return
        if (path := infolabel("Player.Filenameandpath")) == flight:
            self._landed = path
            window_property("trailer_file", value=path)
            return
        window_property("trailer_flight")
        self._landed = None
        self._resume_waiting = False
        self._dropped_flight = True
        self._clear_trailer_props()  # the user's media supersedes the request
        # Ends the busy dialog's wait; Kodi stalls until the script stops
        log.execute("Action(Back,busydialog)")

    def onPlayBackSeek(self, target: int, offset: int) -> None:
        """
        Publish the jump as player_seek_offset, signed as Player.SeekOffset is
        (+10:00): handling the seek message usually resets that to 0 first.

        :param target: The time sought to, in ms.
        :param offset: The jump, in ms.
        """
        minutes, seconds = divmod(abs(offset) // 1000, 60)
        hours, minutes = divmod(minutes, 60)
        clock = ":".join(f"{p:02}" for p in (hours, minutes, seconds)[not hours :])
        sign = "-" if offset < 0 else "+"
        window_property("player_seek_offset", value=bool(offset) and sign + clock)
        self._seek_at = time.monotonic()

    def onPlayBackSeekChapter(self, chapter: int) -> None:
        """
        A chapter jump reports no offset: drop the last seek's.

        :param chapter: The chapter sought to.
        """
        window_property("player_seek_offset")

    def onPlayBackSpeedChanged(self, speed: int) -> None:
        """
        A speed change counts as a seek with no jump: drop the last seek's offset.

        :param speed: The new playback speed.
        """
        window_property("player_seek_offset")

    def expire_seek_offset(self) -> None:
        """
        Poller hook: drop the last jump once its label has faded (Kodi's 3 s from the
        seek's end, then 1x), so a later seek with no offset of its own doesn't show it.
        """
        if (
            self._seek_at is not None
            and time.monotonic() - self._seek_at > 4
            and condition("!Player.HasPerformedSeek(4)")
        ):
            self._seek_at = None
            window_property("player_seek_offset")

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
        Publish video-related window properties on playback start: parent ids
        (tvshowid, setid, with the set's name and its other films' path) via
        JSON-RPC where needed, subtitle type, genre and director picks.
        """
        tag = self.getVideoInfoTag()
        dbid = tag.getDbId()
        media_type = tag.getMediaType()
        # Always published, so stop clears what actions write later; with no lang
        # here it is never missing until the skin's player_stream_refresh passes one
        props = {"player_subtitle_kind": subtitle_status(*player_streams("subtitle"))}
        props |= self._picks(tag)

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
                params={"properties": ["setid", "set"], "movieid": dbid},
                parent="now_playing_movie",
            )
            details = query.get("result", {}).get("moviedetails", {})
            if setid := details.get("setid"):
                props["player_setid"] = str(setid)
                props["player_set"] = details.get("set", "")
                props["player_set_path"] = _set_path(setid, tag.getTitle())
        self._publish(props)

    @staticmethod
    def _picks(tag: InfoTagVideo) -> dict[str, str]:
        """
        player_genre_query (as the library names it), player_genre (cleaned) and
        player_director: one of each, picked once per video and Kodi session.

        :param tag: The playing video's info tag.
        :return: The picks, by property name; none for a missing field.
        """
        media_type = tag.getMediaType()
        rng = random.Random(
            f"{session_salt()}:{media_type}:{tag.getDbId()}:{tag.getTitle()}"
        )
        props = {}
        if genres := tag.getGenres():
            # Kodi split them on its item separator: a "/" inside one stays whole
            props["player_genre_query"], props["player_genre"] = split_random(
                " / ".join(genres),
                rng=rng,
                separator=" / ",
                parts=media_type != "musicvideo",
            )
        if directors := tag.getDirectors():
            props["player_director"] = rng.choice(directors)
        return props

    def _handle_audio_start(self) -> None:
        """
        Publish music-related window properties on audio start.
        Splits the player's artists and their ids into player_artist_1..3 and
        player_artistid_1..3 for exact matching.
        """
        tag = self.getMusicInfoTag()
        query = json_call(
            "Player.GetItem",
            params={"playerid": 0, "properties": ["albumid", "artist", "artistid"]},
            parent="now_playing_song",
        )
        item = query.get("result", {}).get("item", {})
        artists = item.get("artist", [])
        artistids = item.get("artistid", [])
        self._publish(
            {
                "player_artist": tag.getArtist(),
                "player_albumartist": tag.getAlbumArtist(),
                "player_album": tag.getAlbum(),
                "player_albumid": str(item.get("albumid", "")),
                "player_disc": str(tag.getDisc()),
            }
            | {f"player_artist_{i}": a for i, a in enumerate(artists[:3], 1)}
            | {f"player_artistid_{i}": str(a) for i, a in enumerate(artistids[:3], 1)}
        )
        self._record_speed_dial(tag.getDbId())

    def _record_speed_dial(self, songid: int) -> None:
        """
        Records what playback started from: the source a helper action marked,
        else one inferred from the queue when a queue starts (not per track).

        :param songid: Library ID of the playing song; 0 or less if none.
        """
        held, self._dial_source = self._dial_source, False
        playlist = PlayList(PLAYLIST_MUSIC)
        queue = _queue_key(playlist) or songid
        # A held mark is for the queue its play started; another queue replaced it
        source = held[1] if held and held[0] == queue else False
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

    def _land(self, path: str) -> None:
        """
        The flight has started: show it, park it or stop it, and start the
        request that waited behind it.

        :param path: The flight's file.
        """
        window_property("trailer_flight")
        self._resume_waiting = False
        if infolabel("Window(home).Property(trailer_state)") != "pending":
            log.execute("PlayerControl(Stop)")  # left, or given up on: nobody wants it
            return
        waiting = infolabel("Window(home).Property(trailer_request)")
        if self._trailer_is_stale():
            self._orphan_trailer()
        elif waiting != path:  # a later rest's request: this one makes way
            self._pause_session()
            start_flight(waiting)
        elif infolabel("Window(home).Property(trailer_fullscreen)"):
            enter_fullscreen()
        else:
            window_property("trailer_state", value="playing")
            self.zoom.apply_zoom_if_needed()

    def _orphan_trailer(self) -> None:
        """
        Demote a stale or ending trailer to a paused, hidden orphan instead of
        stopping it; the watchdog rewinds it, then reaps it once the user settles.
        """
        self._pause_session()
        window_property("trailer_state", value="orphaned")

    def _clear_trailer_props(self) -> None:
        """
        Reset the trailer session to idle. A flight still resolving is kept: it
        is stopped when it lands, as nobody wants it.
        """
        for key in (
            "trailer_state",
            "trailer_request",
            "trailer_item",
            "trailer_source",
            "trailer_focus_ids",
            "trailer_window",
            "trailer_fullscreen",
            "trailer_viewport",
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
        Poller hook: watch the flight; demote a playing session whose item lost
        focus or whose end is near; rewind a demoted session at once, so no close
        counts it as watched, and reap it once the user settles.
        """
        state = infolabel("Window(home).Property(trailer_state)")
        self._watch_flight(state)
        if state in ("pending", "cancelled"):
            return
        if state == "fullscreen":
            if self._trailer_ending():
                # Full screen would freeze on a paused frame: rewind, then stop
                self._pause_session()
                self.seekTime(0)
                log.execute("PlayerControl(Stop)")
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

    def _watch_flight(
        self, state: str, retire: float = 5.0, cancel: float = 15.0
    ) -> None:
        """
        Retire the flight's request once its trailer is ``retire`` s late, but let
        the resolve run: a cancel stalls Kodi until the script stops, so only one
        ``cancel`` s old (hung) is cancelled, and the poll after it moves on.

        :param state: The session's trailer_state.
        :param retire: Seconds before the flight's request is given up on.
        :param cancel: Seconds before the resolve itself is cancelled.
        """
        flight = infolabel("Window(home).Property(trailer_flight)")
        resume, self._resume_waiting = self._resume_waiting, False
        if not flight or self._landed:
            return
        if resume:  # held a poll, so nothing starts inside the hung wait
            self._next_request(flight)
            return
        since = to_float(infolabel("Window(home).Property(trailer_pending_since)"))
        age = time.time() - since
        if age >= cancel:
            log.debug("PlayerMonitor: Cancelling a hung trailer resolve")
            log.execute("Action(Back,busydialog)")  # ends the busy dialog's wait
            self._resume_waiting = True
            return
        if (
            age < retire
            or state not in ("pending", "cancelled")
            or infolabel("Window(home).Property(trailer_request)") != flight
            or not self._is_trailer_playback()
            and condition("Player.HasMedia")
        ):
            return
        log.debug("PlayerMonitor: Retiring stale pending trailer request")
        self._retire()

    def _next_request(self, gone: str) -> None:
        """
        The flight ``gone`` will never play: hand the request that waited behind
        it to Kodi while it is still wanted, else retire the request.

        :param gone: The path of the flight that ended without playing.
        """
        window_property("trailer_flight")
        state = infolabel("Window(home).Property(trailer_state)")
        request = infolabel("Window(home).Property(trailer_request)")
        if state == "pending" and request != gone and not self._trailer_is_stale():
            start_flight(request)
        elif state in ("pending", "cancelled"):
            self._retire()

    def _retire(self) -> None:
        """
        Give up on the request: the paused trailer it was to replace goes back to
        the reaper, else the session clears. The item may ask again.
        """
        window_property("trailer_played_item")
        if self._is_trailer_playback():
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
        Clear the last jump, the player properties unless the next file already
        plays (its onAVStarted replaces them), then the trailer session.
        """
        window_property("player_seek_offset")  # the last file's jump
        if not self.isPlaying():
            self._publish({})
            self._dropped_flight = False
            if landed := self._landed:  # the flight stopped before its AV start
                self._landed = None
                self._next_request(landed)
        # A pending state belongs to a newer request that superseded the
        # playback this stop event is for — leave its props intact.
        if condition("String.IsEqual(Window(home).Property(trailer_state),pending)"):
            return
        self._clear_trailer_props()
