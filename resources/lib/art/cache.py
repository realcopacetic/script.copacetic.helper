# author: realcopacetic

from pathlib import Path

import xbmc
import xbmcvfs

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

    def __init__(self, sqlite_handler, hash_manager):
        self.sqlite = sqlite_handler
        self.hash_manager = hash_manager
        self.temp_folder = TEMPS

        # Cached state after prepare_cache() is called
        self.decoded_url = None
        self.cached_thumb = None
        self.cached_image_path = None
        self.cached_file_hash = ""

    def prepare_cache(self, url, suffix):
        """
        Prepares cached file path and computes hash for given artwork URL.

        :param url: Original artwork URL.
        :param suffix: File extension (e.g., '.jpg', '.png').
        """
        self.decoded_url = url_decode_path(url)
        self.cached_thumb = self.get_cached_thumb(self.decoded_url, suffix)
        self.cached_image_path = (
            Path(THUMB_DB) / self.cached_thumb[0] / self.cached_thumb
        )
        if validate_path(self.cached_image_path):
            self.cached_file_hash = self.hash_manager.compute_hash(
                self.cached_image_path
            )

    def get_cached_thumb(self, url, suffix):
        """
        Returns thumbnail-safe filename for the given URL and suffix.

        :param url: Artwork URL.
        :param suffix: Desired file extension.
        :returns: Cache-friendly filename string.
        """
        return xbmc.getCacheThumbName(url).replace(".tbn", f"{suffix}")

    def get_image_paths(self, folder):
        """
        Gets source and destination file paths for processing.
        Falls back to a temp copy if the cached path doesn't exist.

        :param folder: Target destination folder for processed images.
        :returns: Tuple (source_path, destination_path)
        """
        source_path = str(self.cached_image_path)
        destination_path = str(Path(folder) / self.cached_thumb)

        if validate_path(source_path):
            return source_path, destination_path

        temp_path = str(Path(self.temp_folder) / self.cached_thumb)
        if not validate_path(temp_path) and xbmcvfs.copy(self.decoded_url, temp_path):
            log(f"{self.__class__.__name__}: Temporary file created → {temp_path}")
            return temp_path, destination_path
        return None, destination_path

    def read_lookup(self, url):
        """
        Reads cached lookup metadata for the given URL.

        :param url: Original image URL.
        :returns: Dict of cached metadata or None.
        """
        if not (entry := self.sqlite.get_entry(url)):
            return None

        processed = validate_path(entry.get("processed"))
        if not processed:
            return None

        # If no hash computed yet (first-touch), trust the processed file
        if not self.cached_file_hash:
            return entry

        db_hash = entry.get("cached_file_hash")

        # If both have hashes, require match
        if db_hash and db_hash == self.cached_file_hash:
            return entry

        # If DB hash empty but we have one now, backfill without reprocessing
        if not db_hash and self.cached_file_hash:
            self.sqlite.update_field(url, "cached_file_hash", self.cached_file_hash)
            return entry

        # Hash mismatch and both populated → stale entry
        return None

    def write_lookup(self, art_type, metadata):
        """
        Writes metadata to the cache lookup database.

        :param art_type: Type of artwork (e.g., 'clearlogo').
        :param metadata: Dictionary of attributes to store.
        """
        if metadata:
            category = "clearlogo" if "clearlogo" in art_type else art_type
            self.sqlite.add_entry(category, metadata)
