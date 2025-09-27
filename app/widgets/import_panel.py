# ===== FILE: app/widgets/import_panel.py =====
from pathlib import Path
from PySide6 import QtCore, QtWidgets


class ImportPanel(QtWidgets.QWidget):
    """Top bar for the Import tab: choose folder, import, show counts."""

    def __init__(self, store):
        super().__init__()
        self.store = store
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.choose_btn = QtWidgets.QPushButton("Add Folder…")
        self.count_label = QtWidgets.QLabel("")
        layout.addWidget(self.choose_btn)
        layout.addStretch(1)
        layout.addWidget(self.count_label)

        self.choose_btn.clicked.connect(self._choose_folder)
        self._update_counts()

    def _choose_folder(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "Choose folder to import")
        if not path:
            return
        new_count = self.store.import_folder(Path(path))
        self._update_counts()
        QtWidgets.QMessageBox.information(
            self, "Import complete", f"Imported {new_count} new files.")

    def _update_counts(self):
        self.count_label.setText(
            f"{self.store.count_all()} photos in library · {self.store.count_recent()} recent")
