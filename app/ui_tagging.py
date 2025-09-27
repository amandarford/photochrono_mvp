# app/ui_tagging.py
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Set

from PySide6.QtCore import Qt, QDate, QSize, QPointF, QRectF, QTimer
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QImageReader
from PySide6.QtWidgets import (
    QWidget, QDockWidget, QLabel, QPushButton, QLineEdit, QComboBox,
    QHBoxLayout, QVBoxLayout, QMessageBox, QCheckBox, QSplitter, QSizePolicy,
    QGroupBox, QToolButton, QCalendarWidget, QToolTip
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


def _norm_path(p: str) -> str:
    if not p:
        return p
    if p.lower().startswith("file://"):
        p = p[7:]
    return os.path.expanduser(p)


@dataclass
class PhotoItem:
    photo_id: int
    path: str
    phash: Optional[str] = None


# ---------- DB helpers ----------

def detect_photos_table(conn: sqlite3.Connection) -> Tuple[str, str, str]:
    for t in TABLE_CANDIDATES:
        try:
            cols = conn.execute(f"PRAGMA table_info({t})").fetchall()
        except sqlite3.OperationalError:
            continue
        if not cols:
            continue
        colnames = [c[1] for c in cols]
        id_col = next((c for c in ("id", "photo_id", "image_id")
                      if c in colnames), None) or "rowid"
        path_col = next(
            (c for c in PATH_COL_CANDIDATES if c in colnames), None)
        if not path_col:
            for c in colnames:
                if "path" in c.lower() or "file" in c.lower():
                    path_col = c
                    break
        if path_col:
            return t, id_col, path_col

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
            lc = c.lower()
            if lc in PATH_COL_CANDIDATES or "path" in lc or "file" in lc:
                path_col = c
                break
        if path_col:
            id_col = next((c for c in ("id", "photo_id", "image_id")
                          if c in colnames), None) or "rowid"
            return t, id_col, path_col

    raise RuntimeError(
        "Could not locate a table/column holding photo file paths.")


def load_people(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        "SELECT person_id, display_name FROM people ORDER BY display_name COLLATE NOCASE"
    ).fetchall()


def add_person(conn: sqlite3.Connection, name: str) -> int:
    cur = conn.execute(
        "INSERT INTO people(display_name) VALUES (?)", (name.strip(),))
    conn.commit()
    return cur.lastrowid


def upsert_person_tag(conn: sqlite3.Connection, photo_id: int, person_id: int,
                      source: str = "human", conf: float = 1.0) -> None:
    conn.execute("""
        INSERT INTO photo_tags(photo_id, tag_type, tag_value, source, confidence)
        VALUES (?, 'person', ?, ?, ?)
        ON CONFLICT(photo_id, tag_type, tag_value) DO UPDATE SET
            source=excluded.source,
            confidence=excluded.confidence
    """, (photo_id, str(person_id), source, conf))


def replace_date_tag(conn: sqlite3.Connection, photo_id: int, iso_dt: str,
                     source: str = "human", conf: float = 1.0) -> None:
    """Delete any existing date(s) for this photo, then insert one new date."""
    conn.execute(
        "DELETE FROM photo_tags WHERE photo_id=? AND tag_type='date'", (photo_id,))
    conn.execute("""
        INSERT INTO photo_tags(photo_id, tag_type, tag_value, source, confidence)
        VALUES (?, 'date', ?, ?, ?)
    """, (photo_id, iso_dt, source, conf))


def fetch_phash(conn: sqlite3.Connection, photo_id: int) -> Optional[str]:
    row = conn.execute(
        "SELECT phash_hex FROM phash WHERE photo_id=?", (photo_id,)).fetchone()
    return row["phash_hex"] if row else None


def photos_by_phash(conn: sqlite3.Connection, phash_hex: str) -> List[int]:
    rows = conn.execute(
        "SELECT photo_id FROM phash WHERE phash_hex=?", (phash_hex,)).fetchall()
    return [r["photo_id"] for r in rows]


def fetch_tags_for_photo(conn: sqlite3.Connection, photo_id: int) -> Tuple[List[sqlite3.Row], List[sqlite3.Row]]:
    people = conn.execute("""
        SELECT p.display_name, pt.source, pt.confidence
        FROM photo_tags pt
        JOIN people p
          ON pt.tag_type='person'
         AND CAST(pt.tag_value AS INTEGER)=p.person_id
        WHERE pt.photo_id=?
        ORDER BY p.display_name COLLATE NOCASE
    """, (photo_id,)).fetchall()
    dates = conn.execute("""
        SELECT pt.tag_value AS iso_dt, pt.source, pt.confidence
        FROM photo_tags pt
        WHERE pt.photo_id=? AND pt.tag_type='date'
        ORDER BY pt.created_at DESC
    """, (photo_id,)).fetchall()
    return people, dates


def fetch_faces_for_photo(conn: sqlite3.Connection, photo_id: int) -> List[sqlite3.Row]:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS face_boxes (
      photo_id INTEGER NOT NULL,
      face_id INTEGER NOT NULL,
      x REAL NOT NULL, y REAL NOT NULL, w REAL NOT NULL, h REAL NOT NULL,
      embedding BLOB, cluster_id TEXT, assigned_person_id INTEGER,
      source TEXT DEFAULT 'detector', confidence REAL DEFAULT 0.0,
      PRIMARY KEY(photo_id, face_id)
    );""")
    return conn.execute("""
        SELECT fb.photo_id, fb.face_id, fb.x, fb.y, fb.w, fb.h,
               fb.cluster_id, fb.assigned_person_id, fb.confidence,
               p.display_name AS person_name
        FROM face_boxes fb
        LEFT JOIN people p ON p.person_id = fb.assigned_person_id
        WHERE fb.photo_id=?
        ORDER BY fb.face_id
    """, (photo_id,)).fetchall()


# ---------- Batch ----------

@dataclass
class BatchConfig:
    limit: int = 500


def build_simple_tagging_batch(conn: sqlite3.Connection, cfg: BatchConfig = BatchConfig()) -> List[PhotoItem]:
    table, id_col, path_col = detect_photos_table(conn)
    reps: List[PhotoItem] = []

    # representative per phash (lowest id)
    rows = conn.execute("SELECT photo_id, phash_hex FROM phash").fetchall()
    best: Dict[str, int] = {}
    for r in rows:
        pid, ph = r["photo_id"], r["phash_hex"]
        if ph not in best or pid < best[ph]:
            best[ph] = pid
    if best:
        ids_tuple = tuple(best.values())
        q = f"SELECT {id_col} AS pid, {path_col} AS pth FROM {table} WHERE {id_col} IN ({','.join(['?']*len(ids_tuple))})"
        rep_rows = conn.execute(q, ids_tuple).fetchall()
        for rr in rep_rows:
            reps.append(PhotoItem(
                photo_id=rr["pid"], path=rr["pth"], phash=fetch_phash(conn, rr["pid"])))

    # any without a phash yet
    if len(reps) < cfg.limit:
        without_hash = conn.execute(f"""
            SELECT {id_col} AS pid, {path_col} AS pth
            FROM {table}
            WHERE {id_col} NOT IN (SELECT photo_id FROM phash)
            LIMIT ?
        """, (cfg.limit - len(reps),)).fetchall()
        for r in without_hash:
            reps.append(
                PhotoItem(photo_id=r["pid"], path=r["pth"], phash=None))
            if len(reps) >= cfg.limit:
                break

    # top-up
    if len(reps) < cfg.limit:
        got_ids = {p.photo_id for p in reps}
        filler = conn.execute(
            f"SELECT {id_col} AS pid, {path_col} AS pth FROM {table} LIMIT ?",
            (cfg.limit - len(reps),)
        ).fetchall()
        for r in filler:
            if r["pid"] in got_ids:
                continue
            reps.append(
                PhotoItem(photo_id=r["pid"], path=r["pth"], phash=fetch_phash(conn, r["pid"])))
            if len(reps) >= cfg.limit:
                break

    reps.sort(key=lambda x: x.photo_id)
    return reps


# ---------- Overlay widget (faces with selectable rectangles + hover name) ----------

class FacePreview(QWidget):
    """
    Draws the current image scaled-to-fit + face rectangles.
    Click a rectangle to select. Ctrl/Cmd or Shift toggles multi-select.
    Shows assigned person name on hover.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(QSize(320, 240))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self._pixmap: Optional[QPixmap] = None
        self._image_size = QSize(0, 0)
        self._faces: List[Dict] = []
        self._people_lu: Dict[int, str] = {}
        self.selected: Set[int] = set()
        self.selection_changed = None
        self.hover_fid: Optional[int] = None

    def set_person_lookup(self, lu: Dict[int, str]):
        self._people_lu = dict(lu or {})

    def set_image(self, pm: Optional[QPixmap]):
        self._pixmap = pm
        self._image_size = pm.size() if pm else QSize(0, 0)
        self.update()

    def set_faces(self, faces: List[sqlite3.Row]):
        self._faces = [dict(r) for r in faces]
        fids = {int(d["face_id"]) for d in self._faces}
        self.selected = {fid for fid in self.selected if fid in fids}
        if self.hover_fid not in fids:
            self.hover_fid = None
        self.update()
        if self.selection_changed:
            self.selection_changed(len(self.selected))

    def clear_selection(self):
        self.selected.clear()
        self.update()
        if self.selection_changed:
            self.selection_changed(0)

    def select_all(self):
        self.selected = {int(d["face_id"]) for d in self._faces}
        self.update()
        if self.selection_changed:
            self.selection_changed(len(self.selected))

    def get_selected_face_ids(self) -> List[int]:
        return sorted(self.selected)

    @staticmethod
    def _load_pixmap_for_widget(path: str, widget: QWidget) -> QPixmap:
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        img = reader.read()
        if img.isNull():
            return QPixmap()
        return QPixmap.fromImage(img)

    # --- geometry helpers (support normalized OR absolute pixel coords) ---
    def _as_normalized(self, x: float, y: float, w: float, h: float) -> Tuple[float, float, float, float]:
        iw, ih = float(self._image_size.width()), float(
            self._image_size.height())
        if iw <= 0 or ih <= 0:
            return 0, 0, 0, 0
        looks_normalized = (0.0 <= x <= 1.0) and (
            0.0 <= y <= 1.0) and (0.0 < w <= 1.0) and (0.0 < h <= 1.0)
        if looks_normalized:
            return x, y, w, h
        return x / iw, y / ih, w / iw, h / ih

    def _rect_for_face(self, draw_rect: QRectF, d: Dict) -> QRectF:
        x, y, w, h = float(d["x"]), float(d["y"]), float(d["w"]), float(d["h"])
        xn, yn, wn, hn = self._as_normalized(x, y, w, h)
        return QRectF(draw_rect.x() + xn * draw_rect.width(),
                      draw_rect.y() + yn * draw_rect.height(),
                      wn * draw_rect.width(),
                      hn * draw_rect.height())

    def _compute_draw_rect(self) -> QRectF:
        if not self._pixmap:
            return QRectF(0, 0, self.width(), self.height())
        iw, ih = self._pixmap.width(), self._pixmap.height()
        ww, wh = self.width(), self.height()
        if iw <= 0 or ih <= 0 or ww <= 0 or wh <= 0:
            return QRectF(0, 0, ww, wh)
        scale = min(ww / iw, wh / ih)
        dw, dh = iw * scale, ih * scale
        dx, dy = (ww - dw) / 2.0, (wh - dh) / 2.0
        return QRectF(dx, dy, dw, dh)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), self.palette().window())

        if not self._pixmap or self._pixmap.isNull():
            p.setPen(QPen(QColor("#999"), 1))
            p.drawText(self.rect(), Qt.AlignCenter, "No photo")
            return

        draw_rect = self._compute_draw_rect()
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        src = QRectF(0, 0, self._pixmap.width(), self._pixmap.height())
        p.drawPixmap(draw_rect, self._pixmap, src)

        p.setRenderHint(QPainter.Antialiasing, True)
        for d in self._faces:
            r = self._rect_for_face(draw_rect, d)
            fid = int(d["face_id"])
            assigned = d.get("assigned_person_id") is not None

            if fid in self.selected:
                pen = QPen(QColor("#21ba45"), 3)  # green: selected
            elif assigned:
                pen = QPen(QColor("#1f77b4"), 2)  # blue: has person
            else:
                pen = QPen(QColor("#d62728"), 2)  # red: unassigned
            p.setPen(pen)
            p.drawRect(r)

            # Hover label with person name
            if self.hover_fid == fid and d.get("person_name"):
                label = d["person_name"]
                text_rect = QRectF(r.x(), r.y() - 20, max(60.0, r.width()), 18)
                bg = QColor(255, 255, 255, 210)
                p.fillRect(text_rect, bg)
                p.setPen(QPen(QColor("#000"), 1))
                p.drawText(text_rect, Qt.AlignCenter, label)

    def _face_at(self, pt: QPointF) -> Optional[int]:
        if not self._pixmap or self._pixmap.isNull():
            return None
        dr = self._compute_draw_rect()
        for d in reversed(self._faces):
            if self._rect_for_face(dr, d).contains(pt):
                return int(d["face_id"])
        return None

    def mouseMoveEvent(self, e):
        fid = self._face_at(e.position())

        # update hover id + repaint
        if fid != self.hover_fid:
            self.hover_fid = fid
            self.update()

        # tooltip with person name
        if fid is not None:
            d = next((d for d in self._faces if int(
                d["face_id"]) == fid), None)
            if d:
                pid = d.get("assigned_person_id")
                if pid is not None:
                    name = self._people_lu.get(int(pid), d.get(
                        "person_name") or f"Person #{pid}")
                    QToolTip.showText(self.mapToGlobal(
                        e.position().toPoint()), name, self)
                else:
                    QToolTip.hideText()
        else:
            QToolTip.hideText()

        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.hover_fid = None
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        fid = self._face_at(e.position())
        if fid is None:
            if not (e.modifiers() & (Qt.ControlModifier | Qt.MetaModifier | Qt.ShiftModifier)):
                self.clear_selection()
            return
        if (e.modifiers() & (Qt.ControlModifier | Qt.MetaModifier | Qt.ShiftModifier)):
            if fid in self.selected:
                self.selected.remove(fid)
            else:
                self.selected.add(fid)
        else:
            self.selected = {fid}
        self.update()
        if self.selection_changed:
            self.selection_changed(len(self.selected))


# ---------- UI ----------

class TaggingPanel(QDockWidget):
    def __init__(self, db, parent=None):
        super().__init__("Tagging", parent)
        self.conn = _open_conn(db)
        _ensure_core_tables(self.conn)

        self.batch: List[PhotoItem] = []
        self.index: int = -1

        self._init_ui()
        self._load_people()
        self._build_batch()

    def _init_ui(self):
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # Top bar
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

        split = QSplitter(Qt.Horizontal)

        # Preview
        left = QWidget()
        leftLay = QVBoxLayout(left)
        leftLay.setContentsMargins(0, 0, 0, 0)
        self.preview = FacePreview()
        selRow = QHBoxLayout()
        self.selCountLbl = QLabel("Selected faces: 0")
        selRow.addWidget(self.selCountLbl)
        selRow.addStretch(1)
        self.preview.selection_changed = lambda n: self.selCountLbl.setText(
            f"Selected faces: {n}")
        leftLay.addWidget(self.preview)
        leftLay.addLayout(selRow)
        split.addWidget(left)

        # Controls
        right = QWidget()
        rightLay = QVBoxLayout(right)
        rightLay.setContentsMargins(4, 4, 4, 4)

        rightLay.addWidget(QLabel("People"))
        self.peopleBox = QComboBox()
        self.newPerson = QLineEdit()
        self.newPerson.setPlaceholderText("Add new person…")
        self.addPersonBtn = QPushButton("Add Person")
        pRow = QHBoxLayout()
        pRow.addWidget(self.newPerson)
        pRow.addWidget(self.addPersonBtn)
        rightLay.addWidget(self.peopleBox)
        rightLay.addLayout(pRow)

        rightLay.addSpacing(8)
        rightLay.addWidget(QLabel("Date"))
        dateRow = QHBoxLayout()
        self.dateLine = QLineEdit()
        self.dateLine.setInputMask("99-99-9999;_")  # MM-DD-YYYY
        self.dateLine.setPlaceholderText("MM-DD-YYYY")
        self.btnCalendar = QToolButton()
        self.btnCalendar.setText("📅")
        self.btnCalendar.setToolTip("Open calendar")
        dateRow.addWidget(self.dateLine, 1)
        dateRow.addWidget(self.btnCalendar, 0)
        rightLay.addLayout(dateRow)

        rightLay.addSpacing(8)
        self.applyToDupes = QCheckBox("Also apply to duplicates (same phash)")
        self.applyToDupes.setChecked(True)
        rightLay.addWidget(self.applyToDupes)

        # Face actions only
        self.applyPersonFaceBtn = QPushButton(
            "Apply Person to Selected Face(s)")
        self.clearPersonFaceBtn = QPushButton(
            "Remove Person from Selected Face(s)")
        rightLay.addWidget(self.applyPersonFaceBtn)
        rightLay.addWidget(self.clearPersonFaceBtn)

        # Existing tags
        rightLay.addSpacing(12)
        gb = QGroupBox("Existing Tags (this photo)")
        gbLay = QVBoxLayout(gb)
        self.tagsPeopleLbl = QLabel("— none —")
        self.tagsPeopleLbl.setWordWrap(True)
        self.tagsPeopleLbl.setTextFormat(Qt.RichText)
        self.tagsDateLbl = QLabel("— none —")
        self.tagsDateLbl.setWordWrap(True)
        self.tagsDateLbl.setTextFormat(Qt.RichText)
        gbLay.addWidget(QLabel("People:"))
        gbLay.addWidget(self.tagsPeopleLbl)
        gbLay.addWidget(QLabel("Date:"))
        gbLay.addWidget(self.tagsDateLbl)
        rightLay.addWidget(gb)
        rightLay.addStretch(1)

        split.addWidget(right)
        split.setSizes([3_000, 1_200])
        root.addWidget(split)

        # Footer status
        self.pathLbl = QLabel("")
        self.pathLbl.setStyleSheet("color: #666;")
        self.statusLbl = QLabel("")
        self.statusLbl.setStyleSheet("color: #0a7;")
        root.addWidget(self.pathLbl)
        root.addWidget(self.statusLbl)

        self.setWidget(container)

        # Calendar popup
        self.calendar = QCalendarWidget()
        self.calendar.setWindowFlags(Qt.Popup)
        self.calendar.hide()
        self.calendar.clicked.connect(self._calendar_date_selected)

        # Autosave debounce for date typing
        self._date_autosave = QTimer(self)
        self._date_autosave.setSingleShot(True)
        self._date_autosave.setInterval(600)
        self._date_autosave.timeout.connect(self._autosave_date_if_complete)

        # Signals
        self.buildBtn.clicked.connect(self._build_batch)
        self.prevBtn.clicked.connect(self._prev)
        self.nextBtn.clicked.connect(self._next)
        self.addPersonBtn.clicked.connect(self._add_person_clicked)
        self.applyPersonFaceBtn.clicked.connect(self._apply_person_faces)
        self.clearPersonFaceBtn.clicked.connect(self._clear_person_faces)
        self.btnCalendar.clicked.connect(self._show_calendar)
        self.dateLine.textChanged.connect(
            lambda _: self._date_autosave.start())

    # ----- Data loads -----

    def _load_people(self):
        people = load_people(self.conn)
        self.peopleBox.clear()
        lu: Dict[int, str] = {}
        for row in people:
            self.peopleBox.addItem(row["display_name"], row["person_id"])
            lu[int(row["person_id"])] = row["display_name"]
        self.preview.set_person_lookup(lu)

    def _build_batch(self):
        try:
            self.batch = build_simple_tagging_batch(self.conn)
        except Exception as e:
            QMessageBox.critical(self, "Batch Error",
                                 f"Failed to build batch:\n{e}")
            self.batch = []
        self.index = 0 if self.batch else -1
        self._update_ui()

    # ----- Navigation & Preview -----

    def _current(self) -> Optional[PhotoItem]:
        if not hasattr(self, "index"):
            self.index = -1
        if 0 <= self.index < len(self.batch):
            return self.batch[self.index]
        return None

    def _update_ui(self):
        n = len(self.batch)
        i = (self.index + 1) if self.index >= 0 else 0
        self.counterLbl.setText(f"{i} / {n}")
        cur = self._current()

        if cur is None:
            self.preview.set_image(None)
            self.preview.set_faces([])
            self.pathLbl.setText("")
            self.statusLbl.setText("")
            self.prevBtn.setEnabled(False)
            self.nextBtn.setEnabled(False)
            self.applyPersonFaceBtn.setEnabled(False)
            self.clearPersonFaceBtn.setEnabled(False)
            self.tagsPeopleLbl.setText("— none —")
            self.tagsDateLbl.setText("— none —")
            self.selCountLbl.setText("Selected faces: 0")
            return

        # wrap-around navigation is handled in _prev/_next; buttons always enabled if there is content
        self.prevBtn.setEnabled(n > 0)
        self.nextBtn.setEnabled(n > 0)
        self.applyPersonFaceBtn.setEnabled(True)
        self.clearPersonFaceBtn.setEnabled(True)

        self.pathLbl.setText(cur.path)
        pth = _norm_path(cur.path)
        pm = FacePreview._load_pixmap_for_widget(pth, self.preview)
        self.preview.set_image(None if pm.isNull() else pm)

        faces = fetch_faces_for_photo(self.conn, cur.photo_id)
        self.preview.set_faces(faces)
        self.selCountLbl.setText(
            f"Selected faces: {len(self.preview.selected)}")

        self._refresh_tags()
        self.statusLbl.setText("")

    def resizeEvent(self, event):
        self.preview.update()
        super().resizeEvent(event)

    def _prev(self):
        if not self.batch:
            return
        self.index = (self.index - 1) % len(self.batch)
        self._update_ui()

    def _next(self):
        if not self.batch:
            return
        self.index = (self.index + 1) % len(self.batch)
        self._update_ui()

    # ----- Date helpers -----

    def _show_calendar(self):
        pos = self.btnCalendar.mapToGlobal(
            self.btnCalendar.rect().bottomLeft())
        self.calendar.move(pos)
        qd = self._parse_date_line()
        if qd.isValid():
            self.calendar.setSelectedDate(qd)
        self.calendar.show()
        self.calendar.setFocus()

    def _calendar_date_selected(self, qdate: QDate):
        self.dateLine.setText(qdate.toString(
            "MM-dd-yyyy"))  # triggers autosave
        self.calendar.hide()

    def _parse_date_line(self) -> QDate:
        text = self.dateLine.text()
        if "_" in text:
            return QDate()  # incomplete
        qd = QDate.fromString(text, "MM-dd-yyyy")
        return qd if qd.isValid() else QDate()

    def _current_date_iso(self) -> Optional[str]:
        qd = self._parse_date_line()
        if not qd.isValid():
            return None
        return qd.toString("yyyy-MM-dd") + "T00:00:00"

    def _autosave_date_if_complete(self):
        iso = self._current_date_iso()
        if iso:
            self._save_date_replace(iso)

    def _save_date_replace(self, iso_dt: str):
        cur = self._current()
        if not cur:
            return
        dupes: List[int] = []
        try:
            replace_date_tag(self.conn, cur.photo_id, iso_dt,
                             source="human", conf=1.0)
            if self.applyToDupes.isChecked() and cur.phash:
                dupes = photos_by_phash(self.conn, cur.phash)
                for pid in dupes:
                    replace_date_tag(self.conn, pid, iso_dt,
                                     source="propagated", conf=0.95)
            self.conn.commit()
        except Exception as e:
            QMessageBox.critical(
                self, "Date Save", f"Failed to save date:\n{e}")
            return

        self._refresh_tags()
        self.statusLbl.setText(
            f"Saved date (replaced previous); also set {len(dupes)} duplicate(s).")

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
        idx = self.peopleBox.findData(pid)
        if idx >= 0:
            self.peopleBox.setCurrentIndex(idx)

    def _apply_person_faces(self):
        cur = self._current()
        if not cur:
            return
        if self.peopleBox.currentIndex() < 0:
            QMessageBox.information(
                self, "Apply Person", "Select or add a person first.")
            return
        face_ids = self.preview.get_selected_face_ids()
        if not face_ids:
            QMessageBox.information(
                self, "Apply Person", "Select one or more face rectangles first.")
            return
        person_id = int(self.peopleBox.currentData())

        qmarks = ",".join(["?"] * len(face_ids))
        rows = self.conn.execute(
            f"SELECT face_id, cluster_id FROM face_boxes WHERE photo_id=? AND face_id IN ({qmarks})",
            (cur.photo_id, *face_ids)
        ).fetchall()
        cluster_ids = sorted({r["cluster_id"]
                             for r in rows if r["cluster_id"]})

        try:
            # assign in current photo
            self.conn.execute(
                f"UPDATE face_boxes SET assigned_person_id=? WHERE photo_id=? AND face_id IN ({qmarks})",
                (person_id, cur.photo_id, *face_ids)
            )

            # ensure photo-level tag exists so it appears in the right panel
            upsert_person_tag(self.conn, cur.photo_id,
                              person_id, source="face", conf=1.0)

            # also mark entire cluster with this person
            for cid in cluster_ids:
                self.conn.execute("UPDATE face_boxes SET assigned_person_id=? WHERE cluster_id=?",
                                  (person_id, cid))

            # propagate person tag to any photo that has these clusters
            if cluster_ids:
                rows2 = self.conn.execute(
                    f"SELECT DISTINCT photo_id FROM face_boxes WHERE cluster_id IN ({','.join('?'*len(cluster_ids))})",
                    cluster_ids
                ).fetchall()
                target_ids = {int(r["photo_id"]) for r in rows2}
                for pid2 in target_ids:
                    self.conn.execute("""
                        INSERT INTO photo_tags(photo_id, tag_type, tag_value, source, confidence)
                        VALUES (?, 'person', ?, 'propagated_cluster', 0.90)
                        ON CONFLICT(photo_id, tag_type, tag_value) DO NOTHING
                    """, (pid2, str(person_id)))

            self.conn.commit()
        except Exception as e:
            QMessageBox.critical(self, "Apply Person to Faces",
                                 f"Failed to write tags:\n{e}")
            return

        self._refresh_tags()
        self.preview.set_faces(fetch_faces_for_photo(self.conn, cur.photo_id))
        self.statusLbl.setText(f"Saved person to {len(face_ids)} face(s).")

    def _clear_person_faces(self):
        """Remove assigned_person_id from selected faces; also drop stale photo-level tags when no faces remain."""
        cur = self._current()
        if not cur:
            return
        face_ids = self.preview.get_selected_face_ids()
        if not face_ids:
            QMessageBox.information(
                self, "Remove Person", "Select one or more face rectangles first.")
            return

        qmarks = ",".join(["?"] * len(face_ids))
        rows = self.conn.execute(
            f"SELECT face_id, assigned_person_id FROM face_boxes WHERE photo_id=? AND face_id IN ({qmarks})",
            (cur.photo_id, *face_ids)
        ).fetchall()
        person_ids = sorted({r["assigned_person_id"]
                            for r in rows if r["assigned_person_id"] is not None})

        try:
            # clear assignments in current photo
            self.conn.execute(
                f"UPDATE face_boxes SET assigned_person_id=NULL WHERE photo_id=? AND face_id IN ({qmarks})",
                (cur.photo_id, *face_ids)
            )

            # remove propagated_cluster tag in this photo for affected people
            for pid in person_ids:
                self.conn.execute("""
                    DELETE FROM photo_tags
                    WHERE photo_id=? AND tag_type='person' AND tag_value=? AND source='propagated_cluster'
                """, (cur.photo_id, str(pid)))

            # if no faces of that person remain in this photo, drop any person tag for them (regardless of source)
            for pid in person_ids:
                row = self.conn.execute(
                    "SELECT COUNT(*) AS c FROM face_boxes WHERE photo_id=? AND assigned_person_id=?",
                    (cur.photo_id, pid)
                ).fetchone()
                if row and int(row["c"]) == 0:
                    self.conn.execute(
                        "DELETE FROM photo_tags WHERE photo_id=? AND tag_type='person' AND tag_value=?",
                        (cur.photo_id, str(pid))
                    )

            self.conn.commit()
        except Exception as e:
            QMessageBox.critical(self, "Remove Person",
                                 f"Failed to clear tags:\n{e}")
            return

        self._refresh_tags()
        self.preview.set_faces(fetch_faces_for_photo(self.conn, cur.photo_id))
        self.statusLbl.setText(f"Removed person from {len(face_ids)} face(s).")

    def _refresh_tags(self):
        cur = self._current()
        if not cur:
            self.tagsPeopleLbl.setText("— none —")
            self.tagsDateLbl.setText("— none —")
            return

        people, dates = fetch_tags_for_photo(self.conn, cur.photo_id)

        if people:
            self.tagsPeopleLbl.setText(
                " • " + "<br> • ".join(
                    f"{r['display_name']} <span style='color:#777'>({r['source']}, {r['confidence']:.2f})</span>"
                    for r in people
                )
            )
        else:
            self.tagsPeopleLbl.setText("— none —")

        if dates:
            latest = dates[0]  # newest first
            self.tagsDateLbl.setText(
                f"{latest['iso_dt']} <span style='color:#777'>({latest['source']}, {latest['confidence']:.2f})</span>"
            )
        else:
            self.tagsDateLbl.setText("— none —")
