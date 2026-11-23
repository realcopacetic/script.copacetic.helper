import hashlib
import os
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=2048)
def _file_digest(path: str, mtime_ns: int, size: int) -> str:
    """
    A file's SHA-256, kept by its identity: a file rewritten has a new mtime, so a
    kept digest is never stale (service-caches finding 6).

    :param path: Absolute file path on disk.
    :param mtime_ns: Its modification time, part of the key.
    :param size: Its size, part of the key.
    :return: SHA-256 hex digest.
    """
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 16):
            digest.update(chunk)
    return digest.hexdigest()


class HashManager:
    @staticmethod
    def compute_hash(file_path: str | Path) -> str | None:
        """
        Compute a SHA-256 file digest for cache validation; a file seen before at
        the same mtime and size reads no bytes.

        :param file_path: Absolute file path on disk.
        :return: SHA-256 hex digest, or None if file is missing.
        """
        try:
            stat = os.stat(file_path)
            return _file_digest(str(file_path), stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            return None

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
