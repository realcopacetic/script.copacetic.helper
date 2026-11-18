# author: realcopacetic, sualfred

import sys
from urllib.parse import urlencode

from xbmc import getLocalizedString
from xbmcgui import ListItem

from resources.lib.shared.utilities import ADDON, set_plugincontent

_OPENED_FROM = {"video": "video", "audio": "music"}  # Kodi's content_type=, a group
_RANDOM = {"limit": "20"}  # the rails' default length
# Per group, Kodi's string and icon, then (add-on string, the rail's icon, its path's
# params) per Home rail the helper lists with no input; no stamps, so paths stay live
GROUPS = {
    "video": (
        3,
        "DefaultVideo.png",
        (
            (32601, "SpinnerGap", {"info": "in_progress"}),
            (32600, "FastForward", {"info": "next_up"}),
            (
                32605,
                "Shuffle",
                {"info": "random_movies", "exclude_played_days": "14"} | _RANDOM,
            ),
            (32606, "SealQuestion", {"info": "random_tvshows"} | _RANDOM),
            (32611, "FilmSlate", {"info": "random_genre", "type": "movie"} | _RANDOM),
            (
                32612,
                "MonitorPlay",
                {"info": "random_genre", "type": "tvshow"} | _RANDOM,
            ),
        ),
    ),
    "music": (
        2,
        "DefaultAudio.png",
        (
            (32826, "DotsNine", {"info": "speed_dial"}),
            (32836, "ClockCounterClockwise", {"info": "rediscover"} | _RANDOM),
            (32610, "Headphones", {"info": "random_albums"} | _RANDOM),
            (32613, "MusicNote", {"info": "random_genre", "type": "album"} | _RANDOM),
            (
                32614,
                "MicrophoneStage",
                {"info": "random_genre", "type": "artist"} | _RANDOM,
            ),
        ),
    ),
}


class PluginListing(object):
    """
    The add-on's own directory: plain folders that open the helper's listings, so
    they can be browsed or picked as widgets from Kodi's add-on browser.
    """

    def build(
        self, group: str | None = None, content_type: str | None = None
    ) -> list[tuple[str, ListItem, bool]]:
        """
        The root's group folders, or one group's on its Home rails' paths: group=, else
        the one Kodi opened the add-on from. Only an opened folder runs its listing.

        :param group: A GROUPS key; None for the root.
        :param content_type: Kodi's content_type= (video, audio) from an add-on list.
        :return: (url, ListItem, True) per folder.
        """
        if (group := group or _OPENED_FROM.get(content_type)) is None:
            category = ADDON.getAddonInfo("name")
            items = [
                self._make_item(getLocalizedString(label), icon, {"group": key})
                for key, (label, icon, _) in GROUPS.items()
            ]
        else:
            label, _, folders = GROUPS[group]
            category = getLocalizedString(label)
            items = [
                self._make_item(
                    ADDON.getLocalizedString(name), f"icons/{icon}.png", params
                )
                for name, icon, params in folders
            ]
        set_plugincontent(content="files", category=category)
        return items

    def _encode_url(self, **kwargs: str) -> str:
        """
        Encodes parameters into a plugin-compatible URL.

        :param kwargs: Arbitrary keyword arguments to include in the query string.
        :return: URL string with encoded parameters.
        """
        filtered = {k: v for k, v in kwargs.items() if v}
        return f"{sys.argv[0]}?{urlencode(filtered)}"

    def _make_item(
        self, label: str, icon: str, params: dict[str, str]
    ) -> tuple[str, ListItem, bool]:
        """
        A folder item with no info tag and no thumb, so skins read it as a plain
        folder and draw its own icon.

        :param label: Display label for the ListItem.
        :param icon: Its icon.
        :param params: The plugin URL's params.
        :return: (url, ListItem, True).
        """
        li_item = ListItem(label=label, offscreen=True)
        li_item.setArt({"icon": icon})
        return (self._encode_url(**params), li_item, True)
