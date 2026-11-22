# author: realcopacetic

"""
Served focus calls, step 0 (the spike): the skin rings on a settle and the warm
service fills a list with no <content>, timed in the log against the plugin call.
Notes: coding-notes/copacetic/features/served-focus-calls.md.
"""

import time
from threading import Event, Thread
from typing import Callable, NamedTuple

import xbmc
from xbmcgui import ListItem, Window, getCurrentWindowId

from resources.lib.shared import logger as log
from resources.lib.shared.parser import parse_plugin_argv
from resources.lib.shared.utilities import infolabel, topmost_window_id

RING = "Other.settle/"  # NotifyAll(script.copacetic.helper,settle/<lists>/<cursor>)
PLUGIN = "plugin://script.copacetic.helper/"
EMPTY = "special://skin/extras/empty/"
PROBES = {9002: 6902}  # served list → the hidden label holding its params
OWED_POLL = 0.1  # seconds between looks while a dialog covers the window


class Request(NamedTuple):
    """One arrival: the lists to serve, in order, the cursor it answers, when heard."""

    lists: tuple[int, ...]
    cursor: str
    heard: float


class _Listener(xbmc.Monitor):
    """Hears the skin's rings; only records them (it can run inside a serve's wait)."""

    def __init__(self, ring: Callable[[Request], None]) -> None:
        super().__init__()
        self.ring = ring

    def onNotification(self, sender: str, method: str, data: str) -> None:
        """
        Kodi event hook: a settle ring from the skin.

        :param sender: Announcement sender.
        :param method: Other.settle/<lists>/<cursor>.
        :param data: Unused.
        """
        if sender == log.ADDON_ID and method.startswith(RING):
            lists, _, cursor = method[len(RING) :].partition("/")
            ids = tuple(i for i in map(int, lists.split(".")) if i in PROBES)
            self.ring(Request(ids, cursor, time.perf_counter()))


class Server:
    """A listener thread and a pipeline thread; the newest request wins."""

    def __init__(self) -> None:
        self.request, self.rung, self.stopped = None, Event(), False
        Thread(target=self._listen, daemon=True).start()
        Thread(target=self._work, daemon=True).start()

    def stop(self) -> None:
        """Release both threads: the listener within a second, the worker at once."""
        self.stopped = True
        self.rung.set()

    def _ring(self, request: Request) -> None:
        """
        Hand the worker the newest request.

        :param request: The arrival heard.
        """
        self.request = request
        self.rung.set()

    def _listen(self) -> None:
        """Made here: Kodi calls a Monitor back on the thread that created it."""
        listener = _Listener(self._ring)
        while not self.stopped and not listener.waitForAbort(1):
            pass

    def _work(self) -> None:
        """Serve each newest request; a ring during a serve starts the next."""
        import resources.lib.plugin.handlers  # noqa: F401 warm before the first ring

        while self.rung.wait():
            self.rung.clear()
            if self.stopped:
                return
            request = self.request
            try:  # one bad item costs one serve (service-caches finding 1)
                self._serve(request)
            except Exception:
                log.exception(f"{self.__class__.__name__} → serve {request}")

    def _serve(self, request: Request) -> None:
        """
        Each list in turn, while the request is current; under a dialog Python reads
        the dialog's controls, so the request waits for its window to be on top.

        :param request: The arrival to answer.
        """
        window_id = getCurrentWindowId()
        for list_id in request.lists:
            while topmost_window_id() != window_id:
                if self.rung.wait(OWED_POLL) or getCurrentWindowId() != window_id:
                    return  # a newer ring (rung stays set) or the window left
            text = infolabel(f"Control.GetLabel({PROBES[list_id]})")
            if not text.startswith(PLUGIN) and text != EMPTY:
                continue  # not mounted in this window
            started = time.perf_counter()
            items = self._handle(text) if text != EMPTY else []
            handled = time.perf_counter()
            if self.request is not request:
                return
            self._bind(window_id, list_id, items, request.cursor)
            log.info(
                f"{self.__class__.__name__} → {list_id} served: "
                f"{(started - request.heard) * 1000:.0f}ms ring to start, "
                f"{(handled - started) * 1000:.0f}ms handler, "
                f"{(time.perf_counter() - handled) * 1000:.0f}ms bind, "
                f"cursor {request.cursor}"
            )

    @staticmethod
    def _handle(url: str) -> list[tuple]:
        """
        Run the plugin handler a URL names, through plugin/main.py's dispatch.

        :param url: The probe's plugin URL.
        :return: Its (url, ListItem, isFolder) items; none for an unknown info.
        """
        # Here, not at the top: the service loads without the plugin stack
        from resources.lib.plugin.opts import ART_URLS
        from resources.lib.plugin.registry import info_handler

        params = parse_plugin_argv(["", "", url[len(PLUGIN) :]], raw=ART_URLS)
        handler = info_handler(params)
        return (handler() or []) if handler else []

    @staticmethod
    def _bind(window_id: int, list_id: int, items: list[tuple], cursor: str) -> None:
        """
        Replace the list's items in one bind; the first carries the cursor it answers.

        :param window_id: Window holding the list.
        :param list_id: The served list.
        :param items: Handler items; none binds one blank item.
        :param cursor: The request's cursor, as Property(current).
        """
        listitems = []
        for url, listitem, _ in items:
            listitem.setPath(url)  # a bind keeps no tuple url
            listitems.append(listitem)
        listitems = listitems or [ListItem(offscreen=True)]
        listitems[0].setProperty("current", cursor)
        # A new Window each bind: a kept one's ControlList rebinds all it was ever given
        window = Window(window_id)
        window.getControl(list_id).addItems(listitems)
