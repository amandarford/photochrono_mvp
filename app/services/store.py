# ===== FILE: app/services/store.py =====
from __future__ import annotations
import hashlib
import json
import os
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from PySide6 import QtCore

from ..widgets.grid_gallery import GalleryItem
from .metadata import writeback_metadata

SUPPORTED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff",
                 ".heic", ".heif", ".JPG", ".PNG", ".JPEG", ".WEBP", ".TIF", ".TIFF"}


class Store(QtCore.QObject):
    aiTagUpdated = QtCore.Signal(object)

    def __init__(self, db_path: Path | None = None):
        super().__init__()
        self.db_path = Path(
            db_path) if db_path else Path.home() / ".photochrono.db"
        self._ensure_db()

    # --- DB bootstrap
    def _ensure_db(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS images (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE,
                added_at TEXT,
                hash TEXT
            );
            CREATE TABLE IF NOT EXISTS image_tags (
                image_id INTEGER,
                tags_json TEXT,
                updated_at TEXT,
                PRIMARY KEY(image_id),
                FOREIGN KEY(image_id) REFERENCES images(id) ON DELETE CASCADE
            );
            """
        )
        conn.commit()
        conn.close()

    # --- Import
    def import_folder(self, folder: Path) -> int:
        folder = Path(folder)
        if not folder.exists():
            return 0
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        imported = 0
        for root, _, files in os.walk(folder):
            for name in files:
                p = Path(root) / name
                if p.suffix not in SUPPORTED_EXT:
                    continue
                h = self._quick_hash(p)
                try:
                    cur.execute("INSERT INTO images(path, added_at, hash) VALUES(?,?,?)", (
                        str(p), datetime.utcnow().isoformat(), h
                    ))
                    imported += 1
                except sqlite3.IntegrityError:
                    pass
        conn.commit()
        conn.close()
        return imported

    def import_path(self, path: Path) -> GalleryItem:
        """Index a single file and return its GalleryItem (existing or new)."""
        path = Path(path)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        h = self._quick_hash(path)
        cur.execute("INSERT OR IGNORE INTO images(path, added_at, hash) VALUES(?,?,?)", (str(
            path), datetime.utcnow().isoformat(), h))
        conn.commit()
        cur.execute(
            "SELECT i.id, i.path, t.tags_json FROM images i LEFT JOIN image_tags t ON i.id=t.image_id WHERE i.path=?", (str(path),))
        row = cur.fetchone()
        conn.close()
        image_id, ipath, tags_json = row
        return GalleryItem(id=image_id, path=Path(ipath), tags=json.loads(tags_json) if tags_json else {})

    def _quick_hash(self, path: Path) -> str:
        s = path.stat().st_size
        m = hashlib.sha1()
        m.update(str(s).encode())
        try:
            with open(path, 'rb') as f:
                m.update(f.read(1024 * 1024))
        except Exception:
            pass
        return m.hexdigest()

    # --- Queries
    def _items_from_rows(self, rows) -> List[GalleryItem]:
        items = []
        for (image_id, path, tags_json) in rows:
            tags = json.loads(tags_json) if tags_json else {}
            items.append(GalleryItem(id=image_id, path=Path(path), tags=tags))
        return items

    def load_all(self) -> List[GalleryItem]:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT i.id, i.path, t.tags_json FROM images i LEFT JOIN image_tags t ON i.id=t.image_id ORDER BY i.added_at DESC")
        rows = cur.fetchall()
        conn.close()
        return self._items_from_rows(rows)

    def load_recent(self, days: int = 7) -> List[GalleryItem]:
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT i.id, i.path, t.tags_json FROM images i LEFT JOIN image_tags t ON i.id=t.image_id WHERE i.added_at >= ? ORDER BY i.added_at DESC", (since,))
        rows = cur.fetchall()
        conn.close()
        return self._items_from_rows(rows)

    def count_all(self) -> int:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM images")
        (n,) = cur.fetchone()
        conn.close()
        return int(n)

    def count_recent(self, days: int = 7) -> int:
        since = (datetime.utcnow() - timedelta(days=days)).isoformat()
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM images WHERE added_at >= ?", (since,))
        (n,) = cur.fetchone()
        conn.close()
        return int(n)

    # --- Save tags
    def save_item(self, item: GalleryItem):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO image_tags(image_id, tags_json, updated_at)
               VALUES(?,?,?)
               ON CONFLICT(image_id) DO UPDATE
                 SET tags_json=excluded.tags_json,
                     updated_at=excluded.updated_at""",
            (item.id, json.dumps(item.tags or {}), datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()

        # --- NEW: also write tags to EXIF ---
        ok, msg = writeback_metadata(item, db_path=self.db_path)
        if not ok:
            print(
                f"[Store.save_item] Metadata writeback failed for {item.path}: {msg}")
