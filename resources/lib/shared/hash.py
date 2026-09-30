import hashlib
from pathlib import Path


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
