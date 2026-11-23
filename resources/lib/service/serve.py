# author: realcopacetic

"""
Served focus calls: the skin rings when an item comes to rest (settle) or a selection
changes with no focused-layout arrival (move), and the warm service fills each named
list in turn, each a list with no <content>; 9300's multiart family then turns on
9400, a slide a beat. Notes: coding-notes/copacetic/features/served-focus-calls.md.
"""

import time
from itertools import chain, count, cycle, islice, takewhile
from threading import Event, RLock, Thread
from typing import Callable, NamedTuple

import xbmc
from xbmcgui import ListItem, Window, getCurrentWindowId

from resources.lib.shared import logger as log
from resources.lib.shared.parser import parse_plugin_argv
from resources.lib.shared.utilities import infolabel, plugin_path, topmost_window_id

# NotifyAll(script.copacetic.helper,<kind>/<region>/<lists, dot-separated>/<mark>);
# a move's mark is <container>/<token>: the list that moved (view: the cursor's list),
# or none, then the token in moved_<region>
KINDS = ("settle", "move")
PLUGIN = "plugin://script.copacetic.helper/?"  # a plugin URL's, before its query
# Served list → the hidden label holding its params, in serving order: the favourite's
# library item, which the others' favourite rows read, then details, the bar, artwork
# and the show logo
PROBES = {9040: 6904, 9000: 6900, 9100: 6901, 9010: 6910, 9300: 6930, 9301: 6931}
WAIT, NONE = "wait", "none"  # a probe's "not yet" and "nothing for this item"
POLL = 0.1  # seconds between looks while a dialog covers the window or a probe waits
# Seconds a probe may say wait before it counts as none: only a backstop, as each wait
# row ends with the state it waits on (a slow Search rail can take several seconds)
WAIT_MAX = 30
SETTLE = 0.225  # a move's own settle, the skin's transition_0.75x
# 9300's multiart family turns on 9400: each slide's params are in its probe, and each
# shows for the register's dwell it replaces, 4.8 s pause and 0.2 s fade
ARTWORK, SLIDES, SLIDE_PROBE = 9300, 9400, 6932
DWELL = 5.0
LEAD = 1.5  # seconds before its beat a slide is made: its params as late as they can be


class Request(NamedTuple):
    """
    One arrival. A settle answers the cursor its hook wrote (artwork_cursor_<region>),
    a move the token its ring wrote (moved_<region>); the mark is that value. again
    marks the helper's own re-serve, never a repeat; container is the list a move
    moved, whose item it binds.
    """

    kind: str
    region: str
    lists: tuple[int, ...]
    mark: str
    container: str = ""
    again: bool = False

    @property
    def current(self) -> str:
        """What the bound item names: the cursor's list/position/dbid/, or the token."""
        if self.kind == "settle":
            return "/".join(self.mark.split("/")[:3]) + "/"
        return self.mark

    @property
    def cursors(self) -> dict[str, str]:
        """A settle's cursor by its region, for a handler that keeps it; a move's none."""
        return {self.region: self.mark} if self.kind == "settle" else {}

    def live(self) -> bool:
        """Whether its cursor or token is still the skin's: no move has come since."""
        prop = "artwork_cursor" if self.kind == "settle" else "moved"
        return Window(10000).getProperty(f"{prop}_{self.region}") == self.mark


class Turn(NamedTuple):
    """A family to turn on 9400: 9300's bind for an arrival, in its window."""

    request: Request
    window_id: int
    identity: str
    family: tuple[str, ...]


class Again(NamedTuple):
    """
    A served list's re-serve for its arrival, once a late answer lands (TMDb's);
    equal for one list and arrival, so a repeat serve asks once.
    """

    server: "Server"
    list_id: int
    mark: str

    def __call__(self) -> None:
        """Serve the list again, if its arrival is still the window's last one."""
        self.server.again(self.list_id, self.mark)

    def current(self) -> bool:
        """Whether its arrival is still the window's last one, so worth fetching for."""
        return self.server.current(self.mark)


def move_token(*regions: str) -> str:
    """
    A new move token in moved_<region> for each region, as the skin's atr_serve_move
    writes one.

    :param regions: Whose token.
    :return: The token, the move's mark.
    """
    token = f"m{time.monotonic_ns()}"
    for region in regions:
        Window(10000).setProperty(f"moved_{region}", token)
    return token


def ring_move(region: str = "primary") -> None:
    """
    A move from Python (a published search query): the token, then the ring.

    :param region: Whose token, moved_<region>.
    """
    lists = ".".join(map(str, PROBES))
    mark = move_token(region)
    xbmc.executebuiltin(f"NotifyAll({log.ADDON_ID},move/{region}/{lists}//{mark})")


class _Listener(xbmc.Monitor):
    """Hears the skin's rings; only records them (it can run inside a serve's wait)."""

    def __init__(self, ring: Callable[[Request], None]) -> None:
        super().__init__()
        self.ring = ring

    def onNotification(self, sender: str, method: str, data: str) -> None:
        """
        Kodi event hook: a settle or move ring from the skin.

        :param sender: Announcement sender.
        :param method: Other.<kind>/<region>/<lists>/<mark>.
        :param data: Unused.
        """
        kind, _, rest = method.removeprefix("Other.").partition("/")
        if sender != log.ADDON_ID or kind not in KINDS:
            return
        region, lists, mark = (rest.split("/", 2) + ["", ""])[:3]
        ids = tuple(i for i in map(int, filter(None, lists.split("."))) if i in PROBES)
        container = ""
        if kind == "move":
            container, _, mark = mark.partition("/")
        self.ring(Request(kind, region, ids, mark, container))


class Server:
    """
    A listener thread, a pipeline thread (the newest request wins) and a rotation
    thread (the newest family turns).
    """

    def __init__(self) -> None:
        self.request, self.rung, self.stopped = None, Event(), False
        self.lock = RLock()  # again's test and ring, against the listener's ring
        self.heard = 0.0  # when the newest request arrived, for the log
        self.last = {}  # window id → its last arrival, for a move with no lists
        self.finished = None  # the last request served whole: a repeat does nothing
        self.blanks = set()  # served lists last bound with the blank item
        self.turn, self.handed = None, Event()  # the family 9300 last bound, and news
        Thread(target=self._listen, daemon=True).start()
        Thread(target=self._work, daemon=True).start()
        Thread(target=self._rotate, daemon=True).start()
        # The landing rang before the service ran (Kodi start, a restart): a move now,
        # its token for either region, as the probe serves the one on screen
        token = move_token("primary", "secondary")
        self._ring(Request("move", "primary", tuple(PROBES), token))

    def stop(self) -> None:
        """Release the threads: the listener within a second, the others at once."""
        self.stopped = True
        self.rung.set()
        self.handed.set()

    def again(self, list_id: int, mark: str = "") -> None:
        """
        Serve one list of the active window's last arrival again (the helper's own
        events: an album's play counts, TMDb's answer), as long as no newer ring
        waits; never cutting the lists of a serve still running.

        :param list_id: The list to serve.
        :param mark: The arrival that asked, if only while it is the last one.
        """
        with self.lock:
            last = self.last.get(getCurrentWindowId())
            pending = self.request
            if not (last and list_id in last.lists and self.current(mark or last.mark)):
                return
            if self.finished is last:  # this list, and those of an again in flight
                wanted = {list_id, *(pending.lists if pending.again else ())}
                lists = tuple(i for i in last.lists if i in wanted)
            else:  # the arrival is still being served: all of it again
                lists = last.lists
            self._ring(last._replace(lists=lists, again=True))

    def current(self, mark: str) -> bool:
        """
        Whether an arrival is the active window's last one, with no newer ring
        waiting (which serves its lists anyway).

        :param mark: The arrival's mark.
        :return: True while it is.
        """
        with self.lock:
            last = self.last.get(getCurrentWindowId())
            return bool(last) and last.mark == mark == self.request.mark

    def _ring(self, request: Request) -> None:
        """
        Hand the worker the newest request.

        :param request: The arrival heard.
        """
        with self.lock:
            self.request, self.heard = request, time.perf_counter()
            self.rung.set()

    def _listen(self) -> None:
        """Made here: Kodi calls a Monitor back on the thread that created it."""
        listener = _Listener(self._ring)
        while not self.stopped and not listener.waitForAbort(1):
            pass

    def _work(self) -> None:
        """Serve each newest request; a ring during a serve or a move's wait wins."""
        import resources.lib.plugin.handlers  # noqa: F401 warm before the first ring

        while self.rung.wait():
            self.rung.clear()
            if self.stopped:
                return
            request = self.request
            if request.kind == "move" and self.rung.wait(SETTLE):
                continue  # still moving: the next ring starts the wait again
            try:  # one bad item costs one serve (service-caches finding 1)
                self._serve(request)
            except Exception:
                log.exception(f"{self.__class__.__name__} → serve {request}")

    def _serve(self, arrival: Request) -> None:
        """
        Each list in turn while the arrival is the newest and live; a list a dialog
        covered before its bind is owed again. A move with no lists or region is the
        window's last request again (every served list, if none), with its token.

        :param arrival: The request heard.
        """
        window_id = getCurrentWindowId()
        request = arrival
        if arrival.kind == "move":
            last = self.last.get(window_id) or Request("move", "primary", (), "")
            request = arrival._replace(
                region=arrival.region or last.region,
                lists=arrival.lists or last.lists or tuple(PROBES),
            )
        if not request.mark:
            return
        if self._repeat(request):
            log.debug(
                f"{self.__class__.__name__} → repeat, not served: "
                f"{'.'.join(map(str, request.lists))} {request.mark}"
            )
            return
        if not request.again:  # an again keeps its arrival's lists for the next move
            with self.lock:
                self.last[window_id] = request
        stale = lambda: self.request is not arrival or not request.live()
        for list_id in request.lists:
            while (params := self._turn(list_id, window_id, stale)) is not None:
                if not params:
                    break  # not mounted in this window
                item = self._item(request)  # beside the probe: the item it was read for
                again = Again(self, list_id, request.mark)
                started = time.perf_counter()
                items = (
                    self._handle(params, stale, again, request.cursors)
                    if params != NONE
                    else []
                )
                handled = time.perf_counter()
                if items is None or stale():
                    return  # its guard stopped it, or a move came: a ring follows
                if topmost_window_id() == window_id:
                    self._bind(window_id, list_id, items, request.current, item)
                    if items:
                        self.blanks.discard(list_id)
                    else:
                        self.blanks.add(list_id)
                    if list_id == ARTWORK:
                        self._hand(Turn(request, window_id, *self._family(items)))
                    log.debug(
                        f"{self.__class__.__name__} → {list_id} served: "
                        f"{(started - self.heard) * 1000:.0f}ms ring to start, "
                        f"{(handled - started) * 1000:.0f}ms handler, "
                        f"{(time.perf_counter() - handled) * 1000:.0f}ms bind, "
                        f"{request.kind} {request.mark}"
                    )
                    break
            else:
                return
        with self.lock:
            if not request.again:
                self.finished = request
                return
            # An again ends with its arrival served whole: a repeat of that does
            # nothing, and the next again keys off the arrival, not this one's lists
            self.finished = self.last.get(window_id)
            if self.request is arrival:
                self.request = self.finished

    @staticmethod
    def _item(request: Request) -> str:
        """
        The item served, as list/position/dbid/: a settle's cursor names it; a move's
        container is read now (view: the cursor's list), so a return to it reads as
        served; a move with none names nothing.

        :param request: The resolved request.
        :return: The item, or empty.
        """
        if request.kind == "settle":
            return request.current
        list_id = request.container
        if list_id == "view":
            cursor = Window(10000).getProperty(f"artwork_cursor_{request.region}")
            list_id = cursor.partition("/")[0]
        if not list_id:
            return ""
        position, dbid = (
            infolabel(f"Container({list_id}).{label}")
            for label in ("CurrentItem", "ListItem.DBID")
        )
        return f"{list_id}/{position}/{dbid}/"

    def _repeat(self, request: Request) -> bool:
        """
        A settle equal to the last one served whole whose lists, read with the window
        on top, still hold its answer (one with no probe here holds none, the blank item
        only a none its probe still says): a layout rebuilt on the same item.

        :param request: The resolved request.
        :return: Whether to do nothing; a move never is.
        """
        return (
            request.kind == "settle"
            and request == self.finished
            and topmost_window_id() == getCurrentWindowId()  # under one, the dialog's
            and all(
                not (probe := infolabel(f"Control.GetLabel({PROBES[list_id]})"))
                or (
                    infolabel(f"Container({list_id}).ListItem.Property(current)")
                    == request.current
                    # The blank answered a none: art landing late (a reload) asks again
                    and (list_id not in self.blanks or probe == NONE)
                )
                for list_id in request.lists
            )
        )

    def _turn(
        self, list_id: int, window_id: int, stale: Callable[[], bool]
    ) -> str | None:
        """
        A list's probe once its window is on top (under a dialog Python reads the
        dialog's controls) and the probe doesn't say wait.

        :param list_id: The served list.
        :param window_id: Window the request is for.
        :param stale: Whether the request is over.
        :return: The probe's text (empty: not mounted); None once the request is over.
        """
        until = None  # from the first wait read: time under a dialog doesn't count
        while not (self.stopped or stale() or getCurrentWindowId() != window_id):
            if topmost_window_id() == window_id:
                params = infolabel(f"Control.GetLabel({PROBES[list_id]})")
                if params != WAIT:
                    return params
                until = until or time.monotonic() + WAIT_MAX
                if time.monotonic() > until:
                    return NONE
            if self.rung.wait(POLL):
                return None  # a newer ring: rung stays set for the worker
        return None

    @staticmethod
    def _handle(
        params: str,
        superseded: Callable[[], bool],
        again: Again,
        cursors: dict[str, str] | None = None,
    ) -> list[tuple] | None:
        """
        Run the handler a probe names, through plugin/main.py's dispatch; an error
        answers nothing (the blank item), so the skin's readers aren't held.

        :param params: The probe's text: info=…&… (a plugin URL's prefix is dropped).
        :param superseded: Whether a newer arrival has come, the guard's first test.
        :param again: Serves the list again for this arrival (TMDb's late answer).
        :param cursors: The settle's cursor by region (Request.cursors).
        :return: Its items, none for an unknown info; None if its guard stopped it.
        """
        # Here, not at the top: the service loads without the plugin stack
        from resources.lib.plugin.opts import ART_URLS
        from resources.lib.plugin.registry import info_handler

        query = params.removeprefix(PLUGIN)
        try:
            parsed = parse_plugin_argv(["", "", query], raw=ART_URLS)
            handler = info_handler(parsed, superseded, again, query, cursors)
            return handler() if handler else []
        except Exception:
            log.exception(f"Server → handler for {query}")
            return []

    @staticmethod
    def _family(items: list[tuple]) -> tuple[str, tuple[str, ...]]:
        """
        9300's bound identity and multiart family, read off its item (no GUI read).

        :param items: The handler's items, as bound.
        :return: The identity and the family's URLs, main first; empty for none.
        """
        if not items:
            return "", ()
        listitem = items[0][1]
        keys = chain(("multiart",), (f"multiart{i}" for i in count(1)))
        family = tuple(takewhile(bool, map(listitem.getArt, keys)))
        return listitem.getProperty("identity"), family

    def _hand(self, turn: Turn) -> None:
        """
        Give the rotation 9300's new bind: its family turns from slide 1 (slide 0 is
        9300's own art), a family of one stops the last, and an again of the same
        arrival, window, identity and family keeps the running turn and its dwell.

        :param turn: The bind's arrival, window, identity and family.
        """
        if self.turn and (self.turn.request.mark, *self.turn[1:]) == (
            turn.request.mark,
            *turn[1:],
        ):
            return
        self.turn = turn if len(turn.family) > 1 else None
        self.handed.set()

    def _rotate(self) -> None:
        """Turn the family last handed; a new one, or the service's stop, ends it."""
        from resources.lib.art.multiart import order_multiart

        while self.handed.wait():
            self.handed.clear()
            if self.stopped:
                return
            if not (turn := self.turn):
                continue
            beat = time.monotonic()
            try:  # one bad slide costs its family's turn
                for url in islice(cycle(order_multiart(turn.family)), 1, None):
                    # From the last beat or a late bind, so a slow slide never bunches
                    # the next ones
                    beat = max(beat, time.monotonic()) + DWELL
                    if self._waited(beat - LEAD, turn):
                        break
                    started = time.perf_counter()
                    items = self._slide(turn, url)
                    made = time.perf_counter() - started
                    if self._waited(beat, turn):
                        break
                    if items and topmost_window_id() == turn.window_id:
                        self._bind(
                            turn.window_id, SLIDES, items, turn.request.current, ""
                        )
                        log.debug(
                            f"{self.__class__.__name__} → {SLIDES} turned: "
                            f"{made * 1000:.0f}ms slide, {turn.request.mark}"
                        )
            except Exception:
                log.exception(f"{self.__class__.__name__} → turn {turn.request}")
            if self.turn is turn:
                self.turn = None  # ended or failed: the same family handed again turns

    def _waited(self, until: float, turn: Turn) -> bool:
        """
        Wait until a moment of the turn's dwell; True if the turn ended meanwhile.

        :param until: The monotonic time to wait for.
        :param turn: The family turning.
        :return: True once a new family or the stop is handed, or the turn is over.
        """
        return self.handed.wait(max(0.0, until - time.monotonic())) or not (
            self._turning(turn)
        )

    def _turning(self, turn: Turn) -> bool:
        """
        Whether a family still turns: no newer ring (an again keeps the mark), its
        arrival's cursor or token is still the skin's, and a rail's still has focus.

        :param turn: The family turning.
        :return: True while it does.
        """
        region = turn.request.region
        return (
            self.request.mark == turn.request.mark
            and turn.request.live()
            # Back on the view the rail's cursor stands until the view's ring
            and (
                region != "secondary"
                or Window(10000).getProperty("focus_region") == region
            )
        )

    @staticmethod
    def _slide(turn: Turn, url: str) -> list[tuple] | None:
        """
        A slide's item for 9400, made with the slide probe's params, the logo read whole
        by its source, while the window is on top (under a dialog Python reads the
        dialog's controls).

        :param turn: The family turning.
        :param url: The slide.
        :return: The item, its art the slide's and its identity 9300's; None for none.
        """
        from resources.lib.art.multiart import slide_art
        from resources.lib.plugin.opts import ART_URLS, read_art_urls
        from resources.lib.plugin.setter import set_items

        if topmost_window_id() != turn.window_id:
            return None
        if (query := infolabel(f"Control.GetLabel({SLIDE_PROBE})")) in ("", NONE):
            return None
        params = parse_plugin_argv(["", "", query], raw=ART_URLS)
        art = slide_art(params | read_art_urls(params, infolabel, True), url)
        if "background" not in art:
            return None  # it wouldn't open: the slide on screen holds
        return set_items(
            [
                {
                    "file": plugin_path("artwork"),
                    "art": art,
                    "properties": {"identity": turn.identity},
                }
            ]
        )

    @staticmethod
    def _bind(
        window_id: int, list_id: int, items: list[tuple], current: str, item: str
    ) -> None:
        """
        Replace the list's items in one bind; the first names the arrival it answers
        and the item it served, for the skin's readiness test.

        :param window_id: Window holding the list.
        :param list_id: The served list.
        :param items: Handler items; none binds one blank item.
        :param current: The request's current, as Property(current).
        :param item: The item served, list/position/dbid/ (or empty), Property(item).
        """
        listitems = []
        for url, listitem, _ in items:
            listitem.setPath(url)  # a bind keeps no tuple url
            listitems.append(listitem)
        listitems = listitems or [ListItem(offscreen=True)]
        listitems[0].setProperties({"current": current, "item": item})
        # A new Window each bind: a kept one's ControlList rebinds all it was ever given
        window = Window(window_id)
        window.getControl(list_id).addItems(listitems)
