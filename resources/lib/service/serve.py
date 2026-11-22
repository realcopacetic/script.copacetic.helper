# author: realcopacetic

"""
Served focus calls: the skin rings when an item comes to rest (settle) or a selection
changes with no focused-layout arrival (move), and the warm service fills each named
list in turn, each a list with no <content>. Notes:
coding-notes/copacetic/features/served-focus-calls.md.
"""

import time
from threading import Event, Thread
from typing import Callable, NamedTuple

import xbmc
from xbmcgui import ListItem, Window, getCurrentWindowId

from resources.lib.shared import logger as log
from resources.lib.shared.parser import parse_plugin_argv
from resources.lib.shared.utilities import (
    focused_control_id,
    infolabel,
    topmost_window_id,
)

# NotifyAll(script.copacetic.helper,<kind>/<region>/<lists, dot-separated>/<mark>)
KINDS = ("settle", "move")
PLUGIN = "plugin://script.copacetic.helper/"
PROBES = {9010: 6910}  # served list → the hidden label holding its params
WAIT, NONE = "wait", "none"  # a probe's "not yet" and "nothing for this item"
POLL = 0.1  # seconds between looks while a dialog covers the window or a probe waits
# Seconds a probe may wait before it counts as none: a favourite that names no library
# item never resolves
WAIT_MAX = 5
SETTLE = 0.225  # a move's own settle, the skin's transition_0.75x


class Request(NamedTuple):
    """
    One arrival. A settle answers the cursor its hook wrote (artwork_cursor_<region>),
    a move the token its ring wrote (moved_<region>); the mark is that value.
    """

    kind: str
    region: str
    lists: tuple[int, ...]
    mark: str

    @property
    def current(self) -> str:
        """What the bound item names: the cursor's list/position/dbid/, or the token."""
        return (
            "/".join(self.mark.split("/")[:3]) + "/"
            if self.kind == "settle"
            else self.mark
        )

    def live(self) -> bool:
        """Whether its cursor or token is still the skin's: no move has come since."""
        prop = "artwork_cursor" if self.kind == "settle" else "moved"
        return Window(10000).getProperty(f"{prop}_{self.region}") == self.mark


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
        self.ring(Request(kind, region, ids, mark))


class Server:
    """A listener thread and a pipeline thread; the newest request wins."""

    def __init__(self) -> None:
        self.request, self.rung, self.stopped = None, Event(), False
        self.heard = 0.0  # when the newest request arrived, for the log
        self.last = {}  # window id → its last request, for a move with no lists
        self.finished = None  # the last request served whole: a repeat does nothing
        Thread(target=self._listen, daemon=True).start()
        Thread(target=self._work, daemon=True).start()

    def stop(self) -> None:
        """Release both threads: the listener within a second, the worker at once."""
        self.stopped = True
        self.rung.set()

    def again(self, list_id: int) -> None:
        """
        Serve one list of the active window's last request again, as a new arrival
        (the helper's own events: an album's play counts changed).

        :param list_id: The list to serve.
        """
        last = self.last.get(getCurrentWindowId())
        if last and list_id in last.lists:
            self.finished = None
            self._ring(last._replace(lists=(list_id,)))

    def _ring(self, request: Request) -> None:
        """
        Hand the worker the newest request.

        :param request: The arrival heard.
        """
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
        window's last request again, with the move's token (an info dialog's close).

        :param arrival: The request heard.
        """
        window_id = getCurrentWindowId()
        request = arrival
        if arrival.kind == "move" and (last := self.last.get(window_id)):
            request = arrival._replace(
                region=arrival.region or last.region, lists=arrival.lists or last.lists
            )
        if not request.lists or not request.mark or request == self.finished:
            return
        self.last[window_id] = request
        stale = lambda: self.request is not arrival or not request.live()
        for list_id in request.lists:
            while (params := self._turn(list_id, window_id, stale)) is not None:
                if not params:
                    break  # not mounted in this window
                started = time.perf_counter()
                items = self._handle(params, stale) if params != NONE else []
                handled = time.perf_counter()
                if items is None or stale():
                    return  # its guard stopped it, or a move came: a ring follows
                if topmost_window_id() == window_id:
                    item = (
                        request.current
                        if request.kind == "settle"
                        else self._identity(request.region, window_id)
                    )
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
        self.finished = request

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
        until = time.monotonic() + WAIT_MAX
        while not (self.stopped or stale() or getCurrentWindowId() != window_id):
            if topmost_window_id() == window_id:
                if (
                    params := infolabel(f"Control.GetLabel({PROBES[list_id]})")
                ) != WAIT:
                    return params
                if time.monotonic() > until:
                    return NONE
            if self.rung.wait(POLL):
                return None  # a newer ring: rung stays set for the worker
        return None

    @staticmethod
    def _identity(region: str, window_id: int) -> str:
        """
        The region's focused item now, as a cursor's list/position/dbid/: what a move
        served, read once its window is on top.

        :param region: The request's region.
        :param window_id: Window the request is for.
        :return: The identity; its list is the cursor's, else the focused control.
        """
        cursor = Window(10000).getProperty(f"artwork_cursor_{region}")
        list_id = cursor.partition("/")[0] or str(focused_control_id(window_id))
        item = f"Container({list_id})"
        position = infolabel(f"{item}.CurrentItem")
        return f"{list_id}/{position}/{infolabel(f'{item}.ListItem.DBID')}/"

    @staticmethod
    def _handle(params: str, superseded: Callable[[], bool]) -> list[tuple] | None:
        """
        Run the handler a probe names, through plugin/main.py's dispatch.

        :param params: The probe's text: info=…&… (a plugin URL's prefix is dropped).
        :param superseded: Whether a newer arrival has come, the guard's first test.
        :return: Its (url, ListItem, isFolder) items; none for an unknown info; None
            if its guard stopped it.
        """
        # Here, not at the top: the service loads without the plugin stack
        from resources.lib.plugin.opts import ART_URLS
        from resources.lib.plugin.registry import info_handler

        query = params.removeprefix(PLUGIN)
        handler = info_handler(
            parse_plugin_argv(["", "", query], raw=ART_URLS), superseded
        )
        return handler() if handler else []

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
        :param item: The item served, as list/position/dbid/, as Property(item).
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
