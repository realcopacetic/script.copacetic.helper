# author: realcopacetic

import random
import time

from resources.lib.art.editor import ImageEditor
from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import (
    condition,
    infolabel,
    json_call,
    log,
    url_decode_path,
    window_property,
)


class SlideshowMonitor:
    """
    Manages dynamic background artwork for slideshows in Kodi.
    Supports videodb, musicdb and custom user sources.
    """

    MAX_FETCH_COUNT = 20

    def __init__(self, sqlite_handler=None):
        """
        Initializes the slideshow with optional SQLite and processing tools.

        :param sqlite_handler: Optional SQLiteHandler instance.
        """
        self.sqlite = sqlite_handler or SQLiteHandler()
        self.image_processor = ImageEditor(self.sqlite).image_processor
        self.slideshow_path = self._get_slideshow_path()
        self.slideshow_source = self._check_slideshow_source()
        self.fetch_count = 0
        self.art = []

    def background_slideshow(self, art_type=None):
        """
        Main method for updating artwork slideshow periodically for use in Kodi.

        :param art_type: Optional content type ("movies", "music", etc.).
        """
        self.art_type = art_type or "global"
        content_map = {"movies": "movies", "tvshows": "tvshows", "music": "artists"}

        self.art_types = (
            [
                content_map[k]
                for k in content_map
                if condition(f"Library.HasContent({k})")
            ]
            if self.art_type == "global"
            else (
                [
                    content_map[k]
                    for k in ["movies", "tvshows"]
                    if condition(f"Library.HasContent({k})")
                ]
                if self.art_type == "videos"
                else (
                    ["custom"]
                    if self.art_type == "custom"
                    else (
                        [content_map.get(self.art_type, self.art_type)]
                        if condition(f"Library.HasContent({self.art_type})")
                        else []
                    )
                )
            )
        )

        new_path, new_source = (
            self._get_slideshow_path(),
            self._check_slideshow_source(),
        )

        if (
            self.fetch_count == 0
            or not self.art
            or new_path != self.slideshow_path
            or new_source != self.slideshow_source
        ):
            self.slideshow_path, self.slideshow_source = new_path, new_source
            log(f"{self.__class__.__name__}: Fetching background art")
            self._get_art()

        self.fetch_count = (self.fetch_count + 1) % self.MAX_FETCH_COUNT
        self._set_art()

    def _get_art(self):
        """Fetches new artwork based on content type and source."""
        if not self.art_types:
            log(
                f"{self.__class__.__name__}: No slideshow artwork available, skipping fetch"
            )
            return

        self.art = []

        if "custom" in self.art_type:
            if not self.slideshow_path:
                log(
                    f"{self.__class__.__name__}: No custom slideshow path found, skipping fetch"
                )
                return

            # Fetch plugin art
            if "library" not in self.slideshow_source and condition(
                "Integer.IsGreater(Container(3300).NumItems,0)"
            ):
                log(f"{self.__class__.__name__}: Fetching plugin art")
                self._get_plugin_art()
                return

            # Fetch custom library art
            log(
                f"{self.__class__.__name__}: Fetching library art from {self.slideshow_path}"
            )
            query = json_call(
                "Files.GetDirectory",
                params={"directory": self.slideshow_path},
                sort={"method": "random"},
                limit=self.MAX_FETCH_COUNT,
                parent="get_directory",
            )
            for result in query.get("result", {}).get("files", []):
                item_type, item_id = result.get("type"), result.get("id")
                dbtype = "Video" if item_type != "artist" else "Audio"
                details_query = json_call(
                    f"{dbtype}Library.Get{item_type}Details",
                    params={"properties": ["art"], f"{item_type}id": item_id},
                    parent="get_item_details",
                )
                item_details = details_query.get("result", {}).get(
                    f"{item_type}details", {}
                )
                if (art_data := item_details.get("art", {})).get("fanart"):
                    self.art.append(
                        {"title": item_details.get("label", ""), **art_data}
                    )

        # Fetch predefined library art
        else:
            log(f"{self.__class__.__name__}: Fetching predefined library artwork")
            for art_type in self.art_types:
                dbtype = "Video" if art_type != "artists" else "Audio"
                query = json_call(
                    f"{dbtype}Library.Get{art_type}",
                    properties=["art"],
                    sort={"method": "random"},
                    limit=self.MAX_FETCH_COUNT,
                    parent="get_art",
                )
                self.art.extend(
                    {"title": result.get("label", ""), **result["art"]}
                    for result in query.get("result", {}).get(art_type, [])
                    if result.get("art", {}).get("fanart")
                )

        if len(self.art) > self.MAX_FETCH_COUNT:
            self.art = random.sample(self.art, self.MAX_FETCH_COUNT)
        log(
            (
                f"{self.__class__.__name__}: Total artwork found: {len(self.art)}"
                if self.art
                else f"{self.__class__.__name__}: WARNING - No artwork was found!"
            ),
            force=not self.art,
        )

    def _get_plugin_art(self):
        """Fetches artwork directly from plugin containers (e.g., widgets)."""
        num_items = int(infolabel("Container(3300).NumItems"))
        self.art.extend(
            {
                "title": infolabel(f"Container(3300).ListItem({i}).Label"),
                "fanart": fanart,
                "clearlogo": infolabel(f"Container(3300).ListItem({i}).Art(clearlogo)"),
            }
            for i in range(num_items)
            if (fanart := infolabel(f"Container(3300).ListItem({i}).Art(fanart)"))
            or (
                "folder" in (self.slideshow_source or "")
                and (fanart := infolabel(f"Container(3300).ListItem({i}).Art(thumb)"))
            )
        )

    def _get_slideshow_path(self):
        """
        Determines the correct slideshow path based on time of day.

        :returns: String path from skin setting.
        """
        current_hour = time.localtime().tm_hour
        start = int(infolabel("Skin.String(slideshow_start)") or 6)
        alt_start = int(infolabel("Skin.String(alt_slideshow_start)") or 20)

        is_alt_slideshow = (
            alt_start > start and (current_hour >= alt_start or current_hour < start)
        ) or (alt_start <= start and start > current_hour >= alt_start)

        slideshow_prefix = "alt_" if is_alt_slideshow else ""
        return infolabel(f"Skin.String({slideshow_prefix}slideshow_path)")

    def _check_slideshow_source(self):
        """
        Identifies whether slideshow source is a folder, plugin, or library.

        :returns: Source type string.
        """
        if "plugin://" in self.slideshow_path:
            return "plugin"
        return (
            "library"
            if any(
                x in self.slideshow_path
                for x in ("db://", "library://", ".xsp", ".xml")
            )
            else "folder"
        )

    def _set_art(self):
        """
        Selects and displays the next random fanart + optional clearlogo,
        writing these values to window properties for use within Kodi.
        """
        if not self.art:
            log(
                f"{self.__class__.__name__}: No art available, waiting for next fetch",
                force=True,
            )
            return

        def get_fanart(art):
            fanart = next((art.get(k) for k in art if "fanart" in k), None)
            return (
                url_decode_path(fanart[:-21])
                if "transform?size=thumb" in fanart
                else url_decode_path(fanart)
            )

        def process_clearlogo(clearlogo):
            if not clearlogo:
                return None

            processed = self.image_processor(
                url=url_decode_path(clearlogo),
                processes={
                    (
                        "clearlogo-billboard"
                        if "billboard" in clearlogo
                        else "clearlogo"
                    ): "crop"
                },
            )
            return (
                processed.get("clearlogo-billboard") or processed.get("clearlogo")
                if processed
                else None
            )

        art = self.art.pop(random.randrange(len(self.art)))
        fanart = get_fanart(art)
        clearlogo = process_clearlogo(
            art.get("clearlogo-billboard") or art.get("clearlogo")
        )

        for key, value in {
            "slideshow_fanart": fanart,
            "slideshow_clearlogo": clearlogo,
            "slideshow_title": art.get("title"),
        }.items():
            window_property(key, value=value)
