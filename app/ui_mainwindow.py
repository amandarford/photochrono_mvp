# ===== FILE: app/ui_mainwindow.py =====
from __future__ import annotations
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets

from .widgets.grid_gallery import GridGallery
from .widgets.tagging_panel import TaggingPanel
from .widgets.editing_panel import EditingPanel
from .widgets.import_panel import ImportPanel
from .services.store import Store
from .services.metadata import writeback_metadata


class PhotoChronoWindow(QtWidgets.QMainWindow):
    """Main window with tabs: Library, Import, Cull, Editing, Logs.
    Left: main area (grid). Right: sidebar (tagging / editing).
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("PhotoChrono")
        self.resize(1280, 800)

        # Data store
        from pathlib import Path
        self.library_tags = TaggingPanel(db=self.store.db_path)

        # Tabs
        self.tabs = QtWidgets.QTabWidget()
        self.setCentralWidget(self.tabs)

        # --- Library tab
        self.library_split = QtWidgets.QSplitter()
        self.library_split.setOpaqueResize(False)
        self.library_grid = GridGallery(self.store, show_recent=False)
        self.library_tags = TaggingPanel(self.store)
        self.library_split.addWidget(self.library_grid)
        self.library_split.addWidget(self.library_tags)
        self.library_split.setStretchFactor(0, 4)
        self.library_split.setStretchFactor(1, 2)
        self.tabs.addTab(self.library_split, "Library")

        # --- Import tab
        self.import_split = QtWidgets.QSplitter()
        self.import_split.setOpaqueResize(False)
        self.import_panel = ImportPanel(self.store)
        self.import_grid = GridGallery(self.store, show_recent=True)
        self.import_tags = TaggingPanel(self.store)
        # In import we want toolbar on top + recent grid left; sidebar right
        import_container = QtWidgets.QWidget()
        import_layout = QtWidgets.QVBoxLayout(import_container)
        import_layout.setContentsMargins(0, 0, 0, 0)
        import_layout.addWidget(self.import_panel)
        import_layout.addWidget(self.import_grid)
        self.import_split.addWidget(import_container)
        self.import_split.addWidget(self.import_tags)
        self.import_split.setStretchFactor(0, 4)
        self.import_split.setStretchFactor(1, 2)
        self.tabs.addTab(self.import_split, "Import")

        # --- Cull tab (placeholder)
        self.cull_placeholder = QtWidgets.QLabel("Cull workspace coming soon.")
        self.cull_placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self.tabs.addTab(self.cull_placeholder, "Cull")

        # --- Editing tab
        self.edit_split = QtWidgets.QSplitter()
        self.edit_grid = GridGallery(self.store, show_recent=False)
        self.edit_panel = EditingPanel(self.store)
        self.edit_split.addWidget(self.edit_grid)
        self.edit_split.addWidget(self.edit_panel)
        self.edit_split.setStretchFactor(0, 4)
        self.edit_split.setStretchFactor(1, 2)
        self.tabs.addTab(self.edit_split, "Editing")

        # --- Logs tab (read-only text view)
        self.logs_view = QtWidgets.QPlainTextEdit()
        self.logs_view.setReadOnly(True)
        self.tabs.addTab(self.logs_view, "Logs")

        # Connections – selection drives sidebar content
        self.library_grid.selectionChanged.connect(self._on_selection_changed)
        self.import_grid.selectionChanged.connect(self._on_selection_changed)
        self.edit_grid.selectionChanged.connect(self._on_selection_changed)

        # Metadata writeback: any tag changes (manual or AI) trigger persist
        self.library_tags.tagChanged.connect(self._on_tag_changed)
        self.import_tags.tagChanged.connect(self._on_tag_changed)
        self.store.aiTagUpdated.connect(
            self._on_tag_changed)  # AI pipeline hook

        # Initial load
        self.refresh_views()

    # ---- Slots ----
    @QtCore.Slot(object)
    def _on_selection_changed(self, item):
        # Route selected item to the active sidebar
        sidebar = self._active_sidebar()
        if sidebar:
            sidebar.load_item(item)

    @QtCore.Slot(object)
    def _on_tag_changed(self, item):
        # Save to DB
        self.store.save_item(item)
        # Writeback to file metadata automatically
        ok, msg = writeback_metadata(item)
        if not ok:
            self._append_log(f"Writeback failed for {item.path}: {msg}")

    def _append_log(self, text: str):
        self.logs_view.appendPlainText(text)

    def _active_sidebar(self) -> Optional[QtWidgets.QWidget]:
        idx = self.tabs.currentIndex()
        if idx == self.tabs.indexOf(self.library_split):
            return self.library_tags
        if idx == self.tabs.indexOf(self.import_split):
            return self.import_tags
        if idx == self.tabs.indexOf(self.edit_split):
            return self.edit_panel
        return None

    def refresh_views(self):
        self.library_grid.reload()
        self.import_grid.reload()
        self.edit_grid.reload()
