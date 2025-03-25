# author: realcopacetic, sualfred

import sys
from urllib.parse import urlencode

import xbmcgui

from resources.lib.shared.utilities import ADDON, ADDON_ID, set_plugincontent

LISTING = {
    "mixed": [{"name": ADDON.getLocalizedString(32601), "info": "in_progress"}],
    "tvshow": [{"name": ADDON.getLocalizedString(32600), "info": "next_up"}],
}


class PluginListing(object):
    """
    Generates and adds plugin-based ListItems for widget browsing categories.
    Used to expose widget routes via plugin content listing.
    """

    def __init__(self, params, li):
        """
        Initializes the PluginListing and adds ListItems immediately.

        :param params: Dictionary of plugin parameters (unused).
        :param li: List container to append ListItems to.
        :returns: None
        """
        self.li = li
        self.list_widgets()

    def list_widgets(self):
        """
        Builds widget items for each category in the LISTING dictionary.

        :returns: None
        """
        for category, widgets in LISTING.items():
            for item in widgets:
                url = self._encode_url(info=item.get("info"), type=category)
                self.plugin_category = item["name"]
                self._add_item(item["name"], url)

    def _encode_url(self, **kwargs):
        """
        Encodes parameters into a plugin-compatible URL.

        :param kwargs: Arbitrary keyword arguments to include in the query string.
        :returns: URL string with encoded parameters.
        """
        kwargs = {key: value for key, value in kwargs.items() if value}
        return f"{sys.argv[0]}?{urlencode(kwargs)}"

    def _add_item(self, label, url):
        """
        Creates and appends a ListItem to the directory with proper art and info tags.

        :param label: Display label for the ListItem.
        :param url: Plugin URL this item will trigger.
        :returns: None
        """
        icon = f"special://home/addons/{ADDON_ID}/resources/icon.png"
        li_item = xbmcgui.ListItem(label=label, offscreen=True)
        videoInfoTag = li_item.getVideoInfoTag()
        videoInfoTag.setTitle(label)
        videoInfoTag.setMediaType("video")
        li_item.setArt({"icon": "DefaultAddonVideo.png", "thumb": icon})
        self.li.append((url, li_item, True))
        set_plugincontent(content="", category=self.plugin_category)
