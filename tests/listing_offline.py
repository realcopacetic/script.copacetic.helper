"""
Offline checks for the add-on's own directory (plugin/listing.py): the root's two
group folders and each group's folders, all plain folders (no info tag, content
files), on the Home rails' paths with no stamps, every one a listing handler that
needs no input; a path with no randomise= takes Copacetic's live seed.
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

from resources.lib.plugin import handlers, listing  # noqa: E402
from resources.lib.plugin.handlers import PluginHandlers  # noqa: E402
from resources.lib.plugin.registry import collect_info_handlers  # noqa: E402

BASE = "plugin://script.copacetic.helper/"
KODI = {2: "Music", 3: "Videos"}
SEED = {"limit": "20"}
VIDEO = {
    "Continue watching": {"info": "in_progress"},
    "Next up": {"info": "next_up"},
    "Random movies": {"info": "random_movies", "exclude_played_days": "14"} | SEED,
    "Random TV shows": {"info": "random_tvshows"} | SEED,
    "Random genre - movies": {"info": "random_genre", "type": "movie"} | SEED,
    "Random genre - TV shows": {"info": "random_genre", "type": "tvshow"} | SEED,
}
MUSIC = {
    "Speed dial": {"info": "speed_dial"},
    "Rediscover": {"info": "rediscover"} | SEED,
    "Random albums": {"info": "random_albums"} | SEED,
    "Random genre - albums": {"info": "random_genre", "type": "album"} | SEED,
    "Random genre - artists": {"info": "random_genre", "type": "artist"} | SEED,
}
# Listings the root must never offer: they need an item, artist, label or channel,
# serve the skin's own controls rather than a list to browse, or (daily_mixes) list
# cards only the skin's rail click plays
EXCLUDED = {
    "actor_credits",
    "art_artist",
    "art_details",
    "art_rail",
    "art_search",
    "artist_credits",
    "artwork",
    "broadcasts",
    "cast",
    "clean_name",
    "creator_credits",
    "daily_mixes",
    "director_credits",
    "discography",
    "epg_time_left",
    "favourite",
    "genre_credits",
    "genre_music",
    "lyrics",
    "lyrics_plain",
    "metadata",
    "multiart_family",
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
}


class Directory(unittest.TestCase):
    """PluginListing.build: the folders each level lists, and what it reads."""

    def build(
        self, group: str | None = None, content_type: str | None = None
    ) -> tuple[list, mock.Mock, ...]:
        with (
            mock.patch.object(sys, "argv", [BASE, "1", ""]),
            mock.patch.object(listing, "ListItem") as list_item,
            mock.patch.object(listing, "getLocalizedString", KODI.get),
            mock.patch.object(listing, "set_plugincontent") as content,
            mock.patch.object(listing, "ADDON") as addon,
        ):
            addon.getLocalizedString = STRINGS.get
            addon.getAddonInfo.return_value = "Copacetic Helper"
            items = listing.PluginListing().build(group, content_type)
        self.assertTrue(all(folder for _, _, folder in items))
        self.assertFalse(list_item.return_value.getVideoInfoTag.called)
        self.assertFalse(list_item.return_value.getMusicInfoTag.called)
        self.assertFalse(list_item.return_value.setInfo.called)
        return items, list_item, content

    @staticmethod
    def folders(items: list, list_item: mock.Mock) -> dict[str, dict[str, str]]:
        labels = [call.kwargs["label"] for call in list_item.call_args_list]
        urls = [urlsplit(url) for url, _, _ in items]
        assert {url.scheme + "://" + url.netloc + url.path for url in urls} == {BASE}
        return {label: dict(parse_qsl(url.query)) for label, url in zip(labels, urls)}

    def test_root_is_two_groups(self):
        items, list_item, content = self.build()
        self.assertEqual(
            self.folders(items, list_item),
            {"Videos": {"group": "video"}, "Music": {"group": "music"}},
        )
        content.assert_called_once_with(content="files", category="Copacetic Helper")

    def test_video_group_on_the_rails_paths(self):
        items, list_item, content = self.build("video")
        self.assertEqual(self.folders(items, list_item), VIDEO)
        content.assert_called_once_with(content="files", category="Videos")

    def test_music_group_on_the_rails_paths(self):
        items, list_item, content = self.build("music")
        self.assertEqual(self.folders(items, list_item), MUSIC)
        content.assert_called_once_with(content="files", category="Music")

    def test_an_unknown_group_is_an_empty_listing(self):
        items, _, content = self.build("pictures")
        self.assertEqual(items, [])
        content.assert_not_called()

    def test_opened_from_an_add_on_list_its_own_group(self):
        # Kodi's ?content_type= for a plugin that provides video and audio
        for content_type, folders in (("video", VIDEO), ("audio", MUSIC)):
            items, list_item, _ = self.build(content_type=content_type)
            self.assertEqual(self.folders(items, list_item), folders)
        items, list_item, _ = self.build(content_type="executable")
        self.assertEqual([*self.folders(items, list_item)], ["Videos", "Music"])

    def test_art_an_icon_alone_the_rails_or_the_groups(self):
        # no thumb: Copacetic's art cell falls back to ListItem.ActualIcon's glyph
        _, list_item, _ = self.build("video")
        arts = [call.args[0] for call in list_item.return_value.setArt.call_args_list]
        self.assertEqual(
            arts[:2],
            [{"icon": "icons/SpinnerGap.png"}] + [{"icon": "icons/FastForward.png"}],
        )
        _, list_item, _ = self.build()
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


class Seed(unittest.TestCase):
    """PluginHandlers.randomise: a folder's path has none, so it reads the live one."""

    def seed(self, params: dict[str, str], live: str = "8812") -> tuple[str, mock.Mock]:
        with mock.patch.object(handlers, "infolabel", return_value=live) as read:
            seed = PluginHandlers(params).randomise
        return seed, read

    def test_no_param_takes_copacetics_live_seed(self):
        seed, read = self.seed({"info": "random_albums"})
        self.assertEqual(seed, "8812")
        read.assert_called_once_with("Window(home).Property(random_seed)")

    def test_the_rails_seed_wins_and_reads_nothing(self):
        seed, read = self.seed({"randomise": "40"})
        self.assertEqual(seed, "40")
        read.assert_not_called()

    def test_an_empty_param_or_no_live_seed_is_a_fresh_order(self):
        self.assertEqual(self.seed({"randomise": ""})[0], "")
        self.assertEqual(self.seed({}, live="")[0], "")


if __name__ == "__main__":
    unittest.main()
