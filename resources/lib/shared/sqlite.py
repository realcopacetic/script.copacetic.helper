# author: realcopacetic

import json
import sqlite3
import time
from typing import Any

from resources.lib.art.policy import ART_DB_COLUMNS
from resources.lib.shared.utilities import LOOKUPS


class BaseSQLiteHandler:
    """
    Base SQLite handler providing a shared connection helper and DB path.

    Subclasses must implement `_initialize_database()` to create their tables.
    """

    def __init__(self, db_path: str | None = None) -> None:
        """
        :param db_path: Optional custom path for the SQLite database.
        """
        self.db_path = db_path or LOOKUPS
        self._initialize_database()

    def _initialize_database(self) -> None:  # pragma: no cover - abstract
        """Create any required tables and indices. Must be implemented by subclasses."""
        raise NotImplementedError

    def _connect(self) -> sqlite3.Connection:
        """Return a new SQLite connection with a small timeout."""
        return sqlite3.connect(self.db_path, timeout=5)

    def _get_one(
        self,
        table: str,
        where: str,
        params: tuple[Any, ...],
    ) -> dict[str, Any] | None:
        """
        Convenience helper to fetch a single row from `table` with a WHERE clause.

        :param table: Table name.
        :param where: WHERE clause without the 'WHERE' keyword.
        :param params: Parameters tuple for the WHERE clause.
        :returns: Row as a dict if found, otherwise None.
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(f"SELECT * FROM {table} WHERE {where}", params)
            row = cursor.fetchone()

        if not row:
            return None

        # Default SQLite rows are tuples; build a dict by introspecting columns.
        col_names = [desc[0] for desc in cursor.description]
        return {name: value for name, value in zip(col_names, row)}


class SQLiteHandler(BaseSQLiteHandler):
    """
    Manages artwork metadata using a lightweight SQLite database.
    Provides methods for adding and retrieving processed image entries.
    """

    _ALLOWED_UPDATE_COLS = set(ART_DB_COLUMNS)

    def __init__(self) -> None:
        super().__init__(db_path=LOOKUPS)

    def _initialize_database(self) -> None:
        """
        Creates the artwork table and index if they don't already exist.
        Uses WAL mode for concurrent read/write access.
        """
        with sqlite3.connect(self.db_path, timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS artwork (
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
                "CREATE INDEX IF NOT EXISTS idx_url ON artwork (original_url)"
            )
            conn.commit()

    def add_entry(self, category: str, attributes: dict[str, Any]) -> None:
        """
        Inserts or replaces an artwork entry into the database.

        :param category: Artwork category (e.g., "clearlogo", "fanart").
        :param attributes: Dictionary with keys matching ART_DB_COLUMNS
                           (except 'category', which is passed explicitly), e.g.:
                           'original_url', 'processed_path', 'cached_file_hash',
                           'color', 'accent', 'contrast', 'luminosity'.
        """
        cols = ", ".join(ART_DB_COLUMNS)
        placeholders = ", ".join(["?"] * len(ART_DB_COLUMNS))

        row = tuple(
            (category if key == "category" else attributes.get(key))
            for key in ART_DB_COLUMNS
        )

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"INSERT OR REPLACE INTO artwork ({cols}) VALUES ({placeholders})",
                row,
            )
            conn.commit()

    def get_entry(self, original_url: str) -> dict[str, Any] | None:
        """
        Retrieves an artwork entry by original URL.

        :param original_url: The URL used to identify the artwork in the DB.
        :return: Dictionary of entry data if found, otherwise None.
        """
        return self._get_one(
            table="artwork",
            where="original_url = ?",
            params=(original_url,),
        )

    def clear_all(self) -> None:
        """
        Deletes all entries from the artwork database.

        :return: None
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM artwork")
            conn.commit()

    def update_fields(self, url: str, **fields: Any) -> int:
        """
        Update one or more columns for a single row identified by original URL.
        Returns number of affected rows.
        """
        if not fields:
            return 0

        # Filter to allowed, non-None values
        safe_items = [
            (k, v) for k, v in fields.items() if k in self._ALLOWED_UPDATE_COLS
        ]
        if not safe_items:
            return 0

        cols, vals = zip(*safe_items)
        sets = ", ".join([f"{c} = ?" for c in cols])

        try:
            with self._connect() as conn:
                cur = conn.cursor()
                cur.execute(
                    f"UPDATE artwork SET {sets} WHERE original_url = ?",
                    (*vals, url),
                )
                conn.commit()
                return cur.rowcount or 0
        except Exception:
            return 0

    def update_field(self, url: str, column: str, value: Any) -> int:
        """Thin wrapper for single-column updates."""
        return self.update_fields(url, **{column: value})


class TmdbCacheHandler(BaseSQLiteHandler):
    """
    Manages cached TMDb canonical payloads in the same SQLite database.

    Schema:
        tmdb_cache(
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            dbtype     TEXT    NOT NULL,
            tmdb_id    INTEGER NOT NULL,
            language   TEXT    NOT NULL,
            fetched_at INTEGER NOT NULL,
            payload    TEXT    NOT NULL,
            UNIQUE (dbtype, tmdb_id, language)
        )

    Notes:
        * Entries older than TTL_SECONDS are automatically removed on read & write.
        * We don't throttle purging because Kodi plugins are short-lived and purge is cheap.
    """

    TTL_SECONDS = 86400 * 7  # 7 days

    def __init__(self) -> None:
        super().__init__(db_path=LOOKUPS)

    def _initialize_database(self) -> None:
        with sqlite3.connect(self.db_path, timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS tmdb_cache (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    dbtype     TEXT    NOT NULL,
                    tmdb_id    INTEGER NOT NULL,
                    language   TEXT    NOT NULL,
                    fetched_at INTEGER NOT NULL,
                    payload    TEXT    NOT NULL,
                    UNIQUE (dbtype, tmdb_id, language)
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_tmdb_cache_lookup
                ON tmdb_cache (dbtype, tmdb_id, language)
                """
            )
            conn.commit()

    def get_entry(
        self, dbtype: str, tmdb_id: int, language: str
    ) -> dict[str, Any] | None:
        """Retrieve a single cached row, deleting it if stale or corrupt."""
        row = self._get_one(
            table="tmdb_cache",
            where="dbtype = ? AND tmdb_id = ? AND language = ?",
            params=(dbtype, tmdb_id, language),
        )
        if not row:
            return None

        # TTL check
        age = int(time.time()) - int(row["fetched_at"])
        if age > self.TTL_SECONDS:
            self.delete_entry(dbtype, tmdb_id, language)
            return None

        # JSON decode check
        try:
            row["payload"] = json.loads(row["payload"])
        except Exception:
            self.delete_entry(dbtype, tmdb_id, language)
            return None

        return row

    def delete_entry(self, dbtype: str, tmdb_id: int, language: str) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM tmdb_cache WHERE dbtype = ? AND tmdb_id = ? AND language = ?",
                (dbtype, tmdb_id, language),
            )
            conn.commit()

    def upsert_entry(
        self, dbtype: str, tmdb_id: int, language: str, payload_json: str
    ) -> None:
        """Always purge stale rows, then write fresh entry."""
        now = int(time.time())
        cutoff = now - self.TTL_SECONDS

        with self._connect() as conn:
            cursor = conn.cursor()

            # Bulk purge every write
            cursor.execute(
                "DELETE FROM tmdb_cache WHERE fetched_at < ?",
                (cutoff,),
            )

            cursor.execute(
                """
                INSERT OR REPLACE INTO tmdb_cache (
                    dbtype, tmdb_id, language, fetched_at, payload
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (dbtype, tmdb_id, language, now, payload_json),
            )
            conn.commit()

    def clear_all(self) -> None:
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM tmdb_cache")
            conn.commit()
