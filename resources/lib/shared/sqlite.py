# author: realcopacetic

import sqlite3

from resources.lib.shared.utilities import LOOKUPS


class SQLiteHandler:
    def __init__(self):
        self.db_path = LOOKUPS
        self._initialize_database()

    def _initialize_database(self):
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
