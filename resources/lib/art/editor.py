# author: realcopacetic

from __future__ import annotations

import dataclasses
import json
import time
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping

import xbmcvfs

from resources.lib.art import compose, policy
from resources.lib.art.cache import ArtworkCacheManager, CacheContext
from resources.lib.plugin.opts import ArtOpts
from resources.lib.shared import logger as log
from resources.lib.shared.hash import HashManager
from resources.lib.shared.sqlite import ArtworkCacheHandler
from resources.lib.shared.utilities import (
    BLURS,
    CROPS,
    create_dir,
    infolabel,
    validate_path,
)

if TYPE_CHECKING:
    from PIL import Image

    from resources.lib.art.processor import ImageProcessor

PROCESS_SPEC = {
    "crop": {
        "folder": CROPS,
        "require": policy.ART_FIELDS_RESULT["crop"],
    },
    "blur": {
        "folder": BLURS,
        "match": policy.ART_FIELDS_INPUT["blur"],
        "require": policy.ART_FIELDS_RESULT["blur"],
    },
    "analyze": {
        "folder": None,
        "require": policy.ART_FIELDS_RESULT["analyze"],
    },
    "darken": {  # the measurement row compose reads; named before the two passes
        "folder": None,
        "match": policy.ART_FIELDS_INPUT["darken"],
        "require": policy.ART_FIELDS_RESULT["darken"],
    },
    "band": {  # step 3's tinted copy of the blur, written by compose
        "folder": BLURS,
        "match": (
            *policy.ART_FIELDS_INPUT["darken"],
            policy.ART_FIELD_RATIO,
            policy.ART_FIELD_ELEMENT_COLORS,
        ),
        "require": (policy.ART_FIELD_PROCESSED, policy.ART_FIELD_ELEMENT_COLOR),
    },
}


class ImageEditor:
    """
    Coordinate artwork processing and caching: prepare each art (crop, blur,
    analyze, measure), then compose its darken and element steps.
    """

    def __init__(self, sqlite_handler: ArtworkCacheHandler | None = None) -> None:
        """
        Initialize caches, processors and lookup dependencies.

        :param sqlite_handler: Optional SQLite handler instance.
        """
        self.sqlite = sqlite_handler or ArtworkCacheHandler()
        self.cache_manager = ArtworkCacheManager(self.sqlite, HashManager())
        self.temp_folder = self.cache_manager.temp_folder
        self.cfg = policy.ColorConfig()

    @cached_property
    def processor(self) -> ImageProcessor:
        """PIL-backed processor, built on first cache miss only."""
        t0 = time.perf_counter()
        from resources.lib.art.processor import ImageProcessor

        log.debug(
            f"{self.__class__.__name__} → PIL import "
            f"{(time.perf_counter() - t0) * 1000:.0f}ms"
        )
        return ImageProcessor(self.cfg)

    def image_processor(
        self,
        jobs: Mapping[str, Iterable[str]],
        art_opts: Mapping[str, ArtOpts],
        source: str | None = None,
    ) -> dict[str, Any]:
        """
        Prepare each art (cache-first, per process), then compose across them;
        returns flattened ListItem.Art-style key/value pairs.

        :param jobs: Mapping of art_type to ordered process names.
        :param art_opts: Mapping of art_type to parsed ArtOpts.
        :param source: Kodi infolabel source prefix for Art() lookups.
        :return: Flattened dict of ListItem.Art keys and metadata values.
        """
        art_types = tuple(jobs)
        shared = {
            "image_cache": {k: {} for k in art_types},
            "results": {k: {} for k in art_types},
            "contexts": {},
        }
        try:
            records = {
                art_type: merged
                for art_type, processes in jobs.items()
                if (opts := art_opts.get(art_type)) is not None
                and (
                    merged := self._handle_jobs(
                        art_type=art_type,
                        processes=tuple(processes),
                        source=source,
                        opts=opts,
                        shared=shared,
                    )
                )
            }
            self._compose(records, art_opts, shared["contexts"])
            return policy.flatten_art_attributes(records.items())
        except Exception:
            log.exception(f"{self.__class__.__name__} → Error during image processing")
            return {}

    def _handle_jobs(
        self,
        *,
        art_type: str,
        processes: Iterable[str],
        source: str | None,
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

        base_ctx = shared["contexts"][art_type] = self.cache_manager.prepare(
            resolved_url, ext
        )
        attrs = shared["results"][art_type] = {
            "cached_file_hash": base_ctx.cached_file_hash
        }
        for process in processes:
            if not opts.enabled(process):
                continue

            spec = PROCESS_SPEC[process]
            require = spec.get("require")
            folder = spec.get("folder")
            expected = self._expected_from_spec(spec, opts=opts)
            ctx = self.cache_manager.with_process_variant(
                base_ctx,
                process=process,
                expected=expected,
                folder=folder,
            )
            cached = (
                self.cache_manager.read_lookup(ctx, require=tuple(require or ())) or {}
            )
            if cached and (
                require is None or self._has_required(cached, require, expected)
            ):
                log.debug(
                    f"{self.__class__.__name__} → Cache hit → {art_type=} → {process=} → {ctx.cache_key=}"
                )
                attrs |= {  # a row's key fields are inputs: only its results merge
                    k: v
                    for k, v in cached.items()
                    if k not in (expected or ()) or k in require
                }
                continue

            processed = self._run_processor(
                art_type=art_type,
                process=process,
                art=art,
                ctx=ctx,
                opts=opts,
                shared=shared,
                folder=folder,
            )
            if processed is None:
                return self._background_fallback(
                    art_type=art_type,
                    processes=processes,
                    source=source,
                    opts=opts,
                    shared=shared,
                )

            attrs |= processed
            log.debug(
                f"{self.__class__.__name__} → Payload returned → {art_type=} → {processed}",
            )
            row = {
                policy.ART_FIELD_CACHE_KEY: ctx.cache_key,
                policy.ART_FIELD_SOURCE_URL: base_ctx.source_url,
                policy.ART_FIELD_PROCESS: process,
                "cached_file_hash": base_ctx.cached_file_hash,
                **(expected or {}),
                **processed,
            }
            self.cache_manager.write_lookup(policy.filter_db_payload(row))

        return attrs

    def _compose(
        self,
        records: Mapping[str, dict[str, Any]],
        art_opts: Mapping[str, ArtOpts],
        contexts: Mapping[str, CacheContext],
    ) -> None:
        """
        Second pass, once every art is prepared: each art's darken and element
        step from its measurement, into its record. Never cached.

        :param records: Prepared attributes per art_type, updated in place.
        :param art_opts: Parsed ArtOpts per art_type.
        :param contexts: Each art's source cache context, for the band copy.
        """
        measures = {
            art_type: json.loads(attrs[policy.ART_FIELD_MEASURE])
            for art_type, attrs in records.items()
            if policy.ART_FIELD_MEASURE in attrs
        }
        logo = measures.get("clearlogo", {}).get("dominant")
        for art_type, attrs in records.items():
            opts = art_opts[art_type]
            if not (opts.darken and (measure := measures.get(art_type))):
                continue
            zones = measure["zones"]
            if opts.darken.enabled:
                sources = [
                    logo or self.cfg.element_overlay_color if s == "clearlogo" else s
                    for s in opts.darken.sources
                ]
                pct = compose.darken(zones, sources, opts.darken.surface, opts.ratio)
                cap = opts.darken.max
                attrs[policy.ART_FIELD_DARKEN] = pct if cap is None else min(pct, cap)
            if opts.element_colors:
                step, color = compose.element(zones, opts.element_colors, opts.ratio)
                if step == 2:
                    attrs[policy.ART_FIELD_BAND] = attrs[policy.ART_FIELD_PROCESSED]
                elif step == 3:
                    color, attrs[policy.ART_FIELD_BAND] = self._band(
                        attrs, opts, contexts[art_type], measure["band"]
                    )
                attrs[policy.ART_FIELD_ELEMENT_COLOR] = color

    def _band(
        self,
        attrs: Mapping[str, Any],
        opts: ArtOpts,
        base_ctx: CacheContext,
        band: list[str],
    ) -> tuple[str, str]:
        """
        Step 3: a tinted copy of the blur in a file of its own (Kodi won't reread a
        rewritten path), cached by the blur's key plus ratio and candidates.

        :param attrs: The art's prepared attributes (the blur's processed_path).
        :param opts: Parsed ArtOpts for this art_type.
        :param base_ctx: The art's source cache context.
        :param band: The band palette's [darkest, lightest], hex.
        :return: (element colour, path of the copy).
        """
        spec = PROCESS_SPEC["band"]
        expected = self._expected_from_spec(spec, opts=opts)
        ctx = self.cache_manager.with_process_variant(
            base_ctx, process="band", expected=expected, folder=spec["folder"]
        )
        if cached := self.cache_manager.read_lookup(ctx, require=spec["require"]):
            return (
                cached[policy.ART_FIELD_ELEMENT_COLOR],
                cached[policy.ART_FIELD_PROCESSED],
            )

        from resources.lib.art.io import write_image  # PIL: a cache miss only

        color, image = self.processor.darken_engine.band(
            self._image_open(attrs[policy.ART_FIELD_PROCESSED]).convert("RGB"),
            opts,
            {c: compose.tint(c, band) for c in opts.element_colors},
        )
        path = str(Path(spec["folder"]) / ctx.dest_thumb)
        create_dir(spec["folder"])
        write_image(path, image, "JPEG", self.cfg)
        self.cache_manager.write_lookup(
            policy.filter_db_payload(
                {
                    policy.ART_FIELD_CACHE_KEY: ctx.cache_key,
                    policy.ART_FIELD_SOURCE_URL: base_ctx.source_url,
                    policy.ART_FIELD_PROCESS: "band",
                    policy.ART_FIELD_HASH: base_ctx.cached_file_hash,
                    **(expected or {}),
                    policy.ART_FIELD_PROCESSED: path,
                    policy.ART_FIELD_ELEMENT_COLOR: color,
                }
            )
        )
        return color, path

    def _background_fallback(
        self,
        *,
        art_type: str,
        processes: Iterable[str],
        source: str | None,
        opts: ArtOpts,
        shared: dict[str, Any],
    ) -> dict[str, Any] | None:
        """
        A background whose image can't be opened (a dead remote thumb) runs once more
        on the item's fanart ladder, so the backstage still gets a blur. A process
        that fails on an opened image would fail again, so it doesn't.

        :param art_type: Artwork type key; only "background" falls back.
        :param processes: Ordered process names for this art_type.
        :param source: Kodi infolabel source prefix.
        :param opts: Parsed ArtOpts whose url failed.
        :param shared: Shared context across jobs; its image_cache holds opened images.
        :return: Merged attributes from the fallback art, or None.
        """
        if art_type != "background" or not source or shared["image_cache"][art_type]:
            return None
        url = self._fetch_art_url("fanart", source).get("fanart")
        if not url or url == opts.url:
            return None
        log.debug(f"{self.__class__.__name__} → background fallback → {url}")
        return self._handle_jobs(
            art_type=art_type,
            processes=processes,
            source=source,
            opts=dataclasses.replace(opts, url=url),
            shared=shared,
        )

    def _expected_from_spec(
        self, spec: dict[str, Any], *, opts: ArtOpts
    ) -> dict[str, object] | None:
        """
        The spec's match fields, picked from ArtOpts.match_fields(); None values
        are left out of the key.

        :param spec: Process spec dict (may contain 'match').
        :param opts: Parsed ArtOpts for the current art_type.
        :return: Expected cache-field values, or None if no matches apply.
        """
        fields = opts.match_fields()
        return {
            key: value
            for key in spec.get("match") or ()
            if (value := fields.get(key)) is not None
        } or None

    def _has_required(
        self,
        row: dict[str, Any],
        require: tuple[str, ...],
        expected: Mapping[str, object] | None = None,
    ) -> bool:
        """
        Validate that a cache row satisfies required fields.
        Treats processed_path as a special-case path validity check.

        :param row: Cached attribute row to validate.
        :param require: Required field names for a process.
        :return: True if requirements are satisfied, else False.
        """
        return (
            (
                policy.ART_FIELD_PROCESSED not in require
                or validate_path(row.get(policy.ART_FIELD_PROCESSED))
            )
            and all(
                row.get(k) is not None
                for k in require
                if k != policy.ART_FIELD_PROCESSED
            )
            and (not expected or all(row.get(k) == v for k, v in expected.items()))
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
        from resources.lib.art.io import write_image

        processed_path = None
        image = None
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
                # Texture cache miss — reuse an image opened by a prior step
                # (e.g. blur), else copy the source to temp.
                cached_images = shared["image_cache"].get(art_type, {})
                if cached_images:
                    source_path, image = next(iter(cached_images.items()))
                elif temp := self.cache_manager.source_temp_path(ctx):
                    source_path = temp
                else:
                    return None

        if image is None:
            image = shared["image_cache"][art_type].get(
                source_path
            ) or self._image_open(source_path)

        if image is None:
            return None

        shared["image_cache"][art_type][source_path] = image
        result = process_method(
            image,
            opts=opts,
            attrs=shared["results"][art_type],
        )
        if result is None:
            return None

        if folder and "image" in result:
            processed_path = destination_path
            create_dir(folder)
            write_image(
                processed_path, result["image"], result.get("format", "PNG"), self.cfg
            )

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
                log.debug(
                    f"{self.__class__.__name__} → Temp file cleanup failed → {source_path}",
                )

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
            for key in policy.ART_SOURCE_KEYS.get(art_type, (art_type,))
            if (path := infolabel(f"{source}.Art({key})"))
        }
        log.debug(
            f"{self.__class__.__name__} → _fetch_art_url({art_type}, {source}) → {candidates=}",
        )
        return policy.resolve_art_type(candidates, art_type)

    def _image_open(self, url: str) -> Image.Image | None:
        """
        Open an image from Kodi VFS via Pillow.
        Skips unsupported formats and returns None on failure.

        :param url: Kodi VFS or translated path to the image resource.
        :return: PIL Image or None if missing/unsupported/unreadable.
        """
        if url.lower().endswith(".svg"):
            log.debug(f"{self.__class__.__name__} → Skipping unsupported SVG → {url}")
            return None

        from PIL import Image

        try:
            return Image.open(xbmcvfs.translatePath(url))

        except (FileNotFoundError, OSError) as error:
            log.error(
                f"{self.__class__.__name__} → Unable to open image {url} → {error}",
            )
            return None
