# author: realcopacetic

from typing import Any, Callable, Iterable, Mapping

import xbmcvfs
from PIL import Image

from resources.lib.art.cache import ArtworkCacheManager
from resources.lib.art.policy import (
    ART_SOURCE_KEYS,
    ArtMeta,
    ColorConfig,
    resolve_art_type,
)
from resources.lib.art.processor import ImageProcessor
from resources.lib.art.darken import DarkenSolution
from resources.lib.shared import logger as log
from resources.lib.shared.hash import HashManager
from resources.lib.shared.sqlite import ArtworkCacheHandler
from resources.lib.shared.utilities import (
    BLURS,
    CROPS,
    infolabel,
    to_float,
    validate_path,
)

RGB = tuple[int, int, int]


class ImageEditor:
    """
    Coordinates image processing and metadata extraction for artwork.
    Handles cropping, blurring, caching, and exposure of color metadata to Kodi.
    """

    PROCESS_CONFIG = {
        "blur": {"folder": BLURS, "extension": ".jpg"},
        "crop": {"folder": CROPS, "extension": ".png"},
        "analyze": {"folder": None, "extension": None},
    }

    # --- Public methods ---
    def __init__(self, sqlite_handler: ArtworkCacheHandler | None = None) -> None:
        """
        Initialize caches, processors, and database/session dependencies.

        :param sqlite_handler: Optional SQLite handler instance, defaults to a new one.
        """
        self.sqlite = sqlite_handler or ArtworkCacheHandler()
        self.cache_manager = ArtworkCacheManager(self.sqlite, HashManager())
        self.temp_folder = self.cache_manager.temp_folder
        self.cfg = ColorConfig()
        self.processor = ImageProcessor(self.cfg)
        self._session: dict[str, Any] = {}

    def image_processor(
        self,
        jobs: Iterable[Mapping[str, str]],
        source: str | None = None,
        **proc_kwargs: Any,
    ) -> list[dict[str, Any]]:
        """
        Process one or more artwork jobs into attribute dictionaries.

        :param jobs: Iterable of job specs with 'process', 'art_type', optional 'url'.
        :param source: Kodi infolabel source prefix. Required if no URL is provided.
        :param proc_kwargs: Global keyword arguments forwarded to all jobs.
        :return: List of attribute dicts; one per art_type (e.g., {"category","processed_path","color",...}).
        """
        try:
            attributes = [
                self._handle_image(
                    art_type=job.get("art_type", ""),
                    process=job.get("process", ""),
                    source=source,
                    url=(job.get("url") or "") or None,
                    **proc_kwargs,
                )
                for job in jobs
            ]
        except Exception as error:
            log.error(
                f"{self.__class__.__name__}: Error during image processing → {error}",
            )
            return []

        return [a for a in attributes if a]

    def compute_darken_runtime(
        self,
        url: str,
        overlay_enabled: bool = True,
        overlay_source: str | None = None,
        overlay_rects: str | None = None,
        overlay_frame: str | None = None,
        overlay_target: float | str | None = None,
    ) -> DarkenSolution | None:
        """
        Compute DarkenSolution for a single image.

        :param url: Image URL.
        :param overlay_enabled: Whether darken is active.
        :param overlay_source: Colour source override.
        :param overlay_rects: Rect string for sampling.
        :param overlay_frame: Frame size "w,h" for rect coordinates.
        :param overlay_target: Contrast target override.
        :return: DarkenSolution or None.
        """
        if not overlay_enabled:
            return None

        return self._darken_core(
            lambda: self._get_runtime_image(url=url),
            overlay_source=overlay_source,
            overlay_rects=overlay_rects,
            overlay_frame=overlay_frame,
            overlay_target=overlay_target,
        )

    # --- Private methods ---
    def _handle_image(
        self,
        art_type: str,
        process: str,
        source: str = "Container.ListItem",
        url: str | None = None,
        **proc_kwargs: Any,
    ) -> dict[str, Any] | None:
        """
        Resolve source URL, process the image, and return metadata.

        :param art_type: Artwork key (e.g. "clearlogo", "fanart").
        :param process: Processor name ("crop", "blur" or "analyze").
        :param source: Optional Kodi infolabel source prefix for Art() lookups.
        :param url: Optional explicit URL to process for this art_type.
        :param proc_kwargs: Extra keyword arguments forwarded to processor methods.
        :return: Metadata dict including processed path and colors, or None.
        """
        art = (
            {art_type: url}
            if url
            else self._fetch_art_url(art_type, source) if source else None
        )
        if not art:
            log.debug(
                f"{self.__class__.__name__} → _handle_image({art_type}) → "
                f"no art resolved for {source=}, {url=}",
            )
            return None

        original_url = next(iter(art.values()))
        if not original_url:
            log.debug(
                f"{self.__class__.__name__} → _handle_image({art_type}) → "
                f"original_url empty → {art=}",
            )
            return None

        config = self.PROCESS_CONFIG.get(process, {})
        extension = config.get("extension")
        if extension:
            self.cache_manager.prepare_cache(original_url, extension)

        attributes = self._run_processor(process, art, **proc_kwargs)
        if not attributes:
            return None

        log.debug(
            f"ImageEditor → Payload returned → {art_type=} → {attributes}",
        )
        attributes["category"] = art_type

        # Stash clearlogo color for downstream fanart (overlay_source=clearlogo).
        if art_type.startswith("clearlogo"):
            col = attributes.get("color")
            if col:
                self._session["clearlogo_color"] = col

        overlay_map = proc_kwargs.get("overlay_params") or {}
        opts = overlay_map.get(art_type)
        if opts and opts.enabled:
            solution = self._darken_core(
                lambda: self._get_runtime_image(attrs=attributes),
                overlay_source=opts.source,
                overlay_rects=opts.rects,
                overlay_frame=opts.frame,
                overlay_target=opts.target,
            )
            if solution:
                attributes["darken"] = solution.bg
                attributes["text_darken"] = solution.text

        return attributes

    def _fetch_art_url(self, art_type: str, source: str):
        """
        Read artwork paths from Kodi infolabels and select the best candidate.

        :param art_type: Target artwork type to resolve (e.g. "clearlogo", "fanart").
        :param source: Kodi info label source prefix (e.g. "ListItem" or "Container.ListItem").
        :return: Dict {chosen_key: path} if found, else {}.
        """
        candidates = {
            key: path
            for key in ART_SOURCE_KEYS.get(art_type, (art_type,))
            if (path := infolabel(f"{source}.Art({key})"))
        }
        log.debug(
            f"{self.__class__.__name__} → _fetch_art_url({art_type}, {source}) → {candidates=}",
        )
        choice = resolve_art_type(candidates, art_type)
        return {choice.target_key: choice.path} if choice.path else {}

    def _run_processor(
        self,
        process: str,
        art: dict[str, str],
        **proc_kwargs: Any,
    ) -> dict[str, Any] | None:
        """
        Execute a processor for a single image and optionally write the file.

        :param process: Processor name ("crop", "blur" or "analyze").
        :param art: Mapping of {resolved_key: url} for the selected artwork.
        :param proc_kwargs: Extra keyword arguments forwarded to processor methods.
        :return: Dict with file paths and color metadata, or None on failure.
        """
        process_method = getattr(self.processor, process, None)
        if not process_method:
            return None

        category, url = next(iter(art.items()), (None, None))
        if not url:
            return None

        config = self.PROCESS_CONFIG.get(process, {})
        folder = config.get("folder")
        if folder:
            source_path, destination_path = self.cache_manager.get_image_paths(folder)
            if not source_path:
                return None

            image = self._image_open(source_path)
            if not image:
                return None
        else:  # Runtime-only process (e.g. analyze): open directly from URL.
            source_path = url
            destination_path = ""
            image = self._get_runtime_image(attrs=None, url=url)
            if not image:
                return None

        result = process_method(image, **proc_kwargs)
        if not result or "image" not in result:
            return None

        processed_path = destination_path

        # Persist processed image only when folder is configured.
        if folder:
            with xbmcvfs.File(destination_path, "wb") as f:
                fmt = result.get("format", "PNG")
                if fmt == "JPEG":
                    result["image"].save(
                        f,
                        "JPEG",
                        quality=self.cfg.jpeg_quality,
                        optimize=self.cfg.jpeg_optimize,
                        progressive=self.cfg.jpeg_progressive,
                        subsampling=self.cfg.jpeg_subsampling,
                    )
                elif fmt == "PNG":
                    result["image"].save(
                        f,
                        "PNG",
                        optimize=self.cfg.png_optimize,
                        compress_level=self.cfg.png_compress_level,
                    )
                log.debug(
                    f"{self.__class__.__name__} → File processed: "
                    f"{url} → {destination_path}",
                )
        else:
            processed_path = ""

        if folder and self.temp_folder in source_path:
            try:
                xbmcvfs.delete(source_path)
                log.debug(
                    f"{self.__class__.__name__} → Temp file deleted → {source_path}",
                )
            except Exception:
                pass

        return {
            **ArtMeta.from_values(
                category=category,
                original_url=url,
                processed_path=processed_path,
                cached_file_hash=self.cache_manager.cached_file_hash,
                values=result.get("metadata", {}),
            ).to_dict(),
            **(
                {"_sample_frame": result["sample_frame"]}
                if "sample_frame" in result
                else {}
            ),
        }

    def _image_open(self, url: str) -> Image.Image | None:
        """
        Open an image from Kodi VFS via Pillow; skips unsupported formats.

        :param url: Kodi VFS or URL-like path to the image resource.
        :return: PIL Image or None if missing/unsupported/unreadable.
        """
        if url.lower().endswith(".svg"):
            log.debug(f"{self.__class__.__name__}: Skipping unsupported SVG → {url}")
            return None

        try:
            return Image.open(xbmcvfs.translatePath(url))
        except (FileNotFoundError, OSError) as error:
            log.error(
                f"{self.__class__.__name__}: Unable to open image {url} → {error}",
            )
            return None

    def _darken_core(
        self,
        get_image: Callable[[], Image.Image | None],
        *,
        overlay_source: str | None = None,
        overlay_rects: str | None = None,
        overlay_frame: str | None = None,
        overlay_target: float | str | None = None,
    ) -> DarkenSolution | None:
        """
        Compute a DarkenSolution for a resolved runtime image.

        :param get_image: Provider returning an image or None.
        :param overlay_source: Optional colour source override ("clearlogo" or hex).
        :param overlay_rects: Rect string for sampling.
        :param overlay_frame: Frame size "w,h" for rect coordinates.
        :param overlay_target: Target contrast ratio override.
        :return: DarkenSolution or None.
        """
        img = get_image()
        if img is None:
            return None

        resolved_source = overlay_source
        src = (overlay_source or "").strip().lower()
        if src == "clearlogo":
            hexc = self._session.get("clearlogo_color")
            resolved_source = hexc or None

        try:
            return self.processor.color_analyzer.darken.compute_solution_from_params(
                image=img,
                overlay_source=resolved_source,
                overlay_rects=overlay_rects,
                overlay_frame=overlay_frame,
                overlay_target=overlay_target,
            )
        except Exception as exc:
            log.error(f"ColorDarken: compute failed: {exc}")
            return None

    def _get_runtime_image(
        self, attrs: dict | None = None, url: str | None = None
    ) -> Image.Image | None:
        """
        Resolve a PIL Image for runtime analysis from local sources only (no network/VFS reads).
        Priority: in-memory sample → texture-cache local path → processed blur (from attrs).

        :param attrs: Optional metadata dict that may contain '_sample_frame' and/or 'processed_path'.
        :param url: Optional art URL used only to prime/locate the texture-cache path.
        :return: PIL Image ready for analysis, or None if no local source is available.
        """
        # prefer in-memory `_sample_frame` from this run
        if attrs and (img := attrs.pop("_sample_frame", None)):
            return img

        # local Kodi texture-cache path for original
        cache_local = str(self.cache_manager.cached_image_path or "")
        if not cache_local and url:
            try:
                self.cache_manager.prepare_cache(url, ".jpg")
                cache_local = str(self.cache_manager.cached_image_path or "")
            except Exception:
                cache_local = ""

        if cache_local and validate_path(cache_local):
            if im := self._image_open(cache_local):
                return im

        # fallback: processed (blurred) image
        if attrs and (cache_blur := attrs.get("processed_path")):
            if im := self._image_open(cache_blur):
                return im

        return None
