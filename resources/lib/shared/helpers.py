# author: realcopacetic

from __future__ import annotations

import json
import posixpath
import random
import re
import time
from collections import Counter
from datetime import datetime, timedelta
from functools import cached_property
from itertools import takewhile
from operator import itemgetter
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Collection, Iterable, Mapping, NamedTuple

from xbmc import Monitor
from xbmcgui import Window

from resources.lib.shared.geometry import (
    PlacementOpts,
    align_y,
    compute_rect,
)
from resources.lib.shared import logger as log
from resources.lib.shared.text import KodiMetric, fit_lines, load_font, skin_font
from resources.lib.shared.utilities import (
    ADDON,
    ADDONDATA,
    clamp,
    condition,
    infolabel,
    json_call,
    named,
    plugin_path,
    session_salt,
    split,
    replace_file,
    split_random,
    to_int,
    topmost_window_id,
    window_property,
)

# Music genres are single names ("Drum & Bass"); " & " joins TMDb's video ones
_WHOLE_GENRES = frozenset({"album", "artist", "song", "musicvideo"})
# Lossless audio by file extension; an .m4a (ALAC or AAC) by its bitrate, kbps
LOSSLESS_EXTENSIONS = frozenset(
    {"aif", "aiff", "alac", "ape", "dff", "dsf", "flac", "tta", "wav", "wv"}
)
M4A_LOSSLESS_KBPS = 320
VARIOUS_ARTISTS = "89ad4ac3-39f7-470e-963a-56509c546377"  # MusicBrainz's artist id
COMPILATION_NAMES = 2  # a compilation's track artists named, the rest counted (+N)

# Bump when fit_lines/wrap_text change so stale clamp results are superseded.
_CLAMP_VERSION = "5"

# The identity lockup's logo (osd.xml blk_osd_identity) and its box, W x H; full-screen
# info's logo (DialogFullScreenInfo.xml, same id) fits its own box by height instead
IDENTITY_LOGO_ID = 4045
IDENTITY_LOGO_BOX = (600, 90)
INFO_LOGO_BOX = (840, 200)
# The windows that mount it: id, and the logo side sized (player_clearlogo_<side>)
IDENTITY_WINDOWS = {
    "seekbar": (10115, "width"),
    "videoosd": (12901, "width"),
    "fullscreeninfo": (10142, "height"),
}

# Skin authoring resolution; Kodi rasterises fonts at size * ScreenHeight / height.
_SKIN_WIDTH = 1920
_SKIN_HEIGHT = 1080


def gui_scale() -> int:
    """
    Image pixels per skin pixel for art the helper draws, rounded up so it is never
    stretched.

    :return: 2 on a 4K GUI, 1 at 1080p or below.
    """
    return -(-to_int(infolabel("System.ScreenHeight"), _SKIN_HEIGHT) // _SKIN_HEIGHT)


def reposition_control(
    control_id: int,
    *,
    x: int | None = None,
    y: int | None = None,
    w: int | None = None,
    h: int | None = None,
    window_id: int | None = None,
) -> bool:
    """
    Set any provided geometry on a control; unset axes are left untouched.
    Setters only (no getWidth/getX), so it never reads a control that may be
    mid-layout. Position needs both x and y; a lone axis is ignored.

    :param control_id: Target control id on the current window.
    :param x: New left in px, or None to leave unchanged.
    :param y: New top in px, or None to leave unchanged.
    :param w: New width in px, or None to leave unchanged.
    :param h: New height in px, or None to leave unchanged.
    :param window_id: A window other than the topmost, holding the control.
    :return: True when the control was found and set.
    """
    if window_id is None:
        window_id = topmost_window_id()
        # Probe first: a getControl miss logs an engine error even when caught.
        # Control.IsEnabled reads the same window and is false for a missing control.
        if not condition(f"Control.IsEnabled({control_id})"):
            log.debug(
                f"reposition_control: control {control_id} not found "
                f"in window {window_id}"
            )
            return False
    window = Window(window_id)  # keep: the window holds the control's only native ref
    try:
        ctrl = window.getControl(control_id)
    except RuntimeError:  # a named window not loaded, or a skin without the control
        log.debug(f"reposition_control: no control {control_id} in {window_id}")
        return False

    log.debug(
        f"reposition_control: window={window_id} control={control_id} "
        f"type={type(ctrl).__name__} → x={x} y={y} w={w} h={h}"
    )

    if w is not None:
        ctrl.setWidth(w)
    if h is not None:
        ctrl.setHeight(h)
    if x is not None and y is not None:
        ctrl.setPosition(x, y)
    return True


def size_identity(window: str) -> None:
    """
    Fit a window's identity logo control to the playing item's logo, so the label
    beside it or the lines under it follow, then stamp the window sized for it.

    :param window: seekbar, videoosd or fullscreeninfo, as in player_identity_<window>.
    """
    window_id, side = IDENTITY_WINDOWS[window]
    size = to_int(infolabel(f"Window(home).Property(player_clearlogo_{side})"))
    if size and not reposition_control(
        IDENTITY_LOGO_ID, window_id=window_id, **{side[0]: size}  # w= or h=
    ):
        return  # unsized: the label stays hidden rather than beside the wrong width
    logo = infolabel("Window(home).Property(player_clearlogo)")
    window_property(f"player_identity_{window}", value=logo)


def fit_height(fit: str, src_w: int, src_h: int) -> int | None:
    """
    Height of a src_w x src_h image kept to its aspect in a "W,H" box: the width
    fills first, and the height never passes H.

    :param fit: The box, "W,H".
    :param src_w: Image width in px.
    :param src_h: Image height in px.
    :return: The fitted height, or None without a box width or an image size.
    """
    fit_w, fit_h = (to_int(v, 0) for v in fit.split(","))
    if not (fit_w and src_w and src_h):
        return None
    return min(fit_h, round(fit_w * src_h / src_w))


def has_value(value: Any) -> bool:
    """Whether a value should be preserved and not overwritten."""
    return value not in (None, "", [], {})


def merge_metadata(
    base: dict[str, Any],
    incoming: Mapping[str, Any],
    *,
    prefer_incoming: bool = False,
    fill_only: Collection[str] = (),
    ignore_keys: Collection[str] = ("art", "file"),
) -> dict[str, Any]:
    """Merge incoming metadata into a base metadata dict.
    Mutates ``base`` in place using has_value rules and overwrite policy.

    :param base: Local metadata dict to update in place.
    :param incoming: Metadata dict to merge values from.
    :param prefer_incoming: If true, prefer incoming over non-empty base.
    :param fill_only: Keys incoming only fills when empty, whatever prefer_incoming.
    :param ignore_keys: Top-level keys to skip entirely when merging.
    :return: Updated base metadata dict.
    """

    def _merge(dst: dict, src: Mapping, skip: Collection[str] = ()) -> None:
        for key, value in src.items():
            if (
                key not in skip
                and has_value(value)
                and (
                    (prefer_incoming and key not in fill_only)
                    or not has_value(dst.get(key))
                )
            ):
                dst[key] = value

    if isinstance(props := incoming.get("properties"), Mapping):
        _merge(base.setdefault("properties", {}), props)
    _merge(base, incoming, skip=("properties", *ignore_keys))
    return base


def get_infolabels(target: str, keys: Iterable[str]) -> dict[str, str]:
    """
    Fetch multiple infolabels for the targeted listitem.

    :param target: Container/listitem prefix indicating where to read from.
    :param keys: Iterable of infolabel suffixes.
    :return: Dict mapping suffix → value.
    """
    return {key: infolabel(f"{target}.{key}") for key in keys}


class DataHandler:
    """Extracts metadata for a Kodi ListItem and prepares a normalized dict."""

    def __init__(
        self,
        target: str,
        dbtype: str,
        dbid: str,
    ) -> None:
        """
        Initialize the handler with listitem, dbtype and dbid.

        :param target: InfoLabel prefix (e.g. "Container(3100).ListItem").
        :param dbtype: Database content type (e.g. video or tvshow).
        :param dbid: Database ID for the given item.
        """
        self.target = target
        self.dbtype = dbtype
        self.dbid = dbid
        self.infolabels = get_infolabels(
            self.target,
            [
                "Label",
                "Director",
                "Writer",
                "Genre",
                "Studio",
                "Plot",
                "PlotOutline",
                "Tagline",
                "Title",
                "Trailer",
                "TVShowTitle",
            ],
        )

    def fetch_data(
        self,
        *,
        random_pick: Collection[str] = (),
        genre_aliases: Iterable[tuple[str, str]] = (),
        genre_chips: int = 0,
        album_format: bool = False,
        most_played: bool = False,
        compilation_artists: bool = False,
    ) -> dict[str, object]:
        """
        Build a normalized metadata dictionary.

        :param random_pick: Fields ("director", "genre") to publish one random pick of.
        :param genre_aliases: (substring, name) pairs renaming the picked genre.
        :param genre_chips: Characters two genre chips may hold (genre_chip_names).
        :param album_format: An album's most common audio format (audio_format).
        :param most_played: An album's or artist's most played song (_most_played).
        :param compilation_artists: A compilation's main track artists (its own).
        :return: Dictionary with art, resume, contributors, etc.
        """
        label = self.infolabels["Label"]
        directors, genres = self.infolabels["Director"], self.infolabels["Genre"]
        pick_genre, pick_director = "genre" in random_pick, "director" in random_pick
        # dbid: whose metadata
        properties = self._albumartist() | self._set_years() | {"dbid": self.dbid}
        if genre_chips:
            properties |= genre_chip_names(self._genres(genres), genre_chips)
        if album_format and self.dbtype == "album":
            properties |= self._album_format()
        if most_played and self.dbtype in ("album", "artist"):
            properties |= self._most_played()
        if compilation_artists and self.dbtype == "album":
            properties |= self._compilation_artists()
        if pick_genre or pick_director:
            # One pick per item and Kodi session, so a refire (closing info, back
            # from a rail) keeps the rails it fed. The genre is drawn first, so a
            # genre-only pick matches a full one's; genre_query is the whole pick.
            rng = random.Random(f"{session_salt()}:{self.dbtype}:{self.dbid}:{label}")
            if pick_genre:
                properties["genre_query"], genres = split_random(
                    genres,
                    rng=rng,
                    aliases=genre_aliases,
                    parts=self.dbtype not in _WHOLE_GENRES,
                )
            if pick_director:  # whole, for credits queries
                directors, _ = split_random(directors, rng=rng)
        return {
            "file": plugin_path("metadata"),
            "label": label,
            "label2": label,
            "Directors": [directors] if pick_director else directors.split(" / "),
            "Genres": [genres] if pick_genre else genres.split(" / "),
            "Studios": self._studio(),
            "Writers": split(self.infolabels["Writer"]),
            "Plot": self.infolabels["Plot"],
            "PlotOutline": self.infolabels["PlotOutline"],
            "TagLine": self.infolabels["Tagline"],
            "Title": self.infolabels["Title"],
            "TvShowTitle": self.infolabels["TVShowTitle"],
            "Trailer": self.infolabels["Trailer"],
            "properties": properties,
        }

    def _albumartist(self) -> dict[str, str]:
        """
        First album artist of an album or song, by id and name, so music rails
        can use musicdb ?artistid= paths and name-safe plugin paths.

        :return: albumartist_id and albumartist, or {} for other types.
        """
        if self.dbtype not in ("album", "song"):
            return {}
        song = self.dbtype == "song"
        ids, names = (
            ("albumartistid", "albumartist") if song else ("artistid", "artist")
        )
        details = json_call(
            f"AudioLibrary.Get{self.dbtype.title()}Details",
            properties=[ids, names],
            params={f"{self.dbtype}id": to_int(self.dbid)},
            parent=self.__class__.__name__,
        )
        found = details.get("result", {}).get(f"{self.dbtype}details", {})
        if not found.get(ids):
            return {}
        return {"albumartist_id": str(found[ids][0]), "albumartist": found[names][0]}

    def _genres(self, genres: str) -> list[str]:
        """
        The item's genres; an episode with none (a served one) takes its show's.

        :param genres: The item's Genre infolabel.
        :return: Genre names, in the library's order.
        """
        if self.dbtype == "episode" and not genres:
            details = json_call(
                "VideoLibrary.GetTVShowDetails",
                properties=["genre"],
                params={"tvshowid": to_int(infolabel(f"{self.target}.TVShowDBID"))},
                parent=self.__class__.__name__,
            )
            return details.get("result", {}).get("tvshowdetails", {}).get("genre", [])
        return genres.split(" / ") if genres else []

    def _album_format(self) -> dict[str, str]:
        """
        The album's most common audio format across its songs (audio_format).

        :return: format_codec with format_samplerate or format_bitrate; {} for none.
        """
        songs = json_call(
            "AudioLibrary.GetSongs",
            properties=["file", "samplerate", "bitrate"],
            params={"filter": {"albumid": to_int(self.dbid)}},
            parent=self.__class__.__name__,
        )
        formats = Counter(
            audio_format(s["file"], s["samplerate"], s["bitrate"])
            for s in songs.get("result", {}).get("songs", [])
        )
        formats.pop(None, None)
        return dict(formats.most_common(1)[0][0]) if formats else {}

    def _most_played(self) -> dict[str, str]:
        """
        The album's or artist's song with the most plays: two or more, and more than
        any other's (an album played through has none). An album's names the song's
        artists when none of them is an album artist (a compilation's song).

        :return: most_played, with most_played_artist as above; {} for none.
        """
        response = json_call(  # the top two, sorted and cut in the database
            "AudioLibrary.GetSongs",
            properties=[
                "title",
                "playcount",
                "displayartist",
                "artistid",
                "albumartistid",
            ],
            sort={"method": "playcount", "order": "descending"},
            query_filter={f"{self.dbtype}id": to_int(self.dbid)},
            limit=2,
            parent=self.__class__.__name__,
        )
        songs = response.get("result", {}).get("songs", [])
        plays = [song["playcount"] for song in songs] + [0]
        if plays[0] < 2 or plays[0] == plays[1]:
            return {}
        top = songs[0]
        found = {"most_played": top["title"]}
        if self.dbtype == "album" and set(top["artistid"]).isdisjoint(
            top["albumartistid"]
        ):
            found["most_played_artist"] = top["displayartist"]
        return found

    def _compilation_artists(self) -> dict[str, str]:
        """
        A compilation's track artists, those on the most tracks first (ties in Kodi's
        order): "Glorilla, Travis Scott +18". One by Kodi's flag or Various Artists.

        :return: compilation_artists; {} for an album that isn't one.
        """
        album = json_call(
            "AudioLibrary.GetAlbumDetails",
            properties=["compilation", "musicbrainzalbumartistid"],
            params={"albumid": to_int(self.dbid)},
            parent=self.__class__.__name__,
        )
        found = album.get("result", {}).get("albumdetails", {})
        if not (
            found.get("compilation")
            or VARIOUS_ARTISTS in found.get("musicbrainzalbumartistid", [])
        ):
            return {}
        songs = json_call(
            "AudioLibrary.GetSongs",
            properties=["artist"],
            query_filter={"albumid": to_int(self.dbid)},
            parent=self.__class__.__name__,
        )
        tracks = Counter(
            name
            for song in songs.get("result", {}).get("songs", [])
            for name in song["artist"]
        )
        if not (names := [name for name, _ in tracks.most_common()]):
            return {}
        shown = names[:COMPILATION_NAMES]
        return {"compilation_artists": named(shown, len(names) - len(shown))}

    def _studio(self) -> str:
        """
        Returns first studio name, as the library has it, so studio queries match.
        Sets carry none, so a set takes its earliest movie's.

        :return: Studio string or empty string.
        """
        if self.dbtype == "set":
            movies = self._set_movies
            return next(iter(movies[0]["studio"]), "") if movies else ""
        return split(self.infolabels["Studio"])

    def _set_years(self) -> dict[str, str]:
        """
        A set's first and last film years, for its span; the last only when it
        differs. Kodi's ListItem(-1) reads relative to the set rail's cursor.

        :return: set_first_year and set_last_year, or {} for other types.
        """
        if self.dbtype != "set" or not (
            years := [m["year"] for m in self._set_movies if m["year"]]
        ):
            return {}
        last = "" if years[-1] == years[0] else str(years[-1])
        return {"set_first_year": str(years[0]), "set_last_year": last}

    @cached_property
    def _set_movies(self) -> list[dict[str, Any]]:
        """
        The set's movies by year, with their studios and years (one call for both).

        :return: Movie rows, earliest first; [] for an empty set.
        """
        details = json_call(
            "VideoLibrary.GetMovieSetDetails",
            params={
                "setid": to_int(self.dbid),
                "movies": {
                    "properties": ["studio", "year"],
                    "sort": {"method": "year"},
                },
            },
            parent=self.__class__.__name__,
        )
        return details.get("result", {}).get("setdetails", {}).get("movies", [])


def genre_chip_names(genres: list[str], budget: int) -> dict[str, str]:
    """
    Two genre chips while both names and the second's " +N" fit budget characters,
    else one; genre_more counts the rest, for a chip's "+N" (empty for none).

    :param genres: Genre names, in order.
    :param budget: Characters the two chips' labels may hold together.
    :return: genre_first, genre_second (two chips only) and genre_more; {} for none.
    """
    if not genres:
        return {}
    first, *rest = genres
    if rest:
        more = len(rest) - 1
        if len(first) + len(rest[0]) + (more and len(f" +{more}")) <= budget:
            return {
                "genre_first": first,
                "genre_second": rest[0],
                "genre_more": str(more or ""),
            }
    return {"genre_first": first, "genre_more": str(len(rest) or "")}


def audio_format(path: str, samplerate: int, bitrate: int) -> tuple | None:
    """
    A file's format as the info screen names it: lossless by its sample rate (kHz,
    as ListItem.SampleRate), lossy by its bitrate (kbps).

    :param path: The file, whose extension is the codec.
    :param samplerate: Sample rate in Hz.
    :param bitrate: Bitrate in kbps.
    :return: Hashable (property, value) pairs; None without an extension or rate.
    """
    if not (codec := posixpath.splitext(path)[1][1:].lower()):
        return None
    if codec in LOSSLESS_EXTENSIONS or (codec == "m4a" and bitrate > M4A_LOSSLESS_KBPS):
        detail = samplerate and ("format_samplerate", f"{samplerate / 1000:.5g}")
    else:
        detail = bitrate and ("format_bitrate", str(bitrate))
    return (("format_codec", codec), detail) if detail else None


def hours_minutes(minutes: int) -> str:
    """
    A duration as the progress bar's labels show it, in the language's units.

    :param minutes: The duration in whole minutes.
    :return: "1h 23m", "1h" or "48m" in English.
    """
    h, m = ADDON.getLocalizedString(32615), ADDON.getLocalizedString(32616)
    hours, mins = divmod(minutes, 60)
    if not hours:
        return f"{mins}{m}"
    return f"{hours}{h} {mins}{m}" if mins else f"{hours}{h}"


class AlbumProgress(NamedTuple):
    """
    An album's seconds heard lately, its length, its state, its resume point and that
    track's index in its songs (0 for none), which are in disc and track order.
    """

    heard: int
    total: int
    state: str
    resume: dict[str, str]
    position: int
    songs: list[dict]


def album_resume(order: list[dict], heard: list[dict]) -> tuple[int, dict[str, str]]:
    """
    Where to pick a part-heard album up: the track after the one heard last, or after
    the album's last track the first not heard. None for a track numbered 0 (untagged).

    :param order: The album's songs from AudioLibrary.GetSongs, by disc and track.
    :param heard: The songs heard lately, some but not all, as album counts them.
    :return: Its index, album_next_track and album_next_title (+ album_next_disc).
    """
    # Songs marked played together share a last played: the latest track wins
    after = order.index(max(heard, key=itemgetter("lastplayed", "disc", "track"))) + 1
    if after == len(order):
        after = next(i for i, s in enumerate(order) if s not in heard)
    if not (song := order[after])["track"]:
        return 0, {}
    resume = {"album_next_track": str(song["track"]), "album_next_title": song["title"]}
    if len({s["disc"] for s in order} - {0}) > 1:  # disc 0: untagged, the same disc
        resume["album_next_disc"] = str(song["disc"])
    return after, resume


def album_progress(album_id: int, days: int, *fields: str) -> AlbumProgress:
    """
    An album's seconds heard in the last days, its length, "played" or "unplayed"
    (every song or none ever played) unless part-heard, its resume point.

    :param album_id: The album's library id.
    :param days: How far back a song's last play counts.
    :param fields: More song properties for its songs, e.g. file to play them.
    :return: The album's progress; heard 0 unless some but not all is recent.
    """
    response = json_call(
        method="AudioLibrary.GetSongs",
        params={
            "filter": {"albumid": album_id},
            "properties": [
                "disc",
                "duration",
                "lastplayed",
                "playcount",
                "title",
                "track",
                *fields,
            ],
        },
        parent="album_progress",
    )
    if not (songs := response.get("result", {}).get("songs")):
        # An error answer: no state, so both menu items show
        return AlbumProgress(0, 0, "", {}, 0, [])
    since = f"{datetime.now() - timedelta(days=days):%Y-%m-%d %H:%M:%S}"
    songs.sort(key=itemgetter("disc", "track"))
    # Unplayed songs keep their last played (CMusicDatabase::UpdateSong), so the
    # play count gates it; JSON-RPC's date strings sort as times
    played = [s for s in songs if s["playcount"]]
    recent = [s for s in played if s["lastplayed"] >= since]
    heard = sum(s["duration"] for s in recent)
    total = sum(s["duration"] for s in songs)
    if 0 < heard < total:
        position, resume = album_resume(songs, recent)
        return AlbumProgress(heard, total, "", resume, position, songs)
    if not played:
        return AlbumProgress(0, total, "unplayed", {}, 0, songs)
    state = "played" if len(played) == len(songs) else ""
    return AlbumProgress(0, total, state, {}, 0, songs)


# This device's Stop rewatch marks (rewatch_stops), in the add-on's own storage
REWATCH_STOPS = Path(ADDONDATA, "rewatch_stopped.json")
REWATCH_STOPPED = "rewatch_stopped"  # the action's word to the service: serve the bar


def rewatch_stops() -> dict[str, str]:
    """
    This device's Stop rewatch marks, by show dbid: when each was stopped, as
    JSON-RPC writes lastplayed ("YYYY-MM-DD HH:MM:SS"), so string order is time's.
    """
    return (
        json.loads(REWATCH_STOPS.read_text("utf-8")) if REWATCH_STOPS.exists() else {}
    )


def stop_rewatch(show_id: int) -> None:
    """
    Mark a show's rewatch stopped now on this device: its bars show none until an
    episode is played after this (decision 17B). Never written to the library.

    :param show_id: The show's library id.
    """
    stops = rewatch_stops() | {str(show_id): f"{datetime.now():%Y-%m-%d %H:%M:%S}"}
    replace_file(REWATCH_STOPS, json.dumps(stops, indent=1).encode())


class ShowItem(NamedTuple):
    """
    A library show or season on the bar: its own id, its show's (0 for a plugin's
    item), its season (None for a show or "* All seasons") and episode counts.
    """

    dbtype: str
    dbid: int
    show_id: int
    season: int | None
    watched: int
    started: bool  # an episode watched or part-watched
    left: int

    @property
    def done(self) -> bool:
        """Whether every episode is watched, specials too."""
        return bool(self.watched) and not self.left

    @property
    def scope(self) -> dict[str, int]:
        """Its GetEpisodes params: GetEpisodes rejects season -1 (* All seasons)."""
        return {"tvshowid": self.show_id} | (
            {} if self.season is None else {"season": self.season}
        )


class Rewatch(NamedTuple):
    """A rewatch's pass: its share played, the episodes left in it, the next one."""

    percent: float
    left: int
    next: dict


def rewatch_pass(episodes: list[dict]) -> int:
    """
    How far a rewatch has got: the episodes on the highest play count, when they run
    unbroken from the first and some are below it (decision 15A); 0 for none.

    :param episodes: A watched show's or season's episodes in order, specials out.
    :return: The run's length; 0 when it is no rewatch.
    """
    counts = [ep["playcount"] for ep in episodes]
    top = max(counts, default=0)
    run = sum(1 for _ in takewhile(top.__eq__, counts))
    return run if run == counts.count(top) < len(counts) else 0


class ProgressBarManager:
    """
    Calculates playback or set progress for a focused item and
    positions the corresponding progress bar UI elements.
    """

    def __init__(
        self,
        target: str,
        base_id: int,
        window_id: int,
        album_days: int,
    ) -> None:
        """
        Initialize default control IDs and sizing.

        :param target: InfoLabel prefix (e.g. "ListItem" or "Container(50).ListItem").
        :param base_id: Base group ID that wraps the bar/btn; sub-controls default to +1/+2/+3/+4.
        :param window_id: Window that holds the controls.
        :param album_days: How far back a song's last play counts towards an album.
        """

        self.window = Window(window_id)
        self.target = target
        self.album_days = album_days
        self.base_id = base_id
        self.progress_id = base_id + 1
        self.btn_id = base_id + 2
        self.img_id = base_id + 3
        self.trailer_id = base_id + 4
        self.infolabels = get_infolabels(
            self.target,
            [
                "DBID",
                "DBType",
                "PercentPlayed",
                "PlayCount",
                "Property(WatchedEpisodePercent)",
                "Property(WatchedProgress)",
                "Property(UnwatchedEpisodes)",
            ],
        )

    def calculate(self, resolution_span: int) -> tuple[float, str]:
        """
        Compute percent and unwatched label for the item referenced by ``target``.

        :param resolution_span: A picture's long edge that fills the bar; 0 for none.
        :return: (percent [0-100], unwatched label as string)
        """

        if resolution_span:  # Kodi's "1920 x 1520"; empty for a file it can't read
            edges = re.findall(r"\d+", self.picture["PictureResolution"])
            return min(max(map(int, edges), default=0) / resolution_span * 100, 100), ""

        if self.infolabels["DBType"] == "album":
            heard, total, *_ = self.album
            return (heard / total * 100 if heard else 0), ""

        unwatched = self.infolabels["Property(UnwatchedEpisodes)"]
        for p in [
            self.infolabels["PercentPlayed"],
            self.infolabels["Property(WatchedEpisodePercent)"],
            self.infolabels["Property(WatchedProgress)"],
        ]:
            if p.isdigit() and (resume := int(p)) > 0:
                return resume, unwatched

        if condition(
            f"String.IsEqual({self.target}.Overlay,OverlayWatched.png) | "
            f"Integer.IsGreater({self.target}.PlayCount,0)"
        ):
            return 100, ""

        if self.infolabels["DBType"] == "set":
            set_id = int(self.infolabels["DBID"] or 0)
            if not set_id:
                return 0, ""

            response = json_call(
                method="VideoLibrary.GetMovieSetDetails",
                params={
                    "setid": set_id,
                    "movies": {"properties": ["playcount"], "limits": {"start": 0}},
                },
                parent=self.__class__.__name__,
            )
            movies = response.get("result", {}).get("setdetails", {}).get("movies", [])

            total = len(movies)
            if not total:
                return 0, ""

            watched = sum(1 for m in movies if m.get("playcount"))
            return watched / total * 100, str(total - watched)

        return 0, unwatched

    def runtime(self, percent: float) -> int:
        """
        Runtime in seconds of a part-watched movie or episode, as Duration(secs), or
        a part-heard album's length.

        :param percent: Progress from calculate().
        :return: The runtime; 0 for other items, or when Kodi has none.
        """
        if not 0 < percent < 100:
            return 0
        if (dbtype := self.infolabels["DBType"]) == "album":
            return self.album.total
        if dbtype in ("movie", "episode"):
            return to_int(infolabel(f"{self.target}.Duration(secs)"))
        return 0

    @cached_property
    def album(self) -> AlbumProgress:
        """
        The focused album's progress (album_progress) over album_days.

        :return: The album's progress; heard 0 unless some but not all is recent.
        """
        if not (album_id := to_int(self.infolabels["DBID"])):
            return AlbumProgress(0, 0, "", {}, 0, [])
        return album_progress(album_id, self.album_days)

    @cached_property
    def picture(self) -> dict[str, str]:
        """
        The focused picture's PictureResolution and Size, read once.

        :return: Kodi's labels, e.g. "1920 x 1520" and "1.4 MB"; empty when unread.
        """
        return get_infolabels(self.target, ["PictureResolution", "Size"])

    def update(
        self,
        percent: float,
        *,
        opts: PlacementOpts,
        progress_id: int | None = None,
        btn_id: int | None = None,
        img_id: int | None = None,
        img_h: int | None = None,
    ) -> None:
        """
        Resolve rect, move/size controls, and position the thumb.

        :param percent: Unified progress percentage (0-100).
        :param opts: Placement options (coords/anchor/inset/track_w/track_h).
        :param progress_id: Optional override for progress bar ID.
        :param btn_id: Optional override for thumb button ID.
        :param img_id: Optional override for track image ID.
        :param img_h: Track image height, centred on the bar; defaults to the bar height.
        """
        base_id = self.base_id
        progress_id = to_int(progress_id, self.progress_id)
        btn_id = to_int(btn_id, self.btn_id)
        img_id = to_int(img_id, self.img_id)

        try:
            base = self.window.getControl(base_id)
            progress = self.window.getControl(progress_id)
        except RuntimeError:
            log.debug(
                f"{self.__class__.__name__} → base_id {base_id} or progress_id {progress_id} not found."
            )
            return

        rect = compute_rect(
            window=self.window,
            caller_name=self.__class__.__name__,
            opts=opts,
        )
        if rect is None:
            return
        posx, posy, width, height = rect

        if width <= 0 or height <= 0:
            log.debug(
                f"{self.__class__.__name__} → Zero-size rect → ({posx},{posy},{width},{height}); aborting."
            )
            return

        # Position/sizing
        base.setPosition(posx, posy)
        progress.setWidth(width)
        progress.setHeight(height)

        try:
            trailer = self.window.getControl(self.trailer_id)
        except RuntimeError:
            log.debug(
                f"{self.__class__.__name__} → Optional trailer_id {self.trailer_id} not found."
            )
        else:
            trailer.setWidth(width)
            trailer.setHeight(height)

        try:
            img = self.window.getControl(img_id)
        except RuntimeError:
            log.debug(
                f"{self.__class__.__name__} → Optional img_id {img_id} not found."
            )
        else:
            img_h = to_int(img_h, height)
            img.setWidth(width)
            img.setHeight(img_h)
            img.setPosition(img.getX(), align_y(0, height, img_h, "center", 0))

        cur_w, cur_h = base.getWidth(), base.getHeight()
        new_w, new_h = max(cur_w, width), max(cur_h, height)
        if (new_w, new_h) != (cur_w, cur_h):
            base.setWidth(new_w)
            base.setHeight(new_h)

        try:
            button = self.window.getControl(btn_id)
        except RuntimeError:
            button = None
            log.debug(
                f"{self.__class__.__name__} → Optional btn_id {btn_id} not found."
            )
        else:
            btn_w, btn_h = button.getWidth(), button.getHeight()
            if not (btn_w and btn_h):
                log.warning(
                    f"{self.__class__.__name__} → btn_id {btn_id} has no size; set width/height in XML"
                )
                button = None

        if button is not None:
            fraction = clamp((percent or 0) / 100.0, 0.0, 1.0)
            unwatched_centre = width * (1 + fraction) / 2
            btn_posx = int(max(0, min(unwatched_centre - btn_w / 2, width - btn_w)))
            btn_posy = int((height - btn_h) / 2)
            button.setPosition(btn_posx, btn_posy)
        log.debug(
            f"{self.__class__.__name__} → DONE → "
            f"rect=({posx},{posy},{width},{height}) "
            f"percent={percent} "
            f"btn={'skipped' if button is None else f'({btn_posx},{btn_posy}) {btn_w}x{btn_h}'}"
        )


def clamp_text(
    *,
    text: str,
    font: str,
    max_width: int,
    max_lines: int,
    sentences: bool = True,
) -> str:
    """Clamp text to max_lines when wrapped at max_width in a Font.xml font.
    Lines are pinned with [CR] so Kodi renders the measured breaks verbatim.

    :param text: Full input string.
    :param font: Kodi font name, e.g. "description_l".
    :param max_width: Wrap width in skin-coordinate pixels.
    :param max_lines: Maximum rendered lines to keep.
    :param sentences: Cap at a sentence end; False always ellipsises (a title).
    :return: Clamped lines joined with [CR].
    """
    from resources.lib.shared.hash import HashManager
    from resources.lib.shared.sqlite import TruncateCacheHandler

    # Keyed by the font's file and size, so a skin's new font for the name re-clamps
    if (spec := skin_font(font)) is None:
        return text
    scale_x = to_int(infolabel("System.ScreenWidth")) / _SKIN_WIDTH
    scale_y = to_int(infolabel("System.ScreenHeight")) / _SKIN_HEIGHT
    cache = TruncateCacheHandler()
    key = HashManager.short_hash_str(
        "|".join(
            (
                _CLAMP_VERSION,
                *map(str, spec),
                f"{scale_x:.4f}",
                f"{scale_y:.4f}",
                str(max_width),
                str(max_lines),
                str(sentences),
                text,
            )
        ),
        length=16,
    )
    if (cached := cache.get_entry(key)) is not None:
        return cached

    if (face := load_font(spec[0])) is None:
        return text
    metric = KodiMetric(face, spec[1], scale_x, scale_y)
    lines = fit_lines(metric, text, max_width, max_lines, sentences=sentences)
    result = "[CR]".join(lines)
    cache.upsert_entry(key, result)
    return result


class TypewriterAnimation:
    """
    Typewriter text effect with PlacementOpts-driven positioning.
    Height grows per line up to max_lines unless track_h is provided.
    """

    leases = {}  # control id → the token this process's last run took for it
    lease_lock = Lock()  # a claim and a stopped run's hand-back, one at a time

    def __init__(
        self,
        control_id: int,
        window_id: int,
        step_time: float = 0.025,
        default_line_h: int = 30,
        max_lines: int = 3,
    ):
        """
        Initialise the animator with default control id, timing, and sizing.
        Line height must match the rendered font pitch or text will clip.

        :param control_id: Text control id to animate.
        :param window_id: Window that holds the control.
        :param step_time: Delay per character (seconds).
        :param default_line_h: Fallback line height (px) when ``opts.track_h`` is unset.
        :param max_lines: Max number of lines the box may grow to.
        """

        self.window = Window(window_id)
        self.window_id = window_id
        self.control_id = control_id
        self.step_time = step_time
        self.default_line_h = default_line_h
        self.max_lines = max_lines

    @staticmethod
    def reset(target_id: int) -> None:
        """
        Supersede any in-flight run and hide the control.
        Stale text is safe: only update() reveals the control, and it clears first.

        :param target_id: Text control id to hide.
        """
        Window(10000).setProperty(f"typewriter_current_{target_id}", "scroll")
        log.execute(f"Control.SetHidden({target_id})")

    @staticmethod
    def retired(target_id: int | str) -> bool:
        """
        Whether the line this process last typed in the control is gone: its lease is
        no longer its run's (the skin's scroll, a reset, another run, or its own stop).

        :param target_id: Text control id.
        :return: True once retired.
        """
        lease = Window(10000).getProperty(f"typewriter_current_{target_id}")
        return lease != TypewriterAnimation.leases.get(int(target_id))

    def claim(self) -> str:
        """
        Take the control's lease for a run: an older run, or the skin's scroll, then
        stops it.

        :return: The run's token.
        """
        token = str(time.time_ns())
        with TypewriterAnimation.lease_lock:
            Window(10000).setProperty(f"typewriter_current_{self.control_id}", token)
            TypewriterAnimation.leases[self.control_id] = token
        return token

    def update(
        self,
        *,
        label: str,
        opts: PlacementOpts,
        max_lines: int | None = None,
        start_delay: float = 0,
        alive: Callable[[], bool] | None = None,
        token: str = "",
    ) -> None:
        """
        Animate label with a typewriter effect using compute_rect placement.
        ``track_h`` must match the rendered font pitch or text will clip.

        :param label: Text to animate.
        :param opts: Placement options; ``track_h`` is line height + growth.
        :param max_lines: Optional cap for number of lines (overrides default).
        :param start_delay: Seconds before typing begins; abort checks apply during the wait.
        :param alive: Optional guard callable; return False to abort animation.
        :param token: The lease claim() already took; empty claims it here.
        """
        monitor = Monitor()

        def _alive() -> bool:
            if monitor.abortRequested():
                return False
            return alive() if alive is not None else True

        log.debug(f"{self.__class__.__name__} → START → '{label}'")
        control_id = self.control_id

        # Ownership lease. Isolated typewriter instances share prop
        owner_key = f"typewriter_current_{control_id}"
        my_token = token or self.claim()
        home = Window(10000)

        def _superseded() -> bool:
            return home.getProperty(owner_key) != my_token

        def _retire() -> None:
            """A run that stops with the lease still its own hands it back: no line."""
            with TypewriterAnimation.lease_lock:  # a claim can't land in between
                if not _superseded():
                    home.setProperty(owner_key, "scroll")

        if start_delay > 0:
            if monitor.waitForAbort(start_delay):
                return
            if not _alive() or _superseded():
                _retire()
                log.debug(
                    f"{self.__class__.__name__} → ABORTED → '{label}' during start_delay"
                )
                return

        try:
            control = self.window.getControl(control_id)
            control.setText("")
        except Exception:
            _retire()
            log.exception(
                f"{self.__class__.__name__} → Control {control_id} not found", log.DEBUG
            )
            return

        def _abort(reason: str) -> None:
            """
            Log the stop; clear the control unless a run or reset took it over while
            this window is in front (one in another window can't reach this control).
            """
            if not _superseded() or topmost_window_id() != self.window_id:
                control.setText("")
            _retire()
            log.debug(f"{self.__class__.__name__} → ABORTED → '{label}' {reason}")

        if not _alive():
            _abort("lost focus")
            return

        line_h = max(1, int(opts.track_h or self.default_line_h))
        max_lines_eff = max_lines or self.max_lines
        max_height = line_h * max_lines_eff

        rect = compute_rect(
            window=self.window,
            caller_name=self.__class__.__name__,
            opts=opts,
            content_h=(max_height if not opts.track_h else None),
        )
        if rect is None:
            _abort("no rect")
            return
        posx, posy, width, height = rect
        posy = align_y(posy, height, line_h, align=opts.valign, pad=0)

        if _superseded():
            _abort("superseded")
            return

        control.setWidth(width)
        control.setHeight(line_h)
        control.setPosition(posx, posy)

        # Animate: add line_h per wrap, up to max_lines
        current_height = line_h
        current_posy = posy
        valign = (opts.valign or "center").lower()
        grows = 0

        def _pages(text: str) -> int | None:
            """NumPages for text; None while the box still holds an older layout.
            Kodi sets the text just before re-wrapping it, so a read can still race.
            """
            if infolabel(f"Control.GetLabel({control_id})") != text:
                return None
            return to_int(infolabel(f"Container({control_id}).NumPages"))

        def _grow(text: str, pages: int) -> None:
            """Grow to the fewest lines that hold pages, keep the anchor, resend text."""
            nonlocal current_height, current_posy, grows
            next_h = min((pages - 1) * current_height + line_h, max_height)
            if next_h <= current_height:
                return
            dy = next_h - current_height
            current_height = next_h
            grows += 1
            if valign == "bottom":
                current_posy -= dy
            elif valign == "center":
                current_posy -= dy // 2
            control.setHeight(current_height)
            control.setPosition(posx, current_posy)
            # Resend: LABEL_SET resets the layout, so it re-wraps at the new height.
            control.setText(text)

        # setText is a thread message, setVisible is immediate: let the clear land.
        control.setText("")
        if monitor.waitForAbort(self.step_time):
            return
        if not _alive():
            _abort("lost focus")
            return
        if _superseded():
            _abort("superseded")
            return
        control.setVisible(True)
        # setVisible waits for a frame: a reset that landed in that wait hid the box
        # first, and it shows again now, so nothing more may go into it.
        if _superseded():
            _abort("superseded")
            return

        for i in range(1, len(label) + 1):
            sub = label[:i]
            control.setText(sub)

            # Step wait: paces the typing. The lockless reads below can land before
            # Kodi lays out sub, so _pages skips the check until the box holds it.
            if monitor.waitForAbort(self.step_time):
                return

            # After the wait, so a run that lost focus or was taken over never grows.
            if not _alive():
                _abort("lost focus")
                return
            if _superseded():
                _abort("superseded")
                return

            if pages := _pages(sub):
                _grow(sub, pages)

        # The last character's check was skipped: give its layout up to four steps.
        # A dialog over the window answers the reads, so those wait for it to close,
        # at a slower pace: under a dialog each guard check waits for a frame.
        steps = 4
        while pages is None and steps:
            covered = topmost_window_id() != self.window_id
            if monitor.waitForAbort(0.25 if covered else self.step_time):
                return
            if not _alive() or _superseded():
                log.debug(
                    f"{self.__class__.__name__} → ABORTED → '{label}' settling, kept"
                )
                return
            if not covered:
                steps -= 1
                if pages := _pages(label):
                    _grow(label, pages)

        log.debug(
            f"{self.__class__.__name__} → DONE → '{label}' "
            f"(len={len(label)} grows={grows} h={current_height}/{max_height} line_h={line_h})"
        )
