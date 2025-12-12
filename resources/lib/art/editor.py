# author: realcopacetic

from typing import Any, Callable, Iterable, Mapping

import xbmcvfs
from PIL import Image

from resources.lib.art.cache import ArtworkCacheManager, CacheContext
from resources.lib.art.darken import DarkenOverlayOpts, DarkenSolution
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
    Coordinates image processing and metadata extraction for artwork.
    Handles cropping, blurring, caching, and exposure of color metadata to Kodi.
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
            "darken_handler": "_apply_darken_background",
        },
        "icon": {
            "process": "analyze",
            "folder": None,
            "extension": ".jpg",
            "analysis": True,
            "darken_handler": "_apply_darken_text_series",
        },
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

        ctx = self.cache_manager.prepare(url, ".jpg")
        img = self._get_runtime_image(ctx=ctx, attrs=None)
        if img is None:
            return None

        resolved_source = self._resolve_overlay_source(overlay_source)
        return self._darken_solution(
            image=img,
            overlay_source=resolved_source,
            overlay_rects=overlay_rects,
            overlay_frame=overlay_frame,
            overlay_target=overlay_target,
        )

    # --- Private methods ---
    def _handle_image(
        self,
        art_type: str,
        source: str = "Container.ListItem",
        url: str | None = None,
        **proc_kwargs: Any,
    ) -> dict[str, Any] | None:
        """
        Resolve source URL, process the image, and return metadata.

        :param art_type: Artwork key (e.g. "clearlogo", "fanart").
        :param source: Optional Kodi infolabel source prefix for Art() lookups.
        :param url: Optional explicit URL to process for this art_type.
        :param proc_kwargs: Extra keyword arguments forwarded to processor methods.
        :return: Metadata dict including processed path and colors, or None.
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
        payload = self._run_processor(art_type=art_type, art=art, ctx=ctx, **proc_kwargs)
        if payload is None:
            return None

        log.debug(
            f"ImageEditor → Payload returned → {art_type=} → {payload}",
        )
        attributes, image, ctx = payload

        # Stash clearlogo color for downstream background darken process
        if art_type.startswith("clearlogo"):
            col = attributes.get("color")
            if col:
                self._session["clearlogo_color"] = col

        overlay_map = proc_kwargs.get("overlay_params") or {}
        opts = overlay_map.get(art_type)
        if opts and opts.enabled:
            self._apply_overlay_darken(
                art_type=art_type,
                attributes=attributes,
                opts=opts,
                image=image,
                ctx=ctx,
            )

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
        art_type: str,
        art: dict[str, str],
        ctx: CacheContext,
        **proc_kwargs: Any,
    ) -> dict[str, Any] | None:
        """
        Execute a processor for a single image and optionally write the file.

        :param art: Mapping of {resolved_key: url} for the selected artwork.
        :param proc_kwargs: Extra keyword arguments forwarded to processor methods.
        :return: Dict with file paths and color metadata, or None on failure.
        """
        flow_cfg = self.FLOW_CONFIG.get(art_type, {})
        proc_name = flow_cfg.get("process", "")
        process_method = getattr(self.processor, proc_name, None)
        if not process_method:
            return None

        url = next(iter(art.values()), (None, None))
        if not url:
            return None

        folder = flow_cfg.get("folder")
        if folder:
            source_path, destination_path = self.cache_manager.get_image_paths(folder)
            if not source_path:
                return None

            image = self._image_open(source_path)
            if not image:
                return None

            result = process_method(image, **proc_kwargs)
            if not result or "image" not in result:
                return None

            processed_path = destination_path

            with xbmcvfs.File(destination_path, "wb") as f:
                self._save_processed_image(f, result)

            log.debug(
                f"{self.__class__.__name__} → File processed: "
                f"{url} → {destination_path}",
            )
            if self.temp_folder in source_path:
                try:
                    xbmcvfs.delete(source_path)
                    log.debug(
                        f"{self.__class__.__name__} → Temp file deleted → {source_path}",
                    )
                except Exception:
                    pass

        else:
            processed_path = ""
            image = self._get_runtime_image(ctx=ctx, attrs=None)
            if not image:
                return None

            result = process_method(image, **proc_kwargs)
            if not result or "image" not in result:
                return None

        attrs = ArtMeta.from_values(
            category=art_type,
            original_url=url,
            processed_path=processed_path,
            cached_file_hash=ctx.cached_file_hash,
            values=result.get("metadata", {}),
        ).to_dict()
        img_for_overlay = result.get("image")
        return attrs, img_for_overlay, ctx

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

    def _get_runtime_image(
        self, *, ctx: CacheContext, attrs: dict[str, Any] | None,
    ) -> Image.Image | None:
        """
        Resolve a PIL Image for runtime analysis from local sources (no network/VFS reads).
        Priority: in-memory sample → texture-cache local path → processed blur (from attrs).

        :param attrs: Optional metadata dict that may contain '_sample_frame' and/or 'processed_path'.
        :param url: Optional art URL used only to prime/locate the texture-cache path.
        :return: PIL Image ready for analysis, or None if no local source is available.
        """
        cache_local = str(ctx.cached_image_path)
        if cache_local and validate_path(cache_local):
            log.debug(
                f"{self.__class__.__name__} → _get_runtime_image: using cached texture → {cache_local}"
            )
            if im := self._image_open(cache_local):
                return im

        return None

    def _resolve_overlay_source(self, overlay_source: str | None) -> str | None:
        """Resolve 'clearlogo' indirection to a hex colour when available."""
        src = (overlay_source or "")
        if src == "clearlogo":
            return self._session.get("clearlogo_color") or None

        return overlay_source

    def _apply_overlay_darken(
        self,
        art_type: str,
        attributes: dict[str, Any],
        opts: DarkenOverlayOpts,
        image: Image.Image | None,
        ctx: CacheContext,
    ) -> None:
        """
        Dispatch overlay-based darken logic using the flow_config handler.

        The handler name is stored in FLOW_CONFIG[art_type]["darken_handler"] and
        is expected to be a method on this class taking:
            (attributes, img, opts, resolved_source)
        """
        flow_cfg = self.FLOW_CONFIG.get(art_type, {})
        handler_name = flow_cfg.get("darken_handler")
        if not handler_name:
            return

        img = image or self._get_runtime_image(ctx=ctx, attrs=attributes)
        if img is None:
            return

        resolved_source = self._resolve_overlay_source(opts.source)
        handler = getattr(self, handler_name, None)
        if not handler:
            log.debug(
                f"{self.__class__.__name__} → _apply_overlay_darken: "
                f"no handler '{handler_name}' for art_type='{art_type}'"
            )
            return

        handler(attributes, img, opts, resolved_source)

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

        log.debug(
            f"{self.__class__.__name__} → _darken_core: "
            f"image_size={getattr(img, 'size', None)}, "
            f"overlay_source={resolved_source!r}, "
            f"rects={overlay_rects!r}, frame={overlay_frame!r}, "
            f"target={overlay_target!r}",
        )
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
