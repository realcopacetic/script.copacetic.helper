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
from heapq import merge
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
    Rewatch,
    ShowItem,
    TypewriterAnimation,
    clamp_text,
    fit_height,
    get_infolabels,
    gui_scale,
    hours_minutes,
    merge_metadata,
    reposition_control,
    rewatch_pass,
    rewatch_stops,
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
    PEOPLE,
    POPULAR,
    SONG_RANK_PROPERTIES,
    WEIGHTS,
    album_credit,
    artist_identity,
    artist_names,
    artist_places,
    artist_years,
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
from resources.lib.plugin.registry import LOG_TAG, PluginInfoRegistry, ongoing
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
from resources.lib.shared.lrc import LINES, LONG, NEIGHBOURS, PLAIN
from resources.lib.shared.mix import genre_ids, kept_mix, leading_cards, played_songs
from resources.lib.shared.parser import parse_plugin_argv
from resources.lib.shared.speed_dial import MUSIC_TYPES, SpeedDial
from resources.lib.shared.text import (
    fit_lines,
    markdown_label,
    plain_text,
    single_quotes,
    skin_metric,
    wrap_text,
)
from resources.lib.shared.utilities import (
    ADDON,
    INFO_DIALOGS,
    clear_label,
    clipped,
    condition,
    file_clean_name,
    file_label,
    focused_control_id,
    fold,
    infolabel,
    json_call,
    library_details,
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
    from resources.lib.apis.cache import Asker

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
}  # VideoLibrary.Get{…}s per library type
_MUSIC_NAMES = {"album": "album", "artist": "artist", "song": "title"}  # name field
# TMDb's show status as _show_news's show_status: no more episodes, or more to come
_SHOW_STATUS = {"Canceled": "ended", "Ended": "ended", "Returning Series": "returning"}
_LABEL = "popularity_label"  # the handler's name: its item's path, its calls' parent


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
# A JSON escape in a search query, as set_search_query writes it (ô, \")
_JSON_ESCAPE = re.compile(r"\\(?:u([0-9a-fA-F]{4})|(.))")
SEARCH_LIMIT = 30  # pictures art_search lists with no limit=: search's longest rail


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
        self.cursors = cursors or {}  # a served arrival's mark: its property's value

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
        show: bool = False,
        follow: Asker | None = None,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Resolve TMDb canonical item for the current listitem.

        :param append_artwork: Whether to include TMDb artwork fields.
        :param cache_only: Read the TMDb cache only; never fetch.
        :param target: Infolabel prefix of the item; the serve's target item if None.
        :param aside: Read the cache, fetching on a thread that calls this on news.
        :param show: A season's or episode's show entry, in place of its own.
        :param follow: Missing or stale: told when another serve's fetch of it ends.
        :return: The canonical item or None, and whether it was asked aside or followed.
        """
        from resources.lib.apis.tmdb.client import tmdb_token
        from resources.lib.apis.tmdb.context import resolve_tmdb_context
        from resources.lib.apis.tmdb.transform import tmdb_lookup

        if not tmdb_token():  # off: skip resolve_tmdb_context's uniqueid lookup
            return None, False

        ctx = resolve_tmdb_context(self.params, target=target or self.target_item)
        tmdb_id = to_int(ctx.get("tmdb_id"), 0)
        kind = "tvshow" if show else ctx.get("kind") or self.dbtype
        item, asked = tmdb_lookup(
            kind=kind,
            tmdb_id=tmdb_id,
            season_number=None if show else ctx.get("season_number"),
            language=self.params.get("language"),
            append_artwork=append_artwork,
            cache_only=cache_only,
            aside=aside,
            follow=follow,
        )
        if not item:
            log.debug(
                f"{self.__class__.__name__} → tmdb: no data for "
                f"type={kind!r}, tmdb_id={tmdb_id}"
            )
        return item or None, asked

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
            )[0]
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
        cursor_prop = f"artwork_cursor_{cursor_key}"
        served_cursor = self.cursors.get(cursor_prop)  # the settle's mark is the cursor
        cursor_snapshot = (
            served_cursor or infolabel(f"Window(home).Property({cursor_prop})")
            if cursor_key
            else ""
        )
        visit = self.params.get("visit", "")
        if self.superseded:
            visit = (
                ArtworkIdentity.parse(served_cursor).visit
                if served_cursor is not None
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
                served_cursor or partial if current_position is None else str(identity)
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
    def multiart_family(self) -> list[DirectoryItem] | None:
        """
        One item per image in a multiart family of the info dialog's item, for a
        viewer to step through: it opens on the image the register shows, if any.

        :return: The family as Art(multiart), wrapped round to the shown image.
        """
        from resources.lib.art.multiart import build_multiart_dict

        if not self._require("art") or not self._info_on_top():
            return

        urls = list(
            build_multiart_dict(
                target="ListItem",
                multiart_type=self.params["art"],
                max_items=self.params.get("multiart_max"),
                tmdb_art={},
            ).values()
        )
        register = self.params.get("register")
        shown = infolabel(f"Control.GetLabel({register})") if register else ""
        start = urls.index(shown) if shown in urls else 0
        # A path per slot: a reload keeps the list on the slot it was on
        return set_items(
            {"file": plugin_path(f"multiart_family/{i}"), "art": {"multiart": url}}
            for i, url in enumerate(urls[start:] + urls[:start])
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
            if not (row := library_details(dbtype, int(dbid), properties, "favourite")):
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
        Cleaned metadata on a helper list item; aborts if focus changes. random_pick,
        genre_chips, album_format, most_played, wikidata, compilation_artists,
        name_counts, place_chips, story_*, heading_*, set_suffix, years_present.

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
        pick = self.params.get("random_pick", "")
        # name_counts=false: Labels, Instruments and a compilation's artists uncounted
        counts = parse_bool(self.params.get("name_counts"), True)
        data = DataHandler(
            target=target,
            dbtype=self.dbtype,
            dbid=self.dbid,
        ).fetch_data(
            random_pick=("director", "genre") if parse_bool(pick) else pick.split(","),
            genre_aliases=[p.split(":", 1) for p in aliases.split(",") if p],
            genre_chips=to_int(self.params.get("genre_chips")),
            album_format=parse_bool(self.params.get("album_format")),
            most_played=parse_bool(self.params.get("most_played")),
            compilation_artists=parse_bool(self.params.get("compilation_artists")),
            name_counts=counts,
        )

        if not guard.alive():
            return

        own_plot, own_tagline = data["Plot"], data["TagLine"]
        enrich_with_tmdb = parse_bool(self.params.get("enrich_with_tmdb"))
        tmdb_art = enrich_with_tmdb and parse_bool(self.params.get("tmdb_art"))
        if enrich_with_tmdb:
            # tmdb_art: the one request also caches the art-bearing entry (a superset)
            # that the artwork serve's get_extra_multiart reads. Served, a stale entry
            # is fetched aside, and its news serves this list again (decision 2A)
            tmdb_item, asked = self._get_tmdb_item(
                append_artwork=tmdb_art, aside=self.again
            )
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
            # A show's TMDb details (tagline, creators, genres, network) asked aside,
            # missing or stale: the skin can mask their re-serve, as wikidata_pending
            if asked and self.dbtype == "tvshow":
                data["properties"]["tmdb_pending"] = "true"
        # A season's show entry, asked aside when missing or stale: its creators, and
        # with enrich_with_tmdb its season bars' airing renewed (11A, 12A's follow)
        creators = parse_bool(self.params.get("show_creators"))
        if self.dbtype == "season" and (creators or enrich_with_tmdb):
            show, asked = self._get_tmdb_item(
                append_artwork=False, aside=self.again, show=True
            )
            if creators:  # Kodi keeps no writers for a season: its show's, alone
                data["Writers"] = data["Writers"] or (show or {}).get("Writers", [])
                if asked:  # its creators re-served: masked as a show's (tmdb_pending)
                    data["properties"]["tmdb_pending"] = "true"
        # Omega's library keeps no show tagline (Kodi 22 scrapes one): TMDb's, if any
        if self.dbtype == "tvshow" and not own_tagline and data["TagLine"]:
            data["properties"]["tagline"] = data["TagLine"]
        if parse_bool(self.params.get("wikidata")):
            data["properties"] |= self._wikidata(data["Title"], data["Writers"], counts)
        # The tagline, else the title, else the label: an artist has no title
        heading = data["TagLine"] or data["Title"] or data["label"]
        data["properties"] |= self._heading_lines(heading)
        # set_suffix=: a film's collection without that last word ("… Collection")
        if (suffix := self.params.get("set_suffix")) and (
            collection := infolabel(f"{target}.Set")
        ):
            trim = collection.casefold().endswith(f" {suffix}".casefold())
            short = collection[: -len(suffix) - 1] if trim else collection
            data["properties"]["set_name"] = short
        # years_present=: an artist's years active, from its dates where Kodi has none
        if self.dbtype == "artist" and (present := self.params.get("years_present")):
            fields = ("yearsactive", "type", "born", "formed", "died", "disbanded")
            artist = {f: infolabel(f"{target}.Property(artist_{f})") for f in fields}
            data["properties"]["artist_years"] = artist_years(artist, present)

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

    def _wikidata(self, title: str, writers: list[str], counts: bool) -> dict[str, str]:
        """
        Wikidata details of a film, show, artist or album as wikidata_* properties,
        while the wikidata setting is on: kept ones only, a missing or stale answer
        asked aside for a served call (wikidata_pending), whose news serves it again.

        :param title: The item's title, for the story band's wording.
        :param writers: The item's writers: a show's creators, TMDb's.
        :param counts: Whether Labels and Instruments count the rest (+N).
        :return: The properties; none for an item with no TMDb, IMDb or MusicBrainz id.
        """
        from resources.lib.shared import wikidata_details as wd

        if not (wd.wanted() and (key := self._wikidata_key())):
            return {}
        found, fresh = wd.kept(key)
        properties = wd.properties(self.dbtype, found, counts)
        if writers:  # Wikidata's creators stand in only for a show TMDb names none for
            properties.pop("wikidata_created_by", None)
        if based := properties.get("wikidata_based_on"):
            properties["wikidata_based_on"] = self._one_line(based)
        # story_width=: the story band's chips, fitted in the skin's chip font
        if (
            self.dbtype in ("movie", "tvshow")
            and (width := to_float(self.params.get("story_width")))
            and (chip := self._chip_width("story_chip_"))
        ):
            properties |= self._story(found or {}, title, chip, width)
        if self.dbtype == "artist":
            kind = infolabel(f"{self.target_item}.Property(artist_type)")
            person = kind.casefold() in PEOPLE
            # instruments: a person's or character's, where Kodi has none of its own
            own = infolabel(f"{self.target_item}.Property(artist_instrument)")
            if own or not person:
                properties.pop("wikidata_instruments", None)
            # place_chips=N: the characters an artist's date chip (a person's born,
            # else formed; another's formed, else born) and its place's chip share
            if (place := properties.get("wikidata_place")) and (
                chips := to_int(self.params.get("place_chips"))
            ):
                dates = ("born", "formed") if person else ("formed", "born")
                labels = (f"{self.target_item}.Property(artist_{d})" for d in dates)
                date = next(filter(None, map(infolabel, labels)), "")
                properties["wikidata_place"] = clipped(place, chips - len(date))
            # The Biography tab's: a group's members, a person's memberships
            line = "member_of" if person else "members"
            properties |= self._bio("artist", found or {}, line)
        if not fresh and self.again:
            wd.ASIDES.ask(key, self.again, found)
            properties["wikidata_pending"] = "true"  # the skin can mask the re-serve
        return properties

    def _story(
        self,
        found: dict[str, Any],
        title: str,
        chip: Callable[[str], float],
        width: float,
    ) -> dict[str, str]:
        """
        A film's or show's story band (wikidata_details.story_chips) fitted to the
        width: story_gap between columns, story_chip_gap between chips, a column at
        least as wide as its story_caption_{column} in story_caption_font.

        :param found: The kept details; {} for none.
        :param title: The item's title.
        :param chip: A chip's width.
        :param width: The band's width.
        :return: The band's wikidata_{column}_{n} and {column}_caption_wide properties.
        """
        from resources.lib.shared import wikidata_details as wd

        year = to_int(infolabel(f"{self.target_item}.Year"))
        film = self.dbtype == "movie"  # a show has no collection
        collection = infolabel(f"{self.target_item}.Set") if film else ""
        columns = wd.story_chips(found, title, year, collection)
        return wd.fit_band(columns, chip, width, *self._band(wd.COLUMNS))

    def _bio(self, kind: str, found: dict[str, Any], line: str) -> dict[str, str]:
        """
        With story_bio, a Biography tab's line, wikidata_{line} (its names cut to one
        line as Based on is), and its band (wikidata_details.bio_band) fitted as the
        story band is, in the story band's params.

        :param kind: artist or painter, as wikidata_details.BIOS names the bands.
        :param found: The details: the line's and each column's labels by key.
        :param line: The line's key: members or member_of.
        :return: The properties; none without story_bio.
        """
        from resources.lib.shared import wikidata_details as wd

        if not parse_bool(self.params.get("story_bio")):
            return {}
        names = wd.joined(found.get(line, []), found.get(f"{line}_cut", False))
        properties = {f"wikidata_{line}": self._one_line(names)} if names else {}
        if (width := to_float(self.params.get("story_width"))) and (
            chip := self._chip_width("story_chip_")
        ):
            gaps, captions = self._band(wd.BIOS[kind][0])
            properties |= wd.bio_band(kind, found, chip, width, gaps, captions)
        return properties

    def _band(
        self, columns: tuple[str, ...]
    ) -> tuple[tuple[float, float], dict[str, float]]:
        """
        A band's gaps, story_gap between columns and story_chip_gap between chips,
        and its columns' story_caption_{column} widths in story_caption_font.

        :param columns: The band's columns' keys.
        :return: The gaps, and each captioned column's caption width.
        """
        gaps = tuple(
            to_float(self.params.get(f"story_{k}")) for k in ("gap", "chip_gap")
        )
        font = self.params.get("story_caption_font")
        if not (font and (metric := skin_metric(font))):
            return gaps, {}
        return gaps, {
            key: metric.getlength(text)
            for key in columns
            if (text := self.params.get(f"story_caption_{key}"))
        }

    def _one_line(self, text: str) -> str:
        """
        Text cut to one line at a word in based_on_font at based_on_width, as the
        line under the Plot tab's text (Based on) draws it; as it is without both.
        """
        if (room := to_float(self.params.get("based_on_width"))) and (
            metric := skin_metric(self.params.get("based_on_font", ""))
        ):
            return fit_lines(metric, text, room, 1, sentences=False)[0]
        return text

    def _heading_lines(self, heading: str) -> dict[str, str]:
        """
        heading_lines: the lines (1 or 2) a heading takes in heading_font at
        heading_width as Kodi wraps it, so a skin can size what sits under it.

        :param heading: The heading's text, as an infolabel returns it.
        :return: The property; none without both params, or for no heading.
        """
        if (
            (width := to_float(self.params.get("heading_width")))
            and (metric := skin_metric(self.params.get("heading_font", "")))
            and (text := plain_text(heading))
        ):
            lines = fit_lines(metric, text, width, 2, sentences=False)
            return {"heading_lines": str(len(lines))}
        return {}

    def _chip_width(self, prefix: str) -> Callable[[str], float] | None:
        """
        A chip's width as Kodi sizes a button to its text: {prefix}font's text (in
        capitals with {prefix}upper), {prefix}padding each side, {prefix}max at most.

        :param prefix: The params' prefix, e.g. "chip_" or "story_chip_".
        :return: The width of a chip of a text; None for an unknown font.
        """
        if not (metric := skin_metric(self.params.get(f"{prefix}font", ""))):
            return None
        upper = parse_bool(self.params.get(f"{prefix}upper"))
        padding = 2 * to_float(self.params.get(f"{prefix}padding"))
        widest = to_float(self.params.get(f"{prefix}max"), math.inf)
        return lambda chip: min(
            metric.getlength(chip.upper() if upper else chip) + padding, widest
        )

    def _wikidata_key(self) -> tuple[str, ...] | None:
        """
        The item's details key (wikidata_details.kept) by its ids: a film's or show's
        TMDb and IMDb ids, an artist's MusicBrainz id, an album's release group.

        :return: The key; None for another type or an item with no id.
        """
        if self.dbtype in ("movie", "tvshow"):
            ids = [
                infolabel(f"{self.target_item}.UniqueID({name})")
                for name in ("tmdb", "imdb")
            ]
        elif self.dbtype == "artist":
            ids = [(artist_identity(to_int(self.dbid), "metadata") or ("", ""))[1]]
        elif self.dbtype == "album":
            properties = ["musicbrainzreleasegroupid"]
            album = library_details("album", to_int(self.dbid), properties, "metadata")
            ids = [(album or {}).get("musicbrainzreleasegroupid", "")]
        else:
            return None
        return (self.dbtype, *ids) if any(ids) else None

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
        pb = ProgressBarManager(
            target=self.target_item,
            base_id=target_id,
            window_id=self.window_id,
            album_days=to_int(self.params.get("album_days"), 14),
        )
        span = to_int(self.params.get("resolution_span"))
        resume, unwatched = pb.calculate(span)
        # With rewatches on, a show's or season's episodes are read before the bar
        # moves, as a set's movies and an album's songs are: a rewatch's pass is its
        # value (15A)
        show = self._show_item(pb.infolabels)
        episodes, played = self._read_ahead(show) if show else (None, None)
        if rewatch := played and self._rewatch(played, show.show_id):
            resume, unwatched = rewatch.percent, str(rewatch.left)
        # Seconds, so the item's EndTimeResume works; PercentPlayed (position / total)
        # is unchanged
        secs = pb.runtime(resume)
        position = secs * resume / 100
        # A film's or episode's own play count (an album's is its songs' average)
        plays = (
            to_int(pb.infolabels["PlayCount"])
            if pb.infolabels["DBType"] in ("movie", "episode")
            else 0
        )
        item = {
            "file": plugin_path("progress"),
            "Duration": secs,
            "resume": (
                {"position": position, "total": secs}
                if secs
                else {"position": resume, "total": 100}
            ),
            "properties": {
                "unwatchedepisodes": str(unwatched),
                "plays": str(plays) if plays > 1 else "",
            },
        }
        if span:  # a picture's labels ride its bar, so a label never leads the fill
            item["properties"] |= {
                "picture_resolution": pb.picture["PictureResolution"],
                "picture_size": pb.picture["Size"],
            }
            # Kodi's "1920 x 1520", or none
            edges = re.findall(r"\d+", pb.picture["PictureResolution"]) or ["", ""]
            # picture_edges: its edges apart, for a skin's own sign between them
            if parse_bool(self.params.get("picture_edges")):
                item["properties"] |= dict(
                    zip(("picture_width", "picture_height"), edges)
                )
            # picture_name_chars=N: its file's name cut with "…" to the characters of
            # N its edges and size leave (a monospace line's)
            if room := to_int(self.params.get("picture_name_chars")):
                room -= sum(map(len, edges)) + len(pb.picture["Size"])
                item["properties"]["picture_name"] = clipped(
                    pb.picture["FileName"], room
                )

        if not guard.alive():
            return set_items([item], tag_applier=apply_videoinfotag)

        # The context menu's Stop rewatch (addon.xml) shows for this item alone: every
        # current bar serve writes or clears them, as album_resume's
        window_property("rewatch", value=show.dbid if rewatch else "")
        window_property("rewatch_show", value=show.show_id if rewatch else "")
        pb.update(
            percent=resume,
            opts=PlacementOpts.from_params(self.params),
            progress_id=to_int(self.params.get("progress_id"), None),
            btn_id=to_int(self.params.get("btn_id"), None),
            img_id=to_int(self.params.get("img_id"), None),
            img_h=to_int(self.params.get("img_h"), None),
            centre_id=to_int(self.params.get("centre_id"), None),
        )
        # The bar is placed first, but it appears only when the item returns, so any
        # item adds at most one library call to that. A superseded serve makes none.
        if guard.alive():
            item["properties"] |= {
                "time_left": (
                    hours_minutes(math.ceil((secs - position) / 60)) if secs else ""
                ),
                **(self._show_context(show, episodes, played, rewatch) if show else {}),
                **self._unwatched_new(pb, resume),
            }
            # An album's resume point; album, for the service's re-serve on song
            # updates (service/monitor.py) and the context menu's Mark and Resume
            # items (addon.xml)
            if pb.infolabels["DBType"] == "album":
                state, dbid = pb.album.state, pb.infolabels["DBID"]
                item["properties"] |= {"album": "true", **pb.album.resume}
                window_property("album_played", value=dbid if state == "played" else "")
                window_property(
                    "album_unplayed", value=dbid if state == "unplayed" else ""
                )
                window_property("album_resume", value=dbid if pb.album.position else "")
            # Last: it compares the row the item now carries
            item["properties"]["row_flip"] = self._row_flip(pb, item["properties"])

        return set_items([item], tag_applier=apply_videoinfotag)

    @staticmethod
    def _row_flip(pb: ProgressBarManager, props: dict[str, str]) -> str:
        """
        row_flip, turned when this window's last bar was the same library item with
        other properties: a re-serve that changes its row in place (a song heard,
        TMDb's answer), which the skin can dip over. An item with no DBID never is.

        :param pb: The serve's bar, for its window and the focused item's labels.
        :param props: The progress item's properties.
        :return: The window's flip after this serve: "true" or empty.
        """
        window, labels = pb.window, pb.infolabels
        last, flip = map(window.getProperty, ("progress_row", "progress_flip"))
        if not labels["DBID"]:  # nothing to know it again by (a file, an add-on's)
            window.setProperty("progress_row", "")
            return flip
        item = f"{labels['DBType']}{labels['DBID']}"
        row = f"{item} {json.dumps(props, sort_keys=True)}"
        if last != row and last.partition(" ")[0] == item:
            flip = "" if flip else "true"
            window.setProperty("progress_flip", flip)
        window.setProperty("progress_row", row)
        return flip

    def _show_item(self, labels: dict[str, str]) -> ShowItem | None:
        """
        The focused show or season, its ids and episode counts read from its labels.

        :param labels: The focused item's infolabels, as ProgressBarManager read them.
        :return: The item; None for other types.
        """
        if (dbtype := labels["DBType"]) not in ("tvshow", "season"):
            return None
        labels = labels | get_infolabels(
            self.target_item,
            [
                "Property(InProgressEpisodes)",
                "Property(WatchedEpisodes)",
                "Property(tvshowid)",
                "Season",
                "TvShowDBID",
            ],
        )
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
        watched = to_int(labels["Property(WatchedEpisodes)"])
        return ShowItem(
            dbtype=dbtype,
            dbid=to_int(labels["DBID"]),
            show_id=show_id,
            # A show's Season is its season count; "* All seasons" has none
            season=to_int(labels["Season"], None) if dbtype == "season" else None,
            watched=watched,
            started=bool(watched or to_int(labels["Property(InProgressEpisodes)"])),
            left=to_int(labels["Property(UnwatchedEpisodes)"]),
        )

    def _read_ahead(
        self, show: ShowItem
    ) -> tuple[list[dict] | None, list[dict] | None]:
        """
        With rewatch_days, a show's or season's episodes read before the bar moves: its
        unwatched ones while any are left, and its regular ones (_played) once each
        is watched, unwatched specials or not. None for each not read here.

        :param show: The focused show or season.
        :return: Its unwatched episodes and its played ones.
        """
        if not (self._rewatch_days and show.show_id) or show.season == 0:
            return None, None  # off, a plugin's item, or the Specials season: none
        unwatched = self._unwatched(show) if show.left else None
        if not show.watched or any(ep["season"] for ep in unwatched or ()):
            return unwatched, None
        return unwatched, self._played(show)

    def _unwatched(self, show: ShowItem) -> list[dict]:
        """
        A show's or season's unwatched episodes, specials too: one GetEpisodes call.

        :param show: The focused show or season.
        :return: Its unwatched episodes, unordered.
        """
        return fetch_raw(
            "VideoLibrary.GetEpisodes",
            "episode",
            [self.filter_unwatched],
            sort=None,
            parent="progressbar",
            params=show.scope,
            properties=["dateadded", "episode", "firstaired", "runtime", "season"],
        )

    def _played(self, show: ShowItem) -> list[dict]:
        """
        A watched show's or season's episodes outside the specials, in order, with
        when each was last played and any resume point: one GetEpisodes call.

        :param show: The focused show or season.
        :return: Its regular episodes.
        """
        episodes = fetch_raw(
            "VideoLibrary.GetEpisodes",
            "episode",
            [self.filter_no_specials],
            sort=None,
            parent="progressbar",
            params=show.scope,
            properties=["episode", "lastplayed", "resume", "runtime", "season"],
        )
        return sorted(episodes, key=itemgetter("season", "episode"))

    @property
    def _rewatch_days(self) -> int:
        """rewatch_days: rewatches are on (opt-in) while a pass is played within it."""
        return to_int(self.params.get("rewatch_days"))

    def _rewatch(self, played: list[dict], show_id: int) -> Rewatch | None:
        """
        A watched show's or season's rewatch (rewatch_pass), unless its latest play is
        older than rewatch_days or before its show's Stop rewatch on this device (17B):
        its share, episodes left and next.

        :param played: Its regular episodes (_played).
        :param show_id: Its show's library id, for the Stop rewatch mark.
        :return: The pass; None for no rewatch.
        """
        if not (run := rewatch_pass(played)):
            return None
        # The run's last play, or the next one's part-play, which moves its lastplayed
        latest = max(ep["lastplayed"] for ep in played[: run + 1])
        stopped = rewatch_stops().get(str(show_id), "")
        if latest < self._since("lastplayed", self._rewatch_days) or latest <= stopped:
            return None
        return Rewatch(run * 100 / len(played), len(played) - run, played[run])

    def _show_context(
        self,
        show: ShowItem,
        unwatched: list[dict] | None,
        played: list[dict] | None,
        rewatch: Rewatch | None,
    ) -> dict[str, str]:
        """
        A show's or season's next airing (_next_air); a rewatch's next; unfinished,
        its next (_next), new_kind and new; a fully watched show's _show_news. A
        property that doesn't apply is left out: it reads empty.

        :param show: The focused show or season.
        :param unwatched: Its unwatched episodes if read ahead (_read_ahead); else None.
        :param played: Its regular episodes if read ahead; else None.
        :param rewatch: Its rewatch's pass; None for none.
        :return: Properties for the progress item.
        """
        props, followed = self._show_tmdb(show.dbtype == "season")
        context = self._next_air(props, show.season)  # 6B, 13A
        if followed:  # the skin's mask: TMDb's answer is coming, and the bar with it
            context["tmdb_pending"] = "true"
        if show.dbtype == "tvshow" and show.done:
            context |= self._show_news(props, show.show_id, played)
        if rewatch:  # 15A: its pass's next and runtime, over a special next (16A)
            return context | self._next([rewatch.following]) | {"rewatch": "true"}
        # Started or not: an unwatched show's or season's next is its first episode
        if not (show.show_id and show.left):
            return context
        if unwatched is None:
            unwatched = self._unwatched(show)
        kind = self._new_kind(show.dbtype == "tvshow", show.started, unwatched)
        new = {"new": "true", "new_kind": kind} if kind else {}
        return context | self._next(unwatched) | new

    @staticmethod
    def _next(episodes: list[dict]) -> dict[str, str]:
        """
        The next of a show's or season's episodes as next_up's sort orders them:
        regular ones, by season then episode, first; specials alone, their first (8A).

        :param episodes: Its unwatched episodes, or a rewatch's next alone.
        :return: next_episode or next_special, and next_runtime; none for no episode.
        """
        regular = [ep for ep in episodes if ep["season"]]
        first = min(
            regular or episodes, key=itemgetter("season", "episode"), default=None
        )
        if not first:
            return {}
        return {
            "next_episode": (
                "{season}x{episode:02d}".format_map(first) if regular else ""
            ),
            "next_special": "" if regular else "true",
            # JSON-RPC's runtime: seconds, 0 when the library has none. To the nearest
            # minute: a runtime, not time left
            "next_runtime": (
                hours_minutes((first["runtime"] + 30) // 60) if first["runtime"] else ""
            ),
        }

    def _new_kind(self, show: bool, started: bool, unwatched: list[dict]) -> str:
        """
        Decision 7's pill: a show added within new_days and not started; else, of its
        unwatched episodes aired within new_days, a new season's first (shows only),
        or how many (specials too). A season counts its own and is never "show".

        :param show: A show, not a season.
        :param started: Any of its episodes watched or part-watched.
        :param unwatched: Its unwatched episodes: all of them, for a show not started.
        :return: "show", "season", "episode", "episodes" or "".
        """
        if show and not started:  # its date added is its earliest episode's
            added = min((ep["dateadded"] for ep in unwatched), default="")
            if added >= self._since("dateadded", self._new_days):
                return "show"
        # By air date, started or not: a back catalogue, or a binge, isn't new; a
        # future date (a pre-release file) is
        since = self._since("firstaired", self._new_days)
        aired = [ep for ep in unwatched if ep["firstaired"] >= since]
        if show and any(ep["season"] > 1 and ep["episode"] == 1 for ep in aired):
            return "season"
        return ("", "episode", "episodes")[min(len(aired), 2)]

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
        if dbtype == "album" and pb.album.state != "unplayed":
            return {}
        item = library_details(dbtype, dbid, [field], "progressbar")
        new = item and item[field] >= self._since(field, self._new_days)  # None: error
        return {"new": "true" if new else ""}

    @property
    def _new_days(self) -> int:
        """new_days: how long an item stays new (default 30)."""
        return to_int(self.params.get("new_days"), 30)

    @staticmethod
    def _since(field: str, days: int) -> str:
        """
        A cutoff days before now, as JSON-RPC writes the field, so string order is
        time order: the earliest still new, or a rewatch's latest play still counting.

        :param field: "firstaired" (a date), or "dateadded" / "lastplayed" (a time).
        :param days: How many days back.
        :return: The cutoff in the field's format, local time.
        """
        fmt = "%Y-%m-%d" if field == "firstaired" else "%Y-%m-%d %H:%M:%S"
        return f"{datetime.now() - timedelta(days=days):{fmt}}"

    def _show_tmdb(self, season: bool) -> tuple[dict[str, str], bool]:
        """
        The focused show's (or season's show's) TMDb properties from the cache only,
        never fetched here; served with follow_tmdb, a fetch the metadata serve asked
        aside is followed: the bar is served again once it ends (12A).

        :param season: The item is a season: its show's entry.
        :return: The tmdb_* properties (empty when not cached), and whether followed.
        """
        # No art: the art entry while fresh, else a fresh art-less one, else stale art
        # first (renewed by the metadata serve with TMDb multiart on; off, an older art
        # entry can win until the art-less one is renewed on the next focus)
        follow = self.again if parse_bool(self.params.get("follow_tmdb")) else None
        tmdb, followed = self._get_tmdb_item(
            append_artwork=False, cache_only=True, show=season, follow=follow
        )
        return (tmdb["properties"] if tmdb else {}), followed

    def _next_air(self, props: dict[str, str], season: int | None) -> dict[str, str]:
        """
        A show's next airing from its TMDb properties: the date in date_format
        (_air_day), the episode and whether it airs today; a season's when in it.

        :param props: The show's TMDb properties (_show_tmdb).
        :param season: A season's number; None for a show or "* All seasons".
        :return: next_air, next_air_episode and next_air_today; none if past or unknown.
        """
        iso, today = props.get("tmdb_next_air_date"), date.today()
        if not iso or (day := date.fromisoformat(iso)) < today:
            return {}
        # An entry cached before the numbers were kept (7-day TTL) has the date alone,
        # which no season can claim
        airs_in = to_int(props.get("tmdb_next_air_season"), None)
        if season is not None and airs_in != season:
            return {}
        episode = props.get("tmdb_next_air_episode")
        return {
            "next_air": self._air_day(day),
            "next_air_episode": f"{airs_in}x{int(episode):02d}" if episode else "",
            "next_air_today": "true" if day == today else "",  # 5A: AIRS TODAY
        }

    def _show_news(
        self, props: dict[str, str], show_id: int, played: list[dict] | None
    ) -> dict[str, str]:
        """
        A fully watched show's news from its TMDb properties: its last aired episode
        if new and not in the library, with its air date (as _air_day), and whether
        the show ended.

        :param props: The show's TMDb properties (_show_tmdb).
        :param show_id: Library id of the show; 0 for a plugin's item.
        :param played: Its regular episodes if read ahead (_played); None: asked here.
        :return: show_status, and new_episode with its _aired and _today.
        """
        news = {"show_status": _SHOW_STATUS.get(props.get("tmdb_status"), "")}
        # Only aired within new_days, as new counts (an ended show's last is old
        # news), and past the library's newest: an episode missing mid-run, or
        # numbered another way (TVDB's order), is no news. Specials left out, as
        # next_episode does. An entry cached before these were kept (7-day TTL) has
        # none; a plugin's item has no episodes to compare
        season = to_int(props.get("tmdb_last_air_season"))
        aired = props.get("tmdb_last_air_date", "")
        since = self._since("firstaired", self._new_days)
        if not (show_id and season > 0 and aired >= since):
            return news
        episode = int(props["tmdb_last_air_episode"])
        # The library's newest: read ahead, or one call for it alone
        newest = played[-1:] if played is not None else self._newest(show_id)
        have = next((itemgetter("season", "episode")(ep) for ep in newest), (0, 0))
        if (season, episode) <= have:
            return news
        day = date.fromisoformat(aired)  # 2A, 5A: AIRED 25 Nov or AIRED TODAY
        return news | {
            "new_episode": f"{season}x{episode:02d}",
            "new_episode_aired": self._air_day(day),
            "new_episode_today": "true" if day == date.today() else "",
        }

    def _newest(self, show_id: int) -> list[dict]:
        """
        A show's newest episode outside the specials: one GetEpisodes call.

        :param show_id: The show's library id.
        :return: It alone; none for a show with no regular episode.
        """
        return fetch_raw(  # "episode" sorts by season, then episode
            "VideoLibrary.GetEpisodes",
            "episode",
            [self.filter_no_specials],
            sort={"method": "episode", "order": "descending"},
            parent="progressbar",
            params={"tvshowid": show_id},
            limit=1,
            properties=["episode", "season"],
        )

    def _air_day(self, day: date) -> str:
        """
        An air date in date_format (strftime, default "%d %b"), its %b Kodi's own
        short month (51-62), in its language as its dates' "mmm" is, not the C locale's.

        :param day: The date.
        :return: E.g. "25 Nov".
        """
        month = getLocalizedString(50 + day.month)
        fmt = self.params.get("date_format", "%d %b")
        # Joined outside strftime, which on Windows encodes its format by locale codec
        return month.join(day.strftime(part) for part in fmt.split("%b"))

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

    def art_details(self) -> list[DirectoryItem]:
        """
        A picture's painting from Wikidata as art_* properties, in folders marked for
        it while the wikidata setting is on; a folder's mark state as Home properties.
        A plugin call reads kept verdicts only: the look-ups are the service's.

        :return: One item, its properties empty for no match (yet).
        """
        from resources.lib.shared import art_details as art

        item = {"file": plugin_path("art_details"), "properties": {}}
        if not ADDON.getSettingBool("wikidata"):
            return set_items([item])
        # Raw, as clean_name's: a decode would split a name at its own encoded "?"
        raw = parse_plugin_argv(["", "", self.query], raw={"folder", "path"})
        listing, path = raw.get("folder"), raw.get("path", "")
        folders = art.marked()
        if listing is not None:  # a listing's serve: none leaves its state as it is
            covered = art.covers(folders, art.folder(listing))
            window_property("art_details_checked", value=listing)
            window_property("art_details_folder", value=covered and listing)
        if path.endswith(("/", "\\")):  # a folder: its state, for the context menu
            art.publish(folders, path)
        elif art.is_picture(path) and art.covers(folders, path):
            if (found := art.verdict(path)) is None and self.again:
                art.ASIDES.ask(path, self.again)  # the network never holds a serve
            item["properties"] = self._art_properties(found or {})
        return set_items([item])

    def _art_properties(self, found: dict[str, Any]) -> dict[str, str]:
        """
        A match's fields as art_* properties, and its chips as art_chip1… (medium,
        genre, collection, dimensions); chip_row and summary_lines fit them.

        :param found: The file's fields; {} for none.
        :return: The item's properties.
        """
        from resources.lib.shared.art_details import fit_chips

        if not found:
            return {}
        fields = found | {
            "collection": (
                ADDON.getLocalizedString(32849)  # Wikidata's "unknown value"
                if found["collection"] is None
                else found["collection"]
            ),
            "depicts": ", ".join(found["depicts"]),
        }
        if (lines := to_int(self.params.get("summary_lines"))) and (
            metric := skin_metric(self.params.get("summary_font", ""))
        ):
            width = to_int(self.params.get("summary_width"))
            fields["summary"] = " ".join(
                fit_lines(metric, fields["summary"], width, lines)
            )
        chips = [fields[k] for k in ("medium", "genre", "collection", "dimensions")]
        chips = [*filter(None, chips)]
        if (row := to_int(self.params.get("chip_row"))) and (
            width := self._chip_width("chip_")
        ):
            chips = fit_chips(
                chips,
                width,
                row,
                to_float(self.params.get("chip_gap")),
            )
        return {f"art_{key}": value for key, value in fields.items()} | {
            f"art_chip{n}": chip for n, chip in enumerate(chips, 1)
        }

    def art_artist(self) -> list[DirectoryItem]:
        """
        An artist's page from Wikidata (qid=) as art_* properties, its portrait as
        thumb, its Biography line and band (story_bio), heading_lines (heading_*):
        kept answers only, one missing or stale asked aside (wikidata_pending).

        :return: One item, its properties empty until the answers land.
        """
        from resources.lib.shared import art_details as art

        item = {"file": plugin_path("art_artist"), "properties": {}}
        if not (ADDON.getSettingBool("wikidata") and (qid := self.params.get("qid"))):
            return set_items([item])
        found, fresh = art.page("painter", qid)
        if asked := not fresh and self.again:
            art.PAGES.ask(("painter", qid), self.again, found)
        if found:
            fields = art.artist_fields(found)
            item |= {
                "label": fields["name"],
                "art": {"thumb": fields.pop("portrait")},
                "properties": {f"art_{key}": value for key, value in fields.items()}
                | self._bio("painter", art.artist_bio(found), "member_of")
                | self._heading_lines(fields["name"]),
            }
            if asked:  # a stale page: the skin can mask its re-serve
                item["properties"]["wikidata_pending"] = "true"
        return set_items([item])

    def art_search(self) -> list[DirectoryItem]:
        """
        Pictures in marked folders for a search (query=, limit=): kept art details
        and file names only, never a request. Select shows an item: its path's a picture.

        :return: The pictures, best first; none with the wikidata setting off.
        """
        from resources.lib.shared import art_details as art

        if not ADDON.getSettingBool("wikidata"):
            return []
        # Decoded once, as Kodi passes the URL's options encoded; then set_search_query's
        # JSON escapes, so "Rhône" is found as typed. A character past U+FFFF comes as
        # two escapes, a surrogate pair, joined back through UTF-16
        query = _JSON_ESCAPE.sub(
            lambda m: chr(int(m[1], 16)) if m[1] else m[2], self.params.get("query", "")
        )
        query = query.encode("utf-16", "surrogatepass").decode(
            "utf-16", "surrogatepass"
        )
        limit = to_int(self.params.get("limit"), SEARCH_LIMIT)
        return set_items(
            {
                "file": path,
                "label": fields.get("title") or file_label(path),
                "label2": fields.get("artist", ""),
                "art": {"thumb": path},
                "properties": {  # no summary: a rail shows none
                    key: value
                    for key, value in self._art_properties(fields).items()
                    if key != "art_summary"
                },
            }
            for path, fields in art.search(query, limit)
        )

    def art_rail(self) -> list[DirectoryItem]:
        """
        An artist's rail from Wikidata (qid=, kind=gallery, similar or influenced),
        each item's picture as thumb and full (full screen), its Q-id as qid.

        :return: The rail's items, none until its answer lands.
        """
        from resources.lib.apis.wikidata import RAILS
        from resources.lib.shared import art_details as art

        kind, qid = self.params.get("kind"), self.params.get("qid")
        if not (ADDON.getSettingBool("wikidata") and qid and kind in RAILS):
            return []
        found, fresh = art.page(kind, qid)
        if not fresh and self.again:
            art.PAGES.ask((kind, qid), self.again, found)
        return set_items(
            {
                "file": plugin_path(f"art_rail/{item}"),
                "label": label,
                "label2": year,
                "art": {"thumb": art.commons(image, art.TILE)},
                "properties": {"qid": item, "full": art.commons(image, art.FULL)},
            }
            for item, label, image, year in found or []
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
            scale=gui_scale(),
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

    @ongoing
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
        if parse_bool(self.params.get("reset")):
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

        :return: List of directory items for Kodi, or None if none.
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

        :return: List of directory items for Kodi, or None if none.
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

        # Assemble in the shows' order, to preserve lastplayed desc.
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
        item = library_details(self.dbtype, dbid, ["cast"], "cast") or {}
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

    @log.duration
    def creator_credits(self) -> list[DirectoryItem] | None:
        """
        Build a container of the library films and TV shows by the creators of TV show
        ``self.dbid`` (or tmdb_id=; a season's or episode's show), less itself: the
        shows TMDb credits them as Creator, and the films and shows they wrote.

        :return: List of directory items for Kodi, or None if empty.
        """
        from resources.lib.apis.tmdb.client import tmdb_token
        from resources.lib.apis.tmdb.context import resolve_tmdb_context
        from resources.lib.apis.tmdb.transform import creator_shows, tmdb_to_canonical

        if not tmdb_token():  # off: skip resolve_tmdb_context's uniqueid lookup
            return
        ctx = resolve_tmdb_context(self.params, target=self.target_item)
        if not (show_id := to_int(ctx["tmdb_id"], 0)):
            return
        show = tmdb_to_canonical(
            "tvshow",
            show_id,
            language=self.params.get("language"),
            append_artwork=False,
        )
        if not (writers := show.get("Writers")):  # the creators' names
            return
        # An entry cached before the ids were kept (7-day TTL) has none
        people = show.get("properties", {}).get("tmdb_creator_ids", "")
        created = {
            show["id"]: show["names"]
            for person in filter(None, people.split(","))
            for show in creator_shows(person)
        }
        created.pop(show_id, None)
        wrote = title_filter(writers, "writers")
        sort = {"method": self.params.get("sort", "year"), "order": "descending"}
        movies = fetch_raw(
            "VideoLibrary.GetMovies",
            "movie",
            [wrote],
            sort,
            "creator_credits",
            limit=self.limit,
        )
        episodes = fetch_raw(  # Kodi's shows keep no writers: their episodes do
            "VideoLibrary.GetEpisodes",
            "episode",
            [wrote],
            None,
            "creator_credits",
            properties=["tvshowid", "showtitle"],
        )
        written = {episode["tvshowid"] for episode in episodes}
        names = [
            *(name for names in created.values() for name in names),
            *(episode["showtitle"] for episode in episodes),
        ]
        shows = names and fetch_raw(  # no uniqueid filter: by name, then by id
            "VideoLibrary.GetTVShows",
            "tvshow",
            [{"or": [title_filter(names), title_filter(names, "originaltitle")]}],
            sort,
            "creator_credits",
            properties=[*JSON_PROPERTIES["tvshow"], "uniqueid"],
        )
        shows = [
            row
            for row in shows
            if (tmdb := to_int(row["uniqueid"].get("tmdb"), 0)) in created
            or (row["tvshowid"] in written and tmdb != show_id)
        ]
        method = sort["method"]
        rank = float if method == "votes" else (lambda value: value)  # votes: strings
        ranked = merge(  # each newest (or sort=) first: one list in that order
            ((row, "movie") for row in movies),
            ((row, "tvshow") for row in shows),
            key=lambda pair: rank(pair[0].get(method, 0)),
            reverse=True,
        )
        set_plugincontent(content="videos", category=ADDON.getLocalizedString(32617))
        return [
            item
            for row, kind in islice(ranked, self.limit)
            for item in build_items([row], kind, apply_videoinfotag)
        ] or None

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
            properties = (
                ["artistid", "compilation"] if seed == "album" else ["artistid"]
            )
            details = library_details(seed, dbid, properties, "similar_music")
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
        is, never a number: with Deezer on "Charting" or "Popular", "#2 song" or "#1
        album"; with it off, by your plays ("Your #3 artist", "Your #2 song").

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
        ListenBrainz never hold the pipeline): it renews the cache for the next visit,
        and serves the list again only when the cache had no word (never a swap).

        :param word: The item type's word function.
        :param dbid: Library id.
        :param served: The word the cache answered.
        """
        try:
            if word(dbid) and not served and self.again.current():
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
        With Deezer off, "Your #1 album" for the album that leads its first
        artist's albums by their songs' summed plays, clearly (play_place); none for a
        compilation (Various Artists).

        :param albumid: Library album id.
        :return: The word, or "" for none.
        """
        album = library_details("album", albumid, ["artistid", "compilation"], _LABEL)
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
        if not (song := library_details("song", songid, ["artistid", "title"], _LABEL)):
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
        "#1 album" for the album that leads Discography's popularity order
        alone, of two or more; none for a compilation (Various Artists).

        :param albumid: Library album id.
        :return: The word, or "" for none.
        """
        album = library_details("album", albumid, ["artistid", "compilation"], _LABEL)
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
        if not (song := library_details("song", songid, ["artistid", "title"], _LABEL)):
            return ""
        properties = [*ALBUM_SONG_PROPERTIES, "playcount"]
        rankings, songs = self._popularity(song["artistid"][0], properties, _LABEL)
        place = song_place(rankings, songs, song["title"])
        return ADDON.getLocalizedString(32997) % place if place else ""

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
    def lyrics_plain(self) -> list[DirectoryItem] | None:
        """
        One item per line of the playing song's plain lyrics, or with type=song&id=
        a library song's (_song_lyrics); with wrap_width= and wrap_font=, a line Kodi
        would wrap is split there. One path for every item: a refetch opens on its first.

        :return: List of directory items for Kodi, or None if none.
        """
        if self.dbtype == "song":
            return self._song_lyrics()
        rows = self._lyric_rows(Window(10000).getProperty(PLAIN))
        return set_items(rows) or None

    def _song_lyrics(self) -> list[DirectoryItem]:
        """
        Library song id's lyrics (lyrics.library); the skin asks only while it offers
        them. A served call asks LRCLIB aside: one blank row marked lyrics_pending.

        :return: List of directory items for Kodi; none for no lyrics.
        """
        from resources.lib.service import lyrics

        if not (dbid := to_int(self.dbid)):
            return []
        fields = lyrics.SONG_FIELDS
        if not (song := library_details("song", dbid, fields, "lyrics_plain")):
            return []
        if (text := lyrics.library(song, self.again)) is None:
            pending = {"label": "", "properties": {"lyrics_pending": "true"}}
            return set_items([{"file": plugin_path("lyrics/plain")} | pending])
        return set_items(self._lyric_rows(text))

    def _lyric_rows(self, text: str) -> list[dict[str, Any]]:
        """
        Plain lyrics as one row a line, a line split where Kodi would wrap it in
        wrap_font= at wrap_width=.

        :param text: The lyrics.
        :return: Item dicts, one path for all; none for no text.
        """
        lines = text.splitlines()
        if (width := to_int(self.params.get("wrap_width"))) and (
            metric := skin_metric(self.params.get("wrap_font", ""))
        ):
            lines = [
                row for line in lines for row in wrap_text(metric, line, width) or [""]
            ]
        path = plugin_path("lyrics/plain")
        return [{"file": path, "label": line} for line in lines]

    @log.duration
    def soundtracks(self) -> list[DirectoryItem] | None:
        """
        Build a container of the soundtrack albums of library film, show, season or
        episode type= id=, by title and Wikidata's links (_soundtrack_links); a season's
        own lead, other seasons' go. type=album: the film or show it's from.

        :return: List of directory items for Kodi, or None if none match.
        """
        if not (self._require("type", "id") and (dbid := to_int(self.dbid))):
            return
        if self.dbtype == "album":
            return self._soundtrack_source(dbid)
        media, season = self.dbtype, None
        if media in ("season", "episode"):
            if not (
                parent := library_details(
                    media, dbid, ["tvshowid", "season"], "soundtracks"
                )
            ):
                return
            media, dbid, season = "tvshow", parent["tvshowid"], parent["season"]
        if not (
            item := library_details(
                media,
                dbid,
                ["title", "originaltitle", "year", "uniqueid"],
                "soundtracks",
            )
        ):
            return
        names = {item["title"], item["originaltitle"]}
        keys = set(map(title_key, filter(None, names)))
        properties = [
            *ALBUM_RANK_PROPERTIES,
            "originaldate",
            "musicbrainzalbumartistid",
            "musicbrainzreleasegroupid",
        ]
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
            properties,
        )
        claims = {album["albumid"]: claim(album["title"]) for album in albums}
        albums = [a for a in albums if claims[a["albumid"]].fits(keys, season)]
        # same-titled films and shows, read for an album only: each album goes to the
        # nearest one, or the one Wikidata links it to or its artist scored
        titled = {"or": [title_filter(names), title_filter(names, "originaltitle")]}
        rivals = cache(
            lambda: [
                (type, row)
                for type in ("movie", "tvshow")
                for row in fetch_raw(
                    f"VideoLibrary.Get{_VIDEO_METHODS[type]}s",
                    type,
                    [titled],
                    None,
                    "soundtracks",
                    properties=["title", "originaltitle", "year", "uniqueid"],
                )
            ]
        )
        albums = [
            album
            for album in albums
            if (
                found := owner(
                    claims[album["albumid"]],
                    release_year(album),
                    rivals(),
                    partial(self._rank, album),
                )
            )
            and (found[0], found[1][f"{found[0]}id"]) == (media, dbid)
        ]
        # Albums Wikidata links to it, whatever their tags or title say; a season's
        # only if they name it or no season
        known = {album["albumid"] for album in albums}
        for album in self._soundtrack_links(media, item["uniqueid"], properties):
            if album["albumid"] not in known and (
                linked := claim(album["title"])
            ).covers(season):
                claims[album["albumid"]] = linked
                albums.append(album)
        if not albums:
            return
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
        The film or show soundtrack album albumid is from: the one its kept Wikidata
        details link it to, else (a soundtrack by its tags) matched by title; a show
        carries the seasons the album names in soundtrack_seasons ("3, 4").

        :param albumid: Library album id.
        :return: List of one directory item, or None if not a soundtrack or no match.
        """
        properties = [
            "genre",
            "musicbrainzalbumartistid",
            "musicbrainzreleasegroupid",
            "originaldate",
            "style",
            "title",
            "type",
            "year",
        ]
        album = library_details("album", albumid, properties, "soundtracks")
        if not album:  # gone from the library
            return
        album_claim = claim(album["title"])
        if not (found := self._soundtrack_film(album["musicbrainzreleasegroupid"])):
            tags = (album["type"], album["title"], *album["genre"], *album["style"])
            if not any(SOUNDTRACK in tag.casefold() for tag in tags):
                return
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
                    properties=[*JSON_PROPERTIES[type], "uniqueid"],
                )
            ]
            rank = partial(self._rank, album)
            if not (found := owner(album_claim, release_year(album), candidates, rank)):
                return
        type, row = found
        set_plugincontent(content=f"{type}s")
        items = build_items([row], type, apply_videoinfotag)
        named = ", ".join(map(str, sorted(album_claim.seasons)))
        for _, li, _ in items:
            li.setProperty("soundtrack_seasons", named)
        return items

    @staticmethod
    def _rank(album: dict, fit: tuple[str, dict]) -> tuple[bool, bool]:
        """
        A library film's or show's ties to an album in its kept Wikidata details: its
        soundtracks list the album's release group; its composers, the album's artist.

        :param album: AudioLibrary row with its MusicBrainz release group and artists.
        :param fit: (movie or tvshow, row with uniqueid).
        :return: (linked by id, scored by the album's artist), the link first.
        """
        from resources.lib.shared import wikidata_details as wd

        found = wd.linked(wd.video_key(fit[0], fit[1]["uniqueid"]))
        return (
            album["musicbrainzreleasegroupid"] in found.get("soundtracks", []),
            not set(album["musicbrainzalbumartistid"]).isdisjoint(
                found.get("composers", [])
            ),
        )

    @staticmethod
    def _soundtrack_links(
        media: str, uniqueid: dict[str, str], properties: list[str]
    ) -> list[dict]:
        """
        The library albums Wikidata links to a film or show, by their release groups
        (its P406 albums', and albums whose P9899 names it).

        :param media: movie or tvshow.
        :param uniqueid: Its library row's uniqueid.
        :param properties: The album properties to read.
        :return: AudioLibrary rows; none with the setting off or no link kept.
        """
        from resources.lib.shared import wikidata_details as wd

        found = wd.linked(wd.video_key(media, uniqueid))
        if not (groups := set(found.get("soundtracks", []))):
            return []
        # No release group filter: every album's, then the linked ones' details
        rows = library_rows(
            "album", None, None, None, "soundtracks", ["musicbrainzreleasegroupid"]
        )
        return [
            library_details("album", row["albumid"], properties, "soundtracks")
            for row in rows
            if row["musicbrainzreleasegroupid"] in groups
        ]

    @staticmethod
    def _soundtrack_film(group: str) -> tuple[str, dict] | None:
        """
        The library film or show Wikidata says a soundtrack album was made for, by
        their TMDb and IMDb ids: the first one found.

        :param group: The album's MusicBrainz release group id; "" for none.
        :return: The (type, row) pair; None with the setting off or no link kept.
        """
        from resources.lib.shared import wikidata_details as wd

        found = wd.linked(("album", group) if group else None)
        if not (films := found.get("films")):
            return None
        for type in ("movie", "tvshow"):
            rows = fetch_raw(  # no uniqueid filter: every id, then the one's details
                f"VideoLibrary.Get{_VIDEO_METHODS[type]}s",
                type,
                [],
                None,
                "soundtracks",
                properties=["uniqueid"],
            )
            for row in rows:
                if any(
                    kind in (type, "") and row["uniqueid"].get(name) == value
                    for kind, name, value in films
                ):
                    dbid, properties = row[f"{type}id"], JSON_PROPERTIES[type]
                    return type, library_details(type, dbid, properties, "soundtracks")
        return None

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
