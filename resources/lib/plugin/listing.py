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

    def __init__(self, params: dict[str, str]) -> None:
        """
        :param params: Dictionary of plugin parameters (unused).
        :param li: List container to append ListItems to.
        """
        self.params = params

    def build(self) -> list[tuple]:
        """Return (url, ListItem, isFolder) tuples for the top-level directory."""
        items = []
        for category, widgets in LISTING.items():
            for item in widgets:
                url = self._encode_url(info=item.get("info"), type=category)
                items.append(self._make_item(item["name"], url))

        set_plugincontent(
            content="plugins",
            category=ADDON.getLocalizedString(32604) or "Copacetic",
        )
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
        Creates and returns a ListItem tuple to the directory with proper art and info tags.

        :param label: Display label for the ListItem.
        :param url: Plugin URL this item will trigger.
        """
        icon = f"special://home/addons/{ADDON_ID}/resources/icon.png"
        li_item = ListItem(label=label, offscreen=True)
        tag = li_item.getVideoInfoTag()
        tag.setTitle(label)
        tag.setMediaType("video")
        li_item.setArt({"icon": "DefaultAddonVideo.png", "thumb": icon})
        return (url, li_item, True)
