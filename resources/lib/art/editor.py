# author: realcopacetic

from typing import Any, Iterable, Mapping

import xbmcvfs
from PIL import Image

from resources.lib.art.cache import ArtworkCacheManager, CacheContext
from resources.lib.art.policy import (
    ART_SOURCE_KEYS,
    ColorConfig,
    filter_db_payload,
    flatten_art_attributes,
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
        jobs: Mapping[str, Iterable[str]],
        art_opts: Mapping[str, ArtOpts],
        source: str | None = None,
    ) -> dict[str, Any]:
        """
        Process jobs into flattened ListItem.Art-style key/value pairs.
        Uses cache-first per-art_type processing and merges deltas when needed.

        :param jobs: Mapping of art_type to ordered process names.
        :param art_opts: Mapping of art_type to parsed ArtOpts.
        :param source: Kodi infolabel source prefix for Art() lookups.
        :return: Flattened dict of ListItem.Art keys and metadata values.
        """
        art_types = tuple(jobs)
        shared = {
            "image_cache": {k: {} for k in art_types},
            "results": {k: {} for k in art_types},
        }
        try:
            return flatten_art_attributes(
                [
                    merged
                    for art_type, processes in jobs.items()
                    if (opts := art_opts.get(art_type)) is not None
                    and (
                        merged := self._handle_jobs(
                            art_type=art_type,
                            processes=tuple(processes),
                            source=source or "Container.ListItem",
                            opts=opts,
                            shared=shared,
                        )
                    )
                ]
            )
        except Exception as error:
            log.error(
                f"{self.__class__.__name__}: Error during image processing → {error}",
            )
            return []

    def _handle_jobs(
        self,
        *,
        art_type: str,
        processes: Iterable[str],
        source: str,
        opts: ArtOpts,
        shared: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        Resolve URL, cache-check required fields, then run processes in order.
        Returns the merged attributes for this art_type.

        :param art_type: Artwork type key.
        :param processes: Ordered process names for this art_type.
        :param source: Kodi infolabel source prefix.
        :param opts: Parsed ArtOpts for this art_type.
        :param shared: Shared context across jobs in this call.
        :return: Merged per-art_type attributes, or None on failure.
        """
        url = opts.url
        art = (
            {art_type: url}
            if url
            else self._fetch_art_url(art_type, source) if source else None
        )
        if not art:
            log.debug(
                f"{self.__class__.__name__} → _handle_jobs({art_type}) → "
                f"no art resolved for {source=}, {url=}",
            )
            return None

        resolved_url = next(iter(art.values()))
        ext = ".png" if resolved_url.lower().endswith(".png") else ".jpg"
        ctx = self.cache_manager.prepare(resolved_url, ext)
        attrs = self.cache_manager.read_lookup(ctx) or {}
        if attrs:
            log.debug(
                f"{self.__class__.__name__} → Cache returned → {art_type=} → {attrs}",
            )

        attrs.setdefault("category", art_type)
        attrs.setdefault("url", resolved_url)
        if ctx.cached_file_hash is not None:
            attrs.setdefault("cached_file_hash", ctx.cached_file_hash)

        updates: list[dict[str, Any]] = []
        for process in processes:
            spec = self.PROCESS_SPEC[process]
            require = spec.get("require")
            if require is not None and self._has_required(attrs, require):
                log.debug(
                    f"{self.__class__.__name__} → Cache sufficient for {art_type=} → {process=}"
                )
                continue

            delta = self._run_processor(
                art_type=art_type,
                process=process,
                art=art,
                ctx=ctx,
                opts=opts,
                shared=shared,
                folder=spec.get("folder"),
            )
            if not delta:
                return None

            log.debug(
                f"{self.__class__.__name__} → Payload returned → {art_type=} → {delta}",
            )
            updates.append(delta)
            attrs |= delta

        if updates:
            self.cache_manager.write_lookup(
                art_type,
                filter_db_payload(attrs),
            )

        shared["results"][art_type] = attrs
        return attrs

    def _has_required(self, row: dict[str, Any], require: tuple[str, ...]) -> bool:
        """
        Validate that a cache row satisfies required fields.
        Treats processed_path as a special-case path validity check.

        :param row: Cached attribute row to validate.
        :param require: Required field names for a process.
        :return: True if requirements are satisfied, else False.
        """
        if not require:
            return True

        if "processed_path" in require and not validate_path(row.get("processed_path")):
            return False

        return all(
            k in row and row.get(k) is not None
            for k in require
            if k != "processed_path"
        )

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
    ) -> dict[str, Any] | None:
        """
        Execute a single processor step and optionally write a processed file.
        Returns only the delta fields produced by this step.

        :param art_type: Artwork type key.
        :param process: Process name to execute.
        :param art: Mapping of {resolved_key: url} for the selected artwork.
        :param ctx: CacheContext for resolving paths and hashes.
        :param opts: Parsed ArtOpts for this art_type.
        :param shared: Shared context across jobs in this call.
        :param folder: Output folder name if this process writes files.
        :return: Delta dict of produced fields, or None on failure.
        """
        processed_path = None
        process_method = getattr(self.processor, process, None)
        if not process_method:
            return None

        url = next(iter(art.values()), None)
        if not url:
            return None

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

        image = shared["image_cache"][art_type].get(source_path) or self._image_open(
            source_path
        )
        if image is None:
            return None

        shared["image_cache"][art_type][source_path] = image
        result = process_method(
            image,
            opts=opts,
            shared=shared,
        )
        if not result:
            return None

        if folder and "image" in result:
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

        meta = result.get("metadata") or {}
        return {
            **(
                {"processed_path": processed_path}
                if processed_path is not None and folder and "image" in result
                else {}
            ),
            **{k: v for k, v in meta.items() if v is not None},
        }

    def _fetch_art_url(self, art_type: str, source: str) -> dict[str, str]:
        """
        Read artwork paths from Kodi infolabels and select the best candidate.

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
        return resolve_art_type(candidates, art_type)

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
        img = result["image"]
        fmt = result.get("format", "PNG")
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
