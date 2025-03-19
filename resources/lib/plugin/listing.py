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
    def __init__(self, params, li):
        self.li = li
        self.list_widgets()

    def list_widgets(self):
        for category, widgets in LISTING.items():
            for item in widgets:
                url = self._encode_url(info=item.get("info"), type=category)
                self.plugin_category = item["name"]
                self._add_item(item["name"], url)

    def _encode_url(self, **kwargs):
        kwargs = {key: value for key, value in kwargs.items() if value}
        return f"{sys.argv[0]}?{urlencode(kwargs)}"

    def _add_item(self, label, url):
        icon = f"special://home/addons/{ADDON_ID}/resources/icon.png"
        li_item = xbmcgui.ListItem(label=label, offscreen=True)
        videoInfoTag = li_item.getVideoInfoTag()
        videoInfoTag.setTitle(label)
        videoInfoTag.setMediaType("video")
        li_item.setArt({"icon": "DefaultAddonVideo.png", "thumb": icon})
        self.li.append((url, li_item, True))
        set_plugincontent(content="", category=self.plugin_category)
