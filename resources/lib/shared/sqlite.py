# author: realcopacetic

import sqlite3

from resources.lib.shared.utilities import LOOKUPS


class SQLiteHandler:
    """
    Manages artwork metadata using a lightweight SQLite database.
    Provides methods for adding and retrieving processed image entries.
    """

    def __init__(self):
        """Initializes the database handler and ensures required tables exist."""
        self.db_path = LOOKUPS
        self._initialize_database()

    def _initialize_database(self):
        """
        Creates the artwork table and index if they don't already exist.
        Uses WAL mode for concurrent read/write access.
        """
        conn = sqlite3.connect(self.db_path, timeout=5)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS artwork (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                original_url TEXT UNIQUE NOT NULL,
                processed_path TEXT,
                color TEXT,
                luminosity INTEGER
            )
            """
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_url ON artwork (original_url)"
        )  # indexing for speed
        conn.commit()
        conn.close()

    def add_entry(self, category, attributes):
        """
        Inserts or replaces an artwork entry into the database.

        :param category: Artwork category (e.g., "clearlogo", "fanart").
        :param attributes: Dictionary with 'url', 'processed', 'color', 'luminosity'.
        """
        with sqlite3.connect(self.db_path, timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO artwork (category, original_url, processed_path, color, luminosity)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    category,
                    attributes.get("url"),
                    attributes.get("processed"),
                    attributes.get("color"),
                    attributes.get("luminosity"),
                ),
            )
            conn.commit()

    def get_entry(self, original_url):
        """
        Retrieves an artwork entry by original URL.

        :param original_url: The URL used to identify the artwork in the DB.
        :returns: Dictionary of entry data if found, otherwise None.
        """
        with sqlite3.connect(self.db_path, timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM artwork WHERE original_url = ?", (original_url,)
            )
            row = cursor.fetchone()
        if row:
            return {
                "id": row[0],
                "category": row[1],
                "url": row[2],
                "processed": row[3],
                "color": row[4],
                "luminosity": row[5],
            }
        return None
    
    def clear_all(self):
        """
        Deletes all entries from the artwork database.

        :returns: None
        """
        with sqlite3.connect(self.db_path, timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM artwork")
            conn.commit()
