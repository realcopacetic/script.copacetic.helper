# author: realcopacetic, sualfred

import sys
from urllib.parse import urlencode

from xbmc import getLocalizedString
from xbmcgui import ListItem

from resources.lib.shared.utilities import (
    ADDON,
    ADDON_ID,
    infolabel,
    set_plugincontent,
)

_SEED = {"randomise": "Window(home).Property(random_seed)"}
# The add-on's own directory: a folder per group, Kodi's string and icon, and in each
# a folder per Home rail the helper lists with no input: (add-on string, the rail's
# icon, its path's params, params read when the group lists, as the rail's $INFO).
# Random rows take the rails' default length; the rest list whole.
GROUPS = {
    "video": (
        3,
        "DefaultAddonVideo.png",
        (
            (32601, "SpinnerGap", {"info": "in_progress"}, {}),
            (32600, "FastForward", {"info": "next_up"}, {}),
            (
                32605,
                "Shuffle",
                {"info": "random_movies", "exclude_played_days": "14", "limit": "20"},
                _SEED,
            ),
            (32606, "SealQuestion", {"info": "random_tvshows", "limit": "20"}, _SEED),
            (
                32611,
                "FilmSlate",
                {"info": "random_genre", "type": "movie", "limit": "20"},
                _SEED,
            ),
            (
                32612,
                "MonitorPlay",
                {"info": "random_genre", "type": "tvshow", "limit": "20"},
                _SEED,
            ),
        ),
    ),
    "music": (
        2,
        "DefaultAddonMusic.png",
        (
            (
                32826,
                "DotsNine",
                {"info": "speed_dial"},
                {"v": "Window(home).Property(speed_dial_version)"},
            ),
            (32837, "Playlist", {"info": "daily_mixes"}, {"day": "System.Date(dd)"}),
            (
                32836,
                "ClockCounterClockwise",
                {"info": "rediscover", "limit": "20"},
                _SEED,
            ),
            (32610, "Headphones", {"info": "random_albums", "limit": "20"}, _SEED),
            (
                32613,
                "MusicNote",
                {"info": "random_genre", "type": "album", "limit": "20"},
                _SEED,
            ),
            (
                32614,
                "MicrophoneStage",
                {"info": "random_genre", "type": "artist", "limit": "20"},
                _SEED,
            ),
        ),
    ),
}


class PluginListing(object):
    """
    The add-on's own directory: plain folders that open the helper's listings, so
    they can be browsed or picked as widgets from Kodi's add-on browser.
    """

    def build(self, group: str | None = None) -> list[tuple[str, ListItem, bool]]:
        """
        The root's group folders, or a group's folders on its Home rails' paths; only
        an opened folder runs its listing.

        :param group: A GROUPS key; None for the root.
        :return: (url, ListItem, True) per folder.
        """
        if group is None:
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
                    ADDON.getLocalizedString(name),
                    f"icons/{icon}.png",
                    params | {key: infolabel(info) for key, info in live.items()},
                )
                for name, icon, params, live in folders
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
        A folder item with no info tag, so skins read it as a plain folder.

        :param label: Display label for the ListItem.
        :param icon: Its icon; the add-on's icon is its thumb.
        :param params: The plugin URL's params.
        :return: (url, ListItem, True).
        """
        thumb = f"special://home/addons/{ADDON_ID}/resources/icon.png"
        li_item = ListItem(label=label, offscreen=True)
        li_item.setArt({"icon": icon, "thumb": thumb})
        return (self._encode_url(**params), li_item, True)
