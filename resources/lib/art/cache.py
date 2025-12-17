# author: realcopacetic

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import xbmc
import xbmcvfs

from resources.lib.art.policy import ART_FIELD_PROCESSED, ART_FIELD_HASH
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
    original_url: str
    decoded_url: str
    suffix: str
    cached_thumb: str
    cached_image_path: Path
    cached_file_hash: str


class ArtworkCacheManager:
    """Resolve texture-cache and processing paths for a given artwork URL."""

    def __init__(
        self, sqlite_handler: ArtworkCacheHandler, hash_manager: HashManager
    ) -> None:
        """
        Initialize managers and working state.

        :param sqlite_handler: SQLite handler with get_entry/add_entry/update_field.
        :param hash_manager: Hash manager with compute_hash(path) -> str.
        """
        self.sqlite = sqlite_handler
        self.hash_manager = hash_manager
        self.temp_folder = TEMPS

    def prepare(self, url: str, suffix: str) -> CacheContext:
        """
        Decode URL, compute cache filename, locate cached image, and file hash.

        :param url: Original artwork URL.
        :param suffix: File extension (e.g., ".jpg", ".png").
        :return CacheContext dataclass.
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
            original_url=url,
            decoded_url = decoded_url,
            suffix=suffix,
            cached_thumb=cached_thumb,
            cached_image_path=cached_image_path,
            cached_file_hash=cached_file_hash,
        )

    @staticmethod
    def get_cached_thumb(url: str, suffix: str) -> str:
        """
        Build a cache-safe filename for the given URL and target suffix.

        :param url: Artwork URL (decoded/encoded accepted).
        :param suffix: Desired file extension (e.g., ".jpg", ".png").
        :return: Cache-friendly filename string (no directories).
        """
        return xbmc.getCacheThumbName(url).replace(".tbn", suffix)

    def get_image_paths(self, folder: str, ctx: CacheContext) -> tuple[str | None, str]:
        """
        Resolve source and destination paths for processing; copy to temp if needed.

        :param folder: Destination folder for processed images.
        :return: (source_path or None, destination_path).
        """
        source_path = str(ctx.cached_image_path)
        destination_path = str(Path(folder) / ctx.cached_thumb)
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
        Read cached metadata for URL and validate against current file hash.

        :param ctx: CacheContext with original_url and cached_file_hash.
        :param require: Require these keys to exist in the row.
        :return: Cached metadata dict if valid, else None.
        """
        if not (entry := self.sqlite.get_entry(ctx.original_url)):
            return None

        if require:
            if ART_FIELD_PROCESSED in require and not validate_path(entry.get(ART_FIELD_PROCESSED)):
                return None

            missing = (set(require) - {ART_FIELD_PROCESSED}) - entry.keys()
            if missing:
                return None

        if not ctx.cached_file_hash: #trust processed if no hash computed yet
            return entry

        db_hash = entry.get(ART_FIELD_HASH)
        if db_hash and db_hash == ctx.cached_file_hash: # require match if both hashed
            return entry

        if not db_hash and ctx.cached_file_hash: # backfill hash without reprocessing 
            self.sqlite.update_field(ctx.original_url, ART_FIELD_HASH, ctx.cached_file_hash)
            return entry

        return None  # Hash mismatch → stale entry

    def write_lookup(self, art_type: str, metadata: dict[str, Any]) -> None:
        """
        Persist processed metadata to SQLite lookup.

        :param art_type: Artwork type for categorization (e.g., "clearlogo").
        :param metadata: Processed attributes including paths, colors, and hashes.
        """
        if not metadata:
            return

        category = "clearlogo" if "clearlogo" in art_type else art_type
        self.sqlite.add_entry(category, metadata)
