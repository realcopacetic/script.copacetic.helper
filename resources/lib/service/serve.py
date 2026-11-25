# author: realcopacetic

"""
Served focus calls: the skin rings when an item comes to rest or a selection changes,
naming the lists to fill and the hidden label (probe) holding each one's params, and
the warm service fills them in turn, each a list with no <content>, in the active
window or a dialog the ring names; a family an artwork row names slides for turns on
that list, a slide a beat, and an ongoing handler's line types on a thread of its own.
The skin's ring: resources/docs/service/serve.md.
"""

import time
from functools import cache
from itertools import chain, count, cycle, islice, takewhile
from threading import Event, RLock, Thread
from typing import Callable, NamedTuple

import xbmc
from xbmcgui import ListItem, Window, getCurrentWindowDialogId, getCurrentWindowId

from resources.lib.plugin.registry import runs_on
from resources.lib.shared import logger as log
from resources.lib.shared.parser import parse_plugin_argv
from resources.lib.shared.utilities import (
    condition,
    infolabel,
    plugin_path,
    topmost_window_id,
)

# NotifyAll(script.copacetic.helper,serve?lists=<list>:<probe>.…&mark=<Home property>
# &is=<its value>[&wait=<ms>][&window=<dialog>.…][&item=<container>][&echo=<text>]);
# bare, the skin's net: a probe on top no longer reads as its list's Property(params)
VERB = "serve"
LOAD = "serve_load"  # the window's load ring, without its is: the service's start
PLUGIN = "plugin://script.copacetic.helper/?"  # a plugin URL's, before its query
WAIT, NONE = "wait", "none"  # a probe's "not yet" and "nothing for this item"
POLL = 0.1  # seconds between looks while a dialog covers the window or a probe waits
# Seconds a probe may say wait before it counts as none: a backstop, so a rail that
# never lands isn't looked at for ever; one landing later leaves none, the net serves it
WAIT_MAX = 5
# A family's slide shows for the register's dwell it replaces, 4.8 s pause and 0.2 s
# fade, made LEAD seconds before its beat: its params as late as they can be
DWELL = 5.0
LEAD = 1.5


def _ids(text: str) -> tuple[int, ...]:
    """
    A ring's dot-separated ids.

    :param text: The field's text.
    :return: The ids, in order.
    """
    return tuple(map(int, filter(None, text.split("."))))


class Request(NamedTuple):
    """
    One arrival, as the skin rang it: its lists and their probes in serving order, the
    Home property naming the arrival (mark) and its value at the ring (is), and how to
    serve it. again marks the helper's own re-serve.
    """

    lists: tuple[tuple[int, int], ...] = ()
    mark: str = ""
    value: str = ""
    wait: float = 0.0  # seconds a newer ring may come first: a move's settle
    # The dialogs its lists are in; none: the active window
    windows: tuple[int, ...] = ()
    item: str = ""  # the container whose item a bind names, read at the serve
    echo: str = ""  # bound back as Property(echo)
    again: bool = False

    @classmethod
    def parse(cls, query: str) -> "Request":
        """
        A ring's fields: lists as <list>:<probe> pairs, ids dot-separated; no mark is
        the net's ring.

        :param query: The ring's query, past serve?.
        :return: The request.
        """
        params = parse_plugin_argv(["", "", query])
        pairs = filter(None, params.get("lists", "").split("."))
        return cls(
            tuple(tuple(map(int, pair.split(":"))) for pair in pairs),
            params.get("mark", ""),
            params.get("is", ""),
            int(params.get("wait") or 0) / 1000,
            _ids(params.get("window", "")),
            params.get("item", ""),
            params.get("echo", ""),
        )

    @property
    def ids(self) -> tuple[int, ...]:
        """Its lists, in serving order."""
        return tuple(list_id for list_id, _ in self.lists)

    @property
    def cursors(self) -> dict[str, str]:
        """Its mark by name, for a handler that keeps a settle's cursor."""
        return {self.mark: self.value}

    def live(self) -> bool:
        """Whether its mark is still the skin's: no arrival has come since."""
        return home_property(self.mark) == self.value


class Turn(NamedTuple):
    """A family to turn on the slides list its artwork row names, for that arrival."""

    request: Request
    window_id: int
    list_id: int  # the artwork list whose bind handed it
    slides: tuple[int, ...]  # the slides list and its probe; empty for none
    identity: str
    family: tuple[str, ...]


class Again(NamedTuple):
    """
    A served list's re-serve for its arrival, once a late answer lands (TMDb's,
    Deezer's); equal for one list and arrival, so a repeat serve asks once.
    """

    server: "Server"
    list_id: int
    value: str
    window_id: int

    def __call__(self) -> None:
        """Serve the list again, if its arrival is still the window's last one."""
        self.server.again(self.list_id, self.value, self.window_id)

    def current(self) -> bool:
        """
        Whether its arrival is still the window's last one, so worth fetching for; never
        once the service stops (Kodi exiting), so nothing aside holds its exit.
        """
        return not self.server.stopped and self.server.current(
            self.value, self.window_id
        )


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


def _token(mark: str) -> str:
    """
    A new arrival's token, written to its mark first, as the skin writes a move's.

    :param mark: The Home property the ring names.
    :return: The token, the ring's is.
    """
    token = f"m{time.monotonic_ns()}"
    _home().setProperty(mark, token)
    return token


def ring(message: str, **fields: str) -> None:
    """
    A ring from Python (a published search query, the view settings editor's row): the
    skin's message, with a new token in its mark as its is.

    :param message: The ring the skin passed: serve?…, with no is.
    :param fields: Fields to add (the editor's own window).
    """
    mark = Request.parse(message.partition("?")[2]).mark
    query = "".join(f"&{k}={v}" for k, v in (fields | {"is": _token(mark)}).items())
    xbmc.executebuiltin(f"NotifyAll({log.ADDON_ID},{message}{query})")


class _Listener(xbmc.Monitor):
    """Hears the skin's rings; only records them (it can run inside a serve's wait)."""

    def __init__(self, ring: Callable[[Request], None]) -> None:
        super().__init__()
        self.ring = ring

    def onNotification(self, sender: str, method: str, data: str) -> None:
        """
        Kodi event hook: a ring from the skin.

        :param sender: Announcement sender.
        :param method: Other.serve?<fields>, or Other.serve bare.
        :param data: Unused.
        """
        verb, _, query = method.removeprefix("Other.").partition("?")
        if sender == log.ADDON_ID and verb == VERB:
            self.ring(Request.parse(query))


class Server:
    """
    A listener thread, a pipeline thread (the newest request wins) and a rotation
    thread (the newest family turns).
    """

    def __init__(self) -> None:
        self.request, self.rung, self.stopped = Request(), Event(), False
        self.lock = RLock()  # again's test and ring, against the listener's ring
        self.heard = 0.0  # when the newest request arrived, for the log
        self.last = {}  # window id → its last arrival, for a ring with no lists
        self.finished = None  # the last request served whole, for again's lists
        # The running serve's lists not yet started (None: none runs), and those a late
        # answer asked again once started: served after it
        self.ahead, self.asked = None, set()
        self.busy = False  # a request is waiting, or being served: the net is let be
        self.net = False  # the net rang: the window on top's last request again
        self.failed = {}  # (window id, list) → the probe text its handler stopped on
        self.owed = {}  # (window id, list) → the arrival a late answer was refused for
        self.lines = {}  # window id → the list its ongoing handler serves (the line)
        self.infos = {}  # (window id, handler) → the list it last served
        self.binds = 0  # binds so far: a net serve that adds none quiets its window
        # Window id → its probes' texts when a net bound nothing: let be till one moves
        self.quiet = {}
        self.turn, self.handed = None, Event()  # the family last handed, and news
        Thread(target=self._listen, daemon=True).start()
        Thread(target=self._work, daemon=True).start()
        Thread(target=self._rotate, daemon=True).start()

    def stop(self) -> None:
        """Release the threads: the listener within a second, the others at once."""
        self.stopped = True
        self.rung.set()
        self.handed.set()

    def again(self, list_id: int, value: str = "", window_id: int = 0) -> None:
        """
        Serve one list of a window's last arrival again (the helper's own events: an
        album's play counts, TMDb's answer), as long as no newer ring waits (else it is
        owed to the arrival's next ring); while a serve of it runs, after that serve.

        :param list_id: The list to serve.
        :param value: The arrival that asked, if only while it is the last one.
        :param window_id: Its window; none: the topmost one served, else the active.
        """
        with self.lock:
            window_id = self._served(window_id)
            last = self.last.get(window_id)
            if not (last and self.current(value or last.value, window_id)):
                # A newer ring has the window: its arrival's next ring serves it
                if value:
                    self.owed[(window_id, list_id)] = value
                return
            if list_id not in last.ids:
                return
            pending = self.request
            # The line follows: a late answer can change its label (a tagline)
            asked = {list_id, *({self.lines.get(window_id)} & {*last.ids})}
            if self.ahead is not None:  # never cut a running serve's handler
                self.asked |= asked - {*self.ahead}
                return
            if self.finished is last:  # these lists, and those of an again rung
                wanted = {*asked, *(pending.ids if pending.again else ())}
                lists = tuple(pair for pair in last.lists if pair[0] in wanted)
            else:  # its serve stopped short (a guard): all of it again
                lists = last.lists
            self._ring(last._replace(lists=lists, again=True))

    def current(self, value: str, window_id: int) -> bool:
        """
        Whether an arrival is its window's last one, with no newer ring waiting (which
        serves its lists anyway).

        :param value: The arrival's value (is).
        :param window_id: Its window.
        :return: True while it is.
        """
        with self.lock:
            last = self.last.get(window_id)
            return bool(last) and last.value == value == self.request.value

    def served(self, info: str) -> int:
        """
        The list the topmost window served last with a handler (an album's bar), for
        again.

        :param info: The handler's name.
        :return: The list's id; 0 for none.
        """
        with self.lock:
            return self.infos.get((self._served(), info), 0)

    def _served(self, window_id: int = 0) -> int:
        """
        A window the service has served: the one asked, else the topmost served, else
        the active one.

        :param window_id: The window asked; 0 for none.
        :return: Its id; 0 for none served.
        """
        ids = (window_id,) if window_id else (topmost_window_id(), getCurrentWindowId())
        return next((i for i in ids if i in self.last), 0)

    def _ring(self, request: Request) -> None:
        """
        Hand the worker the newest request; the net's ring is let be while one waits
        or is served, which answers it.

        :param request: The arrival heard; no mark: the net's.
        """
        with self.lock:
            if not request.mark:
                if not (self.busy or self.rung.is_set()):
                    self.heard, self.net = time.perf_counter(), True
                    self.rung.set()
                return
            self.request, self.heard, self.net = request, time.perf_counter(), False
            self.quiet.clear()  # a ring: the net may heal what it binds
            self.rung.set()

    def _listen(self) -> None:
        """Made here: Kodi calls a Monitor back on the thread that created it."""
        listener = _Listener(self._ring)
        self._load()  # once it hears: a load after this rings it
        while not self.stopped and not listener.waitForAbort(1):
            pass

    @staticmethod
    def _texts(request: Request) -> tuple[str, ...]:
        """
        A request's probes' texts now, for the net's quiet test.

        :param request: The window's last request.
        :return: Each probe's text, in serving order.
        """
        return tuple(
            infolabel(f"Control.GetLabel({probe})") for _, probe in request.lists
        )

    def _load(self) -> None:
        """
        The window's load rang before the service could hear it (Kodi start, a
        restart): that ring now, under a new token.
        """
        if message := home_property(LOAD):
            request = Request.parse(message.partition("?")[2])
            self._ring(request._replace(value=_token(request.mark)))

    def _work(self) -> None:
        """Serve each newest request; a ring during a serve or a move's wait wins."""
        import resources.lib.plugin.handlers  # noqa: F401 warm before the first ring

        while True:
            self.busy = False  # idle: the net may ring
            self.rung.wait()
            self.busy = True  # before the clear: a net ring in between is let be
            self.rung.clear()
            if self.stopped:
                return
            with self.lock:
                request, net, self.net = self.request, self.net, False
                if net:  # the window on top's last request, as it was
                    window_id = topmost_window_id()
                    if not (request := self.last.get(window_id)):
                        continue
                    self.request = request
            texts = net and self._texts(request)  # before the serve: what it answers
            if net and self.quiet.get(window_id) == texts:
                continue  # no probe has changed since a net found nothing to bind
            if not net and request.wait and self.rung.wait(request.wait):
                continue  # still moving: the next ring starts the wait again
            binds = self.binds
            try:  # one bad item costs one serve (service-caches finding 1)
                self._serve(request, net)
            except Exception:
                log.exception(f"{self.__class__.__name__} → serve {request}")
            self.ahead = None  # one stopped short serves nothing it was asked
            if net and self.binds == binds:  # nothing it can bind: till a probe moves
                with self.lock:
                    if self.request is request:  # a ring since has the window
                        log.debug(f"{self.__class__.__name__} → net let be: {texts}")
                        self.quiet[window_id] = texts

    def _serve(self, arrival: Request, net: bool = False) -> None:
        """
        Each list in turn while the arrival is the newest and live, in its window; one
        covered before its bind is owed. With no lists: the window's last request again,
        under this arrival's mark.

        :param arrival: The request heard.
        :param net: The net's ring: a list whose handler stopped on this text is let be.
        """
        if not (window_id := self._window(arrival)):
            return
        request = arrival
        if not arrival.lists:
            if not (last := self.last.get(window_id)):
                return
            request = arrival._replace(lists=last.lists)
        if not request.again:  # an again keeps its arrival's lists for the next ring
            with self.lock:
                self.last[window_id] = request
        stale = lambda: self.request is not arrival or not request.live()
        self.asked = set()
        held = []  # lists that already held their answer
        for i, (list_id, probe) in enumerate(request.lists):
            self.ahead = request.ids[i + 1 :]
            retried = False
            while (params := self._turn(probe, window_id, stale)) is not None:
                if not params:
                    break  # not mounted in this window
                fields = parse_plugin_argv(["", "", params.removeprefix(PLUGIN)])
                info = fields.get("info", "")
                line = runs_on(info)  # a line types on past its answer
                # An again always serves, a line only once it no longer stands
                if (line or not request.again) and self._answers(
                    request, window_id, list_id, params, line
                ):
                    held.append(list_id)
                    break
                if net and self.failed.get((window_id, list_id)) == params:
                    break  # its handler stopped on this text: the net lets it be
                if line:
                    with self.lock:
                        self.lines[window_id] = list_id
                        # A late answer came while the line waited (a tagline): those
                        # lists first, at the serve's end, then the line once
                        if late := bool(self.asked - {list_id}):
                            self.asked.add(list_id)
                    if late:
                        break
                item = self._item(request)  # beside the probe: the item it was read for
                again = Again(self, list_id, request.value, window_id)
                # A line types on past its serve: only the service's stop ends it here,
                # its lease (the skin's scroll at a move) and guard do the rest
                superseded = self._stopped if line else stale
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
                    if stale():
                        return  # a move came: a ring follows
                    # Stopped twice on this text: the net lets it be, and goes on to
                    # the lists after it, for which no ring follows
                    self.failed[(window_id, list_id)] = params
                    if not net:
                        return
                    break
                # A started line binds under a dialog too: its item holds no reads
                if line or topmost_window_id() == window_id:
                    self._bind(
                        window_id,
                        list_id,
                        items,
                        request.value,
                        item,
                        request.echo,
                        params,
                    )
                    with self.lock:
                        self.binds += 1
                        self.failed.pop((window_id, list_id), None)
                        self.owed.pop((window_id, list_id), None)
                        if info:
                            self.infos[(window_id, info)] = list_id
                    slides = fields.get("slides", "")  # <list>:<probe>
                    if slides or (self.turn and self.turn[1:3] == (window_id, list_id)):
                        pair = tuple(map(int, slides.split(":"))) if slides else ()
                        family = self._family(items) if slides else ("", ())
                        self._hand(Turn(request, window_id, list_id, pair, *family))
                    log.debug(
                        f"{self.__class__.__name__} → {list_id} served: "
                        f"{(started - self.heard) * 1000:.0f}ms ring to start, "
                        f"{(handled - started) * 1000:.0f}ms handler, "
                        f"{(time.perf_counter() - handled) * 1000:.0f}ms bind, "
                        f"{request.mark} {request.value}"
                    )
                    break
            else:
                return
        if held:
            log.debug(
                f"{self.__class__.__name__} → repeat, not served: "
                f"{'.'.join(map(str, held))} {request.value}"
            )
        with self.lock:
            self.ahead = None
            # An again ends with its arrival served whole: the next again keys off the
            # arrival, not this one's lists
            self.finished = self.last.get(window_id) if request.again else request
            if self.request is not arrival:
                return
            if self.asked:  # late answers for lists it had started: those again
                # from the arrival's lists: an again's own are a part of them
                arrival_lists = self.last[window_id].lists
                lists = tuple(pair for pair in arrival_lists if pair[0] in self.asked)
                self._ring(request._replace(lists=lists, again=True))
            elif request.again:
                self.request = self.finished

    def _answers(
        self, request: Request, window_id: int, list_id: int, params: str, line: bool
    ) -> bool:
        """
        Whether a list already holds its answer: bound for this arrival from the same
        probe text (a layout rebuilt, the info tabs' return) and owed no late answer; a
        line, the same text while it stands. Read with the window on top.

        :param request: The resolved request.
        :param window_id: Window the request is for.
        :param list_id: The served list.
        :param params: Its probe's text now.
        :param line: Whether its handler is ongoing.
        :return: True when serving it again would bind what it holds.
        """
        bound = f"Container({list_id}).ListItem.Property"
        if infolabel(f"{bound}(params)") != params:
            return False
        if line:
            return not self._retired(params)
        return self.owed.get((window_id, list_id)) != request.value and (
            infolabel(f"{bound}(current)") == request.value
        )

    def _window(self, arrival: Request) -> int:
        """
        The window a request's lists are in: the active window, or the one of the
        dialogs it names on top, waited for under a menu (which of two stacked is meant
        shows only once it closes); 0 once none is open or the request is over.

        :param arrival: The request heard.
        :return: The window id, or 0.
        """
        if not arrival.windows:
            return getCurrentWindowId()
        while self.request is arrival and not self.stopped:
            if (top := getCurrentWindowDialogId()) in arrival.windows:
                return top
            if not any(condition(f"Window.IsActive({w})") for w in arrival.windows):
                return 0  # closed
            if self.rung.wait(POLL):
                return 0  # a newer ring: rung stays set for the worker
        return 0

    @staticmethod
    def _item(request: Request) -> str:
        """
        The item served, as list/position/dbid/: the container the ring names, read
        now (a cursor names its list), so a return to it reads as served; else the
        part of is before its visit, empty for a token.

        :param request: The resolved request.
        :return: The item, or empty.
        """
        if not request.item:
            head, slash, _ = request.value.rpartition("/")
            return head + slash  # no visit: a kept item matches
        if not (list_id := request.item.partition("/")[0]):
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
        :param cursors: The arrival's mark by name (Request.cursors).
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
        An artwork bind's identity and multiart family, read off its item (no GUI read).

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
        Give the rotation an artwork list's new bind: its family turns from slide 1
        (slide 0 is the list's own art), a family of one stops the last, and an again
        of the same arrival, lists, identity and family keeps the turn and its dwell.

        :param turn: The bind's arrival, window, lists, identity and family.
        """
        if self.turn and (self.turn.request.value, *self.turn[1:]) == (
            turn.request.value,
            *turn[1:],
        ):
            return
        self.turn = turn if turn.slides and len(turn.family) > 1 else None
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
            slides, probe = turn.slides
            beat = time.monotonic()
            try:  # one bad slide costs its family's turn
                for url in islice(cycle(order_multiart(turn.family)), 1, None):
                    # From the last beat or a late bind, so a slow slide never bunches
                    # the next ones
                    beat = max(beat, time.monotonic()) + DWELL
                    if self._waited(beat - LEAD, turn):
                        break
                    started = time.perf_counter()
                    slide = self._slide(turn, url)
                    made = time.perf_counter() - started
                    if self.handed.wait(max(0.0, beat - time.monotonic())):
                        break
                    # Asked after the read on top, which can wait out a frame (the GUI
                    # lock) in which a move lands
                    on_top = slide and topmost_window_id() == turn.window_id
                    if not self._turning(turn):
                        break
                    if on_top:
                        params = infolabel(f"Control.GetLabel({probe})")
                        if topmost_window_id() != turn.window_id:
                            continue  # a dialog answered the read: no slide this beat
                        if params != slide[1]:
                            break  # its params moved on (the rail no longer focused)
                        self._bind(
                            turn.window_id, slides, slide[0], turn.request.value, ""
                        )
                        log.debug(
                            f"{self.__class__.__name__} → {slides} turned: "
                            f"{made * 1000:.0f}ms slide, {turn.request.value}"
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
        Whether a family still turns: no newer ring (an again keeps the value), and its
        arrival's mark is still the skin's.

        :param turn: The family turning.
        :return: True while it does.
        """
        return self.request.value == turn.request.value and turn.request.live()

    @staticmethod
    def _slide(turn: Turn, url: str) -> tuple[list[tuple], str] | None:
        """
        A slide's item (its art the slide's, its identity the artwork list's), made
        with the slide probe's params, the logo read whole by its source, while the
        window is on top (under a dialog Python reads the dialog's controls).

        :param turn: The family turning.
        :param url: The slide.
        :return: The item and the params it was made with; None for none.
        """
        from resources.lib.art.multiart import slide_art
        from resources.lib.plugin.opts import ART_URLS, read_art_urls
        from resources.lib.plugin.setter import set_items

        if topmost_window_id() != turn.window_id:
            return None
        if (query := infolabel(f"Control.GetLabel({turn.slides[1]})")) in ("", NONE):
            return None
        params = parse_plugin_argv(["", "", query], raw=ART_URLS)
        art = slide_art(params | read_art_urls(params, infolabel, True), url)
        if topmost_window_id() != turn.window_id:
            return None  # a dialog that opened during the reads answered them
        if "background" not in art:
            return None  # it wouldn't open: the slide on screen holds
        item = {
            "file": plugin_path("artwork"),
            "art": art,
            "properties": {"identity": turn.identity},
        }
        return set_items([item]), query

    @staticmethod
    def _bind(
        window_id: int,
        list_id: int,
        items: list[tuple],
        current: str,
        item: str,
        echo: str = "",
        params: str = "",
    ) -> None:
        """
        Replace the list's items in one bind; the first names the arrival it answers,
        the item it served, the ring's echo and the probe text it was served from.

        :param window_id: Window holding the list.
        :param list_id: The served list.
        :param items: Handler items; none binds one blank item.
        :param current: The ring's is, as Property(current).
        :param item: The item served, list/position/dbid/ (or empty), Property(item).
        :param echo: The ring's echo, as Property(echo); empty for none.
        :param params: The probe's text, as Property(params), for the skin's net.
        """
        listitems = []
        for url, listitem, _ in items:
            listitem.setPath(url)  # a bind keeps no tuple url
            listitems.append(listitem)
        listitems = listitems or [ListItem(offscreen=True)]
        listitems[0].setProperties(
            {"current": current, "item": item, "echo": echo, "params": params}
        )
        # A new Window each bind: a kept one's ControlList rebinds all it was ever given
        window = Window(window_id)
        window.getControl(list_id).addItems(listitems)
