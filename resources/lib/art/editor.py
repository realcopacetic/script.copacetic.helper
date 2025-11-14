# author: realcopacetic

from typing import Any, Callable

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
from resources.lib.shared.hash import HashManager
from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import (
    BLURS,
    CROPS,
    ERROR,
    infolabel,
    log,
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
    }

    # --- Public methods ---
    def __init__(self, sqlite_handler: SQLiteHandler | None = None) -> None:
        """
        Initialize caches, processors, and database/session dependencies.

        :param sqlite_handler: Optional SQLite handler instance, defaults to a new one.
        """
        self.sqlite = sqlite_handler or SQLiteHandler()
        self.cache_manager = ArtworkCacheManager(self.sqlite, HashManager())
        self.temp_folder = self.cache_manager.temp_folder
        self.cfg = ColorConfig()
        self.processor = ImageProcessor(self.cfg)
        self._session: dict[str, Any] = {}

    def image_processor(
        self,
        processes: dict[str, str],
        source: str | None = None,
        url: str | None = None,
        **proc_kwargs: Any,
    ) -> list[dict[str, Any]]:
        """
        Process one or more artwork types and return structured per-item metadata.

        :param processes: Mapping of {art_type: "crop"|"blur"} to run.
        :param source: Kodi infolabel source prefix. Required if no URL is provided.
        :param url: Explicit image path. Required if no source is provided.
        :param proc_kwargs: Extra keyword arguments forwarded to processor methods

        :returns: List of attribute dicts; one per art_type (e.g., {"category","processed_path","color",...}).
        """
        if not processes:
            log(
                f"{self.__class__.__name__}: No processes defined — expected mapping of {{art_type: 'crop'|'blur'}}.",
                level=WARNING
            )
            return []

        if not source and not url:
            log(
                f"{self.__class__.__name__}: Missing both source and URL; nothing to process."
            )
            return []

        items = sorted(
            processes.items(),
            key=lambda kv: (not kv[0].startswith("clearlogo"), kv[0]),
        )
        try:
            attributes = [
                self._handle_image(
                    art_type=art_type,
                    process=process,
                    source=source,
                    url=url,
                    **proc_kwargs,
                )
                for art_type, process in items
            ]
        except Exception as error:
            log(
                f"{self.__class__.__name__}: Error during image processing → {error}",
                level=ERROR,
            )
            return []

        return [a for a in attributes if a]

    def compute_darken_runtime(
        self,
        url: str,
        overlay_enable: str | bool = "true",
        overlay_source: str | None = None,
        overlay_rects: str | None = None,
        overlay_target: float | str | None = None,
    ) -> int | None:
        """
        Compute a runtime darken value (0..100) for a single image using the cache-only resolver.
        Mirrors the in-pipeline path for consistent results; performs no DB writes.

        :param url: Kodi VFS/URL of the fanart to analyze (used only to locate local cache).
        :param overlay_enable: Bool-ish flag; returns None if not truthy.
        :param overlay_source: Hex text colour (e.g. 'fff0efef') or 'clearlogo' to use stashed colour.
        :param overlay_rects: Overlay sampling rects, e.g. "x,y,w,h" or "(x,y,w,h),(x,y,w,h)" in 1920x1080 space.
        :param overlay_target: Desired contrast target (float) or str convertible to float.
        :return: Darken percentage 0..100, or None if disabled/unavailable.
        """
        return self._darken_core(
            lambda: self._get_runtime_image(url=url),
            overlay_enable=overlay_enable,
            overlay_source=overlay_source,
            overlay_rects=overlay_rects,
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
        Resolve source URL, process/cache the image, and persist metadata.

        :param art_type: Artwork key (e.g. "clearlogo", "fanart").
        :param process: Processor name ("crop" or "blur").
        :param source: Optional Kodi infolabel source prefix for Art() lookups.
        :param url: Optional explicit URL to process for this art_type.
        :param proc_kwargs: Extra keyword arguments forwarded to processor methods
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
            or self._run_processor(process, art, **proc_kwargs)
        ):
            return None

        attributes["category"] = art_type
        self.cache_manager.write_lookup(art_type, attributes)

        # stash clearlogo color for downstream fanart (overlay_source=clearlogo)
        if art_type.startswith("clearlogo"):
            col = attributes.get("color")
            if col:
                self._session["clearlogo_color"] = col

        if art_type == "fanart":
            val = self._darken_core(
                lambda: self._get_runtime_image(attrs=attributes),
                overlay_enable=proc_kwargs.get("overlay_enable", ""),
                overlay_source=proc_kwargs.get("overlay_source"),
                overlay_rects=proc_kwargs.get("overlay_rects"),
                overlay_target=proc_kwargs.get("overlay_target"),
            )
            if val is not None:
                attributes["darken"] = val

        return attributes

    def _fetch_art_url(self, art_type: str, source: str):
        """
        Read artwork paths from Kodi infolabels and select the best candidate.

        :param art_type: Target artwork type to resolve (e.g. "clearlogo", "fanart").
        :param source: Kodi info label source prefix (e.g. "ListItem" or "Container.ListItem").
        :returns: Dict {chosen_key: path} if found, else {}.
        """
        candidates = {
            key: path
            for key in ART_SOURCE_KEYS.get(art_type, (art_type,))
            if (path := infolabel(f"{source}.Art({key})"))
        }
        choice = resolve_art_type(candidates, art_type)
        return {choice.target_key: choice.path} if choice.path else {}

    def _run_processor(
        self,
        process: str,
        art: dict[str, str],
        **proc_kwargs: Any,
    ) -> dict[str, Any] | None:
        """
        Execute a processor for a single image and write the processed file.

        :param process: Processor name ("crop" or "blur").
        :param art: Mapping of {resolved_key: url} for the selected artwork.
        :param proc_kwargs: Extra keyword arguments forwarded to processor methods
        :returns: Dict with file paths and color metadata, or None on failure.
        """
        process_method = getattr(self.processor, process, None)
        if not process_method:
            return None

        category, url = next(iter(art.items()), (None, None))
        folder = self.PROCESS_CONFIG.get(process)["folder"]
        source_path, destination_path = self.cache_manager.get_image_paths(folder)
        if not source_path:
            return None

        image = self._image_open(source_path)
        if not image:
            return None

        result = process_method(image, **proc_kwargs)
        if not result or "image" not in result:
            return None

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
            log(
                f"{self.__class__.__name__}: File processed: {url} → {destination_path}"
            )

        if self.temp_folder in source_path:
            try:
                xbmcvfs.delete(source_path)
                log(f"{self.__class__.__name__}: Temp file deleted → {source_path}")
            except Exception:
                pass

        return {
            **ArtMeta.from_values(
                category=category,
                original_url=url,
                processed_path=destination_path,
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
        :returns: PIL Image or None if missing/unsupported/unreadable.
        """
        if url.lower().endswith(".svg"):
            log(f"{self.__class__.__name__}: Skipping unsupported SVG → {url}")
            return None

        try:
            return Image.open(xbmcvfs.translatePath(url))
        except (FileNotFoundError, OSError) as error:
            log(
                f"{self.__class__.__name__}: Unable to open image {url} → {error}",
                level=ERROR,
            )
            return None

    def _darken_core(
        self,
        get_image: Callable[[], Image.Image | None],
        *,
        overlay_enable: str | bool = "true",
        overlay_source: str | None = None,
        overlay_rects: str | None = None,
        overlay_target: float | str | None = None,
    ) -> int | None:
        """
        Unified darken pipeline: parse params, obtain image via provider, resize to target, compute 0..100.
        Used by both the in-pipeline enrichment and the on-demand runtime helper.

        :param get_image: Zero-arg callable that returns a PIL Image or None (no network I/O inside core).
        :param overlay_enable: Bool-ish flag; short-circuits if not truthy.
        :param overlay_source: Hex text colour or 'clearlogo' to resolve from session.
        :param overlay_rects: Sampling rects in 1920x1080 reference space.
        :param overlay_target: Desired contrast target (float) or str convertible to float.
        :return: Darken percentage 0..100, or None if image/params are invalid.
        """
        enable, rects, target, text_rgb = self._resolve_overlay_params(
            overlay_enable=overlay_enable,
            overlay_rects=overlay_rects,
            overlay_target=overlay_target,
            overlay_source=overlay_source,
        )
        if not enable:
            return None

        img = get_image()
        if img is None:
            return None

        target_size = self.cfg.fanart_target_size
        if img.size != target_size:
            try:
                img = img.resize(target_size, Image.BOX)
            except Exception:
                return None

        try:
            return int(
                self._compute_darken_percent(
                    image=img,
                    overlay_rects=rects,
                    text_rgb=text_rgb,
                    target_ratio=target,
                )
            )
        except Exception as exc:
            log(f"ColorDarken: compute failed: {exc}", level=ERROR)
            return None

    def _resolve_overlay_params(
        self, **proc_kwargs
    ) -> tuple[bool, str | None, float | None, RGB | None]:
        """Parse overlay_* kwargs and resolve text_rgb (supports 'clearlogo' source).

        :param proc_kwargs: Arbitrary keyword arguments from the artwork plugin call.
        :returns: Tuple of params needed for runtime image processing
        """
        enable = str(proc_kwargs.get("overlay_enable", "")).lower() == "true"
        rects = proc_kwargs.get("overlay_rects")
        target = proc_kwargs.get("overlay_target")
        if isinstance(target, str):
            try:
                target = float(target)
            except ValueError:
                target = None

        text_rgb = None
        src = (proc_kwargs.get("overlay_source") or "").strip().lower()
        if src == "clearlogo":
            hexc = self._session.get("clearlogo_color")
            if hexc:
                text_rgb = self.processor.color_analyzer.from_hex(hexc)
        elif src:
            text_rgb = self.processor.color_analyzer.from_hex(src)

        return enable, rects, target, text_rgb

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

    def _compute_darken_percent(self, *a, **kw) -> int:
        """Forward to ColorDarken for convenience."""
        return self.processor.color_analyzer.compute_darken_percent(*a, **kw)
