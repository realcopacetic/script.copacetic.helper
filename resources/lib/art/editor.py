# author: realcopacetic

from typing import Any, Iterable, Mapping

import xbmcvfs
from PIL import Image

from resources.lib.art.cache import ArtworkCacheManager, CacheContext
from resources.lib.art.policy import (
    ART_SOURCE_KEYS,
    ArtMeta,
    ColorConfig,
    resolve_art_type,
)
from resources.lib.art.processor import ImageProcessor
from resources.lib.plugin.opts import ArtOpts
from resources.lib.shared import logger as log
from resources.lib.shared.hash import HashManager
from resources.lib.shared.sqlite import ArtworkCacheHandler
from resources.lib.shared.utilities import BLURS, CROPS, infolabel, validate_path


class ImageEditor:
    """
    Coordinate artwork processing, caching and color metadata extraction.
    Handles crop/blur/analyze plus optional overlay darken.
    """
    PROCESS_SPEC: dict[str, dict[str, Any]] = {
        "crop": {"folder": CROPS, "require": ("processed_path",)},
        "blur": {"folder": BLURS, "require": ("processed_path",)},
        "analyze": {
            "folder": None,
            "require": ("color", "accent", "contrast", "luminosity"),
        },
        "darken": {
            "folder": None,
            "require": None,
        },
    }

    def __init__(self, sqlite_handler: ArtworkCacheHandler | None = None) -> None:
        """
        Initialize caches, processors and lookup dependencies.

        :param sqlite_handler: Optional SQLite handler instance.
        """
        self.sqlite = sqlite_handler or ArtworkCacheHandler()
        self.cache_manager = ArtworkCacheManager(self.sqlite, HashManager())
        self.temp_folder = self.cache_manager.temp_folder
        self.cfg = ColorConfig()
        self.processor = ImageProcessor(self.cfg)

    def image_processor(
        self,
        jobs: Iterable[Mapping[str, str]],
        art_opts: Mapping[str, ArtOpts],
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Process jobs into per-art_type attribute dictionaries.
        Each job is cache-checked before processing.

        :param jobs: Iterable of job dicts with 'art_type' and 'process'.
        :param art_opts: Mapping of art_type to parsed ArtOpts.
        :param source: Kodi infolabel source prefix for Art() lookups.
        :return: List of attribute dicts (one per art_type).
        """
        shared = {
            "images": {},
            "cache": {},
            "results": {},
            "last_image": {},
        }
        try:
            updates = [
                (art_type, attrs)
                for job in jobs
                if (art_type := (job.get("art_type") or ""))
                and (process := (job.get("process") or ""))
                and (opts := art_opts.get(art_type)) is not None
                and (
                    attrs := self._handle_job(
                        art_type=art_type,
                        process=process,
                        source=source or "Container.ListItem",
                        url=(job.get("url") or "") or None,
                        opts=opts,
                        shared=shared,
                    )
                )
            ]
            for art_type, attrs in updates:
                shared["results"][art_type] = attrs

        except Exception as error:
            log.error(
                f"{self.__class__.__name__}: Error during image processing → {error}",
            )
            return []

        return list(shared["results"].values())

    def _handle_job(
        self,
        *,
        art_type: str,
        process: str,
        source: str,
        url: str | None = None,
        opts: ArtOpts,
        shared: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Resolve URL, cache-check the DB row, then run one job if needed.
        Returns updated attributes for the art_type.

        :param art_type: Artwork type key.
        :param process: Process name ('crop', 'blur', 'analyze', 'darken').
        :param source: Kodi infolabel source prefix.
        :param url: Optional explicit URL override.
        :param opts: Parsed ArtOpts for this art_type.
        :param shared: Shared context across jobs in this call.
        :return: Updated per-art_type attributes, or None.
        """
        art = (
            {art_type: url}
            if url
            else self._fetch_art_url(art_type, source) if source else None
        )
        if not art:
            log.debug(
                f"{self.__class__.__name__} → _handle_job({art_type}) → "
                f"no art resolved for {source=}, {url=}",
            )
            return None

        original_url = next(iter(art.values()))
        if not original_url:
            log.debug(
                f"{self.__class__.__name__} → _handle_job({art_type}) → "
                f"original_url empty → {art=}",
            )
            return None

        ext = ".png" if original_url.lower().endswith(".png") else ".jpg"
        ctx = self.cache_manager.prepare(original_url, ext)
        spec = self.PROCESS_SPEC[process]

        base_attrs: dict[str, Any] = shared["results"].get(art_type, {}) | {}
        if (require := spec.get("require")) is not None:
            cache_key = (original_url, process)
            if cache_key not in shared["cache"]:
                shared["cache"][cache_key] = self.cache_manager.read_lookup(
                    ctx,
                    require=tuple(require),
                )

            if cached := shared["cache"][cache_key]:
                return base_attrs | cached

        processed = self._run_processor(
            art_type=art_type,
            process=process,
            art=art,
            ctx=ctx,
            opts=opts,
            shared=shared,
            folder=spec.get("folder"),
        )
        if not processed:
            return None

        attrs, img, _ctx = processed
        log.debug(
            f"ImageEditor → Payload returned → {art_type=} → {attrs}",
        )
        if img is not None:
            shared["last_image"][art_type] = img

        return base_attrs | attrs

    def _run_processor(
        self,
        *,
        art_type: str,
        process: str,
        art: dict[str, str],
        ctx: CacheContext,
        opts: ArtOpts,
        shared: dict[str, Any],
        folder: str | None,
    ) -> tuple[dict[str, Any], Image.Image | None, CacheContext] | None:
        """
        Execute a single process and optionally write the processed file.
        Returns attrs plus the best in-memory image for subsequent jobs.

        :param art_type: Artwork type key.
        :param process: Process name to execute.
        :param art: Mapping of {resolved_key: url} for the selected artwork.
        :param ctx: CacheContext for resolving texture-cache and destination paths.
        :param opts: Parsed ArtOpts for this art_type.
        :param shared: Shared context across jobs in this call.
        :param folder: Output folder name if this process writes files.
        :return: Tuple (attrs, image, ctx) or None on failure.
        """
        process_method = getattr(self.processor, process, None)
        if not process_method:
            return None

        url = next(iter(art.values()), None)
        if not url:
            return None

        processed_path = ""
        if folder:
            source_path, destination_path = self.cache_manager.get_image_paths(
                folder, ctx
            )
            if not source_path:
                return None

        else:
            source_path = str(ctx.cached_image_path)
            if not validate_path(source_path):
                return None

        image = shared["image_cache"].get(source_path) or self._image_open(source_path)
        if image is None:
            return None

        shared["image_cache"][source_path] = image

        result = process_method(
            image,
            art_type=art_type,
            opts=opts,
            ctx=ctx,
            shared=shared,
        )
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
        return attrs, result["image"], ctx

    def _fetch_art_url(self, art_type: str, source: str) -> dict[str, str]:
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
