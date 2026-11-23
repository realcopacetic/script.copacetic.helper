# author: realcopacetic

"""
Served focus calls: the skin rings when an item comes to rest (settle) or a selection
changes with no focused-layout arrival (move), and the warm service fills each named
list in turn, each a list with no <content>. Notes:
coding-notes/copacetic/features/served-focus-calls.md.
"""

import time
from functools import partial
from threading import Event, RLock, Thread
from typing import Callable, NamedTuple

import xbmc
from xbmcgui import ListItem, Window, getCurrentWindowId

from resources.lib.shared import logger as log
from resources.lib.shared.parser import parse_plugin_argv
from resources.lib.shared.utilities import infolabel, topmost_window_id

# NotifyAll(script.copacetic.helper,<kind>/<region>/<lists, dot-separated>/<mark>);
# a move's mark is <container>/<token>: the list that moved (view: the cursor's list),
# or none, then the token in moved_<region>
KINDS = ("settle", "move")
PLUGIN = "plugin://script.copacetic.helper/?"  # a plugin URL's, before its query
# Served list → the hidden label holding its params, in serving order: the favourite's
# library item, which the others' favourite rows read, then details and the bar
PROBES = {9040: 6904, 9000: 6900, 9100: 6901, 9010: 6910}
WAIT, NONE = "wait", "none"  # a probe's "not yet" and "nothing for this item"
POLL = 0.1  # seconds between looks while a dialog covers the window or a probe waits
# Seconds a probe may say wait before it counts as none: a backstop, as each wait
# row ends with the state it waits on
WAIT_MAX = 5
SETTLE = 0.225  # a move's own settle, the skin's transition_0.75x


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

    def live(self) -> bool:
        """Whether its cursor or token is still the skin's: no move has come since."""
        prop = "artwork_cursor" if self.kind == "settle" else "moved"
        return Window(10000).getProperty(f"{prop}_{self.region}") == self.mark


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
    """A listener thread and a pipeline thread; the newest request wins."""

    def __init__(self) -> None:
        self.request, self.rung, self.stopped = None, Event(), False
        self.lock = RLock()  # again's test and ring, against the listener's ring
        self.heard = 0.0  # when the newest request arrived, for the log
        self.last = {}  # window id → its last arrival, for a move with no lists
        self.finished = None  # the last request served whole: a repeat does nothing
        Thread(target=self._listen, daemon=True).start()
        Thread(target=self._work, daemon=True).start()
        # The landing rang before the service ran (Kodi start, a restart): a move now,
        # its token for either region, as the probe serves the one on screen
        token = move_token("primary", "secondary")
        self._ring(Request("move", "primary", tuple(PROBES), token))

    def stop(self) -> None:
        """Release both threads: the listener within a second, the worker at once."""
        self.stopped = True
        self.rung.set()

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
            if (
                not last
                or list_id not in last.lists
                or mark not in ("", last.mark)
                or pending.mark != last.mark  # a newer ring: it serves the list anyway
            ):
                return
            if self.finished is last:  # this list, and those of an again in flight
                wanted = {list_id, *(pending.lists if pending.again else ())}
                lists = tuple(i for i in last.lists if i in wanted)
            else:  # the arrival is still being served: all of it again
                lists = last.lists
            self._ring(last._replace(lists=lists, again=True))

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
        if not request.mark or self._repeat(request):
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
                again = partial(self.again, list_id, request.mark)
                started = time.perf_counter()
                items = self._handle(params, stale, again) if params != NONE else []
                handled = time.perf_counter()
                if items is None or stale():
                    return  # its guard stopped it, or a move came: a ring follows
                if topmost_window_id() == window_id:
                    self._bind(window_id, list_id, items, request.current, item)
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
        A settle equal to the last one served whole, whose lists still hold its
        answer (a list with no probe here holds none): a layout rebuilt on the same
        item. A move is always an event, and a rebuilt window's lists start empty.

        :param request: The resolved request.
        :return: Whether to do nothing.
        """
        return (
            request.kind == "settle"
            and request == self.finished
            and all(
                infolabel(f"Container({list_id}).ListItem.Property(current)")
                == request.current
                or not infolabel(f"Control.GetLabel({PROBES[list_id]})")
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
        params: str, superseded: Callable[[], bool], again: Callable[[], None]
    ) -> list[tuple] | None:
        """
        Run the handler a probe names, through plugin/main.py's dispatch; an error
        answers nothing (the blank item), so the skin's readers aren't held.

        :param params: The probe's text: info=…&… (a plugin URL's prefix is dropped).
        :param superseded: Whether a newer arrival has come, the guard's first test.
        :param again: Serves the list again for this arrival (TMDb's late answer).
        :return: Its items, none for an unknown info; None if its guard stopped it.
        """
        # Here, not at the top: the service loads without the plugin stack
        from resources.lib.plugin.opts import ART_URLS
        from resources.lib.plugin.registry import info_handler

        query = params.removeprefix(PLUGIN)
        try:
            parsed = parse_plugin_argv(["", "", query], raw=ART_URLS)
            handler = info_handler(parsed, superseded, again, query)
            return handler() if handler else []
        except Exception:
            log.exception(f"Server → handler for {query}")
            return []

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
