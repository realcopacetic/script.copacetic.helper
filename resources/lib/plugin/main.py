# author: realcopacetic

import sys
import time

import xbmcplugin

from resources.lib.plugin.handlers import PluginHandlers
from resources.lib.plugin.listing import PluginListing
from resources.lib.plugin.registry import LOG_TAG, collect_info_handlers
from resources.lib.shared import logger as log
from resources.lib.shared.parser import parse_params


class Main:
    """Entry point for plugins.

    Parses argv, dispatches content via `info`, and writes directory items
    back to Kodi using xbmcplugin.
    """

    def __init__(self, t0: float | None = None) -> None:
        self._t0 = t0
        self._parse_argv()
        self.info = self.params.get("info")
        if self.info:
            self.run_handler()
        else:
            self.run_listing()

    def _parse_argv(self) -> None:
        """Parse argv using parser (handles both plugin/script styles)."""
        try:
            self.params = parse_params(sys.argv, mode="plugin")
        except Exception as e:
            log.warning(f"_parse_argv error: {e}")
            self.params = {}

    def run_handler(self) -> None:
        """Dispatch a plugin handler (from ?info=...) and emit its items."""
        info = (self.info or "").strip().lower()
        ph = PluginHandlers(self.params)
        handlers = collect_info_handlers(ph)
        fn = handlers.get(info)
        if not fn:
            log.debug(f"Ignoring unknown info: {self.info}")
            return

        imports_ms = (time.perf_counter() - self._t0) * 1000 if self._t0 else -1
        log.debug(
            f"{LOG_TAG} initialized ({imports_ms:.0f}ms imports) with params: {self.params}"
        )
        items = fn()
        if not isinstance(items, (list, tuple)):
            items = []

        self._additems(items)

    def run_listing(self) -> None:
        """Emit the default plugin directory (top-level categories)."""
        log.debug(f"PluginListing initialized")
        items = PluginListing().build()
        self._additems(items)

    def _additems(self, items: list[tuple]) -> None:
        """Flush (url, ListItem, isFolder) tuples to Kodi and close the directory."""
        handle = int(sys.argv[1]) if len(sys.argv) > 1 else 0
        xbmcplugin.addDirectoryItems(handle, items)
        xbmcplugin.endOfDirectory(
            handle=handle, succeeded=True, updateListing=False, cacheToDisc=bool(items)
        )
