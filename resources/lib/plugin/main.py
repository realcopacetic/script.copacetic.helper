# author: realcopacetic

import sys

import xbmcplugin

from resources.lib.plugin.content import ALLOWED_INFO, PluginContent
from resources.lib.plugin.listing import PluginListing
from resources.lib.shared.parser import parse_params
from resources.lib.shared.utilities import log


class Main:
    """Entry point for plugins.

    Parses argv, dispatches content via `info`, and writes directory items
    back to Kodi using xbmcplugin.
    """

    def __init__(self) -> None:
        self._parse_argv()
        self.info = self.params.get("info")
        if self.info:
            self.run_plugin()
            log(f"PluginContent initialized with params: {self.params}")
        else:
            self.run_listing()
            log(f"PluginListing initialized with params: {self.params}")

    def _parse_argv(self) -> None:
        """Parse argv using parser (handles both plugin/script styles)."""
        try:
            self.params = parse_params(sys.argv, mode="plugin")
        except Exception as e:
            log(f"_parse_argv error: {e}")
            self.params = {}

    def run_plugin(self) -> None:
        """Dispatch a plugin info source (from ?info=...) and emit its items."""
        info = (self.info or "").lower()
        if info not in ALLOWED_INFO:
            log(f"Ignoring unknown info: {self.info}")
            return

        items = PluginContent(self.params).build(info)
        self._additems(items)

    def run_listing(self) -> None:
        """Emit the default plugin directory (top-level categories)."""
        items = PluginListing(self.params).build()
        self._additems(items)

    def _additems(self, items: list[tuple]) -> None:
        """Flush (url, ListItem, isFolder) tuples to Kodi and close the directory."""
        handle = int(sys.argv[1]) if len(sys.argv) > 1 else 0
        xbmcplugin.addDirectoryItems(handle, items)
        xbmcplugin.endOfDirectory(
            handle=handle, succeeded=True, updateListing=False, cacheToDisc=True
        )
