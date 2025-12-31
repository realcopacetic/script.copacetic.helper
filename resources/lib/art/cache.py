# author: realcopacetic

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import xbmc
import xbmcvfs

from resources.lib.art import policy
from resources.lib.shared.hash import HashManager
from resources.lib.shared.sqlite import ArtworkCacheHandler
from resources.lib.shared.utilities import (
    TEMPS,
    THUMB_DB,
    log,
    url_decode_path,
    validate_path,
)


@dataclass(frozen=True, slots=True)
class CacheContext:
    """Resolved, immutable cache context for a single artwork URL."""

    source_url: str
    decoded_url: str
    suffix: str
    cached_thumb: str
    cached_image_path: Path
    cached_file_hash: str
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

    def prepare(self, url: str, suffix: str) -> CacheContext:
        """
        Resolve Kodi texture-cache paths and compute source hash.

        :param url: Original artwork URL.
        :param suffix: File extension (e.g., ".jpg", ".png").
        :return: CacheContext for the resolved source.
        """
        decoded_url = url_decode_path(url)
        cached_thumb = self.get_cached_thumb(decoded_url, suffix)
        cached_image_path = Path(THUMB_DB) / cached_thumb[0] / cached_thumb
        cached_file_hash = (
            self.hash_manager.compute_hash(cached_image_path)
            if validate_path(cached_image_path)
            else ""
        )
        return CacheContext(
            source_url=url,
            decoded_url=decoded_url,
            suffix=suffix,
            cached_thumb=cached_thumb,
            cached_image_path=cached_image_path,
            cached_file_hash=cached_file_hash,
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
        return (
            ""
            if not expected
            else "&".join(f"{k}={expected[k]}" for k in sorted(expected))
        )

    def with_process_variant(
        self,
        base: CacheContext,
        *,
        process: str,
        expected: Mapping[str, object] | None = None,
        folder: str | None = None,
    ) -> CacheContext:
        """
        Derive a per-process/per-variant cache context.

        :param base: Base CacheContext resolved from source_url.
        :param process: Process name (e.g., "blur", "crop", "analyze").
        :param expected: Variant match parameters for this process.
        :param folder: Output folder when this process writes a file.
        :return: Derived CacheContext with cache_key and dest_thumb.
        """
        token = self._variant_token(expected)
        cache_key = f"{base.source_url}|{process}" + (f"|{token}" if token else "")

        # Only need unique filenames for file-writing processes (folder is not None).
        if folder and token:
            stem = Path(base.cached_thumb).stem
            vhash = self.hash_manager.short_hash_str(token, length=8)
            dest_thumb = f"{stem}__{vhash}{base.suffix}"
        else:
            dest_thumb = base.cached_thumb

        return CacheContext(
            source_url=base.source_url,
            decoded_url=base.decoded_url,
            suffix=base.suffix,
            cached_thumb=base.cached_thumb,
            cached_image_path=base.cached_image_path,
            cached_file_hash=base.cached_file_hash,
            cache_key=cache_key,
            dest_thumb=dest_thumb,
        )

    def get_image_paths(self, folder: str, ctx: CacheContext) -> tuple[str | None, str]:
        """
        Resolve (source_path, destination_path) for processing.

        :param folder: Destination folder for processed images.
        :param ctx: CacheContext for source/variant.
        :return: Tuple of (source_path or None, destination_path).
        """
        source_path = str(ctx.cached_image_path)
        destination_path = str(Path(folder) / ctx.dest_thumb)
        if validate_path(source_path):
            log.debug(
                f"{self.__class__.__name__} → get_image_paths: "
                f"using existing texture-cache file → {source_path}"
            )
            return source_path, destination_path

        temp_path = str(Path(self.temp_folder) / ctx.cached_thumb)
        if not validate_path(temp_path) and xbmcvfs.copy(ctx.decoded_url, temp_path):
            log.debug(f"{self.__class__.__name__} → Temp file created → {temp_path}")
            return temp_path, destination_path

        return None, destination_path

    def read_lookup(
        self,
        ctx: CacheContext,
        *,
        require: tuple[str, ...] = (),
    ) -> dict[str, Any] | None:
        """
        Read cached metadata and validate against the current source hash.

        :param ctx: CacheContext with cache_key and cached_file_hash.
        :param require: Required field names that must be present.
        :return: Cached metadata dict if valid, else None.
        """
        if not (entry := self.sqlite.get_entry(ctx.cache_key)):
            return None

        if require:
            if policy.ART_FIELD_PROCESSED in require and not validate_path(
                entry.get(policy.ART_FIELD_PROCESSED)
            ):
                return None

            missing = (set(require) - {policy.ART_FIELD_PROCESSED}) - entry.keys()
            if missing:
                return None

        if not ctx.cached_file_hash:  # trust processed if no hash computed yet
            return entry

        db_hash = entry.get(policy.ART_FIELD_HASH)
        if db_hash and db_hash == ctx.cached_file_hash:  # require match if both hashed
            return entry

        if not db_hash and ctx.cached_file_hash:  # backfill hash without reprocessing
            self.sqlite.update_field(
                ctx.cache_key, policy.ART_FIELD_HASH, ctx.cached_file_hash
            )
            return entry

        return None  # Hash mismatch → stale entry

    def write_lookup(self, metadata: dict[str, Any]) -> None:
        """
        Persist a cache row into SQLite.

        :param metadata: Processed attributes including keys and hashes.
        """
        meta = metadata or {}
        cache_key = meta.get(policy.ART_FIELD_CACHE_KEY)
        source_url = meta.get(policy.ART_FIELD_SOURCE_URL)
        process = meta.get(policy.ART_FIELD_PROCESS)

        if not cache_key or not source_url or not process:
            log.error(
                f"{self.__class__.__name__} → write_lookup missing required keys → "
                f"{cache_key=}, {source_url=}, {process=}"
            )
            return

        self.sqlite.add_entry(meta)

    def delete_by_source_url(self, source_url: str) -> int:
        """
        Delete all cache rows for a given source_url.

        :param source_url: Original artwork URL to purge.
        :return: Number of rows deleted.
        """
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"DELETE FROM {self.TABLE_NAME} WHERE {policy.ART_FIELD_SOURCE_URL} = ?",
                (source_url,),
            )
            conn.commit()
            return cur.rowcount

    def delete_by_cache_key(self, cache_key: str) -> int:
        """
        Delete a cache row by cache_key.

        :param cache_key: Unique cache key to purge.
        :return: Number of rows deleted.
        """
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                f"DELETE FROM {self.TABLE_NAME} WHERE {policy.ART_FIELD_CACHE_KEY} = ?",
                (cache_key,),
            )
            conn.commit()
            return cur.rowcount

    def delete_processed_file_by_cache_key(self, cache_key: str) -> bool:
        """
        Delete processed file on disk for a cache_key, if present.

        :param cache_key: Unique cache key to look up processed_path.
        :return: True if a file was deleted, else False.
        """
        entry = self.get_entry(cache_key)
        if not entry:
            return False

        processed_path = entry.get(policy.ART_FIELD_PROCESSED)
        if not processed_path:
            return False

        try:
            if xbmcvfs.exists(processed_path):
                xbmcvfs.delete(processed_path)
                return True
        except Exception:
            return False

        return False
