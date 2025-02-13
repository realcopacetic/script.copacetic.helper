# author: realcopacetic

import sqlite3

from resources.lib.shared.utilities import LOOKUP_DB


class SQLiteHandler:
    def __init__(self):
        self.db_path = LOOKUP_DB
        self._initialize_database()

    def _initialize_database(self):
        conn = sqlite3.connect(self.db_path, timeout=5)
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS artwork (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                original_url TEXT UNIQUE NOT NULL,
                processed_path TEXT,
                height INTEGER,
                color TEXT,
                luminosity INTEGER
            )
        """)
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_url ON artwork (original_url)")  # indexing for speed
        conn.commit()
        conn.close()


    def add_entry(self, category, attributes):
        with sqlite3.connect(self.db_path, timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                        INSERT OR REPLACE INTO artwork (category, original_url, processed_path, height, color, luminosity)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (
                category,
                attributes.get("url"),
                attributes.get("processed"),
                attributes.get("height"),
                attributes.get("color"),
                attributes.get("luminosity")
            ))
            conn.commit()

    def get_entry(self, original_url):
        with sqlite3.connect(self.db_path, timeout=5) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM artwork WHERE original_url = ?", (original_url,))
            row = cursor.fetchone()
        if row:
            return {
                "id": row[0],
                "category": row[1],
                "url": row[2],
                "processed": row[3],
                "height": row[4],
                "color": row[5],
                "luminosity": row[6]
            }
        return None

    # def delete_entry(self, original_url):
    #     """Deletes an artwork entry based on the original image URL."""
    #     conn = sqlite3.connect(self.db_path)
    #     cursor = conn.cursor()
    #     cursor.execute(
    #         "DELETE FROM artwork WHERE original_url = ?", (original_url,))
    #     conn.commit()
    #     conn.close()

    # def get_all_entries(self, category=None):
    #     """Fetches all entries, optionally filtering by category."""
    #     conn = sqlite3.connect(self.db_path)
    #     cursor = conn.cursor()

    #     if category:
    #         cursor.execute(
    #             "SELECT * FROM artwork WHERE category = ?", (category,))
    #     else:
    #         cursor.execute("SELECT * FROM artwork")

    #     rows = cursor.fetchall()
    #     conn.close()

    #     return [
    #         {
    #             "id": row[0],
    #             "category": row[1],
    #             "url": row[2],
    #             "processed": row[3],
    #             "height": row[4],
    #             "color": row[5],
    #             "luminosity": row[6]
    #         }
    #         for row in rows
    #     ]
