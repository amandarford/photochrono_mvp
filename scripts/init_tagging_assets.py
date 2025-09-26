#!/usr/bin/env python3
import sqlite3, sys, os, hashlib, math
from pathlib import Path
from PIL import Image
import imagehash

# ---- config
DB = sys.argv[1] if len(sys.argv) > 1 else "data/photochrono.db"

def ensure_tables(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS phash (
      photo_id INTEGER PRIMARY KEY,
      phash_hex TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS face_boxes (
      photo_id INTEGER NOT NULL,
      face_id INTEGER NOT NULL,
      x REAL NOT NULL, y REAL NOT NULL, w REAL NOT NULL, h REAL NOT NULL,
      embedding BLOB, cluster_id TEXT, assigned_person_id INTEGER,
      source TEXT DEFAULT 'detector', confidence REAL DEFAULT 0.0,
      PRIMARY KEY(photo_id, face_id)
    );
    """)
    conn.commit()

def get_photos(conn):
    # support either 'photos' or 'images' table with a 'path' column
    for table in ("photos","images"):
        try:
            rows = conn.execute(f"SELECT rowid, path FROM {table}").fetchall()
            return table, rows
        except sqlite3.OperationalError:
            continue
    raise SystemExit("No 'photos' or 'images' table with a path column found.")

def compute_phash(conn, table, rows):
    done = set(r[0] for r in conn.execute("SELECT photo_id FROM phash"))
    ins = []
    for pid, p in rows:
        if pid in done: continue
        try:
            with Image.open(p) as im:
                im = im.convert("RGB")
                h = imagehash.phash(im)
            ins.append((pid, h.__str__()))
        except Exception:
            # skip unreadable
            continue
        if len(ins) >= 500:
            conn.executemany("INSERT OR REPLACE INTO phash(photo_id, phash_hex) VALUES (?,?)", ins)
            conn.commit(); ins.clear()
    if ins:
        conn.executemany("INSERT OR REPLACE INTO phash(photo_id, phash_hex) VALUES (?,?)", ins)
        conn.commit()

def main():
    conn = sqlite3.connect(DB)
    ensure_tables(conn)
    table, rows = get_photos(conn)
    print(f"Found {len(rows)} records in {table}")
    compute_phash(conn, table, rows)
    # (Face boxes can be added later once we choose our detector/embeddings.)
    c = conn.execute("SELECT COUNT(*) FROM phash").fetchone()[0]
    print(f"phash rows: {c}")
    print("Done.")
if __name__ == "__main__":
    main()
