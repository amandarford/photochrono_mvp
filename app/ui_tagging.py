# app/ui_tagging.py
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Dict

from PySide6.QtCore import Qt, QDateTime, QTimer, QSize
from PySide6.QtGui import QPixmap, QKeySequence, QAction
from PySide6.QtWidgets import (
    QWidget, QDockWidget, QMainWindow, QLabel, QPushButton, QLineEdit, QComboBox,
    QDateTimeEdit, QHBoxLayout, QVBoxLayout, QFileDialog, QMessageBox, QCheckBox,
    QSplitter, QSizePolicy, QFrame
)

# ---------- Small Utilities ----------


def _open_conn(db_or_conn) -> sqlite3.Connection:
    if isinstance(db_or_conn, sqlite3.Connection):
        return db_or_conn
    db_path = db_or_conn or "data/photochrono.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_core_tables(conn: sqlite3.Connection) -> None:
    # Makes the panel resilient if migrations ran out of band.
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS people (
      person_id INTEGER PRIMARY KEY,
      display_name TEXT NOT NULL,
      alias TEXT,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS photo_tags (
      photo_id INTEGER NOT NULL,
      tag_type TEXT NOT NULL CHECK(tag_type IN ('person','date','keyword')),
      tag_value TEXT NOT NULL,
      source TEXT NOT NULL,
      confidence REAL DEFAULT 1.0,
      created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(photo_id, tag_type, tag_value)
    );

    CREATE TABLE IF NOT EXISTS phash (
      photo_id INTEGER PRIMARY KEY,
      phash_hex TEXT NOT NULL
    );
    """)
    conn.commit()


TABLE_CANDIDATES = ["photos", "images", "files", "media", "assets", "items"]
PATH_COL_CANDIDATES = ["path", "file_path", "filepath",
                       "abs_path", "rel_path", "full_path", "src"]


@dataclass
class PhotoItem:
    photo_id: int
    path: str
    phash: Optional[str] = None

# ---------- DB Introspection ----------


def detect_photos_table(conn: sqlite3.Connection) -> Tuple[str, str, str]:
    """
    Returns (table_name, id_column, path_column)
    Falls back to rowid if no obvious id column.
    """
    # First pass: known table names
    for t in TABLE_CANDIDATES:
        try:
            cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
        except sqlite3.OperationalError:
            continue
        if not cols:
            continue
        colnames = [c[1] for c in cols]
        # choose id
        id_col = None
        for cand in ("id", "photo_id", "image_id"):
            if cand in colnames:
                id_col = cand
                break
        id_col = id_col or "rowid"
        # choose path
        path_col = None
        for cand in PATH_COL_CANDIDATES:
            if cand in colnames:
                path_col = cand
                break
        if path_col is None:
            for c in colnames:
                if "path" in c.lower() or "file" in c.lower():
                    path_col = c
                    break
        if path_col:
            return t, id_col, path_col

    # Second pass: any user table with a path-like column
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
        colnames = [c[1] for c in cols]
        path_col = None
        for c in colnames:
            cl = c.lower()
            if cl in PATH_COL_CANDIDATES or "path" in cl or "file" in cl:
                path_col = c
                break
        if path_col:
            id_col = None
            for cand in ("id", "photo_id", "image_id"):
                if cand in colnames:
                    id_col = cand
                    break
            id_col = id_col or "rowid"
            return t, id_col, path_col

    raise RuntimeError(
        "Could not locate a table/column holding photo file paths.")


def load_people(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute("SELECT person_id, display_name FROM people ORDER BY display_name COLLATE NOCASE").fetchall()


def add_person(conn: sqlite3.Connection, name: str) -> int:
    cur = conn.execute(
        "INSERT INTO people(display_name) VALUES (?)", (name.strip(),))
    conn.commit()
    return cur.lastrowid


def upsert_person_tag(conn: sqlite3.Connection, photo_id: int, person_id: int, source: str = "human", conf: float = 1.0):
    conn.execute("""
        INSERT INTO photo_tags(photo_id, tag_type, tag_value, source, confidence)
        VALUES (?, 'person', ?, ?, ?)
        ON CONFLICT(photo_id, tag_type, tag_value) DO UPDATE SET
            source=excluded.source,
            confidence=excluded.confidence
    """, (photo_id, str(person_id), source, conf))


def upsert_date_tag(conn: sqlite3.Connection, photo_id: int, iso_dt: str, source: str = "human", conf: float = 1.0):
    conn.execute("""
        INSERT INTO photo_tags(photo_id, tag_type, tag_value, source, confidence)
        VALUES (?, 'date', ?, ?, ?)
        ON CONFLICT(photo_id, tag_type, tag_value) DO UPDATE SET
            source=excluded.source,
            confidence=excluded.confidence
    """, (photo_id, iso_dt, source, conf))


def fetch_phash(conn: sqlite3.Connection, photo_id: int) -> Optional[str]:
    row = conn.execute(
        "SELECT phash_hex FROM phash WHERE photo_id=?", (photo_id,)).fetchone()
    return row["phash_hex"] if row else None


def photos_by_phash(conn: sqlite3.Connection, phash_hex: str) -> List[int]:
    rows = conn.execute(
        "SELECT photo_id FROM phash WHERE phash_hex=?", (phash_hex,)).fetchall()
    return [r["photo_id"] for r in rows]

# ---------- Batch Building ----------


def build_simple_tagging_batch(conn: sqlite3.Connection, limit: int = 500) -> List[PhotoItem]:
    """
    Build a practical first batch:
      - 1 representative per exact phash (min photo_id)
      - plus any photos not present in phash table (no hash yet)
      - respects 'limit'
    """
    table, id_col, path_col = detect_photos_table(conn)

    # representatives by exact phash
    reps: List[PhotoItem] = []
    rows = conn.execute("""
        SELECT p.photo_id, p.phash_hex
        FROM phash p
        """).fetchall()
    # Map phash -> min photo_id
    best: Dict[str, int] = {}
    for r in rows:
        pid, ph = r["photo_id"], r["phash_hex"]
        if ph not in best or pid < best[ph]:
            best[ph] = pid

    # fetch paths for representatives
    if best:
        ids_tuple = tuple(best.values())
        q = f"SELECT {id_col} AS pid, {path_col} AS pth FROM {table} WHERE {id_col} IN ({','.join(['?']*len(ids_tuple))})"
        rep_rows = conn.execute(q, ids_tuple).fetchall()
        for rr in rep_rows:
            reps.append(PhotoItem(
                photo_id=rr["pid"], path=rr["pth"], phash=fetch_phash(conn, rr["pid"])))

    # add photos without a phash yet
    without_hash = conn.execute(f"""
        SELECT {id_col} AS pid, {path_col} AS pth
        FROM {table}
        WHERE {id_col} NOT IN (SELECT photo_id FROM phash)
        LIMIT ?
    """, (max(0, limit - len(reps)),)).fetchall()
    for r in without_hash:
        reps.append(PhotoItem(photo_id=r["pid"], path=r["pth"], phash=None))
        if len(reps) >= limit:
            break

    # If still under limit, top up with more arbitrary photos
    if len(reps) < limit:
        got_ids = set(p.photo_id for p in reps)
        filler = conn.execute(f"""
            SELECT {id_col} AS pid, {path_col} AS pth
            FROM {table}
            WHERE {id_col} NOT IN ({','.join(['?']*len(got_ids))}) 
            LIMIT ?
        """, (*got_ids, limit - len(reps))) if got_ids else conn.execute(
            f"SELECT {id_col} AS pid, {path_col} AS pth FROM {table} LIMIT ?", (
                limit - len(reps),)
        )
        for r in filler.fetchall():
            reps.append(
                PhotoItem(photo_id=r["pid"], path=r["pth"], phash=fetch_phash(conn, r["pid"])))
            if len(reps) >= limit:
                break

    # Sort by id for predictable nav
    reps.sort(key=lambda x: x.photo_id)
    return reps

# ---------- UI ----------


class TaggingPanel(QDockWidget):
    """
    Dockable panel you can attach to an existing QMainWindow.
    You can also use TaggingWindow below if you want it standalone.
    """

    def __init__(self, db, parent=None):
        super().__init__("Tagging", parent)
        self.conn = _open_conn(db)
        _ensure_core_tables(self.conn)

        # state
        self.batch: List[PhotoItem] = []
        self.index: int = -1
        self.last_date_iso: Optional[str] = None

        self._init_ui()
        self._load_people()
        # Try to populate a batch immediately (safe if empty DB)
        self._build_batch()

    def _init_ui(self):
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Top bar: Build batch / counts / nav
        top = QHBoxLayout()
        self.buildBtn = QPushButton("Build Tagging Batch")
        self.prevBtn = QPushButton("◀ Prev")
        self.nextBtn = QPushButton("Next ▶")
        self.counterLbl = QLabel("0 / 0")
        self.counterLbl.setMinimumWidth(80)
        self.counterLbl.setAlignment(Qt.AlignCenter)

        top.addWidget(self.buildBtn)
        top.addStretch(1)
        top.addWidget(self.prevBtn)
        top.addWidget(self.counterLbl)
        top.addWidget(self.nextBtn)
        root.addLayout(top)

        # Split center: left preview, right controls
        split = QSplitter(Qt.Horizontal)
        # Preview
        left = QWidget()
        leftLay = QVBoxLayout(left)
        leftLay.setContentsMargins(0, 0, 0, 0)
        self.preview = QLabel("No photo")
        self.preview.setFrameShape(QFrame.StyledPanel)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview.setMinimumSize(QSize(320, 240))
        leftLay.addWidget(self.preview)
        split.addWidget(left)

        # Controls
        right = QWidget()
        rightLay = QVBoxLayout(right)
        rightLay.setContentsMargins(4, 4, 4, 4)

        self.peopleBox = QComboBox()
        self.newPerson = QLineEdit()
        self.newPerson.setPlaceholderText("Add new person…")
        self.addPersonBtn = QPushButton("Add Person")

        pRow = QHBoxLayout()
        pRow.addWidget(self.newPerson)
        pRow.addWidget(self.addPersonBtn)

        rightLay.addWidget(QLabel("People"))
        rightLay.addWidget(self.peopleBox)
        rightLay.addLayout(pRow)

        self.dateEdit = QDateTimeEdit(QDateTime.currentDateTime())
        self.dateEdit.setCalendarPopup(True)
        self.copyPrevBtn = QPushButton("Use previous date")

        rightLay.addSpacing(8)
        rightLay.addWidget(QLabel("Date/Time"))
        rightLay.addWidget(self.dateEdit)
        rightLay.addWidget(self.copyPrevBtn)

        self.applyToDupes = QCheckBox("Also apply to duplicates (same phash)")
        self.applyToDupes.setChecked(True)

        self.applyPersonBtn = QPushButton("Apply Person to Photo")
        self.applyDateBtn = QPushButton("Apply Date to Photo")
        rightLay.addSpacing(12)
        rightLay.addWidget(self.applyToDupes)
        rightLay.addWidget(self.applyPersonBtn)
        rightLay.addWidget(self.applyDateBtn)
        rightLay.addStretch(1)

        split.addWidget(right)
        split.setSizes([3_000, 1_200])

        root.addWidget(split)

        # Footer status
        self.pathLbl = QLabel("")
        self.pathLbl.setStyleSheet("color: #666;")
        root.addWidget(self.pathLbl)

        self.setWidget(container)

        # Signals
        self.buildBtn.clicked.connect(self._build_batch)
        self.prevBtn.clicked.connect(self._prev)
        self.nextBtn.clicked.connect(self._next)
        self.addPersonBtn.clicked.connect(self._add_person_clicked)
        self.copyPrevBtn.clicked.connect(self._copy_prev_date)
        self.applyPersonBtn.clicked.connect(self._apply_person)
        self.applyDateBtn.clicked.connect(self._apply_date)

        # Shortcuts
        self.applyDateBtn.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_D))
        self.applyPersonBtn.setShortcut(QKeySequence(Qt.CTRL | Qt.Key_P))

    # ----- Data loads -----

    def _load_people(self):
        people = load_people(self.conn)
        self.peopleBox.clear()
        for row in people:
            self.peopleBox.addItem(row["display_name"], row["person_id"])

    def _build_batch(self):
        try:
            self.batch = build_simple_tagging_batch(self.conn, limit=500)
        except Exception as e:
            QMessageBox.critical(self, "Batch Error",
                                 f"Failed to build batch:\n{e}")
            self.batch = []
        self.index = 0 if self.batch else -1
        self._update_ui()

    # ----- Navigation & Preview -----

    def _current(self) -> Optional[PhotoItem]:
        if 0 <= self.index < len(self.batch):
            return self.batch[self.index]
        return None

    def _update_ui(self):
        n = len(self.batch)
        i = (self.index + 1) if self.index >= 0 else 0
        self.counterLbl.setText(f"{i} / {n}")
        cur = self._current()

        if cur is None:
            self.preview.setText("No photo")
            self.preview.setPixmap(QPixmap())
            self.pathLbl.setText("")
            self.prevBtn.setEnabled(False)
            self.nextBtn.setEnabled(False)
            self.applyPersonBtn.setEnabled(False)
            self.applyDateBtn.setEnabled(False)
            return

        self.prevBtn.setEnabled(self.index > 0)
        self.nextBtn.setEnabled(self.index < n - 1)
        self.applyPersonBtn.setEnabled(True)
        self.applyDateBtn.setEnabled(True)

        self.pathLbl.setText(cur.path)
        self._load_pixmap(cur.path)

    def _load_pixmap(self, path: str):
        if not path or not os.path.exists(path):
            self.preview.setText("Missing file")
            self.preview.setPixmap(QPixmap())
            return
        pm = QPixmap(path)
        if pm.isNull():
            self.preview.setText("Unsupported image")
            self.preview.setPixmap(QPixmap())
            return
        # scale to fit while keeping aspect
        max_w = max(320, self.preview.width() - 8)
        max_h = max(240, self.preview.height() - 8)
        scaled = pm.scaled(max_w, max_h, Qt.KeepAspectRatio,
                           Qt.SmoothTransformation)
        self.preview.setPixmap(scaled)

    def resizeEvent(self, event):
        # re-scale on resize to keep things crisp
        cur = self._current()
        if cur:
            QTimer.singleShot(0, lambda: self._load_pixmap(cur.path))
        super().resizeEvent(event)

    def _prev(self):
        if self.index > 0:
            self.index -= 1
            self._update_ui()

    def _next(self):
        if self.index < len(self.batch) - 1:
            self.index += 1
            self._update_ui()

    # ----- Actions -----

    def _add_person_clicked(self):
        name = self.newPerson.text().strip()
        if not name:
            return
        try:
            pid = add_person(self.conn, name)
        except Exception as e:
            QMessageBox.critical(self, "Add Person",
                                 f"Failed to add person:\n{e}")
            return
        self.newPerson.clear()
        self._load_people()
        # select newly added
        idx = self.peopleBox.findData(pid)
        if idx >= 0:
            self.peopleBox.setCurrentIndex(idx)

    def _apply_person(self):
        cur = self._current()
        if not cur:
            return
        if self.peopleBox.currentIndex() < 0:
            QMessageBox.information(
                self, "Apply Person", "Select or add a person first.")
            return
        person_id = int(self.peopleBox.currentData())
        try:
            # current photo
            upsert_person_tag(self.conn, cur.photo_id,
                              person_id, source="human", conf=1.0)

            # duplicates by phash
            if self.applyToDupes.isChecked() and cur.phash:
                dupes = photos_by_phash(self.conn, cur.phash)
                for pid in dupes:
                    upsert_person_tag(self.conn, pid, person_id,
                                      source="propagated", conf=0.95)

            self.conn.commit()
        except Exception as e:
            QMessageBox.critical(self, "Apply Person",
                                 f"Failed to write tag:\n{e}")
            return

        # advance
        self._next()

    def _apply_date(self):
        cur = self._current()
        if not cur:
            return
        iso_dt = self.dateEdit.dateTime().toString(Qt.ISODate)
        try:
            # current photo
            upsert_date_tag(self.conn, cur.photo_id, iso_dt,
                            source="human", conf=1.0)

            # duplicates by phash
            if self.applyToDupes.isChecked() and cur.phash:
                dupes = photos_by_phash(self.conn, cur.phash)
                for pid in dupes:
                    upsert_date_tag(self.conn, pid, iso_dt,
                                    source="propagated", conf=0.95)

            self.conn.commit()
        except Exception as e:
            QMessageBox.critical(self, "Apply Date",
                                 f"Failed to write tag:\n{e}")
            return

        self.last_date_iso = iso_dt
        # advance
        self._next()

    def _copy_prev_date(self):
        if not self.last_date_iso:
            QMessageBox.information(
                self, "Copy Date", "No previous date used in this session.")
            return
        try:
            dt = QDateTime.fromString(self.last_date_iso, Qt.ISODate)
            if dt.isValid():
                self.dateEdit.setDateTime(dt)
        except Exception:
            pass

    # ----- Keyboard shortcuts -----

    def keyPressEvent(self, event):
        key = event.key()
        mod = event.modifiers()

        if key in (Qt.Key_Left, Qt.Key_J) and mod == Qt.NoModifier:
            self._prev()
            return
        if key in (Qt.Key_Right, Qt.Key_K) and mod == Qt.NoModifier:
            self._next()
            return

        # Number keys select the nth person in the list (1..9)
        if Qt.Key_1 <= key <= Qt.Key_9 and mod == Qt.NoModifier:
            idx = key - Qt.Key_1
            if 0 <= idx < self.peopleBox.count():
                self.peopleBox.setCurrentIndex(idx)
            return

        super().keyPressEvent(event)

# ---------- Optional: Standalone Window wrapper ----------


class TaggingWindow(QMainWindow):
    """
    Convenience window to run the TaggingPanel standalone, e.g. for testing:
      python -m app.ui_tagging
    """

    def __init__(self, db: Optional[str] = "data/photochrono.db"):
        super().__init__()
        self.setWindowTitle("Tagging")
        self.resize(1100, 700)
        self.panel = TaggingPanel(db, self)
        self.setCentralWidget(self.panel)


# ---------- Module entrypoint for quick testing ----------
if __name__ == "__main__":
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    win = TaggingWindow("data/photochrono.db")
    win.show()
    sys.exit(app.exec())
