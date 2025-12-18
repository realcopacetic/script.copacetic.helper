# author: realcopacetic

import json
import sqlite3
import time
from typing import Any

from resources.lib.art.policy import ART_DB_FIELDS
from resources.lib.shared.utilities import LOOKUPS


TMDB_DB_COLUMNS: tuple[str, ...] = (
    "dbtype",
    "tmdb_id",
    "language",
    "fetched_at",
    "payload",
)


class SQLiteHandler:
    """
    Base SQLite handler providing unified connection (WAL mode),
    table name enforcement and basic CRUD operation helpers.
    Subclasses must set TABLE_NAME, implement _initialize_database().
    """
    TABLE_NAME: str | None = None

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or LOOKUPS
        self._initialize_database()

    def _initialize_database(self) -> None:
        """Subclasses must implement table creation."""
        raise NotImplementedError

    def _connect(self) -> sqlite3.Connection:
        """Unified connection helper with WAL mode."""
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _insert_or_replace(
        self, columns: tuple[str, ...], values: tuple[Any, ...]
    ) -> None:
        """INSERT OR REPLACE helper using a dynamic column list."""
        if not self.TABLE_NAME:
            raise RuntimeError("TABLE_NAME must be defined.")

        cols = ", ".join(columns)
        placeholders = ", ".join("?" for _ in columns)

        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT OR REPLACE INTO {self.TABLE_NAME} (
                    {cols}
                ) VALUES ({placeholders})
                """,
                values,
            )
            conn.commit()

    def _delete_where(self, where: str, params: tuple[Any, ...]) -> None:
        """DELETE helper with dynamic WHERE clause."""
        if not self.TABLE_NAME:
            raise RuntimeError("TABLE_NAME must be defined.")

        with self._connect() as conn:
            conn.execute(
                f"DELETE FROM {self.TABLE_NAME} WHERE {where}",
                params,
            )
            conn.commit()

    def _get_one(
        self,
        table: str,
        where: str,
        params: tuple[Any, ...],
    ) -> dict[str, Any] | None:
        """Return a single row as dict or None."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM {table} WHERE {where}", params)
            row = cursor.fetchone()
            if not row:
                return None

            col_names = [desc[0] for desc in cursor.description]
            return dict(zip(col_names, row))

    def clear_all(self) -> None:
        """Delete every row in this table."""
        if not self.TABLE_NAME:
            raise RuntimeError("TABLE_NAME must be set on subclasses.")

        with self._connect() as conn:
            conn.execute(f"DELETE FROM {self.TABLE_NAME}")
            conn.commit()


class ArtworkCacheHandler(SQLiteHandler):
    """
    Stores processed artwork data (colors, hashes, processed_path, etc.)
    """
    TABLE_NAME = "artwork"
    _IMMUTABLE_COLUMNS = {"category", "original_url"}
    _ALLOWED_UPDATE_COLS = set(ART_DB_FIELDS) - _IMMUTABLE_COLUMNS

    def __init__(self) -> None:
        super().__init__()

    def _initialize_database(self) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    original_url TEXT UNIQUE NOT NULL,
                    processed_path TEXT,
                    cached_file_hash TEXT,
                    color TEXT,
                    accent TEXT,
                    contrast TEXT,
                    luminosity INTEGER
                )
                """
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_url "
                f"ON {self.TABLE_NAME} (original_url)"
            )
            conn.commit()

    def add_entry(self, category: str, attributes: dict[str, Any]) -> None:
        """Insert/replace an artwork entry using ART_DB_FIELDS."""
        row = tuple(
            category if col == "category" else attributes.get(col)
            for col in ART_DB_FIELDS
        )
        self._insert_or_replace(ART_DB_FIELDS, row)

    def get_entry(self, original_url: str) -> dict[str, Any] | None:
        return self._get_one(
            table=self.TABLE_NAME,
            where="original_url = ?",
            params=(original_url,),
        )

    def update_fields(self, url: str, **fields: Any) -> int:
        """Update selected mutable fields by original_url."""
        safe_items = [
            (col, val)
            for col, val in fields.items()
            if col in self._ALLOWED_UPDATE_COLS and val is not None
        ]
        if not safe_items:
            return 0

        cols, vals = zip(*safe_items)
        assignments = ", ".join(f"{c} = ?" for c in cols)

        try:
            with self._connect() as conn:
                cur = conn.cursor()
                cur.execute(
                    f"""
                    UPDATE {self.TABLE_NAME}
                    SET {assignments}
                    WHERE original_url = ?
                    """,
                    (*vals, url),
                )
                conn.commit()
                return cur.rowcount or 0
        except Exception:
            return 0

    def update_field(self, url: str, column: str, value: Any) -> int:
        return self.update_fields(url, **{column: value})


class TmdbCacheHandler(SQLiteHandler):
    """
    Stores canonical TMDb payloads as raw JSON with
    dbtype, tmdb_id, language, fetched_at, payload (TEXT)
    """
    TABLE_NAME = "tmdb_cache"
    TTL_SECONDS = 86400 * 7  # 7 days

    def __init__(self) -> None:
        super().__init__()

    def _initialize_database(self) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    dbtype TEXT NOT NULL,
                    tmdb_id INTEGER NOT NULL,
                    language TEXT NOT NULL,
                    fetched_at INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    UNIQUE (dbtype, tmdb_id, language)
                )
                """
            )
            cursor.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_tmdb_cache_lookup
                ON {self.TABLE_NAME}(dbtype, tmdb_id, language)
                """
            )
            conn.commit()

    def get_entry(
        self, dbtype: str, tmdb_id: int, language: str
    ) -> dict[str, Any] | None:
        row = self._get_one(
            table=self.TABLE_NAME,
            where="dbtype = ? AND tmdb_id = ? AND language = ?",
            params=(dbtype, tmdb_id, language),
        )
        if not row:
            return None

        now = int(time.time())
        if now - int(row["fetched_at"]) > self.TTL_SECONDS:
            self.delete_entry(dbtype, tmdb_id, language)
            return None

        try:
            row["payload"] = json.loads(row["payload"])
        except Exception:
            self.delete_entry(dbtype, tmdb_id, language)
            return None

        return row

    def delete_entry(self, dbtype: str, tmdb_id: int, language: str) -> None:
        self._delete_where(
            "dbtype = ? AND tmdb_id = ? AND language = ?",
            (dbtype, tmdb_id, language),
        )

    def upsert_entry(
        self,
        dbtype: str,
        tmdb_id: int,
        language: str,
        payload: dict[str, Any],
    ) -> None:
        """
        Insert or replace a TMDb cache entry and purge stale rows.

        :param dbtype: 'movie', 'tv', etc.
        :param tmdb_id: TMDb numeric ID.
        :param language: TMDb language/region code (e.g. 'en-US').
        :param payload: Parsed TMDb JSON payload as a dict.
        """
        now = int(time.time())
        cutoff = now - self.TTL_SECONDS
        payload_json = json.dumps(payload, separators=(",", ":"))
        self._delete_where("fetched_at < ?", (cutoff,))
        row = (
            dbtype,
            tmdb_id,
            language,
            now,
            payload_json,
        )
        self._insert_or_replace(TMDB_DB_COLUMNS, row)
