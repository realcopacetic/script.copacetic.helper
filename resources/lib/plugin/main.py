# author: realcopacetic

import sys
import time

import xbmcplugin

from resources.lib.plugin.listing import PluginListing
from resources.lib.plugin.opts import ART_URLS
from resources.lib.plugin.registry import LOG_TAG, info_handler
from resources.lib.shared import logger as log
from resources.lib.shared.parser import parse_plugin_argv


class Main:
    """Entry point for plugins.

    Parses argv, dispatches via `info`, and writes directory items with xbmcplugin.
    """

    def __init__(self, t0: float | None = None) -> None:
        self._t0 = t0
        self.params = self._parse_argv()
        self.info = self.params.get("info")
        if self.info:
            self.run_handler()
        else:
            self.run_listing()

    def _parse_argv(self) -> dict[str, str]:
        """
        Parse the plugin argv. Art URLs stay as Kodi passed them: the form its
        texture cache keys them by, and the one their whole reads extend.
        """
        return parse_plugin_argv(sys.argv, raw=ART_URLS)

    def run_handler(self) -> None:
        """Dispatch a plugin handler (from ?info=...) and emit its items."""
        fn = info_handler(self.params)
        if not fn:
            log.debug(f"Ignoring unknown info: {self.info}")
            self._additems([])  # an empty listing, not Kodi's "Error getting"
            return

        imports_ms = (time.perf_counter() - self._t0) * 1000 if self._t0 else -1
        log.debug(
            f"{LOG_TAG} initialized ({imports_ms:.0f}ms imports) with params: {self.params}"
        )
        self._additems(fn() or [])

    def run_listing(self) -> None:
        """Emit the add-on's own directory: the root, or a group's folders."""
        log.debug(f"PluginListing initialized")
        items = PluginListing().build(
            self.params.get("group"), self.params.get("content_type")
        )
        self._additems(items)

    def _additems(self, items: list[tuple]) -> None:
        """Flush (url, ListItem, isFolder) tuples to Kodi and close the directory."""
        handle = int(sys.argv[1]) if len(sys.argv) > 1 else 0
        xbmcplugin.addDirectoryItems(handle, items)
        xbmcplugin.endOfDirectory(
            handle=handle, succeeded=True, updateListing=False, cacheToDisc=bool(items)
        )
