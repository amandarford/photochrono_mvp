from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QDockWidget, QLabel, QPushButton, QLineEdit, QComboBox,
    QHBoxLayout, QVBoxLayout, QMessageBox, QCheckBox, QSplitter,
    QGroupBox, QToolButton, QCalendarWidget, QPlainTextEdit
)

# --- DB + helpers (from your ui_tagging.py) ---
from app.ui_tagging import (
    _open_conn, _ensure_core_tables, load_people, add_person,
    upsert_person_tag, replace_date_tag, fetch_faces_for_photo,
    fetch_tags_for_photo, photos_by_phash, fetch_phash,
    PhotoItem
)
from app.ui_tagging import FacePreview

from app.services.metadata import writeback_metadata
from app.services.store import Store


class TaggingPanel(QDockWidget):
    tagChanged = QtCore.Signal(object)

    def __init__(self, store: Store, parent=None):
        super().__init__("Tagging", parent)
        self.store = store
        self.conn = sqlite3.connect(str(self.store.db_path))
        self.conn.row_factory = sqlite3.Row
        _ensure_core_tables(self.conn)

        self.current: Optional[PhotoItem] = None
        self._init_ui()
        self._load_people()

    # --- UI ---
    def _init_ui(self):
        container = QWidget()
        root = QVBoxLayout(container)
        root.setContentsMargins(8, 8, 8, 8)

        split = QSplitter(Qt.Horizontal)

        # Left: preview + faces
        left = QWidget()
        lbox = QVBoxLayout(left)
        self.preview = FacePreview()
        self.selCountLbl = QLabel("Selected faces: 0")
        self.preview.selection_changed = (
            lambda n: self.selCountLbl.setText(f"Selected faces: {n}")
        )
        lbox.addWidget(self.preview)
        lbox.addWidget(self.selCountLbl)
        split.addWidget(left)

        # Right: tagging form
        right = QWidget()
        form = QVBoxLayout(right)

        # --- Basic fields ---
        self.title = QLineEdit()
        self.keywords = QLineEdit()
        self.rating = QtWidgets.QSpinBox()
        self.rating.setRange(0, 5)
        self.color = QtWidgets.QComboBox()
        self.color.addItems(
            ["None", "Red", "Green", "Blue", "Yellow", "Purple"]
        )
        self.notes = QPlainTextEdit()

        form.addWidget(QLabel("Title"))
        form.addWidget(self.title)
        form.addWidget(QLabel("Keywords (comma-separated)"))
        form.addWidget(self.keywords)
        form.addWidget(QLabel("Rating"))
        form.addWidget(self.rating)
        form.addWidget(QLabel("Color Label"))
        form.addWidget(self.color)
        form.addWidget(QLabel("Notes"))
        form.addWidget(self.notes)

        # --- Date field ---
        form.addWidget(QLabel("Date"))
        drow = QHBoxLayout()
        self.dateLine = QLineEdit()
        self.dateLine.setInputMask("99-99-9999;_")  # MM-DD-YYYY
        self.dateLine.setPlaceholderText("MM-DD-YYYY")
        self.btnCalendar = QToolButton()
        self.btnCalendar.setText("📅")
        drow.addWidget(self.dateLine, 1)
        drow.addWidget(self.btnCalendar)
        form.addLayout(drow)
        self.applyToDupes = QCheckBox("Apply to duplicates (same phash)")
        self.applyToDupes.setChecked(True)
        form.addWidget(self.applyToDupes)

        # --- People tagging ---
        form.addWidget(QLabel("People"))
        self.peopleBox = QComboBox()
        self.newPerson = QLineEdit()
        self.newPerson.setPlaceholderText("Add new person…")
        self.addPersonBtn = QPushButton("Add Person")
        prow = QHBoxLayout()
        prow.addWidget(self.newPerson)
        prow.addWidget(self.addPersonBtn)
        form.addWidget(self.peopleBox)
        form.addLayout(prow)

        self.applyPersonFaceBtn = QPushButton(
            "Apply Person to Selected Face(s)")
        self.clearPersonFaceBtn = QPushButton(
            "Remove Person from Selected Face(s)")
        form.addWidget(self.applyPersonFaceBtn)
        form.addWidget(self.clearPersonFaceBtn)

        # --- Existing tags ---
        gb = QGroupBox("Existing Tags")
        gbl = QVBoxLayout(gb)
        self.tagsPeopleLbl = QLabel("— none —")
        self.tagsDateLbl = QLabel("— none —")
        gbl.addWidget(QLabel("People:"))
        gbl.addWidget(self.tagsPeopleLbl)
        gbl.addWidget(QLabel("Date:"))
        gbl.addWidget(self.tagsDateLbl)
        form.addWidget(gb)

        form.addStretch(1)
        split.addWidget(right)

        root.addWidget(split)
        self.setWidget(container)

        # Calendar popup
        self.calendar = QCalendarWidget()
        self.calendar.setWindowFlags(Qt.Popup)
        self.calendar.clicked.connect(self._calendar_date_selected)

        # Signals
        self.btnCalendar.clicked.connect(self._show_calendar)
        self.dateLine.textChanged.connect(
            lambda _: self._date_autosave.start())
        self._date_autosave = QtCore.QTimer(self)
        self._date_autosave.setSingleShot(True)
        self._date_autosave.setInterval(600)
        self._date_autosave.timeout.connect(self._autosave_date)

        for w, sig in [
            (self.title, self.title.textChanged),
            (self.keywords, self.keywords.textChanged),
            (self.rating, self.rating.valueChanged),
            (self.color, self.color.currentIndexChanged),
            (self.notes, self.notes.textChanged),
        ]:
            sig.connect(self._emit_change)

        self.addPersonBtn.clicked.connect(self._add_person_clicked)
        self.applyPersonFaceBtn.clicked.connect(self._apply_person_faces)
        self.clearPersonFaceBtn.clicked.connect(self._clear_person_faces)

    # --- Loading ---
    def load_item(self, item: PhotoItem):
        self.current = item
        self.preview.set_image(QPixmap(item.path))
        self.preview.set_faces(fetch_faces_for_photo(self.conn, item.photo_id))

        tags_people, tags_date = fetch_tags_for_photo(self.conn, item.photo_id)
        self.tagsPeopleLbl.setText(
            " • " + "<br> • ".join(r["display_name"] for r in tags_people)
            if tags_people else "— none —"
        )
        if tags_date:
            self.tagsDateLbl.setText(tags_date[0]["iso_dt"])
            self.dateLine.setText(QDate.fromString(
                tags_date[0]["iso_dt"], "yyyy-MM-dd"
            ).toString("MM-dd-yyyy"))
        else:
            self.tagsDateLbl.setText("— none —")

    # --- Change handling ---
    def _emit_change(self, *a):
        if not self.current:
            return
        self.current.tags = {
            "title": self.title.text().strip(),
            "keywords": [s.strip() for s in self.keywords.text().split(",") if s.strip()],
            "rating": int(self.rating.value()),
            "color": self.color.currentText(),
            "notes": self.notes.toPlainText().strip(),
            "date": self.dateLine.text(),
        }
        self.tagChanged.emit(self.current)

        # --- save via Store (DB + EXIF) ---
        self.store.save_item(self.current)

    # --- Date ---

    def _show_calendar(self):
        pos = self.btnCalendar.mapToGlobal(
            self.btnCalendar.rect().bottomLeft())
        self.calendar.move(pos)
        self.calendar.show()

    def _calendar_date_selected(self, qdate: QDate):
        self.dateLine.setText(qdate.toString("MM-dd-yyyy"))

    def _autosave_date(self):
        if not self.current:
            return
        qd = QDate.fromString(self.dateLine.text(), "MM-dd-yyyy")
        if not qd.isValid():
            return
        iso = qd.toString("yyyy-MM-dd")
        replace_date_tag(self.conn, self.current.photo_id,
                         iso, source="human", conf=1.0)
        if self.applyToDupes.isChecked():
            ph = fetch_phash(self.conn, self.current.photo_id)
            if ph:
                for pid in photos_by_phash(self.conn, ph):
                    replace_date_tag(self.conn, pid, iso,
                                     source="propagated", conf=0.95)
        self.conn.commit()

        self.store.save_item(self.current)
        self._emit_change()

    # --- People ---

    def _load_people(self):
        people = load_people(self.conn)
        self.peopleBox.clear()
        for row in people:
            self.peopleBox.addItem(row["display_name"], row["person_id"])
        self.preview.set_person_lookup(
            {r["person_id"]: r["display_name"] for r in people})

    def _add_person_clicked(self):
        name = self.newPerson.text().strip()
        if not name:
            return
        pid = add_person(self.conn, name)
        self.newPerson.clear()
        self._load_people()
        idx = self.peopleBox.findData(pid)
        if idx >= 0:
            self.peopleBox.setCurrentIndex(idx)

    def _apply_person_faces(self):
        if not self.current:
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
            (self.current.photo_id, *face_ids)
        ).fetchall()
        cluster_ids = sorted({r["cluster_id"]
                             for r in rows if r["cluster_id"]})

        self.conn.execute(
            f"UPDATE face_boxes SET assigned_person_id=? WHERE photo_id=? AND face_id IN ({qmarks})",
            (person_id, self.current.photo_id, *face_ids)
        )
        upsert_person_tag(self.conn, self.current.photo_id,
                          person_id, source="face", conf=1.0)

        for cid in cluster_ids:
            self.conn.execute("UPDATE face_boxes SET assigned_person_id=? WHERE cluster_id=?",
                              (person_id, cid))
        if cluster_ids:
            rows2 = self.conn.execute(
                f"SELECT DISTINCT photo_id FROM face_boxes WHERE cluster_id IN ({','.join('?'*len(cluster_ids))})",
                cluster_ids
            ).fetchall()
            for r in rows2:
                self.conn.execute("""
                    INSERT INTO photo_tags(photo_id, tag_type, tag_value, source, confidence)
                    VALUES (?, 'person', ?, 'propagated_cluster', 0.90)
                    ON CONFLICT(photo_id, tag_type, tag_value) DO NOTHING
                """, (r["photo_id"], str(person_id)))
        self.conn.commit()

        self.preview.set_faces(fetch_faces_for_photo(
            self.conn, self.current.photo_id))
        self._emit_change()  # writes EXIF now

    def _clear_person_faces(self):
        if not self.current:
            return
        face_ids = self.preview.get_selected_face_ids()
        if not face_ids:
            QMessageBox.information(
                self, "Remove Person", "Select one or more face rectangles first.")
            return
        qmarks = ",".join(["?"] * len(face_ids))
        rows = self.conn.execute(
            f"SELECT face_id, assigned_person_id FROM face_boxes WHERE photo_id=? AND face_id IN ({qmarks})",
            (self.current.photo_id, *face_ids)
        ).fetchall()
        person_ids = {r["assigned_person_id"]
                      for r in rows if r["assigned_person_id"] is not None}

        self.conn.execute(
            f"UPDATE face_boxes SET assigned_person_id=NULL WHERE photo_id=? AND face_id IN ({qmarks})",
            (self.current.photo_id, *face_ids)
        )
        for pid in person_ids:
            self.conn.execute("""
                DELETE FROM photo_tags
                WHERE photo_id=? AND tag_type='person' AND tag_value=? AND source='propagated_cluster'
            """, (self.current.photo_id, str(pid)))
        self.conn.commit()

        self.preview.set_faces(fetch_faces_for_photo(
            self.conn, self.current.photo_id))
        self._emit_change()  # writes EXIF now
