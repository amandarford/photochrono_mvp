# app/ui_tagging.py
from PySide6.QtWidgets import (QWidget, QDockWidget, QListView, QLabel, QPushButton,
                               QLineEdit, QComboBox, QDateTimeEdit, QHBoxLayout, QVBoxLayout)
from PySide6.QtCore import Qt, QDateTime

class TaggingPanel(QDockWidget):
    def __init__(self, db, parent=None):
        super().__init__("Tagging", parent)
        self.db = db
        self._init_ui()

    def _init_ui(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        self.peopleBox = QComboBox()  # populated from people table + MRU
        self.newPerson = QLineEdit(); self.newPerson.setPlaceholderText("Add new person…")
        self.addPersonBtn = QPushButton("Add")
        self.dateEdit = QDateTimeEdit(QDateTime.currentDateTime()); self.dateEdit.setCalendarPopup(True)
        self.copyPrevBtn = QPushButton("Use previous date")

        layout.addWidget(self.peopleBox)
        row = QHBoxLayout(); row.addWidget(self.newPerson); row.addWidget(self.addPersonBtn)
        layout.addLayout(row)
        layout.addWidget(QLabel("Date/Time"))
        layout.addWidget(self.dateEdit)
        layout.addWidget(self.copyPrevBtn)

        self.applyFaceBtn = QPushButton("Apply to face")
        self.applyPhotoBtn = QPushButton("Apply to all faces in photo")
        self.applyClusterBtn = QPushButton("Apply to cluster")
        self.applyDupesBtn = QPushButton("Apply to duplicates")

        layout.addWidget(self.applyFaceBtn)
        layout.addWidget(self.applyPhotoBtn)
        layout.addWidget(self.applyClusterBtn)
        layout.addWidget(self.applyDupesBtn)

        self.setWidget(w)

        # Connect signals (save tag → call propagation function)
        self.addPersonBtn.clicked.connect(self._add_person)
        self.copyPrevBtn.clicked.connect(self._copy_prev_date)
        # …wire up apply buttons to handlers

    # def _add_person(self): insert into people; refresh combo
    # def _copy_prev_date(self): load prior tagged date for convenience
