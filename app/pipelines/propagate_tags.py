# app/pipelines/propagate_tags.py
from __future__ import annotations
import os
import sqlite3
import datetime as dt
from typing import Tuple, Optional, List

TABLE_CANDIDATES = ["photos", "images", "files", "media", "assets", "items"]
PATH_COL_CANDIDATES = ["path", "file_path", "filepath",
                       "abs_path", "rel_path", "full_path", "src"]
DATE_COL_CANDS = ["exif_date", "exif_datetime",
                  "capture_time", "datetime_original", "date_taken"]


def _conn(db) -> sqlite3.Connection:
    if isinstance(db, sqlite3.Connection):
        c = db
    else:
        c = sqlite3.connect(db if isinstance(db, str)
                            else "data/photochrono.db")
    c.row_factory = sqlite3.Row
    return c


def _detect_photos_table(conn: sqlite3.Connection) -> Tuple[str, str, str, str]:
    # returns table, id_col, path_col, date_col (date_col may be None)
    chosen = None
    # Prefer known names first
    for t in TABLE_CANDIDATES:
        try:
            cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
        except sqlite3.OperationalError:
            continue
        if not cols:
            continue
        names = [r[1] for r in cols]
        id_col = next((c for c in ("id", "photo_id", "image_id")
                      if c in names), None) or "rowid"
        path_col = next((c for c in PATH_COL_CANDIDATES if c in names), None)
        if not path_col:
            for n in names:
                if "path" in n.lower() or "file" in n.lower():
                    path_col = n
                    break
        if not path_col:
            continue
        date_col = next((c for c in DATE_COL_CANDS if c in names), None)
        chosen = (t, id_col, path_col, date_col)
        break
    if chosen:
        return chosen
    # Fallback: any table with a path-like col
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    for t in tables:
        cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
        if not cols:
            continue
        names = [r[1] for r in cols]
        path_col = None
        for n in names:
            ln = n.lower()
            if ln in PATH_COL_CANDIDATES or "path" in ln or "file" in ln:
                path_col = n
                break
        if not path_col:
            continue
        id_col = next((c for c in ("id", "photo_id", "image_id")
                      if c in names), None) or "rowid"
        date_col = next((c for c in DATE_COL_CANDS if c in names), None)
        return t, id_col, path_col, date_col
    raise RuntimeError("Propagate: could not locate photos table.")

# --- PERSON propagation ---


def propagate_person_from_photo(db, photo_id: int, person_id: int) -> int:
    """
    For every face cluster that appears in `photo_id`, add person tag to
    all photos containing faces from those clusters.
    Returns number of photos (excluding the current) newly labeled.
    """
    conn = _conn(db)
    # clusters present in this photo
    clus = conn.execute(
        "SELECT DISTINCT cluster_id FROM face_boxes WHERE photo_id=? AND cluster_id IS NOT NULL",
        (photo_id,)
    ).fetchall()
    if not clus:
        return 0
    cluster_ids = [r[0] for r in clus]

    # all photos that have faces from these clusters
    rows = conn.execute(
        f"SELECT DISTINCT photo_id FROM face_boxes WHERE cluster_id IN ({','.join(['?']*len(cluster_ids))})",
        cluster_ids
    ).fetchall()
    target_ids = {int(r[0]) for r in rows}

    # Insert person tags
    inserted = 0
    for pid in target_ids:
        conn.execute("""
            INSERT INTO photo_tags(photo_id, tag_type, tag_value, source, confidence)
            VALUES (?, 'person', ?, 'propagated_cluster', 0.90)
            ON CONFLICT(photo_id, tag_type, tag_value) DO NOTHING
        """, (pid, str(person_id)))
        inserted += int(conn.total_changes > 0)  # coarse count (at least 1)
    conn.commit()
    # subtract current if present
    return max(0, inserted - (1 if photo_id in target_ids else 0))

# --- DATE propagation ---


def _parse_iso(s: str) -> Optional[dt.datetime]:
    try:
        return dt.datetime.fromisoformat(s)
    except Exception:
        return None


def propagate_date_neighbors(db, photo_id: int, iso_dt: str,
                             window_minutes: int = 45,
                             same_folder_only: bool = True,
                             only_if_missing_human: bool = True) -> int:
    """
    Propagate a human-set date to nearby photos (by exif_date or mtime)
    within a time window. Returns number of photos updated.
    """
    conn = _conn(db)
    table, id_col, path_col, date_col = _detect_photos_table(conn)

    # load current photo path
    row = conn.execute(f"SELECT {path_col} FROM {table} WHERE {id_col}=?",
                       (photo_id,)).fetchone()
    if not row:
        return 0
    base_path = row[0]
    base_dir = os.path.dirname(base_path)
    base_dt = _parse_iso(iso_dt)
    if not base_dt:
        return 0

    # candidate set
    if same_folder_only:
        candidates = conn.execute(
            f"SELECT {id_col} AS pid, {path_col} AS pth, {('' if not date_col else date_col)} FROM {table} WHERE {path_col} LIKE ?",
            (base_dir + os.sep + "%",)
        ).fetchall()
    else:
        candidates = conn.execute(
            f"SELECT {id_col} AS pid, {path_col} AS pth, {('' if not date_col else date_col)} FROM {table}"
        ).fetchall()

    updated = 0
    for r in candidates:
        pid, pth = int(r["pid"]), r["pth"]
        if pid == photo_id:
            continue

        # skip if there is already a human date tag
        if only_if_missing_human:
            exists = conn.execute("""
                SELECT 1 FROM photo_tags
                 WHERE photo_id=? AND tag_type='date' AND source='human'
                 LIMIT 1
            """, (pid,)).fetchone()
            if exists:
                continue

        # time of the neighbor: prefer exif if available, else mtime
        neigh_dt = None
        if date_col and r[date_col]:
            neigh_dt = _parse_iso(str(r[date_col]))
        if not neigh_dt:
            try:
                mtime = os.path.getmtime(pth)
                neigh_dt = dt.datetime.fromtimestamp(mtime)
            except Exception:
                continue

        diff = abs((neigh_dt - base_dt).total_seconds()) / 60.0
        if diff <= window_minutes:
            conn.execute("""
                INSERT INTO photo_tags(photo_id, tag_type, tag_value, source, confidence)
                VALUES (?, 'date', ?, 'propagated_time', 0.75)
                ON CONFLICT(photo_id, tag_type, tag_value) DO UPDATE SET
                  source=excluded.source, confidence=excluded.confidence
            """, (pid, iso_dt))
            updated += 1

    conn.commit()
    return updated
