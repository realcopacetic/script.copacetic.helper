# author: realcopacetic

import time
from contextlib import suppress
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

import xbmc
import xbmcvfs

from resources.lib.art import policy
from resources.lib.shared import logger as log
from resources.lib.shared.hash import HashManager
from resources.lib.shared.sqlite import ArtworkCacheHandler
from resources.lib.shared.utilities import (
    TEMPS,
    THUMB_DB,
    infolabel,
    to_float,
    url_decode_path,
    validate_path,
    window_property,
)

DEAD_SOURCE_TTL = 900  # seconds a failed web source is not asked for again


@dataclass(frozen=True, slots=True)
class CacheContext:
    """Resolved, immutable cache context for a single artwork URL."""

    source_url: str
    decoded_url: str
    suffix: str
    cached_thumb: str
    cached_image_path: Path
    cached_file_hash: str | None
    cache_key: str
    dest_thumb: str


class ArtworkCacheManager:
    """Resolve texture-cache and processing paths for a given artwork URL."""

    def __init__(
        self, sqlite_handler: ArtworkCacheHandler, hash_manager: HashManager
    ) -> None:
        """
        Initialise cache manager dependencies and working folders.

        :param sqlite_handler: SQLite handler instance for artwork cache.
        :param hash_manager: Hash manager for file and string hashing.
        """
        self.sqlite = sqlite_handler
        self.hash_manager = hash_manager
        self.temp_folder = TEMPS

    def prepare(self, url: str) -> CacheContext:
        """
        Resolve Kodi texture-cache paths and compute source hash. Kodi picks its
        copy's suffix by alpha and keeps the old copy when a changed image recaches
        in the other format (TextureDatabase.cpp AddCachedTexture): take the newer.

        :param url: Original artwork URL.
        :return: CacheContext for the resolved source.
        """
        decoded_url = url_decode_path(url)
        suffix = ".png" if decoded_url.lower().endswith(".png") else ".jpg"
        cached_thumb = self.get_cached_thumb(decoded_url, suffix)
        cached_image_path = Path(THUMB_DB) / cached_thumb[0] / cached_thumb
        other = ".jpg" if suffix == ".png" else ".png"
        mtimes = {}  # the URL's suffix first: equal times keep it
        for path in (cached_image_path, cached_image_path.with_suffix(other)):
            with suppress(FileNotFoundError):  # a copy cleared meanwhile
                mtimes[path] = path.stat().st_mtime
        if mtimes:
            cached_image_path = max(mtimes, key=mtimes.get)
            suffix, cached_thumb = cached_image_path.suffix, cached_image_path.name
        return CacheContext(
            source_url=url,
            decoded_url=decoded_url,
            suffix=suffix,
            cached_thumb=cached_thumb,
            cached_image_path=cached_image_path,
            cached_file_hash=self.hash_manager.kept_hash(cached_image_path),
            cache_key=url,
            dest_thumb=cached_thumb,
        )

    @staticmethod
    def get_cached_thumb(url: str, suffix: str) -> str:
        """
        Build a Kodi cache-safe filename for a given URL and suffix.

        :param url: Artwork URL (decoded/encoded accepted).
        :param suffix: Desired file extension (e.g., ".jpg", ".png").
        :return: Cache-friendly filename (no directories).
        """
        return xbmc.getCacheThumbName(url).replace(".tbn", suffix)

    @staticmethod
    def _variant_token(expected: Mapping[str, object] | None) -> str:
        """
        Build a stable variant token from expected match fields.

        :param expected: Mapping of match field names to values.
        :return: Stable token string (or empty string).
        """
        return "&".join(f"{k}={v}" for k, v in sorted((expected or {}).items()))

    def with_process_variant(
        self,
        base: CacheContext,
        *,
        process: str,
        expected: Mapping[str, object] | None = None,
        folder: str | None = None,
        suffix: str | None = None,
    ) -> CacheContext:
        """
        Derive a per-process/per-variant cache context.

        :param base: Base CacheContext resolved from source_url.
        :param process: Process name (e.g., "blur", "crop", "darken").
        :param expected: Variant match parameters for this process.
        :param folder: Output folder when this process writes a file.
        :param suffix: The written file's extension; None keeps the source's.
        :return: Derived CacheContext with cache_key and dest_thumb.
        """
        token = self._variant_token(expected)
        key_id = base.cached_file_hash or base.source_url
        cache_key = f"{key_id}|{process}" + (f"|{token}" if token else "")
        suffix = suffix or base.suffix

        # Only need unique filenames for file-writing processes (folder is not None).
        if folder and token:
            stem = base.cached_file_hash or Path(base.cached_thumb).stem
            vhash = self.hash_manager.short_hash_str(token, length=8)
            dest_thumb = f"{stem}__{vhash}{suffix}"
        else:
            dest_thumb = str(Path(base.cached_thumb).with_suffix(suffix))
        return replace(base, cache_key=cache_key, dest_thumb=dest_thumb)

    def source_path(self, ctx: CacheContext) -> str | None:
        """
        The file to open the source from: Kodi's texture-cache copy, else a local file
        in place (a picture on disk), else a temp copy (a share, the web, image://).

        :param ctx: CacheContext for the source.
        :return: Path of the file, or None when the source can't be copied.
        """
        if validate_path(path := str(ctx.cached_image_path)):
            log.debug(f"{self.__class__.__name__} → texture-cache file → {path}")
            return path
        path = xbmcvfs.translatePath(ctx.decoded_url)
        if "://" not in path and validate_path(path):
            return path
        return self.source_temp_path(ctx)

    def source_temp_path(self, ctx: CacheContext) -> str | None:
        """
        Copy the source artwork to a temp file of this call's own (a parallel serve's
        copy would replace it mid-read); return its path. A web source that fails to
        copy is not asked for again for DEAD_SOURCE_TTL.
        """
        dead = f"artwork_dead_{Path(ctx.cached_thumb).stem}"
        failed = to_float(infolabel(f"Window(home).Property({dead})"))
        if 0 <= time.time() - failed < DEAD_SOURCE_TTL:
            return None
        temp_path = str(Path(self.temp_folder) / f"{uuid4().hex}_{ctx.cached_thumb}")
        if xbmcvfs.copy(ctx.decoded_url, temp_path):
            return temp_path
        if ctx.decoded_url.startswith(("http://", "https://")):
            window_property(dead, str(time.time()))
        return None

    def read_lookup(
        self,
        ctx: CacheContext,
        *,
        require: tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        """
        Read a cached row; a row missing its file or a required field is a miss.

        :param ctx: CacheContext with cache_key.
        :param require: Required field names that must be present.
        :return: Cached metadata dict if valid, else None.
        """
        if not (entry := self.sqlite.get_entry(ctx.cache_key)):
            return None
        processed = entry.get(policy.ART_FIELD_PROCESSED)
        if policy.ART_FIELD_PROCESSED in require and not validate_path(processed):
            return None
        cleaned = {k: v for k, v in entry.items() if v is not None}
        if set(require) - cleaned.keys():  # present and not None
            return None
        return cleaned  # the key holds the source's hash: a changed source misses

    def write_lookup(self, meta: dict[str, Any]) -> None:
        """
        Persist a cache row into SQLite.
        Evicts existing rows for the same source+process+variant — a different
        cache_key for the same variant means the source content has changed.

        :param meta: Processed attributes including keys and hashes.
        """
        cache_key = meta.get(policy.ART_FIELD_CACHE_KEY)
        source_url = meta.get(policy.ART_FIELD_SOURCE_URL)
        process = meta.get(policy.ART_FIELD_PROCESS)

        if not cache_key or not source_url or not process:
            log.error(
                f"{self.__class__.__name__} → write_lookup missing required keys → "
                f"{cache_key=}, {source_url=}, {process=}"
            )
            return

        new_path = meta.get(policy.ART_FIELD_PROCESSED)
        # Every input field, unused ones as None: a row that set more is another variant
        variant = {k: meta.get(k) for k in policy.ART_FIELDS_INPUT.get(process, ())}
        for row in self.sqlite.find_variants(source_url, process, variant):
            stale_key = row.get(policy.ART_FIELD_CACHE_KEY)
            if stale_key == cache_key:
                continue  # Will be replaced by add_entry below
            stale_path = row.get(policy.ART_FIELD_PROCESSED)
            if stale_path and stale_path != new_path:
                try:
                    # False when Kodi failed, or the file was already gone
                    kept = not xbmcvfs.delete(stale_path) and xbmcvfs.exists(stale_path)
                    outcome = "could not delete" if kept else "evicted"
                    log.debug(
                        f"{self.__class__.__name__} → write_lookup {outcome} stale "
                        f"file → {stale_path}"
                    )
                except Exception:
                    log.exception(
                        f"{self.__class__.__name__} → write_lookup could not "
                        f"delete {stale_path}",
                        log.DEBUG,
                    )
                    kept = True
                if kept:
                    continue  # its row keeps the file known: the next write retries
            self.sqlite.delete_entry(stale_key)

        self.sqlite.add_entry(meta)
