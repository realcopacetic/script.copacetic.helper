import hashlib
import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=2048)
def _kept_digest(path: str, mtime_ns: int, size: int) -> str | None:
    """
    A file's SHA-256, kept by its identity: Kodi writes a re-cached thumb as a new
    file, so a kept digest is never stale (service-caches finding 6).

    :param path: Absolute file path on disk.
    :param mtime_ns: Its modification time, part of the key.
    :param size: Its size, part of the key.
    :return: SHA-256 hex digest, or None if it went before the read.
    """
    return HashManager.compute_hash(path)


class HashManager:
    @staticmethod
    def compute_hash(file_path: str | Path) -> str | None:
        """
        Compute a SHA-256 file digest for cache validation.

        :param file_path: Absolute file path on disk.
        :return: SHA-256 hex digest, or None if file is missing.
        """
        digest = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(1 << 16):
                    digest.update(chunk)
        except FileNotFoundError:
            return None
        return digest.hexdigest()

    @staticmethod
    def kept_hash(file_path: str | Path) -> str | None:
        """
        compute_hash for a cached thumb: a file seen before at the same mtime and size
        reads no bytes. Not for files rewritten in place (the builder's outputs).

        :param file_path: Absolute file path on disk.
        :return: SHA-256 hex digest, or None if file is missing.
        """
        try:
            stat = os.stat(file_path)
        except FileNotFoundError:
            return None
        return _kept_digest(str(file_path), stat.st_mtime_ns, stat.st_size)

    @staticmethod
    def compute_hash_str(value: str) -> str:
        """
        Compute a SHA-256 digest for a UTF-8 string.

        :param value: Input string.
        :return: SHA-256 hex digest.
        """
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def short_hash_str(value: str, length: int = 8) -> str:
        """
        Compute a stable shortened SHA-256 digest for a UTF-8 string.

        :param value: Input string.
        :param length: Length of the returned hex digest prefix.
        :return: Short SHA-256 hex digest prefix.
        """
        return HashManager.compute_hash_str(value)[:length]
