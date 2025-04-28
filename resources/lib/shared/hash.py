import hashlib
from pathlib import Path


class HashManager:
    @staticmethod
    def compute_hash(file_path):
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
        return current_hash == stored_hash
