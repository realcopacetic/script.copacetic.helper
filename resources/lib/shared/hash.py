import hashlib
from pathlib import Path


class HashManager:
    @staticmethod
    def compute_hash(file_path):
        """Return the SHA-256 hex digest for a file, or None if the file is missing."""
        file_path = Path(file_path)
        if not file_path.exists():
            return None
        hash_func = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_func.update(chunk)
        return hash_func.hexdigest()

    @staticmethod
    def validate_hash(current_hash, stored_hash):
        """Return True if both hashes match."""
        return current_hash == stored_hash

    @staticmethod
    def compute_hash_str(value: str) -> str:
        """Return sha256 hex digest of a string (utf-8)."""
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def short_hash_str(cls, value: str, length: int = 8) -> str:
        """Return stable short hash for filenames/keys."""
        return HashManager.compute_hash_str(value)[:length]
