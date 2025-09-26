# app/utils/db.py
import sqlite3, os, threading
from typing import List, Dict, Any


class DB:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # allow use across threads; we’ll protect writes with a lock
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        # better concurrency
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self._init()

    def _init(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute(
                """CREATE TABLE IF NOT EXISTS photos (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE,
                exif_date TEXT,
                fs_date TEXT,
                inferred_date TEXT,
                confidence REAL DEFAULT 0.0,
                enhanced_path TEXT
            )"""
            )
            self.conn.commit()

    def insert_photo_if_absent(self, path: str):
        fs_date = None
        try:
            fs_date = str(int(os.path.getmtime(path)))
        except Exception:
            pass
        with self.lock:
            self.conn.execute(
                "INSERT OR IGNORE INTO photos(path, fs_date) VALUES(?,?)",
                (path, fs_date),
            )
            self.conn.commit()

    def list_photos(self, limit: int = 1000) -> List[Dict[str, Any]]:
        cur = self.conn.execute("SELECT * FROM photos LIMIT ?", (limit,))
        return cur.fetchall()

    def update_exif_date(self, photo_id: int, exif_date: str | None):
        with self.lock:
            self.conn.execute("UPDATE photos SET exif_date=? WHERE id=?", (exif_date, photo_id))
            self.conn.commit()

    def update_inferred(self, photo_id: int, date_str: str, conf: float):
        with self.lock:
            self.conn.execute(
                "UPDATE photos SET inferred_date=?, confidence=? WHERE id=?",
                (date_str, conf, photo_id),
            )
            self.conn.commit()

    def set_enhanced_path(self, photo_id: int, out_path: str | None):
        with self.lock:
            self.conn.execute("UPDATE photos SET enhanced_path=? WHERE id=?", (out_path, photo_id))
            self.conn.commit()

    def iter_all(self):
        return self.conn.execute("SELECT * FROM photos")

    def find_by_path(self, path: str):
        cur = self.conn.execute("SELECT * FROM photos WHERE path=?", (path,))
        return cur.fetchone()
