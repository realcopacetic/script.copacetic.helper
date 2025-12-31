# author: realcopacetic

import json
import sqlite3
import time
from typing import Mapping, Any

from resources.lib.art import policy
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
    Base SQLite handler with WAL-enabled connections.
    Provides shared CRUD helpers for SQLite-backed caches.
    Subclasses must set TABLE_NAME, implement _initialize_database().
    """

    TABLE_NAME: str | None = None

    def __init__(self, db_path: str | None = None) -> None:
        """
        Initialise database path and ensure schema exists.

        :param db_path: Optional sqlite database path override.
        :return: None.
        """
        self.db_path = db_path or LOOKUPS
        self._initialize_database()

    def _initialize_database(self) -> None:
        """
        Create tables and indexes for the handler.
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    def _connect(self) -> sqlite3.Connection:
        """
        Open a SQLite connection with WAL mode enabled.

        :return: Active sqlite3 connection.
        """
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def _insert_or_replace(
        self, columns: tuple[str, ...], values: tuple[Any, ...]
    ) -> None:
        """
        Insert or replace a row using dynamic columns.

        :param columns: Ordered column names to write.
        :param values: Ordered values matching the columns.
        """
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
        """
        Delete rows matching a WHERE clause.

        :param where: SQL WHERE clause (without the WHERE keyword).
        :param params: SQL parameters for the WHERE clause.
        """
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
        """
        Fetch a single row from a table.

        :param table: SQL table name.
        :param where: SQL WHERE clause (without the WHERE keyword).
        :param params: SQL parameters for the WHERE clause.
        :return: Row dict if found, else None.
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM {table} WHERE {where}", params)
            row = cursor.fetchone()
            if not row:
                return None

            col_names = [desc[0] for desc in cursor.description]
            return dict(zip(col_names, row))

    def clear_all(self) -> None:
        """
        Remove all rows from TABLE_NAME.
        Clears cached data entirely.
        """
        if not self.TABLE_NAME:
            raise RuntimeError("TABLE_NAME must be set on subclasses.")

        with self._connect() as conn:
            conn.execute(f"DELETE FROM {self.TABLE_NAME}")
            conn.commit()


class ArtworkCacheHandler(SQLiteHandler):
    """
    Cache for processed artwork attributes.
    Stores paths, hashes, and color metadata.
    """

    TABLE_NAME = "artwork"
    _IMMUTABLE_COLUMNS = {policy.ART_FIELD_CACHE_KEY}
    _ALLOWED_UPDATE_COLS = set(policy.ART_DB_FIELDS) - _IMMUTABLE_COLUMNS

    def __init__(self) -> None:
        super().__init__()

    def _initialize_database(self) -> None:
        """
        Create artwork cache table and indexes.
        Ensures schema exists before use.
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    cache_key TEXT UNIQUE NOT NULL,
                    source_url TEXT NOT NULL,
                    process TEXT NOT NULL,
                    processed_path TEXT,
                    cached_file_hash TEXT,
                    blur_radius INTEGER,
                    color TEXT,
                    accent TEXT,
                    contrast TEXT,
                    luminosity INTEGER
                    darken INTEGER,
                    element_darken INTEGER,
                    element_darken1 INTEGER,
                    element_darken2 INTEGER,
                    darken_mode TEXT,
                    darken_source TEXT,
                    darken_rects TEXT,
                    darken_frame TEXT,
                    darken_target TEXT
                )
                """
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_cache_key "
                f"ON {self.TABLE_NAME} (cache_key)"
            )
            cursor.execute(
                f"CREATE INDEX IF NOT EXISTS idx_source_url "
                f"ON {self.TABLE_NAME} (source_url)"
            )
            conn.commit()

    def add_entry(self, attributes: dict[str, Any]) -> None:
        """
        Insert or replace an artwork cache record.

        :param attributes: Canonical artwork attributes for ART_DB_FIELDS.
        """
        row = tuple(attributes.get(col) for col in policy.ART_DB_FIELDS)
        self._insert_or_replace(policy.ART_DB_FIELDS, row)

    def get_entry(self, cache_key: str) -> dict[str, Any] | None:
        """
        Retrieve a cached artwork record by cache_key.

        :param cache_key: Unique key for a process+variant row.
        :return: Cached record dict, or None.
        """
        return self._get_one(
            table=self.TABLE_NAME,
            where="cache_key = ?",
            params=(cache_key,),
        )

    def update_fields(self, cache_key: str, fields: Mapping[str, Any]) -> int:
        """
        Update mutable artwork fields for a cache_key.

        :param cache_key: Unique key for a process+variant row.
        :param fields: Field/value mapping to update.
        :return: Number of rows updated.
        """
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
                    WHERE cache_key = ?
                    """,
                    (*vals, cache_key),
                )
                conn.commit()
                return cur.rowcount or 0
        except Exception:
            return 0

    def update_field(self, cache_key: str, column: str, value: Any) -> int:
        """
        Update a single mutable field for a cache_key.

        :param cache_key: Unique key for a process+variant row.
        :param column: Column name to update.
        :param value: New column value.
        :return: Number of rows updated.
        """
        return self.update_fields(cache_key, **{column: value})


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
        """
        Create TMDb cache table and indexes.
        Ensures schema exists before use.
        """
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
        """
        Retrieve a cached TMDb payload by identifiers.
        Validates TTL and parses stored JSON.

        :param dbtype: Media database type.
        :param tmdb_id: TMDb numeric identifier.
        :param language: Language code.
        :return: Cached TMDb record or None.
        """
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
        """
        Delete a TMDb cache entry.
        Removes matching row from SQLite.

        :param dbtype: Media database type.
        :param tmdb_id: TMDb numeric identifier.
        :param language: Language code.
        """
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
        Insert or update a TMDb cache entry.
        Removes expired entries before write.

        :param dbtype: Media database type.
        :param tmdb_id: TMDb numeric identifier.
        :param language: Language code.
        :param payload: Raw TMDb response payload.
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
