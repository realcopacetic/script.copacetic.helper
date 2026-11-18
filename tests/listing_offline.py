"""
Offline checks for the add-on's own directory (plugin/listing.py): the root's two
group folders and each group's folders, all plain folders (no info tag, content
files), on the Home rails' paths with the live params read only when a group lists,
every one a listing handler that needs no input.
Run from the helper root: python tests/listing_offline.py
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qsl, urlsplit

from build_offline import HELPER, install_stubs

STAGE = Path(tempfile.mkdtemp())
install_stubs(HELPER, STAGE, STAGE, verbose=False)
vars(sys.modules["xbmc"]).update(  # imported names; listing's are patched below
    Monitor=None,
    getCacheThumbName=None,
    getLocalizedString=None,
    AudioStreamDetail=None,
    SubtitleStreamDetail=None,
    VideoStreamDetail=None,
)
sys.modules["xbmcplugin"].SORT_METHOD_LASTPLAYED = 0  # handlers imports it
sys.path.insert(0, str(HELPER))

from resources.lib.plugin import listing  # noqa: E402
from resources.lib.plugin.handlers import PluginHandlers  # noqa: E402
from resources.lib.plugin.registry import collect_info_handlers  # noqa: E402

BASE = "plugin://script.copacetic.helper/"
KODI = {2: "Music", 3: "Videos"}
LIVE = {
    "Window(home).Property(random_seed)": "8812",
    "Window(home).Property(speed_dial_version)": "5",
    "System.Date(dd)": "18",
}
SEED = {"randomise": "8812", "limit": "20"}
VIDEO = {
    "Continue watching": {"info": "in_progress"},
    "Next up": {"info": "next_up"},
    "Random movies": {"info": "random_movies", "exclude_played_days": "14"} | SEED,
    "Random TV shows": {"info": "random_tvshows"} | SEED,
    "Random genre - movies": {"info": "random_genre", "type": "movie"} | SEED,
    "Random genre - TV shows": {"info": "random_genre", "type": "tvshow"} | SEED,
}
MUSIC = {
    "Speed dial": {"info": "speed_dial", "v": "5"},
    "Daily mixes": {"info": "daily_mixes", "day": "18"},
    "Rediscover": {"info": "rediscover"} | SEED,
    "Random albums": {"info": "random_albums"} | SEED,
    "Random genre - albums": {"info": "random_genre", "type": "album"} | SEED,
    "Random genre - artists": {"info": "random_genre", "type": "artist"} | SEED,
}
# Listings the root must never offer: they need an item, artist, label or channel,
# or serve the skin's own controls rather than a list to browse
EXCLUDED = {
    "actor_credits",
    "artist_credits",
    "artwork",
    "broadcasts",
    "cast",
    "clean_name",
    "director_credits",
    "discography",
    "epg_time_left",
    "favourite",
    "genre_credits",
    "genre_music",
    "lyrics",
    "metadata",
    "multiart_tiles",
    "popularity_label",
    "progressbar",
    "reposition",
    "seasons",
    "similar_music",
    "soundtracks",
    "studio_credits",
    "text",
    "top_songs",
    "typewriter",
    "writer_credits",
}
STRINGS = {
    32600: "Next up",
    32601: "Continue watching",
    32605: "Random movies",
    32606: "Random TV shows",
    32610: "Random albums",
    32611: "Random genre - movies",
    32612: "Random genre - TV shows",
    32613: "Random genre - albums",
    32614: "Random genre - artists",
    32826: "Speed dial",
    32836: "Rediscover",
    32837: "Daily mixes",
}


class Directory(unittest.TestCase):
    """PluginListing.build: the folders each level lists, and what it reads."""

    def build(self, group: str | None = None) -> tuple[list, mock.Mock, ...]:
        with (
            mock.patch.object(sys, "argv", [BASE, "1", ""]),
            mock.patch.object(listing, "ListItem") as list_item,
            mock.patch.object(listing, "getLocalizedString", KODI.get),
            mock.patch.object(listing, "infolabel", side_effect=LIVE.get) as read,
            mock.patch.object(listing, "set_plugincontent") as content,
            mock.patch.object(listing, "ADDON") as addon,
        ):
            addon.getLocalizedString = STRINGS.get
            addon.getAddonInfo.return_value = "Copacetic Helper"
            items = listing.PluginListing().build(group)
        self.assertTrue(all(folder for _, _, folder in items))
        self.assertFalse(list_item.return_value.getVideoInfoTag.called)
        self.assertFalse(list_item.return_value.getMusicInfoTag.called)
        self.assertFalse(list_item.return_value.setInfo.called)
        return items, list_item, content, read

    @staticmethod
    def folders(items: list, list_item: mock.Mock) -> dict[str, dict[str, str]]:
        labels = [call.kwargs["label"] for call in list_item.call_args_list]
        urls = [urlsplit(url) for url, _, _ in items]
        assert {url.scheme + "://" + url.netloc + url.path for url in urls} == {BASE}
        return {label: dict(parse_qsl(url.query)) for label, url in zip(labels, urls)}

    def test_root_is_two_groups_and_reads_nothing(self):
        items, list_item, content, read = self.build()
        self.assertEqual(
            self.folders(items, list_item),
            {"Videos": {"group": "video"}, "Music": {"group": "music"}},
        )
        content.assert_called_once_with(content="files", category="Copacetic Helper")
        read.assert_not_called()

    def test_video_group_on_the_rails_paths(self):
        items, list_item, content, _ = self.build("video")
        self.assertEqual(self.folders(items, list_item), VIDEO)
        content.assert_called_once_with(content="files", category="Videos")

    def test_music_group_on_the_rails_paths(self):
        items, list_item, content, _ = self.build("music")
        self.assertEqual(self.folders(items, list_item), MUSIC)
        content.assert_called_once_with(content="files", category="Music")

    def test_no_seed_lists_a_fresh_order(self):
        with mock.patch.dict(LIVE, {"Window(home).Property(random_seed)": ""}):
            items, list_item, _, _ = self.build("music")
        self.assertNotIn("randomise", self.folders(items, list_item)["Rediscover"])

    def test_art_an_icon_alone_the_rails_or_the_groups(self):
        # no thumb: Copacetic's art cell falls back to ListItem.ActualIcon's glyph
        _, list_item, _, _ = self.build("video")
        arts = [call.args[0] for call in list_item.return_value.setArt.call_args_list]
        self.assertEqual(
            arts[:2],
            [{"icon": "icons/SpinnerGap.png"}] + [{"icon": "icons/FastForward.png"}],
        )
        _, list_item, _, _ = self.build()
        arts = [call.args[0] for call in list_item.return_value.setArt.call_args_list]
        self.assertEqual(
            arts, [{"icon": "DefaultVideo.png"}, {"icon": "DefaultAudio.png"}]
        )

    def test_every_folder_a_handler_that_needs_no_input(self):
        handlers = collect_info_handlers(PluginHandlers({}))
        infos = {params["info"] for params in (VIDEO | MUSIC).values()}
        self.assertLessEqual(infos, handlers.keys())
        self.assertFalse(infos & EXCLUDED)
        # every handler is either offered or excluded on purpose
        self.assertEqual(handlers.keys() - infos - EXCLUDED, set())


if __name__ == "__main__":
    unittest.main()
