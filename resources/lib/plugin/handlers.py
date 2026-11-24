# author: realcopacetic

from __future__ import annotations

import json
import math
import random
import re
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from functools import cache, cached_property, partial
from itertools import islice
from operator import itemgetter
from threading import Thread
from typing import TYPE_CHECKING, Any, Callable

from xbmc import Monitor, getLocalizedString
from xbmcgui import Window, getCurrentWindowDialogId, getCurrentWindowId
from xbmcplugin import SORT_METHOD_LASTPLAYED

from resources.lib.apis.cache import cache_only
from resources.lib.shared.geometry import PlacementOpts
from resources.lib.shared.helpers import (
    DataHandler,
    ProgressBarManager,
    TypewriterAnimation,
    clamp_text,
    fit_height,
    get_infolabels,
    hours_minutes,
    merge_metadata,
    reposition_control,
)
from resources.lib.plugin.identity import ArtworkIdentity
from resources.lib.plugin.json_map import (
    HEAVY_FIELDS,
    JSON_PROPERTIES,
    json_to_canonical,
    trim_properties,
)
from resources.lib.plugin.library import (
    DirectoryItem,
    build_items,
    enrich_with_tvshow,
    fetch_and_add,
    fetch_raw,
    random_rows,
    role_endpoint,
    seeded_sort,
    title_filter,
)
from resources.lib.plugin.music import (
    ALBUM_RANK_PROPERTIES,
    ALBUM_SONG_PROPERTIES,
    POPULAR,
    SONG_RANK_PROPERTIES,
    WEIGHTS,
    album_credit,
    artist_identity,
    artist_names,
    artist_places,
    deezer_match,
    details_item,
    dial_item,
    library_item,
    library_rows,
    mix_cards,
    play_place,
    rank_albums,
    rank_songs,
    similar_artists,
    song_place,
    song_play_place,
)
from resources.lib.plugin.pvr import BROADCAST_FIELDS, broadcast_items
from resources.lib.plugin.registry import LOG_TAG, PluginInfoRegistry
from resources.lib.plugin.setter import apply_videoinfotag, set_items
from resources.lib.plugin.soundtracks import (
    SOUNDTRACK,
    claim,
    lead,
    owner,
    release_year,
    title_key,
)
from resources.lib.shared import logger as log
from resources.lib.shared.lrc import LINES, LONG, NEIGHBOURS
from resources.lib.shared.mix import genre_ids, kept_mix, leading_cards, played_songs
from resources.lib.shared.parser import parse_plugin_argv
from resources.lib.shared.speed_dial import MUSIC_TYPES, SpeedDial
from resources.lib.shared.text import markdown_label, single_quotes
from resources.lib.shared.utilities import (
    ADDON,
    DETAILS,
    INFO_DIALOGS,
    clear_label,
    condition,
    file_clean_name,
    file_label,
    focused_control_id,
    fold,
    infolabel,
    json_call,
    parse_bool,
    plugin_path,
    session_salt,
    set_plugincontent,
    to_float,
    to_int,
    topmost_window_id,
    window_property,
)

if TYPE_CHECKING:
    from resources.lib.apis.tmdb.transform import Asker

# The playing song's identity for target=player, by labels a plugin URL carries
# intact (a path or title can hold "&key=" or a "|", which cut it): its id, and its
# queue position and length for songs outside the library
PLAYING_SONG = (
    "MusicPlayer.DBID",
    "MusicPlayer.PlaylistPosition",
    "MusicPlayer.Duration",
)
_VIDEO_METHODS = {
    "movie": "Movie",
    "tvshow": "TVShow",
    "season": "Season",
    "episode": "Episode",
    "musicvideo": "MusicVideo",
    "set": "MovieSet",
}  # VideoLibrary.Get{…}s / Get{…}Details per library type
_MUSIC_NAMES = {"album": "album", "artist": "artist", "song": "title"}  # name field
# TMDb's show status as _show_news's show_status: no more episodes, or more to come
_SHOW_STATUS = {"Canceled": "ended", "Ended": "ended", "Returning Series": "returning"}
_LABEL = "popularity_label"  # the handler's name: its item's path, its calls' parent


def _video_details(
    type: str, dbid: int, properties: list[str], parent: str
) -> dict | None:
    """
    A library video item's details: a film, show, season, episode, music video or set.

    :param type: A _VIDEO_METHODS key.
    :param dbid: Library id.
    :param properties: Properties to fetch.
    :param parent: Caller name for logging.
    :return: The details row, or None if the library lost the item.
    """
    return (
        json_call(
            f"VideoLibrary.Get{_VIDEO_METHODS[type]}Details",
            properties=properties,
            params={f"{type}id": dbid},
            parent=parent,
        )
        .get("result", {})
        .get(f"{type}details")
    )


_INFO_OPEN = " | ".join(f"Window.IsVisible({wid})" for wid in INFO_DIALOGS)
# and the music OSD, whose rails serve alike, and PVR guide and recording info
_SERVE_DIALOGS = (*INFO_DIALOGS, 10120, 10600, 10601)
_SLIDESHOW = 12007  # a modal dialog: a run guarded by SLIDESHOW_PICTURE follows it
SLIDESHOW_PICTURE = ("Slideshow.SlideIndex",)  # the picture shown, free of "|" and "&"
_TRAILER_PENDING = "String.IsEqual(Window(home).Property(trailer_state),pending)"


def _info_open() -> bool:
    """
    Whether an info dialog is open, from its registration to the end of its close:
    Python's container reads can answer for its rails, which share the windows' ids.
    """
    return condition(_INFO_OPEN)


class _FocusGuard:
    """
    Lazy focus/identity guard for plugin operations.
    Evaluates container focus and item identity on demand.
    """

    __slots__ = (
        "caller_name",
        "expected_identity",
        "identity_getter",
        "focus_ids",
        "window_id",
        "dialog",
        "player",
        "through_info",
        "picture",
        "superseded",
        "lost_to",
    )

    def __init__(
        self,
        caller_name: str,
        expected_identity: str | None,
        identity_getter: Callable[[], str],
        window_id: int,
        dialog: bool,
        focus_ids: tuple[str, ...] = (),
        player: bool = False,
        through_info: bool = False,
        picture: bool = False,
        superseded: Callable[[], bool] | None = None,
    ):
        """
        Create a guard that checks container focus and item identity.

        :param caller_name: Name of the calling handler, used for logging.
        :param expected_identity: Focused item's snapshot identity; None to skip.
        :param identity_getter: Callable returning current item identity.
        :param window_id: Window whose focus is read, which holds the serve's controls.
        :param dialog: Whether window_id is a dialog, so its closing aborts the run.
        :param focus_ids: Control ids of which one must hold focus; empty to skip.
        :param player: Whether the item is the playing song, which no focus follows.
        :param through_info: Whether the run passes under an info dialog too.
        :param picture: Whether the identity is the slideshow's picture.
        :param superseded: A served list's test for a newer arrival, checked first.
        """
        self.caller_name = caller_name
        self.expected_identity = expected_identity
        self.identity_getter = identity_getter
        self.window_id = window_id
        self.dialog = dialog
        self.focus_ids = focus_ids
        self.player = player
        self.through_info = through_info
        self.picture = picture
        self.superseded = superseded
        self.lost_to = ""  # the identity read when the item moved on

    def alive(self) -> bool:
        """
        Validate current focus and item identity.

        :return: True if guard conditions still hold, otherwise False.
        """
        # A served run stops at a newer arrival: one identity test and a property read
        if self.superseded and self.superseded():
            log.debug(f"{LOG_TAG} → {self.caller_name}: ABORTED → superseded")
            return False

        # Nothing in the visualisation takes focus: its window and the song decide.
        # A stop empties the identity, so it aborts too.
        if self.player:
            if getCurrentWindowId() != self.window_id or (
                self.expected_identity
                and self.identity_getter() != self.expected_identity
            ):
                log.debug(f"{LOG_TAG} → {self.caller_name}: ABORTED → song or window")
                return False
            return True

        # A closed info dialog still reports the rail it closed on as focused.
        if (
            self.dialog
            and topmost_window_id() != self.window_id
            and not condition(f"Window.IsActive({self.window_id})")
        ):
            log.debug(
                f"{LOG_TAG} → {self.caller_name}: ABORTED → "
                f"dialog {self.window_id} closed"
            )
            return False

        # A modal dialog over the window answers the reads below, and nothing under
        # it moves. An info dialog's rails share the window's ids, so under one only
        # a run that reads none of them carries on. The slideshow's picture moves.
        modal = getCurrentWindowDialogId()
        if modal != 9999 and self.window_id == getCurrentWindowId():
            if self.picture and modal == _SLIDESHOW:
                return self._same_item()
            if self.through_info or not _info_open():
                return True
            log.debug(f"{LOG_TAG} → {self.caller_name}: ABORTED → under an info dialog")
            return False

        if not (focus_id := focused_control_id(self.window_id)):
            return True
        current = str(focus_id)

        if (
            self.focus_ids
            and current not in self.focus_ids
            and not any(condition(f"Control.HasFocus({fid})") for fid in self.focus_ids)
        ):
            log.debug(
                f"{LOG_TAG} → {self.caller_name}: ABORTED → focus left "
                f"({', '.join(self.focus_ids)}) to {current}"
            )
            return False

        return self._same_item()

    def _same_item(self) -> bool:
        """
        Identity check: the live identity, when it reads, is still the snapshot.

        :return: False once the item has moved on (lost_to is then set).
        """
        if not self.expected_identity:
            return True

        current_identity = self.identity_getter()
        if current_identity and current_identity != self.expected_identity:
            self.lost_to = current_identity
            log.debug(
                f"{LOG_TAG} → {self.caller_name}: ABORTED → "
                f"'{self.expected_identity}' lost focus to '{current_identity}'"
            )
            return False

        return True


# A library show's titles path: its id, then the listed season, if any
_TITLES = "videodb://tvshows/titles/"
_TITLES_PATH = re.compile(rf"{_TITLES}(\d+)/(?:(-?\d+)/)?")


class PluginHandlers(metaclass=PluginInfoRegistry):
    """
    High-level plugin actions (artwork, metadata, typewriter) with focus guarding.
    """

    def __init__(
        self,
        params: dict[str, str],
        superseded: Callable[[], bool] | None = None,
        again: Asker | None = None,
        query: str = "",
        cursors: dict[str, str] | None = None,
    ) -> None:
        self.params = params
        self.superseded = superseded  # a served list's: its guards test it first
        self.again = again  # a served list's re-serve, for an answer that lands later
        self.query = query  # the raw query params came from: a service has no argv
        self.cursors = cursors or {}  # a served settle's cursor by region

        self.label = params.get("label", "")
        self.dbtype = params.get("type", "").lower()
        self.dbid = params.get("id", "")
        self.target = to_int(params.get("target"), None)
        self.expected_identity = params.get("focus_guard")
        self.focus_ids = tuple(filter(None, params.get("focus_ids", "").split(",")))
        self.identity_labels = tuple(
            filter(None, params.get("identity_labels", "").split(","))
        )
        self.target_container = (
            f"Container({self.target})" if self.target is not None else "Container"
        )
        # target=item reads the window's own item (an info dialog's): a bare
        # ListItem prefix, since a Container one lands on the focused container.
        self.item = params.get("target") == "item"
        # target=player reads the playing song (Player.Art); it has no position either
        self.player = params.get("target") == "player"
        self.target_item = (
            "ListItem"
            if self.item
            else "Player" if self.player else f"{self.target_container}.ListItem"
        )
        self.dialog = self.item or parse_bool(params.get("dialog"))
        self.identity_id = to_int(params.get("identity_container"), self.target)
        self.identity_container = (
            f"Container({self.identity_id})"
            if self.identity_id is not None
            else "Container"
        )
        self.identity_item = (
            "ListItem" if self.item else f"{self.identity_container}.ListItem"
        )
        self.sort_lastplayed = {"order": "descending", "method": "lastplayed"}
        self.limit = to_int(params.get("limit"), None)

        self.exclude_key = params.get("exclude_key", "title")
        self.exclude_value = params.get("exclude_value", "")
        self.filter_unwatched = {
            "field": "playcount",
            "operator": "lessthan",
            "value": "1",
        }
        self.filter_no_specials = {
            "field": "season",
            "operator": "greaterthan",
            "value": "0",
        }
        self.filter_inprogress = {
            "field": "inprogress",
            "operator": "true",
            "value": "",
        }
        self.filter_exclude = {
            "field": self.exclude_key,
            "operator": "isnot",
            "value": self.exclude_value,
        }

    def _guard(self, through_info: bool = False) -> _FocusGuard:
        """
        Focus/identity guard for the running handler, logged under its info name.

        :param through_info: Whether the run passes under an info dialog too.
        """
        labels = PLAYING_SONG if self.player else self.identity_labels
        if labels:
            # A "|" ends a plugin URL's options, so a guard ending in a label holding
            # one arrived cut there: the live identity is cut to match
            getter = lambda: ",".join(infolabel(p) for p in labels).partition("|")[0]
        else:
            getter = lambda: infolabel(f"{self.identity_container}.CurrentItem")
        # The identity the URL carries (song=, focus_guard=); with none, the one now: a
        # "|" in an earlier param, such as a plot, cuts the guard off the URL
        key = "song" if self.player else "focus_guard"
        if (expected := self.params.get(key)) is None and labels:
            expected = getter()
        return _FocusGuard(
            self.params.get("info", ""),
            expected,
            getter,
            self.window_id,
            self.dialog,
            self.focus_ids,
            self.player,
            through_info,
            labels == SLIDESHOW_PICTURE,
            self.superseded,
        )

    @cached_property
    def randomise(self) -> str:
        """
        The order seed: randomise= (empty for a fresh order), else Copacetic's live
        one, so a path saved without it follows the rails' seed.
        """
        seed = self.params.get("randomise")
        return infolabel("Window(home).Property(random_seed)") if seed is None else seed

    @cached_property
    def window_id(self) -> int:
        """
        Window whose controls this serve draws into, read once: its info dialog
        (_info_window) for a dialog serve (dialog=true, target=item); else the active
        window.
        """
        return self._info_window if self.dialog else getCurrentWindowId()

    @cached_property
    def _info_window(self) -> int:
        """
        The dialog a dialog serve belongs to (an info dialog, PVR info or the music
        OSD), read once: the topmost dialog when it is one, else the one a menu,
        Select or busy dialog covers, else 9999 (it has closed).
        """
        if (top := topmost_window_id()) in _SERVE_DIALOGS:
            return top
        active = (wid for wid in _SERVE_DIALOGS if condition(f"Window.IsActive({wid})"))
        # Never another window: a serve its dialog's close outran would read controls
        # there (Non-Existent Control 4046); 9999 fails _info_on_top and the guard
        return next(active, 9999)

    def _info_on_top(self) -> bool:
        """
        Wait up to a second, and up to five more behind the busy dialog, for the
        serve's info dialog to be topmost: under a menu, ListItem reads miss it.

        :return: False if it never was, it closed, Kodi exits, or busy with no guard.
        """
        monitor, left, busy_left, swap = Monitor(), 10, 50, False
        while (top := topmost_window_id()) != self._info_window:
            # Kodi's own Information swaps the item behind the busy dialog; a
            # trailer's resolve shows it too (service/player.py), swapping nothing
            if top == 10138:
                busy_left -= 1
                swap |= not condition(_TRAILER_PENDING)
            else:
                left -= 1
            if (
                min(left, busy_left) < 0
                or not condition(f"Window.IsVisible({self._info_window})")
                or monitor.waitForAbort(0.1)
            ):
                return False
        # Behind the busy dialog the item may have swapped: a run whose guard a "|" cut
        # off would guard the new item (_guard reads it now), so it stops instead
        return (
            not swap or self.expected_identity is not None or not self.identity_labels
        )

    def _item_key(self, item: str | None = None) -> str:
        """
        An item's library identity, dbtype:dbid.

        :param item: Infolabel prefix of the item; the art source's if None.
        :return: The identity, "dbtype:dbid".
        """
        item = item or self.target_item
        return f"{infolabel(f'{item}.DBType')}:{infolabel(f'{item}.DBID')}"

    def _visit_superseded(self) -> bool:
        """
        A URL whose visit stamp is no longer live is a replay or a superseded serve:
        the live visit's URL fires on its own, so this run must do nothing.

        :return: True when the URL carries a visit, even an empty one, not the live one.
        """
        if self.superseded:  # served: the arrival is the visit
            return self.superseded()
        visit = self.params.get("visit")
        stamp = "Window(home).Property(artwork_visit)"
        return visit is not None and visit != infolabel(stamp)

    def _info_swapped(self) -> bool:
        """
        Kodi's own Information (a rail's context menu) swaps the open dialog's item
        with no onload to record it: hand the item to info_swap, as a rail click.

        :return: True when the dialog is about to reopen.
        """
        current = infolabel("Window(home).Property(info_current)")
        key = self._item_key()
        if (
            not current
            or key == current
            or infolabel("Window(home).Property(info_hop)")
        ):
            return False
        window_property("info_hop", value="forward")
        log.execute(f"RunScript(script.copacetic.helper,action=info_swap,key={key})")
        return True

    def _get_tmdb_item(
        self,
        *,
        append_artwork: bool,
        cache_only: bool = False,
        target: str | None = None,
        aside: Asker | None = None,
    ) -> dict[str, Any] | None:
        """Resolve TMDb canonical item for the current listitem.

        :param append_artwork: Whether to include TMDb artwork fields.
        :param cache_only: Read the TMDb cache only; never fetch.
        :param target: Infolabel prefix of the item; the serve's target item if None.
        :param aside: Read the cache, fetching on a thread that calls this on news.
        :return: canonical item dict or None.
        """
        from resources.lib.apis.tmdb.client import tmdb_token
        from resources.lib.apis.tmdb.context import resolve_tmdb_context
        from resources.lib.apis.tmdb.transform import tmdb_to_canonical

        if not tmdb_token():  # off: skip resolve_tmdb_context's uniqueid lookup
            return

        ctx = resolve_tmdb_context(self.params, target=target or self.target_item)
        tmdb_id = to_int(ctx.get("tmdb_id"), 0)

        item = tmdb_to_canonical(
            kind=ctx.get("kind") or self.dbtype,
            tmdb_id=tmdb_id,
            season_number=ctx.get("season_number"),
            language=self.params.get("language"),
            append_artwork=append_artwork,
            cache_only=cache_only,
            aside=aside,
        )
        if not item:
            log.debug(
                f"{self.__class__.__name__} → tmdb: no data for "
                f"type={(ctx.get('kind') or self.dbtype)!r}, tmdb_id={tmdb_id}"
            )
            return

        return item

    def _probe_text(self, param: str) -> str:
        """The label of the probe control a URL param names; empty if it names none.

        :param param: URL param holding the control id.
        :return: The control's label.
        """
        label_id = to_int(self.params.get(param, 0))
        return infolabel(f"Control.GetLabel({label_id})") if label_id else ""

    def _apply_truncated_label(
        self,
        data: dict[str, Any],
        *,
        target: str,
        default_text: str | None = None,
        probe: bool = True,
        probed: str = "",
    ) -> None:
        """Attach a truncated label to a metadata dict.
        Text precedence: truncate_label, truncate_label_id probe, default_text, Plot.
        Geometry is measured plugin-side against the declared skin font.

        :param data: Metadata dict to update in place.
        :param target: ListItem infolabel prefix for plot fallback.
        :param default_text: Optional plot to use before infolabel fallback.
        :param probe: Whether to use the truncate_label_id probe.
        :param probed: The truncate_label_id probe's text, read before any wait.
        """
        truncate_width = to_int(self.params.get("truncate_width", 0))
        truncate_font = self.params.get("truncate_font", "")
        if not truncate_width:
            return
        if not truncate_font:
            log.warning(
                f"{self.__class__.__name__} → truncate_width without "
                f"truncate_font; skipping"
            )
            return

        truncate_label = (
            self.params.get("truncate_label")
            or (probed if probe else "")
            or default_text
            or infolabel(f"{target}.Plot")
        )
        if not truncate_label:
            return

        truncated = clamp_text(
            text=truncate_label,
            font=truncate_font,
            max_width=truncate_width,
            max_lines=to_int(self.params.get("truncate_lines"), 3),
        )

        props = data.setdefault("properties", {})
        props["truncated_label"] = truncated

    def _apply_truncated_title(self, data: dict[str, Any], title: str) -> None:
        """Attach the title cut with an ellipsis, only if it overflows: a title that
        fits sets nothing, so the skin's live text never changes.

        :param data: Metadata dict to update in place.
        :param title: The truncate_title_id probe's text; empty does nothing.
        """
        width = to_int(self.params.get("truncate_title_width", 0))
        if not (title and width):
            return
        truncated = clamp_text(
            text=title,
            font=self.params["truncate_title_font"],
            max_width=width,
            max_lines=to_int(self.params.get("truncate_title_lines"), 3),
            sentences=False,
        )
        if truncated.replace("[CR]", " ") != title:
            data.setdefault("properties", {})["truncated_title"] = truncated

    def _require(self, *names: str) -> bool:
        """
        Warn and return False when any named URL param is absent.

        :param names: Required param names.
        :return: True when all present.
        """
        if missing := [n for n in names if not self.params.get(n)]:
            log.warning(f"{self.params.get('info')} → {', '.join(missing)} required")
            return False
        return True

    @property
    def _prop_suffix(self) -> str:
        """
        The artwork serve's window property suffix: _<prop_key>, or none without one.
        """
        return f"_{key}" if (key := self.params.get("prop_key")) else ""

    def _bridge_props(self) -> list[tuple[str, str]]:
        """
        The artwork serve's art fields and the window properties they are written to.
        """
        suffix = self._prop_suffix
        return [
            ("background", f"background_blur{suffix}"),
            ("background_darken", f"background_darken{suffix}"),
            ("icon_darken", f"icon_darken{suffix}"),
        ]

    def _cover_size(
        self, art: dict[str, str], played: str, alive: Callable[[], bool]
    ) -> None:
        """
        Publish the playing song's cover size from a player icon_shape serve:
        cover_small (under 500 on its short side, or none), then its song, cover_file,
        each _prop_suffix ended. Nothing once the song has moved on (a late serve).

        :param art: The serve's art; empty for a song with no art.
        :param played: Player.Filenameandpath when the serve started.
        :param alive: The serve's guard.
        """
        if not (self.player and parse_bool(self.params.get("icon_shape"))):
            return
        if not alive() or infolabel("Player.Filenameandpath") != played:
            return
        suffix = self._prop_suffix
        size = min(to_int(art.get("icon_width"), 0), to_int(art.get("icon_height"), 0))
        window_property(f"cover_small{suffix}", size < 500)
        window_property(f"cover_file{suffix}", played)

    @property
    def _scope_prop(self) -> str:
        """
        The window property naming the scope the bridge properties were written for.
        """
        return f"artwork_scope{self._prop_suffix}"

    def _artwork_held(self, lost_to: str = "") -> list[DirectoryItem] | None:
        """
        An aborted plugin serve re-serves what its list (prop_key, an id) shows, under
        an identity no cursor matches; with no id, an empty list, or a dialog over the
        serve's window (window_id), the last blur and darkens this list wrote.

        :param lost_to: The identity the guard read when the item moved on, if it did.
        :return: The held item for Kodi; None served, as a stopped stage binds nothing.
        """
        if self.superseded:
            return None
        key = self.params.get("prop_key", "")
        shown = f"Container({key}).ListItem"
        props = self._bridge_props()
        on_top = topmost_window_id() == self.window_id
        # Kodi takes a non-numeric id as 0, the focused container; another window on
        # top would answer with its own control of that id.
        if key.isdigit() and on_top and infolabel(f"{shown}.Art(background)"):
            # <scope>/pos/dbid/visit, or held/<scope>/<key> from an earlier hold
            current = infolabel(f"{shown}.Property(current)")
            scope = current.removeprefix("held/").partition("/")[0]
            labels = {field: f"{shown}.Art({field})" for field, _ in props}
        else:
            scope = infolabel(f"Window(home).Property({self._scope_prop})")
            labels = {field: f"Window(home).Property({prop})" for field, prop in props}
        # The next visit stamp carries this count, so the URL held here never repeats.
        holds = to_int(infolabel("Window(home).Property(artwork_holds)"), 0)
        window_property("artwork_holds", holds + 1)
        # The guard's own read, not a fresh one: the cursor may be back already.
        if lost_to and on_top and not self._visit_superseded():
            self._name_unstamped_hold()
        return set_items(
            [
                {
                    "file": plugin_path("artwork"),
                    "art": {field: infolabel(label) for field, label in labels.items()},
                    "properties": dict.fromkeys(
                        ("current", "identity"), f"held/{scope}/{key}"
                    ),
                }
            ]
        )

    def _name_unstamped_hold(self) -> None:
        """
        A hold on a move that stamped no visit (the jumpbar, a list with no cursor):
        name the held position (artwork_held_<cursor_key or hold_key>) and count it
        (artwork_holds_unstamped). The URL carries the count only on that position.
        """
        position = self.expected_identity
        # Identity labels guard something other than a position. The cursor's
        # container must be in this window: absent in another (Back to Home over a
        # trailer), where the guard read another window's item. A list with no
        # cursor names its hold itself (hold_key), in its own target.
        if key := self.params.get("hold_key"):
            scope = self.target
        elif key := self.params.get("cursor_key"):
            cursor = f"Window(home).Property(artwork_cursor_{key})"
            scope = ArtworkIdentity.parse(infolabel(cursor)).scope
        else:
            return
        if not (scope and position) or self.identity_labels:
            return
        if not infolabel(f"Container({scope}).CurrentItem"):
            return
        # The name first: a URL read between the two then never pairs a new count
        # with the position the cursor is on.
        window_property(f"artwork_held_{key}", position)
        unstamped = to_int(
            infolabel("Window(home).Property(artwork_holds_unstamped)"), 0
        )
        window_property("artwork_holds_unstamped", unstamped + 1)

    def _multiart_dict(self, item: str, multiart_type: str | None) -> dict[str, str]:
        """
        The multiart family of an item, led by multiart_first and extended by TMDb's
        cached art of the same type when the URL asks (get_extra_multiart).

        :param item: Infolabel prefix of the item.
        :param multiart_type: Base art type; None for no family.
        :return: The family as "multiart", "multiart1" … keys.
        """
        from resources.lib.art.multiart import build_multiart_dict

        # Cache only: no network wait before the seed; the metadata serve fills it.
        # Served, a stale or missing entry is fetched aside, and its news serves artwork
        # again
        extra = multiart_type and parse_bool(self.params.get("get_extra_multiart"))
        tmdb_item = (
            self._get_tmdb_item(
                append_artwork=True, cache_only=True, target=item, aside=self.again
            )
            if extra
            else None
        )
        # multiart_first: read from the serve's own item, which the skin draws under
        # the register (a favourite's thumb), not from multiart_target's. A skin icon
        # or Kodi's thumb:// pseudo-path is no image the slot draws: none then.
        art = self.params.get("multiart_first")
        first = (
            infolabel(f"{self.target_item}.Art({art})") if art and multiart_type else ""
        )
        return build_multiart_dict(
            target=item,
            multiart_type=multiart_type,
            max_items=self.params.get("multiart_max"),
            tmdb_art=(tmdb_item or {}).get("art", {}),
            first="" if first.startswith(("Default", "thumb://")) else first,
        )

    @log.duration
    def artwork(self) -> list[DirectoryItem] | None:
        """
        Process/calculate artwork and attach to listitem, sizing any clearlogo_fit_ids
        to the cropped logo; an aborted plugin serve (focus or visit moved on) holds the
        last blur and darkens instead.

        :return: Directory items for Kodi, none with no art; None for a stopped serve.
        """
        start = time.perf_counter()
        if self._visit_superseded() or self.dialog and not self._info_on_top():
            return self._artwork_held()
        # A serve with no focus_ids (the primary view) is unguarded on focus moves.
        window_id = self.window_id
        focus = focused_control_id(window_id)
        read = time.perf_counter()

        from resources.lib.art.editor import ImageEditor
        from resources.lib.art.multiart import seed_multiart
        from resources.lib.plugin.opts import art_jobs, read_art_urls

        imported = time.perf_counter()
        guard = self._guard(through_info=True)
        if not guard.alive():
            return self._artwork_held(guard.lost_to)

        # Read here, not passed in the URL: a "|" in the text would end Kodi's options
        cleaned = (
            {
                "clean_label": markdown_label(
                    infolabel(label), self.params.get("clean_label_color")
                )
            }
            if (label := self.params.get("clean_label"))
            else {}
        )
        # The window's own item or the playing song has no position, and a modal
        # dialog over the window would answer for it: no cursor stamp, no neighbours.
        current_position = (
            None
            if self.item or self.player or topmost_window_id() != window_id
            else to_int(infolabel(f"{self.identity_container}.CurrentItem"), None)
        )
        # Songs outside the library share an empty DBID: their file doesn't (not the
        # guard's identity, whose queue position a shuffle moves mid-song)
        played = infolabel("Player.Filenameandpath") if self.player else ""
        dbid = (
            played + infolabel("MusicPlayer.DBID")
            if self.player
            else infolabel(f"{self.identity_item}.DBID")
        )
        # A served settle's cursor is the request's, its visit too; a move's, as a
        # plugin's, is read now with the live visit
        cursor_key = self.params.get("cursor_key", "")
        cursor_snapshot = (
            self.cursors.get(cursor_key)
            or infolabel(f"Window(home).Property(artwork_cursor_{cursor_key})")
            if cursor_key
            else ""
        )
        visit = self.params.get("visit", "")
        if self.superseded:
            visit = (
                ArtworkIdentity.parse(self.cursors[cursor_key]).visit
                if cursor_key in self.cursors
                else infolabel("Window(home).Property(artwork_visit)")
            )
        # Scope of this serve, needed before seeding: the seeder must know
        # whether the register's previous content is same-container.
        if self.item or self.player:
            stamp_scope = self.params["target"]
        elif self.target is not None:
            stamp_scope = str(self.target)
        else:
            # A cleared cursor (back from an info dialog) scopes to the focused view.
            stamp_scope = ArtworkIdentity.parse(cursor_snapshot).scope or str(
                focused_control_id(window_id)
            )
        multiart_type = self.params.get("multiart")
        params = self.params
        alive = guard.alive
        family = {}
        # multiart_target: the family's own item when the focused one only stands
        # for it (a favourite's library item, 9040); identity stays the focused one.
        # Read before the image jobs: a seeded family's first slide is the backdrop,
        # so 9300's blur is 9400's blur of slide 0.
        if source := self.params.get("multiart_target"):
            multiart_item = f"Container({source}).ListItem"
            # The target reading as another item (it hadn't landed, or a modal dialog
            # opened, whose containers Python reads) holds: no seed or clear from it.
            key = self.params.get("multiart_target_key")
            alive = lambda: guard.alive() and (
                key is None or self._item_key(multiart_item) == key
            )
            if not alive():
                return self._artwork_held(guard.lost_to)
            multiart_dict = self._multiart_dict(multiart_item, multiart_type)
            if len(multiart_dict) > 1:  # seed_multiart seeds only then
                family = {"background_url": multiart_dict["multiart"]}
        # Kodi ends a plugin URL's options at its first "|" (art headers), and the
        # parser a value at a raw URL's own "&KEY=": each art URL is read whole by the
        # label the skin names (read_art_urls), headers kept, and a band label cut off
        # after the icon's is the item's own. A dialog on top would answer the reads,
        # so then only a read the URL's value vouches for stands: a hold could outlast
        # the dialog (an info rail's URL rests through it).
        on_top = topmost_window_id() == window_id
        params = params | read_art_urls(params, infolabel, on_top) | family
        if on_top and params.get("icon_source") and "icon_darken_label" not in params:
            params = params | {
                "icon_darken_label": infolabel(
                    "Player.Title" if self.player else f"{self.target_item}.Label"
                )
            }
        # Served, a dialog that opened during the reads answered them: stop as covered,
        # and the service reads the probe again once the window is back on top
        if self.superseded and on_top and topmost_window_id() != window_id:
            return None
        art_opts, jobs = art_jobs(params)
        if not jobs:
            log.debug(f"{self.__class__.__name__} → artwork: no jobs created")
            # A song with no art (a stream): none of the last one stays
            if self.player and alive():
                clear_label(self.params.get("multiart_fadelabel", ""))
                for _, prop in self._bridge_props():
                    window_property(prop)
                self._cover_size({}, played, alive)
            # A dialog item with no art still lands, so the page isn't held back.
            return (
                set_items([{"file": plugin_path("artwork"), "properties": cleaned}])
                if self.item
                else []
            )

        guarded = time.perf_counter()
        image_processor = ImageEditor().image_processor
        # Where the time before the image work goes: each window and focus read waits
        # for Kodi's render lock.
        log.debug(
            f"{self.__class__.__name__} → artwork before images: "
            f"{(read - start) * 1000:.0f}ms window reads, "
            f"{(imported - read) * 1000:.0f}ms imports, "
            f"{(guarded - imported) * 1000:.0f}ms guard and item reads, "
            f"{(time.perf_counter() - guarded) * 1000:.0f}ms editor setup"
        )
        art = image_processor(
            jobs=jobs,
            art_opts=art_opts,
            source=self.target_item,
        )
        if not alive():
            return self._artwork_held(guard.lost_to)

        # Under an info dialog its rails answer for this window's (they share ids): no
        # family, register or window properties from them; its close serves again.
        # The playing song is read from Player infos, which no dialog answers for.
        covered = lambda: not (self.dialog or self.player) and _info_open()
        blind = covered()
        if not source:
            multiart_dict = self._multiart_dict(
                self.target_item, None if blind else multiart_type
            )
        if len(multiart_dict) > 1:  # one image never turns: no family lands
            art |= multiart_dict
        log.debug(f"{self.__class__.__name__} → artwork returned: {', '.join(art)}")
        if not alive():
            return self._artwork_held(guard.lost_to)
        folder = infolabel(f"{self.identity_container}.FolderPath")
        # A serve whose visit ended (A→B→A: the same window) leaves the live visit's
        # register alone; one ending mid-seed holds (the reset may have run)
        hands_off = blind or self._visit_superseded()
        art = seed_multiart(
            fadelabel_id=None if hands_off else self.params.get("multiart_fadelabel"),
            multiart_dict=multiart_dict,
            art=art,
            seed_scope=f"{stamp_scope}@{folder}",
            seed_item=f"{current_position}/{dbid}/{visit}",
            alive=lambda: alive() and not self._visit_superseded(),
            window_id=window_id,
            dialog=self.dialog,
        )
        if art is None:
            return self._artwork_held(guard.lost_to)
        self._cover_size(art, played, alive)

        # Sized before the list lands (no blank). A cancelled job still runs: size only
        # for the URL's item, in its window, still topmost (windows share control ids).
        if (
            (fit := self.params.get("clearlogo_fit"))
            and alive()
            and not self._visit_superseded()
            and topmost_window_id() == window_id
            and (self.item or self.focus_ids or focused_control_id(window_id) == focus)
            and self.params.get("clearlogo_fit_key") in (None, self._item_key())
            and (
                h := fit_height(
                    fit,
                    to_int(art.get("clearlogo_width"), 0),
                    to_int(art.get("clearlogo_height"), 0),
                )
            )
        ):
            for control_id in filter(
                None, self.params.get("clearlogo_fit_ids", "").split(",")
            ):
                reposition_control(int(control_id), h=h)

        # Not once the cursor has moved on (a new focus, a window left): the properties
        # are the next item's or the next window's by now. Nor under an info dialog,
        # whose backstage reads them.
        cursor = f"Window(home).Property(artwork_cursor_{cursor_key})"
        if not covered() and (not cursor_key or infolabel(cursor) == cursor_snapshot):
            for field, prop in self._bridge_props():
                window_property(prop, art.get(field, ""))
            window_property(self._scope_prop, stamp_scope)

        total = to_int(infolabel(f"{self.identity_container}.NumItems"), 0)

        identity = ArtworkIdentity(
            scope=stamp_scope, pos=current_position, dbid=dbid, visit=visit
        )
        prev_item = identity.neighbour(-1, total)
        next_item = identity.neighbour(1, total)

        # Self-certify currency when no skin-side cursor writer fired for
        # this invocation, or the register predates this subject (preview
        # swaps fire no writer): a passed guard is the same proof
        # atr_artwork_cursor encodes. If a writer landed mid-run, it wins.
        stamped = (
            str(identity)
            if cursor_key
            and "visit" in self.params
            and current_position is not None
            and cursor_snapshot != str(identity)
            else ""
        )
        if stamped and alive() and infolabel(cursor) == cursor_snapshot:
            window_property(f"artwork_cursor_{cursor_key}", stamped)
        # The serve's identity, for the skin's currency and scope readers: served, its
        # own (the bind names the arrival in current), or with no position (read under
        # a modal) the settle's cursor; a plugin's, its current
        partial = identity.partial(("scope", "pos", "dbid"))
        if self.superseded:
            current = (
                self.cursors.get(cursor_key) or partial
                if current_position is None
                else str(identity)
            )
        else:
            current = stamped or cursor_snapshot or partial

        return set_items(
            [
                {
                    "file": plugin_path("artwork"),
                    "art": art,
                    "properties": (
                        {
                            "previous": prev_item.partial(("scope", "pos")),
                            "current": current,
                            "identity": current,
                            "next": next_item.partial(("scope", "pos")),
                            "current_pos": str(current_position),
                            "previous_pos": str(prev_item.pos),
                            "next_pos": str(next_item.pos),
                        }
                        if not (self.item or self.player)
                        # The playing song has no position: current tells songs apart,
                        # so a slide serve (9400) is matched to its song's
                        else (
                            {"current": partial, "identity": partial}
                            if self.player
                            else {}
                        )
                    )
                    | cleaned,
                }
            ]
        )

    @log.duration
    def multiart_tiles(self) -> list[DirectoryItem] | None:
        """
        Seed one register per artwork tile of the info dialog's item so the tiles
        take turns on one beat, each starting on its main image unless an earlier
        tile holds it; an image repeats only in a tile with no other image free.

        :return: One item echoing the visit once the registers are seeded.
        """
        from resources.lib.art.multiart import (
            build_multiart_dict,
            order_multiart,
            seed_registers,
            share_out,
            take_turns,
        )

        if not self._require("tiles") or not self._info_on_top():
            return

        visit = self.params.get("visit", "")
        stamp = "Window(home).Property(infoscreen_gallery_visit)"
        alive = lambda: infolabel(stamp) == visit
        families = {
            to_int(register): order_multiart(art.values())
            for register, art_type in (
                tile.split(":") for tile in self.params["tiles"].split(",")
            )
            if (
                art := build_multiart_dict(
                    target="ListItem",
                    multiart_type=art_type,
                    max_items=self.params.get("multiart_max"),
                    tmdb_art={},
                )
            )
        }
        sequences = take_turns(share_out(families))
        if not seed_registers(self._info_window, sequences, alive=alive):
            return
        return set_items(
            [{"file": plugin_path("multiart_tiles"), "properties": {"visit": visit}}]
        )

    @log.duration
    def favourite(self) -> list[DirectoryItem] | None:
        """
        A favourite's library item, whole, for the metadata, progress bar and
        artwork serves to read; it echoes favourite.index and favourite.path (the
        favourite's FileNameAndPath, as Kodi lists it) so the skin knows it.

        :return: The item; none when it names no library item; None if aborted.
        """
        from resources.lib.plugin.favourites import forget, library_key, listed_path

        if not self._require("path"):
            return
        guard = self._guard()
        path = self.params["path"]
        if not guard.alive():
            return
        if not (key := library_key(path)):
            return []  # served, the blank item: the lists after it go on
        dbtype, dbid = key.split(":")
        echo = {
            "favourite.index": self.params.get("index", ""),
            "favourite.path": listed_path(path),
        }
        if dbtype in MUSIC_TYPES:
            extra = () if dbtype == "song" else ("description",)
            if not (found := details_item(dbtype, int(dbid), "favourite", extra)):
                forget(path, dbtype)
                return []
            _, li, _ = found
            li.setProperties(echo)
            items = [(plugin_path("favourite"), li, False)]
        else:
            properties = JSON_PROPERTIES["movieset" if dbtype == "set" else dbtype]
            if not (row := _video_details(dbtype, int(dbid), properties, "favourite")):
                forget(path, dbtype)
                return []
            if dbtype in ("episode", "season"):
                enrich_with_tvshow([row], "favourite")  # the show's studio and rating
            item = json_to_canonical(row, dbtype)
            item["file"] = plugin_path("favourite")  # no thumb loader on the file
            item["properties"] |= echo
            items = set_items([item], media_type=dbtype, tag_applier=apply_videoinfotag)
        return items if guard.alive() else None

    @log.duration
    def metadata(self) -> list[DirectoryItem] | None:
        """
        Fetch/attach cleaned metadata to a helper list item; aborts if focus changes.
        random_pick=true picks one director and genre (genre_aliases renames it);
        tmdb_art=true also caches TMDb's images for artwork's get_extra_multiart.

        :return: List of directory items for Kodi, or None if aborted/failed.
        """
        if self.dialog and not self._info_on_top():
            return
        if self.item and self._info_swapped():
            return
        guard = self._guard()
        if not guard.alive():
            return

        # Read now: during the TMDb wait the probes can follow a rail to another item
        caption = self._probe_text("truncate_label_id")
        title = self._probe_text("truncate_title_id")
        target = self.target_item
        aliases = self.params.get("genre_aliases", "")
        data = DataHandler(
            target=target,
            dbtype=self.dbtype,
            dbid=self.dbid,
        ).fetch_data(
            random_pick=parse_bool(self.params.get("random_pick")),
            genre_aliases=[p.split(":", 1) for p in aliases.split(",") if p],
        )

        if not guard.alive():
            return

        own_plot = data["Plot"]
        enrich_with_tmdb = parse_bool(self.params.get("enrich_with_tmdb", "false"))
        tmdb_art = enrich_with_tmdb and parse_bool(self.params.get("tmdb_art"))
        if enrich_with_tmdb:
            # tmdb_art: the one request also caches the art-bearing entry (a superset)
            # that the artwork serve's get_extra_multiart reads. Served, a stale entry
            # is fetched aside, and its news serves this list again (decision 2A)
            tmdb_item = self._get_tmdb_item(append_artwork=tmdb_art, aside=self.again)
            if tmdb_item:
                trailers = tmdb_item["properties"].pop("tmdb_trailers", "")
                if trailers and parse_bool(self.params.get("random_trailer")):
                    # One pick per item and Kodi session, seeded by its own list
                    rng = random.Random(f"{session_salt()}:{trailers}")
                    tmdb_item["Trailer"] = rng.choice(trailers.split(" | "))
                if parse_bool(self.params.get("tmdb_trailer_only")):
                    tmdb_item = {"Trailer": tmdb_item.get("Trailer")}
                # Library plot, title and tagline keep their language. A library
                # trailer outranks TMDb's pick, unless prefer_tmdb_trailer and it is
                # online (the scraper's): a trailer file always plays first.
                fill_only = ("Plot", "Title", "TagLine", "Trailer")
                if self.dbtype == "season":  # Kodi gives seasons their show's plot
                    fill_only = fill_only[1:]
                online = data["Trailer"].startswith(
                    ("plugin://", "http://", "https://")
                )
                if online and parse_bool(self.params.get("prefer_tmdb_trailer")):
                    fill_only = fill_only[:-1]
                data = merge_metadata(
                    base=data,
                    incoming=tmdb_item,
                    prefer_incoming=True,
                    fill_only=fill_only,
                    ignore_keys=("art", "file"),
                )

        if not guard.alive():
            return

        # truncate_probe=<dbtype>: that type skips the skin's probe (a season's reads
        # its show's plot); =false: every video type does (a favourite's reads its
        # action text). Music keeps it: an album's or artist's caption is its
        # description. A plot only TMDb has skips it too: the probe is empty, or the
        # last serve's plot, another item's if neither has a dbid and their labels match
        skip = self.params.get("truncate_probe", "true")
        self._apply_truncated_label(
            data,
            target=target,
            default_text=data.get("Plot"),
            probe=skip != self.dbtype
            and (skip != "false" or self.dbtype in MUSIC_TYPES)
            and (bool(own_plot) or not data.get("Plot")),
            probed=caption,
        )
        self._apply_truncated_title(data, title)
        if self.params.get("tagline_quotes") == "single" and data["TagLine"]:
            data["properties"]["clean_tagline"] = single_quotes(data["TagLine"])

        return set_items([data], tag_applier=apply_videoinfotag)

    @log.duration
    def progressbar(self) -> list[DirectoryItem] | None:
        """
        Compute resume/unwatched values and expose a helper item for the list.
        If focus changes before or after the bar moves, return the bare item.

        :return: List of directory items for Kodi, or None if aborted/failed.
        """
        if self.dialog and not self._info_on_top():
            return
        guard = self._guard()
        if not guard.alive():
            return

        if not self._require("target_id"):
            return

        target_id = to_int(self.params.get("target_id"), None)
        since = datetime.now() - timedelta(
            days=to_int(self.params.get("album_days"), 14)
        )
        pb = ProgressBarManager(
            target=self.target_item,
            base_id=target_id,
            window_id=self.window_id,
            album_since=f"{since:%Y-%m-%d %H:%M:%S}",
        )
        resume, unwatched = pb.calculate()
        # Seconds, so the item's EndTimeResume works; PercentPlayed (position / total)
        # is unchanged
        secs = pb.runtime(resume)
        position = secs * resume / 100
        item = {
            "file": plugin_path("progress"),
            "Duration": secs,
            "resume": (
                {"position": position, "total": secs}
                if secs
                else {"position": resume, "total": 100}
            ),
            "properties": {"unwatchedepisodes": str(unwatched)},
        }

        if not guard.alive():
            return set_items([item], tag_applier=apply_videoinfotag)

        pb.update(
            percent=resume,
            opts=PlacementOpts.from_params(self.params),
            progress_id=to_int(self.params.get("progress_id"), None),
            btn_id=to_int(self.params.get("btn_id"), None),
            img_id=to_int(self.params.get("img_id"), None),
            img_h=to_int(self.params.get("img_h"), None),
        )
        # The bar is placed first, but it appears only when the item returns, so any
        # item adds at most one library call to that. A superseded serve makes none.
        if guard.alive():
            item["properties"] |= {
                "time_left": (
                    hours_minutes(math.ceil((secs - position) / 60)) if secs else ""
                ),
                **self._show_context(pb.infolabels),
                **self._unwatched_new(pb, resume),
            }
            # An album's resume point; album, for the service's re-serve on song
            # updates (service/monitor.py) and the context menu's Mark items (addon.xml)
            if pb.infolabels["DBType"] == "album":
                state, dbid = pb.album.state, pb.infolabels["DBID"]
                item["properties"] |= {"album": "true", **pb.album.resume}
                window_property("album_played", value=dbid if state == "played" else "")
                window_property(
                    "album_unplayed", value=dbid if state == "unplayed" else ""
                )

        return set_items([item], tag_applier=apply_videoinfotag)

    def _show_context(self, labels: dict[str, str]) -> dict[str, str]:
        """
        An unfinished show's or season's next_episode (as next_up) and next_runtime,
        and a show's new, from one GetEpisodes call; a fully watched show's
        _show_news.

        :param labels: The focused item's infolabels, as ProgressBarManager read them.
        :return: Properties for the progress item; none for other types.
        """
        dbtype = labels["DBType"]
        if dbtype not in ("tvshow", "season"):
            return {}
        labels = labels | get_infolabels(
            self.target_item,
            [
                "Property(WatchedEpisodes)",
                "Property(tvshowid)",
                "Season",
                "TvShowDBID",
            ],
        )
        watched = to_int(labels["Property(WatchedEpisodes)"])
        left = to_int(labels["Property(UnwatchedEpisodes)"])
        if dbtype == "tvshow" and watched and not left:  # fully watched
            return self._show_news(to_int(labels["DBID"]))

        # No library id (a plugin's item): tvshowid 0 would ask for every show. A
        # favourite's season (a helper item) has a DBID but no TvShowDBID, only
        # Property(tvshowid); another add-on's may hold some other id.
        if dbtype == "tvshow":
            show_id = to_int(labels["DBID"])
        else:
            show_id = to_int(
                labels["TvShowDBID"]
                or (labels["DBID"] and labels["Property(tvshowid)"])
            )
        # A show's Season is its season count; "* All seasons" has none
        season = to_int(labels["Season"], None) if dbtype == "season" else None
        # Started or not: an unwatched show's or season's next is its first episode
        if not (show_id and left) or season == 0:
            return {"next_episode": "", "next_runtime": "", "new": ""}  # 0: Specials

        # GetEpisodes rejects season -1 (its schema minimum is 0): omit it for all
        scope = {"tvshowid": show_id} | ({} if season is None else {"season": season})
        unwatched = fetch_raw(
            "VideoLibrary.GetEpisodes",
            "episode",
            [self.filter_unwatched],
            sort=None,
            parent="progressbar",
            params=scope,
            properties=["episode", "firstaired", "runtime", "season"],
        )
        # As next_up's episode sort, which orders non-specials by season then episode
        first = min(
            (ep for ep in unwatched if ep["season"] > 0),
            key=itemgetter("season", "episode"),
            default=None,
        )
        # By air date, specials too, started or not: a back catalogue isn't new
        aired = max((ep["firstaired"] for ep in unwatched), default="")
        new = dbtype == "tvshow" and aired >= self._new_since("firstaired")
        return {
            "next_episode": (
                "{season}x{episode:02d}".format_map(first) if first else ""
            ),
            # JSON-RPC's runtime: seconds, 0 when the library has none. To the nearest
            # minute: a runtime, not time left
            "next_runtime": (
                hours_minutes((first["runtime"] + 30) // 60)
                if first and first["runtime"]
                else ""
            ),
            "new": "true" if new else "",
        }

    def _unwatched_new(self, pb: ProgressBarManager, resume: float) -> dict[str, str]:
        """
        A film's, episode's or album's new: unwatched or never played, and a film or
        album added or an episode aired within new_days (one Get…Details call:
        ListItem.DateAdded and ListItem.Premiered are regional dates).

        :param pb: The focused item's ProgressBarManager.
        :param resume: Progress from ProgressBarManager.calculate: 0 for unwatched.
        :return: The new property; none for other types, or a started or watched item.
        """
        # No library id (a plugin's item): nothing to look up
        if (
            (dbtype := pb.infolabels["DBType"]) not in ("movie", "episode", "album")
            or resume
            or not (dbid := to_int(pb.infolabels["DBID"]))
        ):
            return {}
        # An episode by air date: a show added late, or a binge, isn't new. Empty (not
        # aired, or unknown) sorts first; a future date (a pre-release file) is new
        field = "firstaired" if dbtype == "episode" else "dateadded"
        if dbtype != "album":
            item = _video_details(dbtype, dbid, [field], "progressbar")
        elif pb.album.state == "unplayed":
            response = json_call(
                method="AudioLibrary.GetAlbumDetails",
                params={"albumid": dbid, "properties": [field]},
                parent="progressbar",
            )
            item = response.get("result", {}).get("albumdetails")
        else:
            return {}
        new = item and item[field] >= self._new_since(field)  # None: an error answer
        return {"new": "true" if new else ""}

    def _new_since(self, field: str) -> str:
        """
        The earliest dateadded or firstaired that is still new: new_days (default 30)
        before now, as JSON-RPC writes that field, so string order is time order.

        :param field: "dateadded" ("YYYY-MM-DD HH:MM:SS") or "firstaired" (a date).
        :return: The cutoff in the field's format, local time.
        """
        days = to_int(self.params.get("new_days"), 30)
        fmt = "%Y-%m-%d %H:%M:%S" if field == "dateadded" else "%Y-%m-%d"
        return f"{datetime.now() - timedelta(days=days):{fmt}}"

    def _show_news(self, show_id: int) -> dict[str, str]:
        """
        A fully watched show's news from the TMDb cache, never fetched here: its last
        aired episode if new and not in the library, its next air date in date_format
        (strftime, default "%d %b"; %b is Kodi's short month) and whether it ended.

        :param show_id: Library id of the show, for the episodes the library has.
        :return: new_episode, next_air, next_air_episode, show_status; empty if unknown.
        """
        # No art: the art entry while fresh, else a fresh art-less one, else stale art
        # first (renewed by the metadata serve with TMDb multiart on; off, an older art
        # entry can win until the art-less one is renewed on the next focus)
        tmdb = self._get_tmdb_item(append_artwork=False, cache_only=True)
        props = tmdb["properties"] if tmdb else {}
        news = {
            "new_episode": "",
            "next_air": "",
            "next_air_episode": "",
            "show_status": _SHOW_STATUS.get(props.get("tmdb_status"), ""),
        }
        # Only aired within new_days, as new counts (an ended show's last is old
        # news), and past the library's newest: an episode missing mid-run, or
        # numbered another way (TVDB's order), is no news. Specials left out, as
        # next_episode does. An entry cached before these were kept (7-day TTL) has
        # none; show_id 0 (a plugin's item) would ask every show
        season = to_int(props.get("tmdb_last_air_season"))
        aired = props.get("tmdb_last_air_date", "")
        if show_id and season > 0 and aired >= self._new_since("firstaired"):
            episode = int(props["tmdb_last_air_episode"])
            newest = fetch_raw(  # "episode" sorts by season, then episode
                "VideoLibrary.GetEpisodes",
                "episode",
                [{"field": "season", "operator": "greaterthan", "value": "0"}],
                sort={"method": "episode", "order": "descending"},
                parent="progressbar",
                params={"tvshowid": show_id},
                limit=1,
                properties=["episode", "season"],
            )
            have = next(((ep["season"], ep["episode"]) for ep in newest), (0, 0))
            if (season, episode) > have:
                news["new_episode"] = f"{season}x{episode:02d}"
        iso = props.get("tmdb_next_air_date")
        if not iso or (day := date.fromisoformat(iso)) < date.today():
            return news
        # An entry cached before the numbers were kept (7-day TTL) has the date alone
        episode = props.get("tmdb_next_air_episode")
        # strftime's %b is the C locale's (English): Kodi's own (51-62) follow its
        # language, as its dates' "mmm" does. Joined outside strftime, which on
        # Windows encodes its format with the locale codec
        month = getLocalizedString(50 + day.month)
        fmt = self.params.get("date_format", "%d %b")
        return news | {
            "next_air": month.join(day.strftime(part) for part in fmt.split("%b")),
            "next_air_episode": (
                f"{int(props['tmdb_next_air_season'])}x{int(episode):02d}"
                if episode
                else ""
            ),
        }

    @log.duration
    def clean_name(self) -> list[DirectoryItem] | None:
        """
        A file's readable name by Kodi's clean-up: a film's title and year, or an
        episode's show, 1x07 code and title, as clean_* properties.

        :return: One item echoing the label param, so a skin can match it to its item.
        """
        if not self._require("path"):
            return
        # Kodi passes the plugin URL's values raw: decoding once more would split a
        # web name at its own encoded '?' or '#', so the path is read undecoded
        path = parse_plugin_argv(["", "", self.query], raw={"path"})["path"]
        names = file_clean_name(path)
        return set_items(
            [
                {
                    "file": plugin_path("clean_name"),
                    "label": self.params.get("label", ""),
                    "properties": {f"clean_{k}": v for k, v in names.items()},
                }
            ]
        )

    @log.duration
    def epg_time_left(self) -> list[DirectoryItem] | None:
        """
        A TV guide programme's time left to its end, as time_left: Kodi has it only for
        the playing one. Works from the URL alone, so a move mid-call changes nothing.

        :return: One item labelled with the programme's path, or None after its end.
        """
        if not self._require("programme", "runtime"):
            return
        # A guide item's path ends in its start in UTC (pvr://guide/0012/2026-11-16
        # 20:00:00.epg): with the runtime, its end, and no regional time to parse
        programme = self.params["programme"]
        start = datetime.fromisoformat(
            programme.rpartition("/")[2].removesuffix(".epg")
        )
        end = start.replace(tzinfo=timezone.utc) + timedelta(
            seconds=to_int(self.params["runtime"])
        )
        left = math.ceil((end - datetime.now(timezone.utc)).total_seconds() / 60)
        # On air follows a timeshifted channel's playback, which can run past the end
        if left < 1:
            return
        return set_items(
            [
                {
                    "file": plugin_path("epg_time_left"),
                    "label": programme,
                    "properties": {
                        "time_left": hours_minutes(left),
                        "visit": self.params.get("visit", ""),
                    },
                }
            ]
        )

    @log.duration
    def reposition(self) -> list[DirectoryItem] | None:
        """
        Set geometry on a control from optional x/y/w/h params. ``fit=W,H`` with
        ``src=w,h`` derives h as the aspect-keep height of src in the fit box.

        :return: One item echoing src_w/src_h once the controls are set.
        """
        if not self._require("target_id"):
            return

        target_ids = [to_int(v, None) for v in self.params["target_id"].split(",")]
        h = to_int(self.params.get("h"), None)
        src_w, _, src_h = self.params.get("src", "").partition(",")
        if fit := self.params.get("fit"):
            if (h := fit_height(fit, to_int(src_w, 0), to_int(src_h, 0))) is None:
                log.warning("reposition → fit requires src=w,h")
                return
        for target_id in target_ids:
            reposition_control(
                target_id,
                x=to_int(self.params.get("x"), None),
                y=to_int(self.params.get("y"), None),
                w=to_int(self.params.get("w"), None),
                h=h,
            )
        return set_items(
            [
                {
                    "file": plugin_path("reposition"),
                    "properties": {"src_w": src_w, "src_h": src_h},
                }
            ]
        )

    @log.duration
    def text(self) -> list | None:
        """
        Rasterise a string to a cached white PNG mask and return its path; with
        target_id, first set that control's height to the text's, in the serve's
        window as it started (a modal on top since doesn't take the resize).

        :return: Single ListItem carrying Art(text), none if empty, None if aborted.
        """
        from resources.lib.art.text import TextRenderer

        if self.dialog and not self._info_on_top():
            return
        guard = self._guard()
        if not guard.alive():
            return

        box_width = to_int(self.params.get("text_width"), 1280)
        result = TextRenderer().render(
            text=self.params.get("text", ""),
            font_path=self.params.get("text_font", ""),
            font_size=to_int(self.params.get("text_size"), 42),
            box_width=box_width,
            max_height=to_int(self.params.get("text_height"), 720),
            line_height=to_float(self.params.get("text_line_height"), 1.3),
            letter_spacing=to_float(self.params.get("text_letter_spacing"), 0.0),
        )
        if not guard.alive():
            return
        if not result:  # nothing to draw: the blank item, which a served list binds
            return []

        path, height = result
        if target_id := to_int(self.params.get("target_id"), None):
            window = Window(guard.window_id)  # keep: holds the control's native ref
            try:
                window.getControl(target_id).setHeight(height)
            except RuntimeError:  # the window was replaced (a rail opened another item)
                log.debug(f"text: control {target_id} gone from {guard.window_id}")
                return
        return set_items(
            [
                {
                    "file": plugin_path("text"),
                    "art": {"text": path},
                    "properties": {"text_height": str(height)},
                }
            ]
        )

    @log.duration
    def typewriter(self) -> list[DirectoryItem] | None:
        """
        Type the current item's label, guarded against focus changes; served, on a thread
        of its own. A reset=true call supersedes any run and hides the control. With no
        label, a file param captions by its name (an add-on's screenshots).
        """
        if not self._require("target_id"):
            return []

        target_id = to_int(self.params.get("target_id"), None)
        if parse_bool(self.params.get("reset", "false")):
            TypewriterAnimation.reset(target_id=target_id)
            window_property("typewriter_container")
            window_property("typewriter_pos")
            return []
        if not (label := self.label or file_label(self.params.get("file", ""))):
            log.warning("typewriter → label or file required")
            return []

        if self._visit_superseded():
            return None

        guard = self._guard()
        if not guard.alive():
            return None

        window_property(
            "typewriter_container",
            value=str(self.identity_id) if self.identity_id is not None else "",
        )
        window_property("typewriter_pos", value=self.expected_identity)
        t = TypewriterAnimation(control_id=target_id, window_id=self.window_id)
        run = partial(
            t.update,
            label=label,
            opts=PlacementOpts.from_params(self.params),
            max_lines=to_int(self.params.get("max_lines"), None),
            start_delay=to_float(self.params.get("start_delay"), 0),
            alive=guard.alive,
        )
        if self.superseded:  # served: the pipeline binds 9020 and goes on
            # The lease is taken now, so the service's next look finds this line's own
            run = partial(run, token=t.claim())
            Thread(target=self._type, args=(run, label), daemon=True).start()
        else:  # a plugin call's directory ends with the line
            run()
        return []

    def _type(self, run: Callable[[], None], label: str) -> None:
        """
        A served line, on its own thread: the lease and its arrival's end stop it.

        :param run: The animation, bound to its label, placement and guard.
        :param label: The text typed, for the log.
        """
        try:
            run()
        except Exception:  # its own thread: nothing above it would log
            log.exception(f"{self.__class__.__name__} → typewriter '{label}'")

    @log.duration
    def in_progress(self) -> list[DirectoryItem] | None:
        """
        Build a container of in-progress movies and episodes.

        :return: List of directory items for Kodi, or None if aborted/failed.
        """
        from concurrent.futures import ThreadPoolExecutor

        set_plugincontent(
            content="videos",
            category=ADDON.getLocalizedString(32601),
            sort_method=SORT_METHOD_LASTPLAYED,
        )
        filters = [self.filter_inprogress]
        jobs = []
        if self.dbtype != "tvshow":
            jobs.append(
                lambda: fetch_and_add(
                    method="VideoLibrary.GetMovies",
                    media_type="movie",
                    filters=filters,
                    sort=self.sort_lastplayed,
                    limit=self.limit,
                    parent="in_progress",
                    tag_applier=apply_videoinfotag,
                    properties=trim_properties("movie", HEAVY_FIELDS),
                )
            )

        if self.dbtype != "movie":
            jobs.append(
                lambda: fetch_and_add(
                    method="VideoLibrary.GetEpisodes",
                    media_type="episode",
                    filters=filters,
                    sort=self.sort_lastplayed,
                    limit=self.limit,
                    parent="in_progress",
                    tag_applier=apply_videoinfotag,
                    postprocess=lambda eps: enrich_with_tvshow(
                        eps, parent="in_progress"
                    ),
                    properties=trim_properties("episode", HEAVY_FIELDS),
                )
            )

        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = [pool.submit(job) for job in jobs]
            results = [item for f in futures for item in f.result()]

        return results or None

    @log.duration
    def next_up(self) -> list[DirectoryItem] | None:
        """
        Build a container of "next up" TV episodes — the lowest unwatched
        non-special episode for each in-progress show.

        :return: List of directory items for Kodi, or None if aborted/failed.
        """
        set_plugincontent(
            content="episodes",
            category=ADDON.getLocalizedString(32600),
            sort_method=SORT_METHOD_LASTPLAYED,
        )
        # 1: In-progress shows, ordered by lastplayed desc: the first `limit`, then
        # the rest in one uncapped round only if specials-only shows (no card)
        # left the first page short. Omitting "end" returns all (List.Amount -1),
        # and a start at the end returns every show again, so seen ones are dropped.
        page = self.limit
        rounds = [{"start": 0, "end": page}, {"start": page}] if page else [None]
        ordered_episodes, seen = [], set()
        for limits in rounds:
            fetched = fetch_raw(
                "VideoLibrary.GetTVShows",
                "tvshow",
                [self.filter_inprogress],
                sort=self.sort_lastplayed,
                parent="next_up",
                params=limits and {"limits": limits},
                properties=[
                    "title",
                    "studio",
                    "mpaa",
                    "lastplayed",
                    "episode",
                    "watchedepisodes",
                    "art",
                ],
            )
            if shows := [s for s in fetched if s["tvshowid"] not in seen]:
                ordered_episodes += self._next_up_cards(shows)
                seen.update(s["tvshowid"] for s in shows)
            if not page or len(fetched) < page or len(ordered_episodes) >= page:
                break

        if not ordered_episodes:
            log.debug(f"{self.__class__.__name__} → next_up: No next up episodes.")
            return None

        return build_items(
            ordered_episodes[:page], "episode", tag_applier=apply_videoinfotag
        )

    def _next_up_cards(self, shows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Lowest unwatched non-special episode per show, in the shows' order.

        :param shows: In-progress shows from VideoLibrary.GetTVShows.
        :return: Episode dicts carrying show-level studio, mpaa and art.
        """
        pending_ids = {s["tvshowid"] for s in shows}

        # 2: Unwatched non-special episodes for the pending shows only,
        # episode-level properties (no art, no streamdetails). Single MySQL
        # round-trip; Python picks the first per pending show below.
        bulk_episodes = fetch_raw(
            "VideoLibrary.GetEpisodes",
            "episode",
            [
                self.filter_unwatched,
                self.filter_no_specials,
                title_filter((s["title"] for s in shows), field="tvshow"),
            ],
            sort={"order": "ascending", "method": "episode"},
            parent="next_up",
            properties=trim_properties("episode", HEAVY_FIELDS | {"art"}),
        )

        # 3: First episode per pending show. Bulk result is sorted ascending
        # by episode, so the first hit per tvshowid wins.
        first_per_show = {}
        for ep in bulk_episodes:
            sid = ep.get("tvshowid")
            if sid in pending_ids and sid not in first_per_show:
                first_per_show[sid] = ep

        # Assemble in pending_shows order to preserve lastplayed desc.
        # Attach show-level studio/mpaa to each episode.
        cards = []
        for s in shows:
            ep = first_per_show.get(s["tvshowid"])
            if ep is None:
                # In-progress show with only unwatched specials; bulk query
                # excludes specials, so nothing to surface for this show.
                continue
            ep["studio"] = s.get("studio", [])
            ep["mpaa"] = s.get("mpaa", "")
            ep["art"] = {f"tvshow.{k}": v for k, v in s.get("art", {}).items()}
            cards.append(ep)
        return cards

    def seasons(self) -> list[DirectoryItem] | None:
        """
        The seasons of the show listed at ``path`` (a library titles path) for the
        season tabs: All first, where Kodi shows it, and Specials last. The listed
        season carries property current; a flattened listing gets none.

        :return: One item per season, or None for a path that is no show's.
        """
        found = _TITLES_PATH.match(self.params.get("path", ""))
        if not found or found[2] == "-2":  # flattened: the show has no season folders
            return None
        show, listed = found.groups()
        rows = (
            json_call(
                "VideoLibrary.GetSeasons",
                properties=["season"],
                params={"tvshowid": int(show)},
                parent="seasons",
            )
            .get("result", {})
            .get("seasons", [])
        )
        # Specials sort after the rest; All is added below as Kodi does
        seasons = [
            (row["season"], row["label"])
            for row in sorted(rows, key=lambda r: (r["season"] == 0, r["season"]))
        ]
        # Kodi's own All item: its setting, and more than one item (AddQueuingFolder);
        # its count also takes linked movies, which GetSeasons leaves out
        if listed == "-1" or (
            len(seasons) > 1 and condition("System.GetBool(videolibrary.showallitems)")
        ):
            seasons.insert(0, (-1, getLocalizedString(20366).lstrip("* ")))
        return set_items(
            {
                # as Kodi's own season paths, so Back finds the season in its list
                "file": f"{_TITLES}{show}/{season}/?tvshowid={show}",
                "label": label,
                "properties": {"current": "true" if str(season) == listed else ""},
            }
            for season, label in seasons
        )

    @log.duration
    def random_movies(self) -> list[DirectoryItem] | None:
        """
        Build a seed-stable randomised container of movies.
        exclude_played_days=N leaves out movies played in the last N days.
        """
        days = to_int(self.params.get("exclude_played_days"))
        played = {
            "field": "lastplayed",
            "operator": "notinthelast",
            "value": f"{days} days",
        }
        return self._random_video(
            method="VideoLibrary.GetMovies",
            media_type="movie",
            content="movies",
            category=ADDON.getLocalizedString(32605),
            parent="random_movies",
            filters=[played] if days else [],
        )

    @log.duration
    def random_tvshows(self) -> list[DirectoryItem] | None:
        """Build a seed-stable randomised container of TV shows."""
        return self._random_video(
            method="VideoLibrary.GetTVShows",
            media_type="tvshow",
            content="tvshows",
            category=ADDON.getLocalizedString(32606),
            parent="random_tvshows",
            filters=[],
        )

    @log.duration
    def random_albums(self) -> list[DirectoryItem] | None:
        """Build a seed-stable randomised container of library albums."""
        return self._random_music(
            "album", [], ADDON.getLocalizedString(32610), "random_albums"
        )

    @log.duration
    def rediscover(self) -> list[DirectoryItem] | None:
        """
        Build a seed-stable randomised container of songs not played in 90 days
        that you played five times or more, or liked (Skin.String(like_threshold)).
        """
        missed = [{"field": "playcount", "operator": "greaterthan", "value": "4"}]
        if (threshold := to_int(infolabel("Skin.String(like_threshold)"))) > 0:
            missed.append(
                {
                    "field": "userrating",
                    "operator": "between",
                    "value": [str(threshold), "10"],
                }
            )
        stale = {"field": "lastplayed", "operator": "notinthelast", "value": "90"}
        return self._random_music(
            "song",
            [stale, {"or": missed}],
            ADDON.getLocalizedString(32836),
            "rediscover",
        )

    @log.duration
    def daily_mixes(self) -> list[DirectoryItem] | None:
        """
        A card per genre bucket you played most lately (shared.mix.leading_cards), its
        mix drawn once a day and kept (kept_mix), similar artists from the cache alone;
        the skin's click plays it (start_mix type=daily).
        """
        set_plugincontent(category=ADDON.getLocalizedString(32837))
        # the album artists, read once and only if a card is drawn
        owned = cache(partial(artist_names, "daily_mixes", album_artists=True))
        ids = genre_ids()
        with cache_only():
            drawn = (
                (key, kept_mix(key, seeds, owned))
                for key, seeds in leading_cards(played_songs())
            )
            # A card whose genres a clean removed has none to open: the next one
            # takes its place, drawn only when needed
            live = ((key, mix) for key, mix in drawn if ids.keys() & mix["genres"])
            mixes = [*islice(live, self.limit)]
        return mix_cards(mixes, ids) if mixes else None  # none until there are plays

    @log.duration
    def random_genre(self) -> list[DirectoryItem] | None:
        """
        Build a seed-stable randomised container from one genre of type=: the
        slot=-th, in seeded order, of the genres holding min_items= or more.
        Items carry the genre and seed as ListItem.Property(genre_pick/genre_seed).
        """
        video = self.dbtype in ("movie", "tvshow")
        if not (
            self._require("type") and (video or self.dbtype in ("album", "artist"))
        ):
            return
        least = to_int(self.params.get("min_items"), 10)
        slot = to_int(self.params.get("slot"), 0)
        method = f"VideoLibrary.Get{_VIDEO_METHODS[self.dbtype]}s" if video else ""
        # One read sizes every genre, from the tables Kodi's genre rule reads: video
        # genre links, and the genres of a music item's songs (songgenres)
        if video:
            rows = fetch_raw(
                method, self.dbtype, [], None, "random_genre", properties=["genre"]
            )
            sizes = Counter(genre for row in rows for genre in row["genre"])
        else:
            rows = library_rows(
                self.dbtype, None, None, None, "random_genre", ["songgenres"]
            )
            listed = json_call("AudioLibrary.GetGenres", parent="random_genre")
            labels = {
                row["genreid"]: row["label"]
                for row in listed.get("result", {}).get("genres", [])
            }  # songgenres titles swap commas for hyphens: the rule needs the label
            sizes = Counter(
                labels[genre["genreid"]] for row in rows for genre in row["songgenres"]
            )
        genres = seeded_sort(
            (genre for genre, size in sizes.items() if size >= least),
            self.randomise,
            self.dbtype,
        )
        if not genres:
            return
        genre = genres[slot % len(genres)]  # fewer genres than slots: wrap round
        rule = [{"field": "genre", "operator": "is", "value": genre}]
        items = (
            self._random_video(
                method=method,
                media_type=self.dbtype,
                content=f"{self.dbtype}s",
                category=genre,
                parent="random_genre",
                filters=rule,
            )
            if video
            else self._random_music(self.dbtype, rule, genre, "random_genre")
        )
        for _, li, _ in items or ():
            li.setProperties({"genre_pick": genre, "genre_seed": self.randomise})
        return items

    def _random_music(
        self, media_type: str, filters: list[dict[str, Any]], category: str, parent: str
    ) -> list[DirectoryItem] | None:
        """Seed-stable random container of library albums, artists or songs."""
        set_plugincontent(content=f"{media_type}s", category=category)
        rows = random_rows(
            lambda filters, properties: library_rows(
                media_type,
                {"and": filters} if filters else None,  # "and" needs 1+ rules
                None,
                None,
                parent,
                properties,
            ),
            filters,
            (f"{media_type}id", _MUSIC_NAMES[media_type]),
            self.randomise,
            self.limit,
        )
        return [library_item(row, media_type) for row in rows] or None

    def _random_video(
        self,
        *,
        method: str,
        media_type: str,
        content: str,
        category: str,
        parent: str,
        filters: list[dict[str, Any]],
    ) -> list[DirectoryItem] | None:
        """
        Seed-stable random container in two queries: an id+label pool fetch,
        then one title-filtered details fetch for the seeded slice.
        """
        set_plugincontent(content=content, category=category)
        rows = random_rows(
            partial(fetch_raw, method, media_type, sort=None, parent=parent),
            filters,
            (f"{media_type}id", "title"),
            self.randomise,
            self.limit,
            properties=trim_properties(media_type, HEAVY_FIELDS),
        )
        return build_items(rows, media_type, tag_applier=apply_videoinfotag) or None

    @log.duration
    def speed_dial(self) -> list[DirectoryItem] | None:
        """
        Pinned music entries in pin order, then the sources played most recently.
        Skins add &v=$INFO[Window(home).Property(speed_dial_version)] to refetch.

        :return: List of directory items for Kodi, or None if empty.
        """
        from concurrent.futures import ThreadPoolExecutor

        set_plugincontent(category=ADDON.getLocalizedString(32826))
        with ThreadPoolExecutor(max_workers=8) as pool:
            items = pool.map(lambda pair: dial_item(*pair), SpeedDial().items())
        return [item for item in items if item][: self.limit] or None

    @log.duration
    def broadcasts(self) -> list[DirectoryItem] | None:
        """
        Build a container of PVR channel ``channelid``'s programmes from the one on
        air, for the live channel list's guide: Kodi's own lists the playing one's.

        :return: List of directory items for Kodi, or None if none.
        """
        if not self._require("channelid"):
            return
        if (channelid := to_int(self.params["channelid"], None)) is None:
            return
        params = {"channelid": channelid}
        broadcasts = (
            json_call(
                "PVR.GetBroadcasts",
                properties=BROADCAST_FIELDS,
                params=params,
                parent="broadcasts",
            )
            .get("result", {})
            .get("broadcasts")
        )
        if not broadcasts:
            return
        logo = (
            json_call(
                "PVR.GetChannelDetails",
                properties=["thumbnail"],
                params=params,
                parent="broadcasts",
            )
            .get("result", {})
            .get("channeldetails", {})
            .get("thumbnail", "")
        )
        items = broadcast_items(
            broadcasts, params["channelid"], logo, datetime.now(timezone.utc)
        )
        return set_items(items[: self.limit]) or None

    @log.duration
    def cast(self) -> list[DirectoryItem] | None:
        """
        Build a container of library video ``self.dbid``'s (type=) cast in Kodi's
        billing order: the name as label, the role as label2, the actor's thumb.

        :return: List of directory items for Kodi, or None if empty.
        """
        if not (self._require("type", "id") and (dbid := to_int(self.dbid))):
            return
        details = json_call(
            f"VideoLibrary.Get{_VIDEO_METHODS[self.dbtype]}Details",
            properties=["cast"],
            params={f"{self.dbtype}id": dbid},
            parent="cast",
        )
        item = details.get("result", {}).get(f"{self.dbtype}details", {})
        set_plugincontent(content="actors")
        actors = [
            {
                "file": plugin_path("cast"),
                "label": actor["name"],
                "label2": actor["role"],
                "art": {
                    "icon": "DefaultActor.png",
                    "thumb": actor.get("thumbnail", ""),
                },
            }
            for actor in item.get("cast", [])[: self.limit]
        ]
        return set_items(actors) or None

    @role_endpoint(
        field="actor",
        category_id=32603,
        sources=[
            ("VideoLibrary.GetMovies", "movie"),
            ("VideoLibrary.GetTVShows", "tvshow"),
        ],
        parent="actor_credits",
    )
    def actor_credits(self) -> list[DirectoryItem] | None:
        """
        Build a container of movies and TV shows featuring ``self.label``.
        """
        pass

    @role_endpoint(
        field="artist",
        category_id=32609,
        sources=[("VideoLibrary.GetMusicVideos", "musicvideo")],
        parent="artist_credits",
    )
    def artist_credits(self) -> list[DirectoryItem] | None:
        """
        Build a container of music videos by artist ``self.label``.
        """
        pass

    @role_endpoint(
        field="director",
        category_id=32602,
        sources=[
            ("VideoLibrary.GetMovies", "movie"),
            ("VideoLibrary.GetMusicVideos", "musicvideo"),
        ],
        parent="director_credits",
    )
    def director_credits(self) -> list[DirectoryItem] | None:
        """
        Build a container of movies and music videos directed by ``self.label``.
        """
        pass

    @role_endpoint(
        field="genre",
        category_id=32607,
        sources=[
            ("VideoLibrary.GetMovies", "movie"),
            ("VideoLibrary.GetTVShows", "tvshow"),
        ],
        parent="genre_credits",
    )
    def genre_credits(self) -> list[DirectoryItem] | None:
        """
        Build a container of movies and TV shows in genre ``self.label``.
        """
        pass

    @log.duration
    def genre_music(self) -> list[DirectoryItem] | None:
        """
        Build a container of library artists, albums or songs (type=) in any of the
        genres in ``self.label`` (" / " joined) or, with id=, of that artist's albums;
        random order fixed by randomise=; exclude_value leaves one out by name.

        :return: List of directory items for Kodi, or None if empty.
        """
        if not (self._require("type") and self.dbtype in MUSIC_TYPES):
            return
        genres = {*self.label.split(" / ")}  # a list value matches any of them
        if dbid := to_int(self.dbid):  # a scraped artist genre may tag no library song
            albums = library_rows(
                "album",
                {"artistid": dbid},
                None,
                None,
                "genre_music",
                ["genre"],
            )
            genres.update(*(row["genre"] for row in albums))
        return self._random_music(
            self.dbtype,
            [
                {"field": "genre", "operator": "is", "value": sorted(genres)},
                {
                    "field": _MUSIC_NAMES[self.dbtype],
                    "operator": "isnot",
                    "value": self.exclude_value,
                },
            ],
            self.label,
            "genre_music",
        )

    @log.duration
    def similar_music(self) -> list[DirectoryItem] | None:
        """
        Build a container of library artists, albums or songs (type=) like artist id=
        (an album's or song's with seed=): its similar artists', topped up as
        genre_music; genre_music alone with no id, similar artist or source.

        :return: List of directory items for Kodi, or None if empty.
        """
        if not (self._require("type") and self.dbtype in MUSIC_TYPES):
            return
        seed = self.params.get("seed", "artist")
        if (dbid := to_int(self.dbid)) and seed != "artist":
            details = (
                json_call(
                    DETAILS[seed],
                    properties=(
                        ["artistid", "compilation"] if seed == "album" else ["artistid"]
                    ),
                    params={f"{seed}id": dbid},
                    parent="similar_music",
                )
                .get("result", {})
                .get(f"{seed}details")
            )
            # gone from the library, or a compilation (its first artist is Various
            # Artists): genres only
            if not details or details.get("compilation"):
                self.dbid = ""
            else:
                self.dbid = str(details["artistid"][0])
        if not (
            (dbid := to_int(self.dbid))
            and (similar := similar_artists(dbid, "similar_music"))
        ):
            return self.genre_music()
        if self.dbtype == "artist":  # closest first
            set_plugincontent(content="artists", category=self.label)
            place = {fold(name): n for n, name in enumerate(similar)}
            rule = {"field": "artist", "operator": "is", "value": similar}
            rows = library_rows("artist", rule, None, None, "similar_music")
            # "is" is a LIKE: a name's "_" or "%" may match another artist too
            rows.sort(key=lambda row: place.get(fold(row["artist"]), len(place)))
            items = [library_item(row, "artist") for row in rows[: self.limit]]
        else:
            by = "albumartist" if self.dbtype == "album" else "artist"  # not features
            rules = [
                {"field": by, "operator": "is", "value": similar},
                {
                    "field": _MUSIC_NAMES[self.dbtype],
                    "operator": "isnot",
                    "value": self.exclude_value,
                },
            ]
            items = (
                self._random_music(self.dbtype, rules, self.label, "similar_music")
                or []
            )
        if self.limit is None or len(items) < self.limit:
            shown = {path for path, *_ in items}
            items += [item for item in self.genre_music() or [] if item[0] not in shown]
        return items[: self.limit] or None

    @staticmethod
    def _artist_songs(artistid: int, properties: list[str], parent: str) -> list[dict]:
        """
        A library artist's songs, for ranking.

        :param artistid: Library artist id.
        :param properties: Song properties to fetch.
        :param parent: Caller name for logging.
        :return: Song rows, possibly empty.
        """
        return library_rows(
            "song", {"artistid": artistid}, None, None, parent, properties
        )

    @staticmethod
    def _deezer_tracks(
        name: str, mbid: str, songs: Callable[[], list[dict]]
    ) -> list[list[str]]:
        """
        A library artist's Deezer top tracks, matched against its songs.

        :param name: Artist name.
        :param mbid: Artist MBID; empty when untagged.
        :param songs: Gives its songs, called only when a match is checked.
        :return: ["", title, album title] rows, possibly empty.
        """
        from resources.lib.apis import deezer

        key = deezer.artist_key(mbid, name)
        return deezer.top_tracks(key, name, lambda *args: deezer_match(songs(), *args))

    def _popularity(
        self, artistid: int, properties: list[str], parent: str
    ) -> tuple[list[tuple[float, list]], list[dict]]:
        """
        A library artist's popularity rankings from the sources that are on, and its
        songs, for Top songs and Discography alike; ([], []) when none can rank.

        :param artistid: Library artist id.
        :param properties: Song properties to fetch.
        :param parent: Caller name for logging.
        :return: ((weight, rows) pairs, song rows).
        """
        from resources.lib.apis import deezer, listenbrainz

        if not (identity := artist_identity(artistid, parent)):
            return [], []
        name, mbid = identity
        on_deezer = deezer.enabled()
        listens = partial(listenbrainz.top_recordings, mbid)
        if not (mbid and listenbrainz.enabled()):
            listens = list
        # Deezer first when on (ListenBrainz may queue); else ListenBrainz before the
        # songs, so an artist it doesn't know costs no song read
        recordings = None if on_deezer else listens()
        if not (
            (on_deezer or recordings)
            and (songs := self._artist_songs(artistid, properties, parent))
        ):
            return [], []
        tracks = self._deezer_tracks(name, mbid, lambda: songs) if on_deezer else []
        if recordings is None:
            recordings = listens()
        # ListenBrainz first in the ranking, so an MBID match claims its title
        rankings = [(WEIGHTS["listenbrainz"], recordings), (WEIGHTS["deezer"], tracks)]
        return rankings, songs

    @log.duration
    def top_songs(self) -> list[DirectoryItem] | None:
        """
        Build a container of artist ``self.dbid``'s songs most popular on ListenBrainz
        (all-time) and Deezer (now), blended, topped up with its most played; empty
        with both off.

        :return: List of directory items for Kodi, or None if empty.
        """
        from resources.lib.apis import deezer, listenbrainz

        if not (
            (deezer.enabled() or listenbrainz.enabled())
            and self._require("id")
            and (artistid := to_int(self.dbid))
        ):
            return
        rankings, songs = self._popularity(artistid, SONG_RANK_PROPERTIES, "top_songs")
        if not songs:
            return
        set_plugincontent(content="songs")
        rows = rank_songs(rankings, songs)[: self.limit]
        return [library_item(row, "song") for row in rows] or None

    @log.duration
    def discography(self) -> list[DirectoryItem] | None:
        """
        Build a container of artist ``self.dbid``'s library albums, most popular on
        ListenBrainz and Deezer first (blended), the rest newest first; all newest
        first with both off.

        :return: List of directory items for Kodi, or None if empty.
        """
        from resources.lib.apis import deezer, listenbrainz

        if not (self._require("id") and (artistid := to_int(self.dbid))):
            return
        albums = self._artist_albums(artistid, "discography")
        rankings, songs = [], []
        if albums and (deezer.enabled() or listenbrainz.enabled()):
            # Top songs' own lists and order, so the two rails agree
            rankings, songs = self._popularity(
                artistid, ALBUM_SONG_PROPERTIES, "discography"
            )
        set_plugincontent(content="albums")
        rows = rank_albums(rankings, songs, albums)[: self.limit]
        return [library_item(row, "album") for row in rows] or None

    @staticmethod
    def _artist_albums(artistid: int, parent: str) -> list[dict]:
        """
        A library artist's albums as its folder shows them: albums it only features on
        need Kodi's "Show song and album artists" (the artistid filter takes song
        artists too).

        :param artistid: Library artist id.
        :param parent: Caller name for logging.
        :return: Album rows with ALBUM_RANK_PROPERTIES, possibly empty.
        """
        albums = library_rows(
            "album", {"artistid": artistid}, None, None, parent, ALBUM_RANK_PROPERTIES
        )
        if condition("System.GetBool(musiclibrary.showcompilationartists)"):
            return albums
        return [album for album in albums if artistid in album["artistid"]]

    @log.duration
    def popularity_label(self) -> list[DirectoryItem]:
        """
        One item labelled with how popular library artist, album or song ``self.dbid``
        is, never a number: with Deezer on "Charting" or "Popular", "#2 song" or "Most
        popular album"; with it off, by your plays ("Your #3 artist", "Your #2 song").

        :return: List of one directory item, or none with no label.
        """
        from resources.lib.apis import deezer

        if not (
            self.dbtype in MUSIC_TYPES
            and self._require("id")
            and (dbid := to_int(self.dbid))
        ):
            return []
        if online := deezer.enabled():
            words = {
                "album": self._album_word,
                "artist": self._artist_word,
                "song": self._song_word,
            }
        else:
            words = {
                "album": self._played_album,
                "artist": self._played_artist,
                "song": self._played_song,
            }
        word = words[self.dbtype]
        if online and self.again:  # served: from the cache, the network asked aside
            with cache_only():
                label = word(dbid)
            Thread(
                target=self._word_aside, args=(word, dbid, label), daemon=True
            ).start()
        else:
            label = word(dbid)
        if not label:
            return []
        # Whose word: a skin shows it only on that item, not the last one's
        whose = {"dbid": self.dbid, "dbtype": self.dbtype}
        item = {"file": plugin_path(_LABEL), "label": label, "properties": whose}
        return set_items([item])

    def _word_aside(self, word: Callable[[int], str], dbid: int, served: str) -> None:
        """
        A served popularity word, asked again online on its own thread (Deezer and
        ListenBrainz never hold the pipeline): a new one serves the list again.

        :param word: The item type's word function.
        :param dbid: Library id.
        :param served: The word the cache answered.
        """
        try:
            if self.again.current() and word(dbid) != served:
                self.again()
        except Exception:  # its own thread: nothing above it would log
            log.exception(f"{self.__class__.__name__} → popularity_label aside {dbid}")

    @staticmethod
    def _played_artist(artistid: int) -> str:
        """
        With Deezer off, "Your #3 artist": its place by the library's plays, within
        PLACES.

        :param artistid: Library artist id.
        :return: The word, or "" for none.
        """
        if artistid not in (places := artist_places(_LABEL)):
            return ""
        return ADDON.getLocalizedString(32999) % (places.index(artistid) + 1)

    def _played_album(self, albumid: int) -> str:
        """
        With Deezer off, "Your most played album" for the album that leads its first
        artist's albums by their songs' summed plays, clearly (play_place); none for a
        compilation (Various Artists).

        :param albumid: Library album id.
        :return: The word, or "" for none.
        """
        album = self._music_details("album", albumid, ["artistid", "compilation"])
        if not album or album["compilation"]:
            return ""
        artistid = album["artistid"][0]
        albums = self._artist_albums(artistid, _LABEL)
        plays = Counter(dict.fromkeys(map(itemgetter("albumid"), albums), 0))
        for song in self._artist_songs(artistid, ["albumid", "playcount"], _LABEL):
            if song["albumid"] in plays:  # not a song it features on outside them
                plays[song["albumid"]] += song["playcount"]
        if play_place(plays, albumid) != 1:
            return ""
        return ADDON.getLocalizedString(32994)

    def _played_song(self, songid: int) -> str:
        """
        With Deezer off, "Your #2 song": its title's place among its first artist's
        song titles by plays, within PLACES and clear (song_play_place).

        :param songid: Library song id.
        :return: The word, or "" for none.
        """
        if not (song := self._music_details("song", songid, ["artistid", "title"])):
            return ""
        songs = self._artist_songs(song["artistid"][0], ["playcount", "title"], _LABEL)
        place = song_play_place(songs, song["title"])
        return ADDON.getLocalizedString(32993) % place if place else ""

    def _artist_word(self, artistid: int) -> str:
        """
        "Charting" for an artist in Deezer's artist chart today, else "Popular" with
        POPULAR Deezer fans or more; nothing below, so no artist reads as unpopular.

        :param artistid: Library artist id.
        :return: The word, or "" for none.
        """
        from resources.lib.apis import deezer

        if not (identity := artist_identity(artistid, _LABEL)):
            return ""
        name, mbid = identity
        songs = cache(lambda: self._artist_songs(artistid, ["album", "title"], _LABEL))
        key = deezer.artist_key(mbid, name)
        match = deezer.artist_match(
            key, name, lambda *args: deezer_match(songs(), *args)
        )
        if not match:
            return ""
        if match[0] in deezer.chart():
            return ADDON.getLocalizedString(32995)
        return ADDON.getLocalizedString(32996) if match[1] >= POPULAR else ""

    def _album_word(self, albumid: int) -> str:
        """
        "Most popular album" for the album that leads Discography's popularity order
        alone, of two or more; none for a compilation (Various Artists).

        :param albumid: Library album id.
        :return: The word, or "" for none.
        """
        album = self._music_details("album", albumid, ["artistid", "compilation"])
        if not album or album["compilation"]:
            return ""
        artistid = album["artistid"][0]
        albums = self._artist_albums(artistid, _LABEL)
        rankings, songs = self._popularity(artistid, ALBUM_SONG_PROPERTIES, _LABEL)
        # Over the artist's albums (uncredited 0), as Discography ranks them: it must
        # lead alone, and an artist with one album has no ranking
        credit = album_credit(rankings, songs, albums)
        ranked = sorted((credit[row["albumid"]] for row in albums), reverse=True)
        if len(ranked) > 1 and credit[albumid] == ranked[0] > ranked[1]:
            return ADDON.getLocalizedString(32998)
        return ""

    def _song_word(self, songid: int) -> str:
        """
        "#2 song": the song's place in its first artist's Top songs, within PLACES.

        :param songid: Library song id.
        :return: The word, or "" for none.
        """
        if not (song := self._music_details("song", songid, ["artistid", "title"])):
            return ""
        properties = [*ALBUM_SONG_PROPERTIES, "playcount"]
        rankings, songs = self._popularity(song["artistid"][0], properties, _LABEL)
        place = song_place(rankings, songs, song["title"])
        return ADDON.getLocalizedString(32997) % place if place else ""

    @staticmethod
    def _music_details(type: str, dbid: int, properties: list[str]) -> dict | None:
        """
        A library album's or song's details, for popularity_label.

        :param type: album or song.
        :param dbid: Library id.
        :param properties: Properties to fetch.
        :return: The details object, or None for an id Kodi no longer has.
        """
        return (
            json_call(
                DETAILS[type],
                properties=properties,
                params={f"{type}id": dbid},
                parent=_LABEL,
            )
            .get("result", {})
            .get(f"{type}details")
        )

    @log.duration
    def lyrics(self) -> list[DirectoryItem] | None:
        """
        One item per synced lyric line of the playing song, as the service published
        them, with its neighbours' indexes and long when it overflows the playing box.
        The path's revision refetches; a path per line keeps a selection by path.

        :return: List of directory items for Kodi, or None if none.
        """
        home = Window(10000)
        lines = json.loads(home.getProperty(LINES) or "[]")
        long = set(json.loads(home.getProperty(LONG) or "[]"))
        return (
            set_items(
                {
                    "file": plugin_path(f"lyrics/{index}"),
                    "label": text,
                    "properties": {
                        "index": index,
                        "time": ms,
                        "gap": "" if text else "true",
                        "long": "true" if index in long else "",
                    }
                    | {key: index + step for key, step in NEIGHBOURS.items()},
                }
                for index, (ms, text) in enumerate(lines)
            )
            or None
        )

    @log.duration
    def soundtracks(self) -> list[DirectoryItem] | None:
        """
        Build a container of the soundtrack albums of library film, show, season or
        episode type= id=, matched by title; a season's own lead, other seasons' go.
        With type=album, the film or show that soundtrack is from.

        :return: List of directory items for Kodi, or None if none match.
        """
        if not (self._require("type", "id") and (dbid := to_int(self.dbid))):
            return
        if self.dbtype == "album":
            return self._soundtrack_source(dbid)
        media, season = self.dbtype, None
        if media in ("season", "episode"):
            if not (
                parent := _video_details(
                    media, dbid, ["tvshowid", "season"], parent="soundtracks"
                )
            ):
                return
            media, dbid, season = "tvshow", parent["tvshowid"], parent["season"]
        if not (
            item := _video_details(
                media, dbid, ["title", "originaltitle", "year"], parent="soundtracks"
            )
        ):
            return
        names = {item["title"], item["originaltitle"]}
        keys = set(map(title_key, filter(None, names)))
        albums = library_rows(
            "album",
            {
                "or": [
                    {"field": field, "operator": "contains", "value": SOUNDTRACK}
                    for field in ("type", "genre", "styles", "album")
                ]
            },
            None,
            None,
            "soundtracks",
            [*ALBUM_RANK_PROPERTIES, "originaldate"],
        )
        claims = {album["albumid"]: claim(album["title"]) for album in albums}
        if not (
            albums := [a for a in albums if claims[a["albumid"]].fits(keys, season)]
        ):
            return
        # same-titled films and shows: each album goes to the nearest one
        rivals = [
            (type, row)
            for type in ("movie", "tvshow")
            for row in fetch_raw(
                f"VideoLibrary.Get{_VIDEO_METHODS[type]}s",
                type,
                [{"or": [title_filter(names), title_filter(names, "originaltitle")]}],
                None,
                "soundtracks",
                properties=["title", "originaltitle", "year"],
            )
        ]
        albums = [
            album
            for album in albums
            if (found := owner(claims[album["albumid"]], release_year(album), rivals))
            and (found[0], found[1][f"{found[0]}id"]) == (media, dbid)
        ]
        albums.sort(
            key=lambda album: (
                season not in claims[album["albumid"]].seasons,
                release_year(album),
            )
        )
        set_plugincontent(content="albums")
        return [library_item(album, "album") for album in albums] or None

    def _soundtrack_source(self, albumid: int) -> list[DirectoryItem] | None:
        """
        The film or show soundtrack album albumid is from, matched by title; a show
        carries the seasons the album names in soundtrack_seasons ("3, 4").

        :param albumid: Library album id.
        :return: List of one directory item, or None if not a soundtrack or no match.
        """
        album = (
            json_call(
                "AudioLibrary.GetAlbumDetails",
                properties=["genre", "originaldate", "style", "title", "type", "year"],
                params={"albumid": albumid},
                parent="soundtracks",
            )
            .get("result", {})
            .get("albumdetails")
        )
        if not album:  # gone from the library
            return
        tags = (album["type"], album["title"], *album["genre"], *album["style"])
        if not any(SOUNDTRACK in tag.casefold() for tag in tags):
            return
        album_claim = claim(album["title"])
        # search the lead only; owner compares keys, so separators may differ
        prefix = lead(album["title"])
        rule = {
            "or": [
                {"field": field, "operator": "startswith", "value": prefix}
                for field in ("title", "originaltitle")
            ]
        }
        candidates = [
            (type, row)
            for type in ("movie", "tvshow")
            for row in fetch_raw(
                f"VideoLibrary.Get{_VIDEO_METHODS[type]}s",
                type,
                [rule],
                None,
                "soundtracks",
            )
        ]
        if not (found := owner(album_claim, release_year(album), candidates)):
            return
        type, row = found
        set_plugincontent(content=f"{type}s")
        items = build_items([row], type, apply_videoinfotag)
        named = ", ".join(map(str, sorted(album_claim.seasons)))
        for _, li, _ in items:
            li.setProperty("soundtrack_seasons", named)
        return items

    @role_endpoint(
        field="studio",
        category_id=32608,
        sources=[
            ("VideoLibrary.GetMovies", "movie"),
            ("VideoLibrary.GetTVShows", "tvshow"),
        ],
        parent="studio_credits",
    )
    def studio_credits(self) -> list[DirectoryItem] | None:
        """
        Build a container of movies and TV shows from studio ``self.label``.
        """
        pass

    @role_endpoint(
        field="writers",
        category_id=32604,
        sources=[
            ("VideoLibrary.GetMovies", "movie"),
            ("VideoLibrary.GetEpisodes", "episode"),
        ],
        parent="writer_credits",
        postprocess=lambda eps: enrich_with_tvshow(eps, parent="writer_credits"),
    )
    def writer_credits(self) -> list[DirectoryItem] | None:
        """
        Build a container of movies and episodes written by ``self.label``.
        """
        pass
