# author: realcopacetic

import time

import xbmcvfs
from PIL import Image

from resources.lib.art.cache import ArtworkCacheManager
from resources.lib.art.processor import ImageProcessor
from resources.lib.shared.hash import HashManager
from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import (
    BLURS,
    CROPS,
    TEMPS,
    condition,
    infolabel,
    log,
    window_property,
)


class ImageEditor:
    """
    Coordinates image processing and metadata extraction for artwork.
    Handles cropping, blurring, caching, and exposure of color metadata to Kodi.
    """

    PROCESS_CONFIG = {
        "blur": {"folder": BLURS, "extension": ".jpg"},
        "crop": {"folder": CROPS, "extension": ".png"},
    }

    def __init__(self, sqlite_handler=None):
        self.sqlite = sqlite_handler or SQLiteHandler()
        self.cache_manager = ArtworkCacheManager(self.sqlite, HashManager())
        self.processor = ImageProcessor()
        self.temp_folder = TEMPS

    def image_processor(self, dbid=None, source=None, processes=None, url=None):
        """
        Processes one or more image types and returns processed paths and metadata.

        :param dbid: Optional database ID.
        :param source: Kodi container or source item.
        :param processes: Dict of {art_type: "crop" or "blur"}.
        :param url: Optional manual URL override.
        :returns: Dict of results per art_type.
        """
        if not processes:
            return {}

        try:
            attributes = [
                self._handle_image(
                    source=source,
                    url=url,
                    art_type=art_type,
                    process=process,
                )
                for art_type, process in processes.items()
            ]
        except Exception as error:
            log(
                f"{self.__class__.__name__}: Error during image processing → {error}",
                force=True,
            )
            return {}

        return {
            (
                f"{attr['category']}_{key}"
                if key in ["color", "contrast", "luminosity"]
                else attr["category"]
            ): attr[key]
            for attr in attributes
            if attr
            for key in ["processed", "color", "contrast", "luminosity"]
            if attr.get(key) is not None
        }

    def _handle_image(
        self,
        source="Container.ListItem",
        url=False,
        art_type="clearlogo",
        process="crop",
    ):
        """
        Retrieves or processes a single image and writes it to the lookup table.

        :returns: Metadata dict or None.
        """
        if not (
            art := {art_type: url} if url else self._fetch_art_url(source, art_type)
        ):
            return None

        original_url = next(iter(art.values()))
        extension = self.PROCESS_CONFIG.get(process)["extension"]
        self.cache_manager.prepare_cache(original_url, extension)

        attributes = self.cache_manager.read_lookup(
            original_url
        ) or self._run_processor(process, art)

        self.cache_manager.write_lookup(art_type, attributes)
        self._expose_to_kodi(attributes)
        return attributes

    def _run_processor(self, process, art):
        """
        Executes the processor and returns metadata.
        """
        process_method = getattr(self.processor, process, None)
        if not process_method:
            return None

        category, url = next(iter(art.items()), (None, None))
        folder = self.PROCESS_CONFIG.get(process)["folder"]
        source, destination = self.cache_manager.get_image_paths(folder)

        image = self._image_open(source)
        if not image:
            return None

        result = process_method(image)
        if not result or "image" not in result:
            return None

        with xbmcvfs.File(destination, "wb") as f:
            result["image"].save(f, result.get("format", "PNG"))
            log(f"{self.__class__.__name__}: File processed: {url} → {destination}")

        if self.temp_folder in source:
            xbmcvfs.delete(source)
            log(f"{self.__class__.__name__}: Temp file deleted → {source}")

        return {
            "category": category,
            "url": url,
            "processed": destination,
            "cached_file_hash": self.cache_manager.cached_file_hash,
            "color": result["metadata"]["color"],
            "contrast": result["metadata"]["contrast"],
            "luminosity": result["metadata"]["luminosity"],
        }

    def _fetch_art_url(self, source, art_type):
        """
        Retrieves artwork URL from a Kodi infolabel.

        :returns: Dict with {art_type: url} or False if not found.
        """
        if not self._wait_for_art():
            return {art_type: False}
        return {art_type: infolabel(f"{source}.Art({art_type})")}

    def _wait_for_art(self):
        """
        Waits briefly for artwork to populate in Kodi UI.
        """
        timeout = time.time() + 2

        if not condition("String.IsEmpty(Window(home).Property(art_loaded))"):
            return True

        while time.time() < timeout:
            if condition("!String.IsEmpty(Control.GetLabel(6010))"):
                window_property("art_loaded", value="true")
                return True
            xbmc.Monitor().waitForAbort(0.02)

        return False

    def _image_open(self, url):
        """
        Opens a Kodi VFS image path using PIL.
        """
        try:
            return Image.open(xbmcvfs.translatePath(url))
        except (FileNotFoundError, OSError) as error:
            log(
                f"{self.__class__.__name__}: Error opening image {url} → {error}",
                force=True,
            )
            return None

    def _expose_to_kodi(self, attributes):
        """
        Exposes color, contrast, and luminosity as Kodi window properties.
        """
        if not attributes:
            return

        for key in ["color", "contrast", "luminosity"]:
            value = attributes.get(key)
            if value is not None:
                window_property(key, str(value))
