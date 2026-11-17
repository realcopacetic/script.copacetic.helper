# author: realcopacetic, sualfred

import sys
from urllib.parse import urlencode

from xbmcgui import ListItem

from resources.lib.shared.utilities import ADDON, ADDON_ID, set_plugincontent

LISTING = {
    "mixed": [{"name": ADDON.getLocalizedString(32601), "info": "in_progress"}],
    "tvshow": [{"name": ADDON.getLocalizedString(32600), "info": "next_up"}],
}


class PluginListing(object):
    """
    Generates and returns plugin-based ListItems for widget browsing categories.
    Used to expose widget routes via plugin content listing.
    """

    def build(self) -> list[tuple]:
        """Return (url, ListItem, isFolder) tuples for the top-level directory."""
        items = []
        for category, widgets in LISTING.items():
            for item in widgets:
                url = self._encode_url(info=item.get("info"), type=category)
                items.append(self._make_item(item["name"], url))

        set_plugincontent(content="files", category=ADDON.getAddonInfo("name"))
        return items

    def _encode_url(self, **kwargs: str) -> str:
        """
        Encodes parameters into a plugin-compatible URL.

        :param kwargs: Arbitrary keyword arguments to include in the query string.
        :return: URL string with encoded parameters.
        """
        filtered = {k: v for k, v in kwargs.items() if v}
        return f"{sys.argv[0]}?{urlencode(filtered)}"

    def _make_item(self, label: str, url: str) -> tuple[str, ListItem, bool]:
        """
        A folder item with no info tag, so skins read it as a plain folder.

        :param label: Display label for the ListItem.
        :param url: Plugin URL this item will trigger.
        :return: (url, ListItem, True).
        """
        icon = f"special://home/addons/{ADDON_ID}/resources/icon.png"
        li_item = ListItem(label=label, offscreen=True)
        li_item.setArt({"icon": "DefaultAddonVideo.png", "thumb": icon})
        return (url, li_item, True)
