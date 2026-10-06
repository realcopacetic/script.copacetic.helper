# author: realcopacetic

import json
import sqlite3
import time
from functools import cached_property
from pathlib import Path
from typing import Any, Mapping

from resources.lib.art import policy
from resources.lib.shared import logger as log
from resources.lib.shared.utilities import LOOKUPS, create_dir

TRUNCATE_DB_SCHEMA = (
    ("cache_key", "TEXT NOT NULL UNIQUE"),
    ("result", "TEXT NOT NULL"),
    ("created_at", "INTEGER NOT NULL"),
)

TRUNCATE_DB_FIELDS = tuple(name for name, _ in TRUNCATE_DB_SCHEMA)


class SQLiteHandler:
    """
    Base SQLite handler: one WAL connection per instance, shared CRUD helpers.
    Subclasses must set TABLE_NAME, implement _initialize_database().
    """

    TABLE_NAME = None

    def __init__(self, db_path: str | None = None) -> None:
        """
        Initialise database path and ensure schema exists.

        :param db_path: Optional sqlite database path override.
        :return: None.
        """
        self.db_path = db_path or LOOKUPS
        create_dir(str(Path(self.db_path).parent))
        self._initialize_database()

    def _initialize_database(self) -> None:
        """
        Create tables and indexes for the handler.
        Must be implemented by subclasses.
        """
        raise NotImplementedError

    @cached_property
    def _conn(self) -> sqlite3.Connection:
        """
        This handler's connection, opened on first use. WAL mode persists in
        the database file, so it is set once here rather than per query.
        """
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.row_factory = sqlite3.Row
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

        with self._conn as conn:
            conn.execute(
                f"""
                INSERT OR REPLACE INTO {self.TABLE_NAME} (
                    {cols}
                ) VALUES ({placeholders})
                """,
                values,
            )

    def _delete_where(self, where: str, params: tuple[Any, ...]) -> None:
        """
        Delete rows matching a WHERE clause.

        :param where: SQL WHERE clause (without the WHERE keyword).
        :param params: SQL parameters for the WHERE clause.
        """
        if not self.TABLE_NAME:
            raise RuntimeError("TABLE_NAME must be defined.")

        with self._conn as conn:
            conn.execute(
                f"DELETE FROM {self.TABLE_NAME} WHERE {where}",
                params,
            )

    def _get_one(
        self,
        where: str,
        params: tuple[Any, ...],
    ) -> dict[str, Any] | None:
        """
        Fetch a single row from a table.

        :param where: SQL WHERE clause (without the WHERE keyword).
        :param params: SQL parameters for the WHERE clause.
        :return: Row dict if found, else None.
        """
        row = self._conn.execute(
            f"SELECT * FROM {self.TABLE_NAME} WHERE {where}", params
        ).fetchone()
        return dict(row) if row else None

    def _get_many(
        self,
        where: str,
        params: tuple[Any, ...],
    ) -> list[dict[str, Any]]:
        """
        Fetch all rows matching a WHERE clause.

        :param where: SQL WHERE clause (without the WHERE keyword).
        :param params: SQL parameters for the WHERE clause.
        :return: List of row dicts (empty if no matches).
        """
        rows = self._conn.execute(
            f"SELECT * FROM {self.TABLE_NAME} WHERE {where}", params
        )
        return [dict(row) for row in rows]

    def clear_all(self) -> None:
        """
        Remove all rows from TABLE_NAME.
        Clears cached data entirely.
        """
        if not self.TABLE_NAME:
            raise RuntimeError("TABLE_NAME must be set on subclasses.")

        with self._conn as conn:
            conn.execute(f"DELETE FROM {self.TABLE_NAME}")


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
        Create artwork cache table and indexes, adding any columns an older
        cache lacks so writes of every ART_DB_FIELDS column succeed.
        """
        cols_sql = ",\n".join(f"{name} {decl}" for name, decl in policy.ART_DB_SCHEMA)
        unique_sql = ", ".join(policy.ART_DB_UNIQUE)

        with self._conn as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    {cols_sql},
                    UNIQUE ({unique_sql})
                )
                """)

            have = {
                row[1] for row in conn.execute(f"PRAGMA table_info({self.TABLE_NAME})")
            }
            for name, decl in policy.ART_DB_SCHEMA:
                if name not in have:
                    conn.execute(
                        f"ALTER TABLE {self.TABLE_NAME} ADD COLUMN {name} {decl}"
                    )

            for idx_name, cols in policy.ART_DB_INDEXES:
                idx_cols_sql = ", ".join(cols)
                conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS {idx_name}
                    ON {self.TABLE_NAME}({idx_cols_sql})
                    """)

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
            where="cache_key = ?",
            params=(cache_key,),
        )

    def find_variants(
        self,
        source_url: str,
        process: str,
        variant: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Find rows for a sourceprocess whose stored variant fields equal `variant`.
        Used to identify stale rows when writing a new entry: same sourceprocessvariant
        but a different cache_key implies the underlying content has changed.

        :param source_url: Source URL column value.
        :param process: Process column value.
        :param variant: Variant field values to match exactly. None/empty matches all.
        :return: List of matching row dicts.
        """
        rows = self._get_many(
            where=(
                f"{policy.ART_FIELD_SOURCE_URL} = ? AND "
                f"{policy.ART_FIELD_PROCESS} = ?"
            ),
            params=(source_url, process),
        )
        if not variant:
            return rows
        return [r for r in rows if all(r.get(k) == v for k, v in variant.items())]

    def delete_entry(self, cache_key: str) -> None:
        """
        Delete a single row by cache_key.

        :param cache_key: Unique key of the row to remove.
        """
        self._delete_where(
            where=f"{policy.ART_FIELD_CACHE_KEY} = ?",
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
            with self._conn as conn:
                cur = conn.execute(
                    f"""
                    UPDATE {self.TABLE_NAME}
                    SET {assignments}
                    WHERE cache_key = ?
                    """,
                    (*vals, cache_key),
                )
                return cur.rowcount or 0
        except Exception:
            log.debug(
                f"{self.__class__.__name__} → update_fields failed for {cache_key=}"
            )
            return 0

    def update_field(self, cache_key: str, column: str, value: Any) -> int:
        """
        Update a single mutable field for a cache_key.

        :param cache_key: Unique key for a process+variant row.
        :param column: Column name to update.
        :param value: New column value.
        :return: Number of rows updated.
        """
        return self.update_fields(cache_key, {column: value})


class TruncateCacheHandler(SQLiteHandler):
    """Stores clamp_text results keyed by a hash of text and geometry."""

    TABLE_NAME = "truncate_cache"

    def __init__(self) -> None:
        super().__init__()

    def _initialize_database(self) -> None:
        """Create the truncate cache table."""
        cols_sql = ",\n".join(f"{name} {decl}" for name, decl in TRUNCATE_DB_SCHEMA)
        with self._conn as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    {cols_sql}
                )
                """)

    def get_entry(self, cache_key: str) -> str | None:
        """
        Retrieve a cached clamp result.

        :param cache_key: Hash of text, font, size, width and line count.
        :return: Clamped string, or None.
        """
        row = self._get_one(where="cache_key = ?", params=(cache_key,))
        return row["result"] if row else None

    def upsert_entry(self, cache_key: str, result: str) -> None:
        """
        Insert or replace a clamp result.

        :param cache_key: Hash of text, font, size, width and line count.
        :param result: Clamped string to store.
        """
        self._insert_or_replace(
            TRUNCATE_DB_FIELDS, (cache_key, result, int(time.time()))
        )


class ApiCacheHandler(SQLiteHandler):
    """
    Web API answers as JSON keyed "<api>:<what>:<id>"; the writer picks each
    row's expiry, a NULL payload is a negative entry, and reads never delete.
    """

    TABLE_NAME = "api_cache"

    def _initialize_database(self) -> None:
        """Create the API cache table and its expiry index; drop the old tmdb_cache."""
        with self._conn as conn:
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.TABLE_NAME} (
                    key TEXT PRIMARY KEY,
                    payload TEXT,
                    expires_at INTEGER NOT NULL
                ) WITHOUT ROWID
                """)
            conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_api_cache_expires
                ON {self.TABLE_NAME}(expires_at)
                """)
            conn.execute("DROP TABLE IF EXISTS tmdb_cache")  # TMDb's own, pre api_cache

    def get(self, key: str) -> tuple[Any, bool] | None:
        """
        The cached answer for key, expired or not.

        :param key: Cache key.
        :return: (payload, fresh), payload None for a negative entry; None if absent.
        """
        if not (row := self._get_one(where="key = ?", params=(key,))):
            return None
        payload = row["payload"] and json.loads(row["payload"])
        return payload, row["expires_at"] > time.time()

    def put(self, key: str, payload: Any, ttl: int) -> None:
        """
        Store payload for key until ttl seconds from now.

        :param key: Cache key.
        :param payload: JSON-serialisable answer; None for a negative entry.
        :param ttl: Seconds the row stays fresh.
        """
        self._insert_or_replace(
            ("key", "payload", "expires_at"),
            (
                key,
                None if payload is None else json.dumps(payload, separators=(",", ":")),
                int(time.time()) + ttl,
            ),
        )

    def prune(self, grace: int = 86400 * 30) -> None:
        """
        Delete rows expired more than grace seconds ago.

        :param grace: Seconds an expired row is kept to serve when a refresh fails.
        """
        self._delete_where("expires_at < ?", (int(time.time()) - grace,))
