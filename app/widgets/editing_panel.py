# ===== FILE: app/widgets/editing_panel.py =====
from __future__ import annotations
from pathlib import Path
from PySide6 import QtCore, QtWidgets

from ..services import edit_ops


class EditingPanel(QtWidgets.QWidget):
    """Sidebar for per-photo edits. For now: Basic Enhance + Super Enhance."""

    def __init__(self, store):
        super().__init__()
        self.store = store
        self._item = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        self.title = QtWidgets.QLabel("Editing tools")
        self.title.setStyleSheet("font-weight:600;")
        layout.addWidget(self.title)

        self.basic_btn = QtWidgets.QPushButton("Basic Enhance")
        self.super_btn = QtWidgets.QPushButton("Super Enhance")
        self.status = QtWidgets.QLabel("")
        self.status.setWordWrap(True)

        layout.addWidget(self.basic_btn)
        layout.addWidget(self.super_btn)
        layout.addSpacing(8)
        layout.addWidget(self.status)
        layout.addStretch(1)

        self.basic_btn.clicked.connect(self._apply_basic)
        self.super_btn.clicked.connect(self._apply_super)

    def load_item(self, item):
        self._item = item
        self.status.setText(f"Selected: {Path(item.path).name}")

    def _apply_basic(self):
        if not self._item:
            return
        out_path, msg = edit_ops.basic_enhance(self._item.path)
        self._post_edit(out_path, msg)

    def _apply_super(self):
        if not self._item:
            return
        out_path, msg = edit_ops.super_enhance(self._item.path)
        self._post_edit(out_path, msg)

    def _post_edit(self, out_path: Path | None, msg: str):
        if out_path is None:
            self.status.setText(f"Edit failed: {msg}")
            return
        # Import the new image into library if not present and log it
        try:
            new_item = self.store.import_path(out_path)
            self.status.setText(f"Saved: {out_path.name}\n{msg}")
            # Optional: could emit a signal to refresh grids; main window periodically reloads
        except Exception as e:
            self.status.setText(f"Saved file but could not index: {e}")
