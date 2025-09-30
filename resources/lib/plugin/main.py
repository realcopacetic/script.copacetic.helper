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
        try:
            self.params = parse_params(sys.argv)
        except Exception as e:
            log(f"_parse_argv error: {e}")
            self.params = {}
        log(f"PluginContent initialized with params: {self.params}")

    def run_plugin(self) -> None:
        """Dispatch a plugin action (from ?info=...) and emit its items."""
        li = []
        plugin = PluginContent(self.params, li)
        self._execute(plugin, self.info)
        self._additems(li)

    def run_listing(self) -> None:
        """Emit the default plugin directory (top-level categories)."""
        li = []
        PluginListing(self.params, li)
        self._additems(li)

    def _execute(self, plugin, action: str) -> None:
        name = action.lower()
        if name in ALLOWED_ACTIONS and hasattr(plugin, name):
            getattr(plugin, name)()
        else:
            log(f"Ignoring unknown action: {action}")

    def _additems(self, li: list[tuple]) -> None:
        handle = int(sys.argv[1]) if len(sys.argv) > 1 else 0
        xbmcplugin.addDirectoryItems(handle, li)
        xbmcplugin.endOfDirectory(handle=handle)
