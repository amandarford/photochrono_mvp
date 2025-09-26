# app/pipelines/face.py
from __future__ import annotations
import os
import sqlite3
import math
from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict

import numpy as np

# lazy imports so the app can run even without insightface until indexing
_cv = None
_insight = None

TABLE_CANDIDATES = ["photos", "images", "files", "media", "assets", "items"]
PATH_COL_CANDIDATES = ["path", "file_path", "filepath",
                       "abs_path", "rel_path", "full_path", "src"]


def _conn(db) -> sqlite3.Connection:
    if isinstance(db, sqlite3.Connection):
        c = db
    else:
        c = sqlite3.connect(db if isinstance(db, str)
                            else "data/photochrono.db")
    c.row_factory = sqlite3.Row
    return c


def _detect_photos_table(conn: sqlite3.Connection) -> Tuple[str, str, str]:
    # Prefer known table names
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
        if path_col:
            return t, id_col, path_col
    # Fallback: scan any user table
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )]
    for t in tables:
        try:
            cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
        except sqlite3.OperationalError:
            continue
        if not cols:
            continue
        names = [r[1] for r in cols]
        path_col = None
        for n in names:
            ln = n.lower()
            if ln in PATH_COL_CANDIDATES or "path" in ln or "file" in ln:
                path_col = n
                break
        if path_col:
            id_col = next((c for c in ("id", "photo_id", "image_id")
                          if c in names), None) or "rowid"
            return t, id_col, path_col
    raise RuntimeError("FaceIndexer: could not locate photos table/columns")


def _ensure_face_table(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS face_boxes (
      photo_id INTEGER NOT NULL,
      face_id INTEGER NOT NULL,
      x REAL NOT NULL, y REAL NOT NULL, w REAL NOT NULL, h REAL NOT NULL,
      embedding BLOB,
      cluster_id TEXT,
      assigned_person_id INTEGER,
      source TEXT DEFAULT 'detector',
      confidence REAL DEFAULT 0.0,
      PRIMARY KEY(photo_id, face_id)
    );
    """)
    conn.commit()


def _load_cv() -> None:
    global _cv
    if _cv is None:
        import cv2
        _cv = cv2


def _load_insight() -> None:
    global _insight
    if _insight is None:
        from insightface.app import FaceAnalysis
        _insight = FaceAnalysis(name="buffalo_l", providers=[
                                "CPUExecutionProvider"])
        _insight.prepare(ctx_id=0, det_size=(640, 640))


def _read_image_bgr(path: str):
    _load_cv()
    img = _cv.imread(path)
    if img is not None:
        return img
    # heic or other formats: use Pillow as fallback
    from PIL import Image
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return None
    arr = np.array(im)  # RGB
    return arr[:, :, ::-1].copy()  # to BGR


def _l2_normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / (n + 1e-9)


@dataclass
class FaceRecord:
    photo_id: int
    face_id: int
    x: float
    y: float
    w: float
    h: float  # normalized 0..1
    emb: Optional[np.ndarray]
    score: float


class FaceIndexer:
    """
    Detect faces & compute embeddings → store in face_boxes.
    Also performs a simple incremental clustering over embeddings.
    """

    def __init__(self, db):
        self.conn = _conn(db)
        _ensure_face_table(self.conn)
        self.table, self.id_col, self.path_col = _detect_photos_table(
            self.conn)

    def index(self, limit: Optional[int] = None, step_commit: int = 200) -> int:
        _load_insight()
        rows = self.conn.execute(
            f"SELECT {self.id_col} AS pid, {self.path_col} AS pth FROM {self.table}"
            + ("" if limit is None else " LIMIT ?"),
            (() if limit is None else (limit,))
        ).fetchall()

        processed = 0
        for r in rows:
            pid, pth = int(r["pid"]), r["pth"]
            if not os.path.exists(pth):
                continue
            img = _read_image_bgr(pth)
            if img is None:
                continue
            h, w = img.shape[:2]
            # list of dets with .bbox, .kps, .det_score, .normed_embedding
            faces = _insight.get(img)
            # clear existing faces for this photo to avoid duplicates (safe to rebuild)
            self.conn.execute(
                "DELETE FROM face_boxes WHERE photo_id=?", (pid,))
            face_id = 0
            for f in faces:
                x1, y1, x2, y2 = f.bbox.astype(float)
                x = max(0.0, x1 / w)
                y = max(0.0, y1 / h)
                ww = min(1.0, (x2 - x1) / w)
                hh = min(1.0, (y2 - y1) / h)
                emb = _l2_normalize(np.asarray(
                    f.normed_embedding, dtype=np.float32))
                self.conn.execute(
                    "INSERT OR REPLACE INTO face_boxes(photo_id, face_id, x,y,w,h, embedding, cluster_id, assigned_person_id, source, confidence) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (pid, face_id, x, y, ww, hh, emb.tobytes(), None, None,
                     "insightface", float(getattr(f, 'det_score', 0.0)))
                )
                face_id += 1
            processed += 1
            if processed % step_commit == 0:
                self.conn.commit()
        self.conn.commit()

        # cluster after indexing
        self._cluster_embeddings(sim_threshold=0.68, min_examples=2)
        return processed

    def _cluster_embeddings(self, sim_threshold: float = 0.68, min_examples: int = 2) -> int:
        """
        Very small, incremental cosine-similarity clustering:
        - normalize embeddings
        - assign to an existing cluster if cos_sim >= threshold
        - otherwise create new cluster
        """
        rows = self.conn.execute(
            "SELECT photo_id, face_id, embedding FROM face_boxes WHERE embedding IS NOT NULL"
        ).fetchall()
        if not rows:
            return 0

        # Load all embeddings
        items = []
        for r in rows:
            emb = np.frombuffer(r["embedding"], dtype=np.float32)
            if emb.size == 0:
                continue
            emb = _l2_normalize(emb)
            items.append((int(r["photo_id"]), int(r["face_id"]), emb))
        if not items:
            return 0

        # incremental clusters
        centroids: List[np.ndarray] = []
        members: List[List[Tuple[int, int]]] = []

        def best_cluster(e: np.ndarray) -> Tuple[int, float]:
            if not centroids:
                return -1, -1.0
            csims = [float(np.dot(e, c)) for c in centroids]  # cos sim
            idx = int(np.argmax(csims))
            return idx, csims[idx]

        for pid, fid, emb in items:
            idx, sim = best_cluster(emb)
            if idx >= 0 and sim >= sim_threshold:
                members[idx].append((pid, fid))
                # update centroid (running mean, re-normalize)
                c = centroids[idx]
                c = _l2_normalize(
                    (c * (len(members[idx])-1) + emb) / len(members[idx]))
                centroids[idx] = c
            else:
                centroids.append(emb.copy())
                members.append([(pid, fid)])

        # write cluster ids (only for clusters with enough examples)
        cluster_count = 0
        for ci, m in enumerate(members):
            if len(m) < min_examples:
                # leave small clusters unassigned (None)
                continue
            cluster_id = f"C{ci:05d}"
            cluster_count += 1
            self.conn.executemany(
                "UPDATE face_boxes SET cluster_id=? WHERE photo_id=? AND face_id=?",
                [(cluster_id, pid, fid) for (pid, fid) in m]
            )
        self.conn.commit()
        return cluster_count
