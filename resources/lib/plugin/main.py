# author: realcopacetic

import xbmcplugin

from resources.lib.plugin.content import PluginContent, ALLOWED_ACTIONS
from resources.lib.shared.utilities import log, sys, parse_params
from resources.lib.plugin.listing import PluginListing


class Main:
    """Entry point for the helper plugin.

    Parses argv, dispatches actions via `info`, and writes directory items
    back to Kodi using xbmcplugin.
    """

    def __init__(self) -> None:
        self._parse_argv()
        self.info = self.params.get("info")
        if self.info:
            self.run_plugin()
        else:
            self.run_listing()

    def _parse_argv(self) -> None:
        """Parse argv using parser (handles both plugin/script styles)."""
        try:
            self.params = parse_params(sys.argv)
        except Exception as e:
            log(f"_parse_argv error: {e}")
            self.params = {}
        log(f"PluginContent initialized with params: {self.params}")

    def run_plugin(self) -> None:
        """Dispatch a plugin action (from ?info=...) and emit its items."""
        action = (self.info or "").lower()
        if action not in ALLOWED_ACTIONS:
            log(f"Ignoring unknown action: {self.info}")
            return
        
        items = PluginContent(self.params).build(action)
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
