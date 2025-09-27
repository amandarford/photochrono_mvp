# ===== FILE: app/widgets/grid_gallery.py =====
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import List

from PySide6 import QtCore, QtGui, QtWidgets

THUMB_SIZE = 160


@dataclass
class GalleryItem:
    id: int
    path: Path
    rating: int = 0
    flags: int = 0
    tags: dict | None = None


class GalleryModel(QtCore.QAbstractListModel):
    def __init__(self, items: List[GalleryItem] | None = None):
        super().__init__()
        self._items = items or []

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None
        item = self._items[index.row()]
        if role == QtCore.Qt.DecorationRole:
            pm = QtGui.QPixmap(str(item.path))
            if pm.isNull():
                # Placeholder icon
                pm = QtGui.QPixmap(THUMB_SIZE, THUMB_SIZE)
                pm.fill(QtGui.QColor("#222"))
            return pm.scaled(THUMB_SIZE, THUMB_SIZE, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
        if role == QtCore.Qt.ToolTipRole:
            return str(item.path)
        return None

    def rowCount(self, parent=QtCore.QModelIndex()):
        return len(self._items)

    # Helpers
    def set_items(self, items: List[GalleryItem]):
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def item_at(self, row: int) -> GalleryItem:
        return self._items[row]


class GridGallery(QtWidgets.QWidget):
    selectionChanged = QtCore.Signal(object)  # emits GalleryItem

    def __init__(self, store, show_recent=False):
        super().__init__()
        self.store = store
        self.show_recent = show_recent
        self.view = QtWidgets.QListView()
        self.view.setViewMode(QtWidgets.QListView.IconMode)
        self.view.setIconSize(QtCore.QSize(THUMB_SIZE, THUMB_SIZE))
        self.view.setResizeMode(QtWidgets.QListView.Adjust)
        self.view.setSpacing(12)
        self.view.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)

        self.model = GalleryModel([])
        self.view.setModel(self.model)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        # Simple toolbar with a search box and size slider
        toolbar = QtWidgets.QHBoxLayout()
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("Search filename or tag…")
        self.size_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.size_slider.setRange(96, 384)
        self.size_slider.setValue(THUMB_SIZE)
        self.size_slider.valueChanged.connect(self._on_size)
        toolbar.addWidget(self.search)
        toolbar.addWidget(QtWidgets.QLabel("Thumb Size"))
        toolbar.addWidget(self.size_slider)
        layout.addLayout(toolbar)
        layout.addWidget(self.view)

        self.view.selectionModel().selectionChanged.connect(self._on_selection)
        self.search.textChanged.connect(self._apply_search)

    def reload(self):
        items = self.store.load_recent() if self.show_recent else self.store.load_all()
        self.model.set_items(items)

    def _on_selection(self):
        idxs = self.view.selectedIndexes()
        if not idxs:
            return
        item = self.model.item_at(idxs[0].row())
        self.selectionChanged.emit(item)

    def _apply_search(self, text: str):
        # naive client-side filter for now
        all_items = self.store.load_recent() if self.show_recent else self.store.load_all()
        text_low = text.lower()
        filtered = [i for i in all_items if text_low in str(i.path).lower() or any(
            text_low in (str(v).lower()) for v in (i.tags or {}).values())]
        self.model.set_items(filtered)

    def _on_size(self, value: int):
        self.view.setIconSize(QtCore.QSize(value, value))
