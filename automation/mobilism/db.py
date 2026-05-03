import sqlite3
import time
from contextlib import contextmanager

from automation.mobilism.config import DB_PATH

@contextmanager
def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS mobilism_apps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                app_name TEXT NOT NULL,
                version TEXT NOT NULL,
                raw_title TEXT,
                url TEXT,
                status TEXT DEFAULT 'NEW',  -- NEW, SEEN, IGNORED
                first_seen DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(app_name, version)
            )
        """)
        conn.commit()

def app_exists(app_name: str, version: str) -> bool:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM mobilism_apps WHERE app_name = ? AND version = ?",
            (app_name, version)
        ).fetchone()
        return row is not None

def insert_app(app_name: str, version: str, raw_title: str, url: str, status: str = "NEW"):
    try:
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO mobilism_apps (app_name, version, raw_title, url, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (app_name, version, raw_title, url, status)
            )
            conn.commit()
            return True
    except sqlite3.IntegrityError:
        return False

def get_new_updates():
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM mobilism_apps WHERE status = 'NEW' ORDER BY first_seen DESC"
        ).fetchall()

def mark_seen(app_id: int):
    with get_connection() as conn:
        conn.execute("UPDATE mobilism_apps SET status = 'SEEN' WHERE id = ?", (app_id,))
        conn.commit()
