# author: realcopacetic

from typing import Any

import xbmcvfs
from PIL import Image

from resources.lib.art.cache import ArtworkCacheManager
from resources.lib.art.policy import ART_KEYS, ArtMeta, resolve_art_type
from resources.lib.art.processor import ImageProcessor
from resources.lib.shared.hash import HashManager
from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import BLURS, CROPS, infolabel, log


class ImageEditor:
    """
    Coordinates image processing and metadata extraction for artwork.
    Handles cropping, blurring, caching, and exposure of color metadata to Kodi.
    """

    PROCESS_CONFIG = {
        "blur": {"folder": BLURS, "extension": ".jpg"},
        "crop": {"folder": CROPS, "extension": ".png"},
    }

    def __init__(self, sqlite_handler: SQLiteHandler | None = None) -> None:
        """
        Initialize caches, processors, and database/session dependencies.

        :param sqlite_handler: Optional SQLite handler instance, defaults to a new one.
        """
        self.sqlite = sqlite_handler or SQLiteHandler()
        self.cache_manager = ArtworkCacheManager(self.sqlite, HashManager())
        self.processor = ImageProcessor()
        self.temp_folder = self.cache_manager.temp_folder

    def image_processor(
        self,
        processes: dict[str, str],
        source: str | None = None,
        url: str | None = None,
    ) -> list[dict[str, str]]:
        """
        Process one or more artwork types and return structured per-item metadata.

        :param processes: Mapping of {art_type: "crop"|"blur"} to run.
        :param source: Kodi infolabel source prefix. Required if no URL is provided.
        :param url: Explicit image path. Required if no source is provided.
        :returns: List of attribute dicts; one per art_type (e.g., {"category","processed_path","color",...}).
        """
        if not processes:
            log(
                f"{self.__class__.__name__}: No processes defined — expected mapping of {{art_type: 'crop'|'blur'}}."
            )
            return []

        if not source and not url:
            log(
                f"{self.__class__.__name__}: Missing both source and URL; nothing to process."
            )
            return []

        try:
            attributes = [
                self._handle_image(
                    art_type=art_type,
                    process=process,
                    source=source,
                    url=url,
                )
                for art_type, process in processes.items()
            ]
        except Exception as error:
            log(
                f"{self.__class__.__name__}: Error during image processing → {error}",
                force=True,
            )
            return []

        return [a for a in attributes if a]

    def _handle_image(
        self,
        art_type: str,
        process: str,
        source: str = "Container.ListItem",
        url: str | None = None,
    ) -> dict[str, Any] | None:
        """
        Resolve source URL, process/cache the image, and persist metadata.

        :param art_type: Artwork key (e.g. "clearlogo", "fanart").
        :param process: Processor name ("crop" or "blur").
        :param source: Optional Kodi infolabel source prefix for Art() lookups.
        :param url: Optional explicit URL to process for this art_type.
        :returns: Metadata dict including processed path and colors, or None.
        """
        art = (
            {art_type: url}
            if url
            else self._fetch_art_url(art_type, source) if source else None
        )
        if not art:
            return None

        original_url = next(iter(art.values()))
        if not original_url:
            return None

        extension = self.PROCESS_CONFIG.get(process)["extension"]
        self.cache_manager.prepare_cache(original_url, extension)

        if not (
            attributes := self.cache_manager.read_lookup(original_url)
            or self._run_processor(process, art)
        ):
            return None

        attributes["category"] = art_type
        self.cache_manager.write_lookup(art_type, attributes)
        return attributes

    def _run_processor(
        self, process: str, art: dict[str, str]
    ) -> dict[str, Any] | None:
        """
        Execute a processor for a single image and write the processed file.

        :param process: Processor name ("crop" or "blur").
        :param art: Mapping of {resolved_key: url} for the selected artwork.
        :returns: Dict with file paths and color metadata, or None on failure.
        """
        process_method = getattr(self.processor, process, None)
        if not process_method:
            return None

        _source_key, url = next(iter(art.items()), (None, None))
        folder = self.PROCESS_CONFIG.get(process)["folder"]
        source_path, destination_path = self.cache_manager.get_image_paths(folder)
        if not source_path:
            return None

        image = self._image_open(source_path)
        if not image:
            return None

        result = process_method(image)
        if not result or "image" not in result:
            return None

        fmt = result.get("format", "PNG")
        if fmt == "JPEG" and result["image"].mode != "RGB":
            img = result["image"]
            result["image"] = (
                img.convert("RGBA").convert("RGB")
                if img.mode in ("RGBA", "LA", "P")
                else img.convert("RGB")
            )

        with xbmcvfs.File(destination_path, "wb") as f:
            result["image"].save(f, result.get("format", "PNG"))
            log(
                f"{self.__class__.__name__}: File processed: {url} → {destination_path}"
            )

        if self.temp_folder in source_path:
            try:
                xbmcvfs.delete(source_path)
                log(f"{self.__class__.__name__}: Temp file deleted → {source_path}")
            except Exception:
                pass
        values = result.get("values", {})
        return ArtMeta.from_values(
            category=art["category"],
            original_url=url,
            processed_path=destination_path,
            cached_file_hash=self.cache_manager.cached_file_hash,
            values=values,
        ).to_dict()

    def _fetch_art_url(self, art_type: str, source: str):
        """
        Read artwork paths from Kodi infolabels and select the best candidate.

        :param art_type: Target artwork type to resolve (e.g. "clearlogo", "fanart").
        :param source: Kodi info label source prefix (e.g. "ListItem" or "Container.ListItem").
        :returns: Dict {chosen_key: path} if found, else {}.
        """
        candidates = {
            key: path
            for key in ART_KEYS.get(art_type, (art_type,))
            if (path := infolabel(f"{source}.Art({key})"))
        }
        choice = resolve_art_type(candidates, art_type)
        return {choice.target_key: choice.path} if choice.path else {}

    def _image_open(self, url: str) -> Image.Image | None:
        """
        Open an image from Kodi VFS via Pillow; skips unsupported formats.

        :param url: Kodi VFS or URL-like path to the image resource.
        :returns: PIL Image or None if missing/unsupported/unreadable.
        """
        if url.lower().endswith(".svg"):
            log(f"{self.__class__.__name__}: Skipping unsupported SVG → {url}")
            return None

        try:
            return Image.open(xbmcvfs.translatePath(url))
        except (FileNotFoundError, OSError) as error:
            log(
                f"{self.__class__.__name__}: Error opening image {url} → {error}",
                force=True,
            )
            return None
