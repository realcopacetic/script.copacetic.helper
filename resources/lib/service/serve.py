# author: realcopacetic

"""
Served focus calls: the skin rings when an item comes to rest (settle) or a selection
changes with no focused-layout arrival (move), and the warm service fills each named
list in turn, each a list with no <content>, in the active window or, for a dialog's
region, the dialog; 9300's multiart family then turns on 9400, a slide a beat, and the
typewriter's line types on a thread of its own. Notes:
coding-notes/copacetic/features/served-focus-calls.md.
"""

import time
from functools import cache
from itertools import chain, count, cycle, islice, takewhile
from threading import Event, RLock, Thread
from typing import Callable, NamedTuple

import xbmc
from xbmcgui import ListItem, Window, getCurrentWindowDialogId, getCurrentWindowId

from resources.lib.shared import logger as log
from resources.lib.shared.parser import parse_plugin_argv
from resources.lib.shared.utilities import (
    INFO_DIALOGS,
    condition,
    infolabel,
    plugin_path,
    topmost_window_id,
)

# NotifyAll(script.copacetic.helper,<kind>/<region>/<lists, dot-separated>/<mark>);
# a move's mark is <container>/<token>: the list that moved (view: the cursor's list),
# or none, then the token in moved_<region>. A bare serve is the skin's net: a probe no
# longer reads as its list's Property(params)
KINDS = ("settle", "move", "serve")
PLUGIN = "plugin://script.copacetic.helper/?"  # a plugin URL's, before its query
# Served list → the hidden label holding its params, in serving order: the favourite's
# library item, which the others' favourite rows read, then details, the bar, artwork,
# the show logo and last the typewriter, whose label reads them
PROBES = {
    9040: 6904,
    9000: 6900,
    9100: 6901,
    9010: 6910,
    9300: 6930,
    9301: 6931,
    9020: 6920,
}


class Dialog(NamedTuple):
    """
    A dialog's region: its lists' probes, the dialogs it can be (none: any), and the
    Home property naming the dialog's open, stamped on each bind as Property(open).
    """

    probes: dict[int, int]
    windows: tuple[int, ...] = ()
    token: str = ""


# A dialog's regions, by the name its rings give: served in that dialog, not the active
# window. item: an info dialog's own item (its details, floor, popularity word, Plot
# tab's text and bar); infoscreen: its rails (their details, bar, floor and typewriter),
# whose probes hold the rail rows; preview: the view settings editor's backdrop blur
DIALOGS = {
    "item": Dialog(
        {9000: 6900, 9300: 6933, 9030: 6903, 9360: 6936, 9010: 6911},
        INFO_DIALOGS,
        "moved_item",
    ),
    "infoscreen": Dialog(
        {9100: 6901, 9010: 6910, 9300: 6930, 9020: 6920}, INFO_DIALOGS, "moved_item"
    ),
    "preview": Dialog({9370: 6937}),
}
# Lists a late answer (TMDb's, Deezer's) serves again: a move rung again serves them
# even when bound for its token, as an answer landing while a rail had focus is lost
ASIDE = (9000, 9030)
CURSORS = {"infoscreen": "primary"}  # a region whose settles answer another's cursor
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
# The typewriter's handler starts its line on a thread of its own and answers at once;
# the line runs until its lease or guard stops it, and stands while its params do
TYPEWRITER = 9020


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
        """What the bound item names: the cursor, visit and all, or the token."""
        return self.mark

    @property
    def cursor(self) -> str:
        """Whose cursor a settle answers (artwork_cursor_<cursor>): its region's own."""
        return CURSORS.get(self.region, self.region)

    @property
    def cursors(self) -> dict[str, str]:
        """A settle's cursor by its name, for a handler that keeps it; a move's none."""
        return {self.cursor: self.mark} if self.kind == "settle" else {}

    @property
    def probes(self) -> dict[int, int]:
        """Its region's lists' probes: a dialog's own, else the windows'."""
        return dialog.probes if (dialog := DIALOGS.get(self.region)) else PROBES

    def live(self) -> bool:
        """Whether its cursor or token is still the skin's: no move has come since."""
        prop = (
            f"artwork_cursor_{self.cursor}"
            if self.kind == "settle"
            else f"moved_{self.region}"
        )
        return home_property(prop) == self.mark


class Turn(NamedTuple):
    """A family to turn on 9400: 9300's bind for an arrival, in its window."""

    request: Request
    window_id: int
    identity: str
    family: tuple[str, ...]


class Again(NamedTuple):
    """
    A served list's re-serve for its arrival, once a late answer lands (TMDb's,
    Deezer's); equal for one list and arrival, so a repeat serve asks once.
    """

    server: "Server"
    list_id: int
    mark: str
    window_id: int

    def __call__(self) -> None:
        """Serve the list again, if its arrival is still the window's last one."""
        self.server.again(self.list_id, self.mark, self.window_id)

    def current(self) -> bool:
        """Whether its arrival is still the window's last one, so worth fetching for."""
        return self.server.current(self.mark, self.window_id)


@cache
def _home() -> Window:
    """Home, kept: Kodi destroys it only at shutdown; each Window(10000) made waits."""
    return Window(10000)


def home_property(key: str) -> str:
    """
    A Home property, through the kept Home: one graphics-lock wait, the GIL released
    (an infolabel read waits on the same lock holding it).

    :param key: Property name.
    :return: Its value, or empty.
    """
    return _home().getProperty(key)


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
    A move from Python (a published search query, a view settings editor change): the
    token, then the ring for the region's lists.

    :param region: Whose token, moved_<region>; a dialog's region names its lists.
    """
    lists = ".".join(map(str, Request("move", region, (), "").probes))
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
        probes = Request(kind, region, (), "").probes
        ids = tuple(i for i in map(int, filter(None, lists.split("."))) if i in probes)
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
        # The running serve's lists not yet started (None: none runs), and those a late
        # answer asked again once started: served after it
        self.ahead, self.asked = None, set()
        self.busy = False  # a request is waiting, or being served: the net is let be
        self.failed = {}  # (window id, list) → the probe text its handler stopped on
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

    def again(self, list_id: int, mark: str = "", window_id: int = 0) -> None:
        """
        Serve one list of a window's last arrival again (the helper's own events: an
        album's play counts, TMDb's answer), as long as no newer ring waits; while a
        serve of it runs, after that serve, unless the serve has yet to reach the list.

        :param list_id: The list to serve.
        :param mark: The arrival that asked, if only while it is the last one.
        :param window_id: Its window; with none, the topmost one served, else the active.
        """
        with self.lock:
            ids = (
                (window_id,)
                if window_id
                else (topmost_window_id(), getCurrentWindowId())
            )
            window_id = next((i for i in ids if i in self.last), 0)
            last = self.last.get(window_id)
            pending = self.request
            if not (
                last
                and list_id in last.lists
                and self.current(mark or last.mark, window_id)
            ):
                return
            # The line follows: a late answer can change its label (a tagline)
            asked = {list_id, *({TYPEWRITER} & {*last.lists})}
            if self.ahead is not None:  # never cut a running serve's handler
                self.asked |= asked - {*self.ahead}
                return
            if self.finished is last:  # these lists, and those of an again rung
                wanted = {*asked, *(pending.lists if pending.again else ())}
                lists = tuple(i for i in last.lists if i in wanted)
            else:  # its serve stopped short (a guard): all of it again
                lists = last.lists
            self._ring(last._replace(lists=lists, again=True))

    def current(self, mark: str, window_id: int) -> bool:
        """
        Whether an arrival is its window's last one, with no newer ring waiting (which
        serves its lists anyway).

        :param mark: The arrival's mark.
        :param window_id: Its window.
        :return: True while it is.
        """
        with self.lock:
            last = self.last.get(window_id)
            return bool(last) and last.mark == mark == self.request.mark

    def _ring(self, request: Request) -> None:
        """
        Hand the worker the newest request.

        :param request: The arrival heard.
        """
        with self.lock:
            if request.kind == "serve" and (self.busy or self.rung.is_set()):
                return  # the net's ring: the serve in hand answers it
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

        while True:
            self.busy = False  # idle: the net may ring
            self.rung.wait()
            self.rung.clear()
            self.busy = True
            if self.stopped:
                return
            request = self.request
            # An info dialog's item moves nothing: its open or the tabs' return
            if request.kind == "move" and request.region != "item":
                if self.rung.wait(SETTLE):
                    continue  # still moving: the next ring starts the wait again
            net = request.kind == "serve"
            if net:  # the window on top's last request, as it was
                with self.lock:
                    last = self.last.get(topmost_window_id())
                    if not last or self.request is not request:
                        continue
                    self.request = request = last
            try:  # one bad item costs one serve (service-caches finding 1)
                self._serve(request, net)
            except Exception:
                log.exception(f"{self.__class__.__name__} → serve {request}")
            self.ahead = None  # one stopped short serves nothing it was asked

    def _serve(self, arrival: Request, net: bool = False) -> None:
        """
        Each list in turn while the arrival is the newest and live, in the active window
        (a dialog region's: the topmost dialog); one covered before its bind is owed. A
        move with no lists or region: the window's last request (else every list) again.

        :param arrival: The request heard.
        :param net: The net's ring: a list whose handler stopped on this text is let be.
        """
        window_id = self._window(arrival.region)
        request = arrival
        if arrival.kind == "move":
            last = self.last.get(window_id) or Request("move", "primary", (), "")
            request = arrival._replace(
                region=arrival.region or last.region,
                lists=arrival.lists or last.lists or tuple(PROBES),
            )
        if not request.mark:
            return
        if not request.again:  # an again keeps its arrival's lists for the next move
            with self.lock:
                self.last[window_id] = request
        stale = lambda: self.request is not arrival or not request.live()
        dialog = DIALOGS.get(request.region)
        opened = dialog and dialog.token and Window(10000).getProperty(dialog.token)
        self.asked = set()
        held = []  # lists that already held their answer
        for i, list_id in enumerate(request.lists):
            self.ahead = request.lists[i + 1 :]
            probe = request.probes[list_id]
            retried = False
            while (params := self._turn(probe, window_id, stale)) is not None:
                if not params:
                    break  # not mounted in this window
                # An again always serves, a line only once it no longer stands
                if (list_id == TYPEWRITER or not request.again) and self._answers(
                    request, list_id, params
                ):
                    held.append(list_id)
                    break
                if net and self.failed.get((window_id, list_id)) == params:
                    break  # its handler stopped on this text: the net lets it be
                if list_id == TYPEWRITER:
                    with self.lock:
                        # A late answer came while the line waited (a tagline): those
                        # lists first, at the serve's end, then the line once
                        if late := bool(self.asked - {TYPEWRITER}):
                            self.asked.add(TYPEWRITER)
                    if late:
                        break
                item = self._item(request)  # beside the probe: the item it was read for
                again = Again(self, list_id, request.mark, window_id)
                # A line types on past its serve: only the service's stop ends it here,
                # its lease (the skin's scroll at a move) and guard do the rest
                superseded = self._stopped if list_id == TYPEWRITER else stale
                started = time.perf_counter()
                items = (
                    self._handle(params, superseded, again, request.cursors)
                    if params != NONE
                    else []
                )
                handled = time.perf_counter()
                if items is None and not (retried or stale()):
                    # Its guard or reads met a dialog (a menu, or one that flashed
                    # by): nothing rings after it, so the probe is read again on top
                    retried = True
                    continue
                if items is None or stale():
                    if not stale():  # stopped twice on this text: the net lets it be
                        self.failed[(window_id, list_id)] = params
                    return  # its guard stopped it, or a move came: a ring follows
                # A started line binds under a dialog too: its item holds no reads
                if list_id == TYPEWRITER or topmost_window_id() == window_id:
                    self._bind(
                        window_id,
                        list_id,
                        items,
                        request.current,
                        item,
                        opened or "",
                        params,
                    )
                    self.failed.pop((window_id, list_id), None)
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
        if held:
            log.debug(
                f"{self.__class__.__name__} → repeat, not served: "
                f"{'.'.join(map(str, held))} {request.mark}"
            )
        with self.lock:
            self.ahead = None
            # An again ends with its arrival served whole: a repeat of that does
            # nothing, and the next again keys off the arrival, not this one's lists
            self.finished = self.last.get(window_id) if request.again else request
            if self.request is not arrival:
                return
            if self.asked:  # late answers for lists it had started: those again
                lists = tuple(i for i in request.probes if i in self.asked)
                self._ring(request._replace(lists=lists, again=True))
            elif request.again:
                self.request = self.finished

    def _answers(self, request: Request, list_id: int, params: str) -> bool:
        """
        Whether a list already holds its answer: bound for this arrival from the same
        probe text (a layout rebuilt, the info tabs' return); a line, the same text while
        it stands. Read with the window on top.

        :param request: The resolved request.
        :param list_id: The served list.
        :param params: Its probe's text now.
        :return: True when serving it again would bind what it holds.
        """
        bound = f"Container({list_id}).ListItem.Property"
        if infolabel(f"{bound}(params)") != params:
            return False
        if list_id == TYPEWRITER:
            return not self._retired(params)
        # A dialog's move serves a late answer's lists, which a rail may have cut
        aside = request.kind == "move" and request.region in DIALOGS
        return not (aside and list_id in ASIDE) and (
            infolabel(f"{bound}(current)") == request.current
        )

    @staticmethod
    def _window(region: str) -> int:
        """
        The window a region's lists are in: the active window, or a dialog region's
        dialog: the topmost, else under a menu the open one whose token is Home's.

        :param region: The request's region.
        :return: The window id.
        """
        if not (dialog := DIALOGS.get(region)):
            return getCurrentWindowId()
        top = getCurrentWindowDialogId()
        if not dialog.windows or top in dialog.windows:
            return top
        active = [w for w in dialog.windows if condition(f"Window.IsActive({w})")]
        token = Window(10000).getProperty(dialog.token)
        owner = (w for w in active if Window(w).getProperty(dialog.token) == token)
        return next(owner, next(iter(active), top))

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
            return (
                request.mark.rpartition("/")[0] + "/"
            )  # no visit: a kept item matches
        list_id = request.container
        if list_id == "view":
            cursor = Window(10000).getProperty(f"artwork_cursor_{request.cursor}")
            list_id = cursor.partition("/")[0]
        if not list_id:
            return ""
        position, dbid = (
            infolabel(f"Container({list_id}).{label}")
            for label in ("CurrentItem", "ListItem.DBID")
        )
        return f"{list_id}/{position}/{dbid}/"

    def _stopped(self) -> bool:
        """
        Whether the service has stopped: a served line's only stop test here.

        :return: True once stopped.
        """
        return self.stopped

    @staticmethod
    def _retired(params: str) -> bool:
        """
        Whether the line a typewriter probe names is gone since it typed (the skin's
        scroll, a reset, its own stop): the same line then types again.

        :param params: The probe's text.
        :return: True once its control's lease says so.
        """
        from resources.lib.shared.helpers import TypewriterAnimation

        query = params.removeprefix(PLUGIN)
        target_id = parse_plugin_argv(["", "", query]).get("target_id")
        return bool(target_id) and TypewriterAnimation.retired(target_id)

    def _turn(
        self, probe: int, window_id: int, stale: Callable[[], bool]
    ) -> str | None:
        """
        A list's probe once its window is on top (under a dialog Python reads the
        dialog's controls) and the probe doesn't say wait.

        :param probe: The served list's probe.
        :param window_id: Window the request is for.
        :param stale: Whether the request is over.
        :return: The probe's text (empty: skip it); None once the request is over.
        """
        until = None  # from the first wait read: time under a dialog doesn't count
        while not (self.stopped or stale()):
            if topmost_window_id() == window_id:
                params = infolabel(f"Control.GetLabel({probe})")
                if topmost_window_id() != window_id:
                    continue  # read under a dialog that opened meanwhile: wait it out
                if params != WAIT:
                    return params
                if until is None:
                    log.debug(f"{self.__class__.__name__} → {probe} says wait")
                    until = time.monotonic() + WAIT_MAX
                if time.monotonic() > until:
                    log.debug(f"{self.__class__.__name__} → {probe} waited out: none")
                    return NONE
            elif not self._open(window_id):
                return None  # left, or the dialog closed
            if self.rung.wait(POLL):
                return None  # a newer ring: rung stays set for the worker
        return None

    @staticmethod
    def _open(window_id: int) -> bool:
        """
        Whether a request's window is still up under whatever covers it: the active
        window, or a dialog still open.

        :param window_id: Window the request is for.
        :return: True while it is.
        """
        return getCurrentWindowId() == window_id or condition(
            f"Window.IsVisible({window_id})"
        )

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
                    if self.handed.wait(max(0.0, beat - time.monotonic())):
                        break
                    # Asked after the read on top, which can wait out a frame (the GUI
                    # lock) in which a move lands
                    on_top = items and topmost_window_id() == turn.window_id
                    if not self._turning(turn):
                        break
                    if on_top:
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
        if topmost_window_id() != turn.window_id:
            return None  # a dialog that opened during the reads answered them
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
        window_id: int,
        list_id: int,
        items: list[tuple],
        current: str,
        item: str,
        opened: str = "",
        params: str = "",
    ) -> None:
        """
        Replace the list's items in one bind; the first names the arrival it answers,
        the item it served, a dialog's open and the probe text it was served from.

        :param window_id: Window holding the list.
        :param list_id: The served list.
        :param items: Handler items; none binds one blank item.
        :param current: The request's current, as Property(current).
        :param item: The item served, list/position/dbid/ (or empty), Property(item).
        :param opened: The dialog's open token, as Property(open); empty for none.
        :param params: The probe's text, as Property(params), for the skin's net.
        """
        listitems = []
        for url, listitem, _ in items:
            listitem.setPath(url)  # a bind keeps no tuple url
            listitems.append(listitem)
        listitems = listitems or [ListItem(offscreen=True)]
        listitems[0].setProperties(
            {"current": current, "item": item, "open": opened, "params": params}
        )
        # A new Window each bind: a kept one's ControlList rebinds all it was ever given
        window = Window(window_id)
        window.getControl(list_id).addItems(listitems)
