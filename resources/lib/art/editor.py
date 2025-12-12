# author: realcopacetic

from dataclasses import replace
from typing import Any, Iterable, Mapping

import xbmcvfs
from PIL import Image

from resources.lib.art.cache import ArtworkCacheManager, CacheContext
from resources.lib.art.darken import DarkenOverlayOpts, DarkenUpdates
from resources.lib.art.policy import (
    ART_SOURCE_KEYS,
    ArtMeta,
    ColorConfig,
    resolve_art_type,
)
from resources.lib.art.processor import ImageProcessor
from resources.lib.shared import logger as log
from resources.lib.shared.hash import HashManager
from resources.lib.shared.sqlite import ArtworkCacheHandler
from resources.lib.shared.utilities import BLURS, CROPS, infolabel, validate_path

RGB = tuple[int, int, int]


class ImageEditor:
    """
    Coordinate artwork processing, caching and color metadata extraction.
    Handles crop/blur/analyze plus optional overlay darken.
    """

    FLOW_CONFIG: dict[str, dict[str, Any]] = {
        "clearlogo": {
            "process": "crop",
            "folder": CROPS,
            "extension": ".png",
            "analysis": True,
            "darken_handler": None,
        },
        "background": {
            "process": "blur",
            "folder": BLURS,
            "extension": ".jpg",
            "analysis": True,
            "darken_handler": "compute_background_darken",
        },
        "icon": {
            "process": "analyze",
            "folder": None,
            "extension": ".jpg",
            "analysis": True,
            "darken_handler": "compute_element_darken_series",
        },
    }

    def __init__(self, sqlite_handler: ArtworkCacheHandler | None = None) -> None:
        """
        Initialize caches, processors and lookup dependencies.
        Creates a per-instance session for cross-job sharing (e.g. clearlogo color).

        :param sqlite_handler: Optional SQLite handler instance.
        """
        self.sqlite = sqlite_handler or ArtworkCacheHandler()
        self.cache_manager = ArtworkCacheManager(self.sqlite, HashManager())
        self.temp_folder = self.cache_manager.temp_folder

        self.cfg = ColorConfig()
        self.processor = ImageProcessor(self.cfg)
        self._session: dict[str, Any] = {}

    # --- Public API ---
    def image_processor(
        self,
        jobs: Iterable[Mapping[str, str]],
        source: str | None = None,
        **proc_kwargs: Any,
    ) -> list[dict[str, Any]]:
        """
        Process artwork jobs into attribute dictionaries.
        Each job is resolved from explicit URL or Kodi infolabel artwork.

        :param jobs: Iterable of job specs with 'art_type' and optional 'url'.
        :param source: Kodi infolabel source prefix for Art() lookups.
        :param proc_kwargs: Extra keyword arguments forwarded to processor methods.
        :return: List of attribute dicts for successfully processed jobs.
        """
        try:
            attributes = [
                self._handle_image(
                    art_type=job.get("art_type", ""),
                    source=source or "Container.ListItem",
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

    def compute_darken(
        self,
        *,
        url: str,
        handler_name: str,
        opts: DarkenOverlayOpts,
        image: Image.Image | None = None,
    ) -> DarkenUpdates | None:
        """
        Compute darken updates for a single image URL.
        Uses local texture-cache only and does not write files.

        :param url: Image URL.
        :param handler_name: ColorDarken method name to call.
        :param opts: Parsed overlay options for sampling/target/source.
        :param image: Optional already-open PIL image to avoid re-opening.
        :return: Dict of attribute updates, or None on failure/disabled.
        """
        if not opts.enabled:
            return None

        allowed = {
            "compute_background_darken",
            "compute_element_darken_series",
        }
        if handler_name not in allowed:
            log.debug(
                f"{self.__class__.__name__} → darken handler not allowed → {handler_name!r}"
            )
            return None

        img = image
        if img is None:
            ctx = self.cache_manager.prepare(url, ".jpg")
            img = self._image_open(url=ctx.cached_image_path)
            if img is None:
                return None

        darken = self.processor.color_analyzer.darken
        handler = getattr(darken, handler_name, None)
        if not callable(handler):
            log.debug(
                f"{self.__class__.__name__} → darken handler not found → {handler_name!r}"
            )
            return None

        resolved_opts = self._resolve_overlay_opts(opts)

        try:
            return handler(img, opts=resolved_opts)
        except Exception as exc:
            log.error(
                f"{self.__class__.__name__} → darken compute failed ({handler_name}): {exc}"
            )
            return None

    # --- Internal helpers ---
    def _handle_image(
        self,
        art_type: str,
        source: str = "Container.ListItem",
        url: str | None = None,
        **proc_kwargs: Any,
    ) -> dict[str, Any] | None:
        """
        Resolve a URL, run processing and return metadata.
        Applies overlay darken when configured for this art_type.

        :param art_type: Artwork key (e.g. "clearlogo", "background", "icon").
        :param source: Kodi infolabel source prefix for Art() lookups.
        :param url: Optional explicit URL to process for this art_type.
        :param proc_kwargs: Extra keyword arguments forwarded to processor methods.
        :return: Metadata dict including processed path and colours, or None.
        """
        flow_cfg = self.FLOW_CONFIG.get(art_type, {})
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

        extension = flow_cfg.get("extension")
        ctx = self.cache_manager.prepare(original_url, extension)
        processed = self._run_processor(art_type=art_type, art=art, ctx=ctx, **proc_kwargs)
        if processed is None:
            return None

        attributes, image_for_overlay, ctx = processed
        log.debug(
            f"ImageEditor → Payload returned → {art_type=} → {attributes}",
        )

        # Stash clearlogo color for downstream background darken process
        if art_type.startswith("clearlogo"):
            col = attributes.get("color")
            if col:
                self._session["clearlogo_color"] = col

        overlay_map = proc_kwargs.get("overlay_params") or {}
        opts = overlay_map.get(art_type)
        handler_name = flow_cfg.get("darken_handler")
        if handler_name and opts and opts.enabled:
            updates = self.compute_darken(
                url=original_url,
                handler_name=handler_name,
                opts=opts,
                image=image_for_overlay,
            )
            if updates:
                attributes.update(updates)

        return attributes

    def _fetch_art_url(self, art_type: str, source: str):
        """
        Read artwork paths from Kodi infolabels and select the best candidate.
        Uses :data:`ART_SOURCE_KEYS` and :func:`resolve_art_type`.

        :param art_type: Target artwork type to resolve.
        :param source: Kodi info label source prefix (e.g. "Container.ListItem").
        :return: Mapping {chosen_key: path} if found, else {}.
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
        art_type: str,
        art: dict[str, str],
        ctx: CacheContext,
        **proc_kwargs: Any,
    ) -> tuple[dict[str, Any], Image.Image | None, CacheContext] | None:
        """
        Execute a processor for a single image and optionally write the file.
        Returns attributes plus a best in-memory image for downstream overlay darken.

        :param art_type: Logical art type used to select flow configuration.
        :param art: Mapping of {resolved_key: url} for the selected artwork.
        :param ctx: CacheContext for resolving texture-cache and destination paths.
        :param proc_kwargs: Extra keyword arguments forwarded to processor methods.
        :return: Tuple (attrs, img_for_overlay, ctx) or None on failure.
        """
        flow_cfg = self.FLOW_CONFIG.get(art_type, {})
        proc_name = flow_cfg.get("process", "")
        process_method = getattr(self.processor, proc_name, None)
        if not process_method:
            return None

        url = next(iter(art.values()), None)
        if not url:
            return None

        folder = flow_cfg.get("folder")
        processed_path = ""
        if folder:
            source_path, destination_path = self.cache_manager.get_image_paths(folder, ctx)
            if not source_path:
                return None

        else:
            source_path = str(ctx.cached_image_path)
            if not validate_path(source_path):
                return None

        image = self._image_open(source_path)
        if not image:
            return None

        result = process_method(image, **proc_kwargs)
        if not result or "image" not in result:
            return None

        if folder:
            processed_path = destination_path
            with xbmcvfs.File(processed_path, "wb") as f:
                self._save_processed_image(f, result)

            log.debug(
                f"{self.__class__.__name__} → File processed: "
                f"{url} → {processed_path}",
            )
            if self.temp_folder in source_path:
                try:
                    xbmcvfs.delete(source_path)
                    log.debug(
                        f"{self.__class__.__name__} → Temp file deleted → {source_path}",
                    )
                except Exception:
                    pass

        attrs = ArtMeta.from_values(
            category=art_type,
            original_url=url,
            processed_path=processed_path,
            cached_file_hash=ctx.cached_file_hash,
            values=result.get("metadata", {}),
        ).to_dict()
        return attrs, result.get("image"), ctx

    def _image_open(self, url: str) -> Image.Image | None:
        """
        Open an image from Kodi VFS via Pillow.
        Skips unsupported formats and returns None on failure.

        :param url: Kodi VFS or translated path to the image resource.
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

    def _save_processed_image(self, fh: Any, result: Mapping[str, Any]) -> None:
        """
        Save a processed image result to a file handle.
        Uses configured JPEG/PNG settings from ColorConfig.

        :param fh: Open binary file handle for writing.
        :param result: Processor result mapping with 'image' and optional 'format'.
        :return: None.
        """
        fmt = result.get("format", "PNG")
        img = result["image"]
        if fmt == "JPEG":
            img.save(
                fh,
                "JPEG",
                quality=self.cfg.jpeg_quality,
                optimize=self.cfg.jpeg_optimize,
                progressive=self.cfg.jpeg_progressive,
                subsampling=self.cfg.jpeg_subsampling,
            )
            return

        img.save(
            fh,
            "PNG",
            optimize=self.cfg.png_optimize,
            compress_level=self.cfg.png_compress_level,
        )

    def _resolve_overlay_opts(self, opts: DarkenOverlayOpts) -> DarkenOverlayOpts:
        """
        Resolve 'clearlogo' indirection to a hex colour when available.

        :param opts: Overlay options to resolve.
        :return: New DarkenOverlayOpts with resolved source if needed.
        """
        src = (opts.source or "").strip().lower()
        if src != "clearlogo":
            return opts

        hexc = self._session.get("clearlogo_color")
        return replace(opts, source=hexc or None)
