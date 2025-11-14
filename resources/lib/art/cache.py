# author: realcopacetic

from pathlib import Path
from typing import Any

import xbmc
import xbmcvfs

from resources.lib.art.policy import ART_FIELD_PROCESSED, ART_FIELD_HASH
from resources.lib.shared.hash import HashManager
from resources.lib.shared.sqlite import SQLiteHandler
from resources.lib.shared.utilities import (
    TEMPS,
    THUMB_DB,
    log,
    url_decode_path,
    validate_path,
)


class ArtworkCacheManager:
    """
    Handles file path resolution, thumbnail naming, and lookup caching
    for processed artwork files using file hash verification and SQLite.
    """

    def __init__(
        self, sqlite_handler: SQLiteHandler, hash_manager: HashManager
    ) -> None:
        """
        Initialize managers and working state.

        :param sqlite_handler: SQLite handler with get_entry/add_entry/update_field.
        :param hash_manager: Hash manager with compute_hash(path) -> str.
        """
        self.sqlite = sqlite_handler
        self.hash_manager = hash_manager
        self.temp_folder = TEMPS

        # Cached state after prepare_cache() is called
        self.decoded_url = None
        self.cached_thumb = None
        self.cached_image_path = None
        self.cached_file_hash = None

    def prepare_cache(self, url: str, suffix: str) -> None:
        """
        Decode URL, compute cache filename, locate cached image, and file hash.

        :param url: Original artwork URL.
        :param suffix: File extension (e.g., ".jpg", ".png").
        """
        self.decoded_url = url_decode_path(url)
        self.cached_thumb = self.get_cached_thumb(self.decoded_url, suffix)
        self.cached_image_path = (
            Path(THUMB_DB) / self.cached_thumb[0] / self.cached_thumb
        )
        self.cached_file_hash = ""
        if validate_path(self.cached_image_path):
            self.cached_file_hash = self.hash_manager.compute_hash(
                self.cached_image_path
            )

    def get_cached_thumb(self, url: str, suffix: str) -> str:
        """
        Build a cache-safe filename for the given URL and target suffix.

        :param url: Artwork URL (decoded/encoded accepted).
        :param suffix: Desired file extension (e.g., ".jpg", ".png").
        :return: Cache-friendly filename string (no directories).
        """
        return xbmc.getCacheThumbName(url).replace(".tbn", f"{suffix}")

    def get_image_paths(self, folder: str) -> tuple[str | None, str]:
        """
        Resolve source and destination paths for processing; copy to temp if needed.

        :param folder: Destination folder for processed images.
        :return: (source_path or None, destination_path).
        """
        source_path = str(self.cached_image_path)
        destination_path = str(Path(folder) / self.cached_thumb)

        if validate_path(source_path):
            return source_path, destination_path

        temp_path = str(Path(self.temp_folder) / self.cached_thumb)
        if not validate_path(temp_path) and xbmcvfs.copy(self.decoded_url, temp_path):
            log.debug(f"{self.__class__.__name__}: Temporary file created → {temp_path}")
            return temp_path, destination_path
        return None, destination_path

    def read_lookup(self, url: str) -> dict[str, Any] | None:
        """
        Read cached metadata for URL and validate against current file hash.

        :param url: Original image URL (lookup key).
        :return: Cached metadata dict if valid, else None.
        """
        if not (entry := self.sqlite.get_entry(url)):
            return None

        processed = validate_path(entry.get(ART_FIELD_PROCESSED))
        if not processed:
            return None

        # If no hash computed yet (first-touch), trust the processed file
        if not self.cached_file_hash:
            return entry

        db_hash = entry.get(ART_FIELD_HASH)

        # If both have hashes, require match
        if db_hash and db_hash == self.cached_file_hash:
            return entry

        # If DB hash empty but we have one now, backfill without reprocessing
        if not db_hash and self.cached_file_hash:
            self.sqlite.update_field(url, ART_FIELD_HASH, self.cached_file_hash)
            return entry

        # Hash mismatch and both populated → stale entry
        return None

    def write_lookup(self, art_type: str, metadata: dict[str, Any]) -> None:
        """
        Persist processed metadata to SQLite lookup.

        :param art_type: Artwork type for categorization (e.g., "clearlogo").
        :param metadata: Processed attributes including paths, colors, and hashes.
        """
        if metadata:
            category = "clearlogo" if "clearlogo" in art_type else art_type
            self.sqlite.add_entry(category, metadata)
