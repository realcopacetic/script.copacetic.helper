# author: realcopacetic

import json
import random
import time
from contextlib import suppress
from functools import cached_property
from typing import Any
from urllib.parse import quote

from xbmc import PLAYLIST_MUSIC, InfoTagVideo, Player, PlayList
from xbmcgui import getCurrentWindowDialogId

from resources.lib.art.editor import ImageEditor
from resources.lib.plugin.helpers import IDENTITY_LOGO_BOX, size_identity
from resources.lib.plugin.opts import ArtOpts
from resources.lib.service import playnext, segments
from resources.lib.service.trailer import (
    TrailerZoomController,
    enter_fullscreen,
    start_flight,
    trailer_source,
)
from resources.lib.shared import logger as log
from resources.lib.shared.mix import artist_genres, mix_songs
from resources.lib.shared.speed_dial import (
    SpeedDial,
    clear_properties,
    queue_source,
    take_source,
)
from resources.lib.shared.streams import player_streams, subtitle_status
from resources.lib.shared.utilities import (
    add_songs,
    condition,
    file_clean_name,
    infolabel,
    json_call,
    session_salt,
    split_random,
    to_float,
    to_int,
    window_property,
)

# No modal (9999) or a busy dialog (10138, 10160): a trailer resolve shows one.
_NO_MODAL_OR_BUSY = frozenset({9999, 10138, 10160})
# The endless queue: on, and Kodi isn't refilling or looping the queue itself
ENDLESS_QUEUE = (
    "Skin.HasSetting(endless_queue) + !MusicPartyMode.Enabled + !Playlist.IsRepeat"
)
QUEUE_LOW = 10  # it grows once fewer songs than this follow the playing one
QUEUE_GROWTH = 10  # songs it adds then


def _videodb_path(path: str, rules: list[dict], **xsp: Any) -> str:
    """
    A videodb URL filtered by a smart playlist, its JSON quoted so a name's "&" or
    "#" can't cut the URL.

    :param path: The videodb node, with or without options.
    :param rules: Filter rules, ANDed.
    :param xsp: The playlist's other fields: type, and order or limit if wanted.
    :return: The URL.
    """
    query = json.dumps(xsp | {"rules": {"and": rules}}, ensure_ascii=False)
    return f"{path}{'&' if '?' in path else '?'}xsp={quote(query, safe='')}"


def _not_file(file: str) -> dict:
    """
    The smart playlist rule that leaves out a library file, by the filename field's
    value: the whole path for a stack, archive or plugin, else the name.

    :param file: The item's library file.
    :return: The rule.
    """
    whole = file.lower().startswith(("stack://", "rar://", "zip://", "plugin://"))
    name = file if whole else file.replace("\\", "/").rsplit("/", 1)[-1]
    return {"field": "filename", "operator": "isnot", "value": name}


def _episode_paths(tvshowid: int, season: int, episode: int, other: dict) -> dict:
    """
    A library episode's rails: its next 20 in season and episode order, into the
    next season, and its season's unwatched; none for a special.

    :param tvshowid: Library TV show id.
    :param season: The episode's season.
    :param episode: The episode's number.
    :param other: The rule that leaves out the playing file (its other parts too).
    :return: player_next_path and player_season_path, or nothing.
    """
    if season < 1:
        return {}
    show, order = f"videodb://tvshows/titles/{tvshowid}", {"method": "episode"}
    later = {
        "or": [
            {"field": "season", "operator": "greaterthan", "value": str(season)},
            {
                "and": [
                    {"field": "season", "operator": "is", "value": str(season)},
                    {
                        "field": "episode",
                        "operator": "greaterthan",
                        "value": str(episode),
                    },
                ]
            },
        ]
    }
    unwatched = {"field": "playcount", "operator": "is", "value": "0"}
    return {
        "player_next_path": _videodb_path(
            f"{show}/-1/", [other, later], type="episodes", order=order, limit=20
        ),
        "player_season_path": _videodb_path(
            f"{show}/{season}/", [other, unwatched], type="episodes", order=order
        ),
    }


def _queue_key(playlist: PlayList) -> tuple[int, str] | None:
    """
    Tells one music queue from another: its size and first path.

    :param playlist: The music playlist.
    :return: (size, first path), or None while it is empty.
    """
    return (playlist.size(), playlist[0].getPath()) if playlist.size() else None


def _publish_seek(offset: str = "", chapter: str = "") -> None:
    """
    Publish the last seek: its jump, or the chapter a chapter jump went to.
    Empty clears.

    :param offset: The jump, signed as Player.SeekOffset is (+10:00).
    :param chapter: The chapter number a chapter jump went to.
    """
    window_property("player_seek_offset", value=offset)
    window_property("player_seek_chapter", value=chapter)


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
        self._successor = ""  # the file Play next queued after this episode
        self._segments = None  # the playing video's skip segments
        self._starts = 0  # files started: a lookup lands only for its own file
        self._queue_songs = (None, set())  # music queue key, its song ids
        self._album_queue = (None, False)  # (queue key, album id), queue is the album
        SpeedDial().publish()
        if self.isPlaying():
            self.onAVStarted()
            window_property("player_start")  # entered mid-playback: no start label

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
        _publish_seek()
        self._segments = None
        segments.clear()
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
        _publish_seek()  # Next or a new item sends no stop
        self._segments, self._starts = None, self._starts + 1  # the last file's
        segments.clear()
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
        A chapter jump's player_seek_chapter goes.

        :param target: The time sought to, in ms.
        :param offset: The jump, in ms.
        """
        minutes, seconds = divmod(abs(offset) // 1000, 60)
        hours, minutes = divmod(minutes, 60)
        clock = ":".join(f"{p:02}" for p in (hours, minutes, seconds)[not hours :])
        sign = "-" if offset < 0 else "+"
        _publish_seek(offset=sign + clock if offset else "")
        self._seek_at = time.monotonic()

    def onPlayBackSeekChapter(self, chapter: int) -> None:
        """
        A chapter jump's offset isn't reliable: publish its chapter as
        player_seek_chapter in place of the last seek's jump.

        :param chapter: The chapter sought to.
        """
        _publish_seek(chapter=str(chapter))
        self._seek_at = time.monotonic()

    def onPlayBackSpeedChanged(self, speed: int) -> None:
        """
        A speed change counts as a seek with no jump: drop the last seek's.

        :param speed: The new playback speed.
        """
        _publish_seek()

    def expire_seek_offset(self) -> None:
        """
        Poller hook: drop the last jump or chapter 4 s after the seek, once Kodi's
        seek display is over, so a later seek with neither doesn't show it.
        """
        if (
            self._seek_at is not None
            and time.monotonic() - self._seek_at > 4
            and condition("!Player.HasPerformedSeek(4)")
        ):
            self._seek_at = None
            _publish_seek()

    def watch_playnext(self) -> None:
        """
        Poller hook: Play next switched off during an episode drops the successor
        it queued, so playback ends with the episode.
        """
        if self._successor and not condition("Skin.HasSetting(playnext_enabled)"):
            playnext.withdraw(self._successor)
            self._successor = ""

    def watch_segments(self) -> None:
        """Poller hook: publish the playing video's skip segment in play or next."""
        if self._segments and self.isPlayingVideo():
            try:
                now = self.getTime()
            except RuntimeError:  # stopped since isPlayingVideo
                return
            self._segments.tick(now)

    def onPlayBackStopped(self) -> None:
        """Clean up managed properties when playback is stopped by the user."""
        self._cleanup()

    def onPlayBackEnded(self) -> None:
        """Cleanup managed window properties when playback ends naturally."""
        self._cleanup()

    def onPlayBackError(self) -> None:
        """
        Clean up when requested playback fails and clear the refire stamp so the
        item can retry on its next focus; a failed flight that a newer request
        waited behind leaves that request's stamp.
        """
        request = infolabel("Window(home).Property(trailer_request)")
        own = self._landed in (None, request)  # else _cleanup hands on to request
        self._cleanup()
        if own:
            window_property("trailer_played_item")

    def _handle_video_start(self) -> None:
        """
        Publish video properties on start: parent ids with the rails' paths (an
        episode's next and its season's; a set's name and other films), subtitle type,
        stream count, picks, identity; Play next's successor; then skip segments.
        """
        tag = self.getVideoInfoTag()
        dbid = tag.getDbId()
        media_type = tag.getMediaType()
        path = infolabel("Player.Filenameandpath")
        # Always published, so stop clears what actions write later; with no lang
        # here it is never missing until the skin's player_stream_refresh passes one
        props = {
            "player_subtitle_kind": subtitle_status(*player_streams("subtitle")),
            "player_video_count": str(len(self.getAvailableVideoStreams())),
            "player_start": path,  # the skin's video_start timer clears it
        }
        props |= self._picks(tag) | self._identity(tag, path)
        self._successor = ""
        library = ("movie", 0)  # what TheIntroDB is asked by: a film, or a show's id

        if media_type == "episode":
            props["player_tvshowtitle"] = tag.getTVShowTitle()
            props["player_season"] = str(tag.getSeason())
            if dbid > 0:
                query = json_call(
                    "VideoLibrary.GetEpisodeDetails",
                    params={"properties": ["tvshowid", "file"], "episodeid": dbid},
                    parent="now_playing_episode",
                )
                details = query.get("result", {}).get("episodedetails", {})
                if tvshowid := details.get("tvshowid"):
                    props["player_tvshowid"] = str(tvshowid)
                    library = ("tvshow", tvshowid, tag.getSeason(), tag.getEpisode())
                    props |= _episode_paths(
                        tvshowid,
                        tag.getSeason(),
                        tag.getEpisode(),
                        _not_file(details["file"]),
                    )
                    self._successor = playnext.ensure_successor(dbid, tvshowid)

        elif media_type == "movie" and dbid > 0:
            query = json_call(
                "VideoLibrary.GetMovieDetails",
                params={"properties": ["setid", "set", "file"], "movieid": dbid},
                parent="now_playing_movie",
            )
            if details := query.get("result", {}).get("moviedetails", {}):
                library = ("movie", dbid)
            if setid := details.get("setid"):
                props["player_setid"] = str(setid)
                props["player_set"] = details["set"]
                props["player_set_path"] = _videodb_path(
                    f"videodb://movies/titles/?setid={setid}",
                    [_not_file(details["file"])],
                    type="movies",
                )
        self._publish(props)
        size_identity("seekbar")
        if condition("Window.IsVisible(videoosd)"):  # Next with the OSD up
            size_identity("videoosd")
        segments.clear()  # after the props: a lookup's wait never holds them back
        # The lookup's queue wait runs callbacks queued meanwhile, a next file's
        # start among them: the answer lands only if no other file started
        started = self._starts
        found = segments.lookup(self.getTotalTime(), *library)
        if started == self._starts:
            self._segments = found

    @cached_property
    def _image_editor(self) -> ImageEditor:
        """The artwork cache and processor, built on the first logo."""
        return ImageEditor()

    def _identity(self, tag: InfoTagVideo, path: str) -> dict[str, str]:
        """
        The identity lockup's logo, cropped, with its width in the lockup's box; for
        a file outside the library whose title is its file name, a clean name.

        :param tag: The playing video's info tag.
        :param path: The playing file.
        :return: player_clearlogo(_width) and player_clean_* properties, if any.
        """
        props = {}
        if tag.getDbId() <= 0:  # VideoPlayer.Title: tag, else label, else file name
            title = infolabel("VideoPlayer.Title")
            # A .strm or playlist entry plays its target, titled by that file's name
            names = file_clean_name(path, title)
            with suppress(RuntimeError):  # stopped since the AV start
                names = names or file_clean_name(self.getPlayingFile(), title)
            props |= {f"player_clean_{k}": v for k, v in names.items()}
        logo = infolabel("VideoPlayer.Art(clearlogo)") or infolabel(
            "VideoPlayer.Art(tvshow.clearlogo)"
        )
        if not logo:
            return props
        art = self._image_editor.image_processor(
            jobs={"clearlogo": ("crop",)},
            art_opts={
                "clearlogo": ArtOpts.from_params(
                    {"clearlogo_url": logo, "clearlogo_crop": "true"}, "clearlogo"
                )
            },
        )
        box_w, box_h = IDENTITY_LOGO_BOX
        w, h = (to_int(art.get(f"clearlogo_{k}")) for k in ("width", "height"))
        return props | {
            "player_clearlogo": art.get("clearlogo") or logo,
            "player_clearlogo_width": str(
                min(box_w, round(box_h * w / h)) if h else box_w
            ),
        }

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
        player_artistid_1..3 for exact matching; the album's rail path; song id, genres.
        """
        tag = self.getMusicInfoTag()
        songid = tag.getDbId()
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
                "player_songid": str(songid),
                "player_album_path": self._album_path(item.get("albumid", 0)),
                "player_disc": str(tag.getDisc()),
                "player_genres": " / ".join(tag.getGenres()),
            }
            | {f"player_artist_{i}": a for i, a in enumerate(artists[:3], 1)}
            | {f"player_artistid_{i}": str(a) for i, a in enumerate(artistids[:3], 1)}
        )
        self._record_speed_dial(songid)
        if songid > 0 and condition(ENDLESS_QUEUE):
            self._extend_queue(artists, tag.getGenres())

    def _album_path(self, albumid: int) -> str:
        """
        The playing album's songs, every disc in one list, for its rail; empty
        outside the library or when the queue is exactly that album's songs.

        :param albumid: Library album id; 0 or less if none.
        :return: musicdb://songs/?albumid=<albumid>, or empty.
        """
        if albumid <= 0:
            return ""
        # The album is read once per album in a queue
        queue = _queue_key(PlayList(PLAYLIST_MUSIC))
        if (key := (queue, albumid)) != self._album_queue[0]:
            album = json_call(
                "AudioLibrary.GetSongs",
                query_filter={"albumid": albumid},
                params={"includesingles": True},  # else a single's songs are left out
                parent="now_playing_album",
            )
            songs = {s["songid"] for s in album.get("result", {}).get("songs", [])}
            self._album_queue = (key, self._queue_ids() == songs)
        # Not musicdb://albums/<id>/: a two-disc album lists its discs, folders a
        # dialog's rail can't open
        return "" if self._album_queue[1] else f"musicdb://songs/?albumid={albumid}"

    def _queue_ids(self) -> set[int | None]:
        """
        The music queue's song ids, read once per queue (a long one costs a moment).

        :return: Its items' library ids; None for an item outside the library.
        """
        queue = _queue_key(PlayList(PLAYLIST_MUSIC))
        if queue != self._queue_songs[0]:
            items = json_call(
                "Playlist.GetItems",
                params={"playlistid": PLAYLIST_MUSIC},
                parent="now_playing_queue",
            )
            ids = {item.get("id") for item in items.get("result", {}).get("items", [])}
            self._queue_songs = (queue, ids)
        return self._queue_songs[1]

    def _extend_queue(self, artists: list[str], genres: list[str]) -> None:
        """
        Endless queue: once fewer than QUEUE_LOW songs follow the playing one, append
        QUEUE_GROWTH from a mix seeded by it, none already queued.

        :param artists: The playing song's artists.
        :param genres: Its genres.
        """
        position = (
            json_call(
                "Player.GetProperties",
                params={"playerid": 0, "properties": ["position"]},
                parent="endless_queue",
            )
            .get("result", {})
            .get("position", -1)
        )  # -1 unless playing from the music queue
        playlist = PlayList(PLAYLIST_MUSIC)
        if position < 0 or playlist.size() - position - 1 >= QUEUE_LOW:
            return
        queued = self._queue_ids()
        songs = mix_songs(
            artists, genres or artist_genres(artists), QUEUE_GROWTH, queued
        )
        add_songs(playlist, songs)
        # The same queue, grown: keep its reads, and speed dial must not count it new
        self._dial_queue = _queue_key(playlist)
        self._queue_songs = (self._dial_queue, queued | {s["songid"] for s in songs})

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
        the reaper, else the session clears. Its item may ask again; a newer item's
        stamp, set before that item's request arrives, stays.
        """
        item = infolabel("Window(home).Property(trailer_item)")
        if infolabel("Window(home).Property(trailer_played_item)") == item:
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
        _publish_seek()  # the last file's jump
        if not self.isPlaying():
            self._publish({})
            self._dropped_flight = False
            self._successor = ""
            self._segments, self._starts = None, self._starts + 1
            segments.clear()
            if landed := self._landed:  # the flight stopped before its AV start
                self._landed = None
                self._next_request(landed)
        # A pending state belongs to a newer request that superseded the
        # playback this stop event is for — leave its props intact.
        if condition("String.IsEqual(Window(home).Property(trailer_state),pending)"):
            return
        self._clear_trailer_props()
