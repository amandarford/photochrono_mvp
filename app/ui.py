# app/ui.py
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QFileDialog,
    QMessageBox,
    QVBoxLayout,
    QPushButton,
    QLabel,
    QTabWidget,
    QListWidget,
    QProgressBar,
    QPlainTextEdit,
    QHBoxLayout,
)
from PySide6.QtCore import QThread, Signal, Qt
import os

from .ui_tagging import TaggingPanel  # Tagging dock

from .utils.logger import app_logger
from .utils.db import DB
from .state import AppState
from .pipelines.date_infer import DateInfer
from .pipelines.face import FaceIndexer
from .pipelines.enhance import quick_enhance, super_enhance
from .pipelines.metadata import extract_exif_datetime, writeback_high_confidence
from .utils.exif import write_exif_datetime


class ImportThread(QThread):
    progress = Signal(int, int)
    done = Signal(int)

    def __init__(self, db: DB, folder: str):
        super().__init__()
        self.db = db
        self.folder = folder

    def run(self):
        count = 0
        filepaths = []
        for root, _, files in os.walk(self.folder):
            for f in files:
                path = os.path.join(root, f)
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".bmp")):
                    filepaths.append(path)

        total = len(filepaths)
        app_logger.log(f"Import: found {total} candidate files.")

        for i, path in enumerate(filepaths, start=1):
            try:
                self.db.insert_photo_if_absent(path)
                exif_dt = extract_exif_datetime(path)
                if exif_dt:
                    row = self.db.find_by_path(path)
                    if row:
                        self.db.update_exif_date(row["id"], exif_dt)
            except Exception as e:
                app_logger.log(
                    f"Import error on {os.path.basename(path)}: {e}")

            self.progress.emit(i, total)
            count += 1

        self.done.emit(count)


class PhotoChronoWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PhotoChrono (MVP)")
        self.resize(1100, 700)

        self.db = DB("data/photochrono.db")
        self.state = AppState()
        self.date_infer = DateInfer(self.db)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self._build_import_tab()
        self._build_tagging_tab()
        self._build_timeline_tab()
        self._build_enhance_tab()
        self._build_writeback_tab()
        self._build_logs_tab()

        # --- Tagging dock (menu toggled or via button) ---
        self.tagDock = TaggingPanel(db="data/photochrono.db", parent=self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.tagDock)
        self.tagDock.hide()  # start hidden

        # --- Menu action (still available if you want it) ---
        self.taggingAct = self.menuBar().addAction("Tagging…")
        self.taggingAct.setShortcut("Ctrl+T")
        self.taggingAct.triggered.connect(self.toggle_tagging_panel)

    # ----------------- Import Tab -----------------
    def _build_import_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        self.import_btn = QPushButton("Import Folder…")
        self.import_btn.clicked.connect(self._choose_folder)
        self.progress = QProgressBar()
        self.import_list = QListWidget()

        lay.addWidget(QLabel("Import & Index"))
        lay.addWidget(self.import_btn)
        lay.addWidget(self.progress)
        lay.addWidget(self.import_list)

        self.tabs.addTab(w, "Import")

    def _choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Folder")
        if not folder:
            return
        self._log(f"Import: selected folder: {folder}")
        self.import_thread = ImportThread(self.db, folder)
        self.import_thread.progress.connect(self._on_import_progress)
        self.import_thread.done.connect(self._on_import_done)
        self.progress.setValue(0)
        self.import_thread.start()

    def _on_import_progress(self, i, total):
        self.progress.setMaximum(total)
        self.progress.setValue(i)
        if i == 1 or i == total or i % 50 == 0:
            self._log(f"Import progress: {i}/{total}")

    def _on_import_done(self, count):
        self._log(f"Import finished. {count} photos processed.")
        self.import_list.addItem(f"Imported {count} photos.")
        QMessageBox.information(self, "Import", f"Imported {count} photos.")

    # ----------------- Tagging Tab -----------------
    def _build_tagging_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        lay.addWidget(QLabel("Tagging"))

        btn_open = QPushButton("Open Tagging Panel")
        btn_open.clicked.connect(self.open_tagging_panel)
        lay.addWidget(btn_open)

        btn_index = QPushButton("Run Face Index (stub embeddings)")
        btn_index.clicked.connect(self._run_face_index)
        lay.addWidget(btn_index)

        self.tabs.addTab(w, "Tagging")

    def open_tagging_panel(self):
        if not self.tagDock.isVisible():
            self.tagDock.show()
        self.tagDock.raise_()
        self.tagDock.activateWindow()

    def _run_face_index(self):
        indexer = FaceIndexer(self.db)
        n = indexer.index()
        QMessageBox.information(
            self, "Face Index", f"Indexed faces/embeddings for {n} photos (stub).")

    # ----------------- Timeline Tab -----------------
    def _build_timeline_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        btn = QPushButton("Infer Dates")
        btn.clicked.connect(self._infer_dates)
        self.timeline_label = QLabel("No timeline yet.")
        self.timeline_label.setWordWrap(True)

        lay.addWidget(QLabel("Timeline / Date Inference"))
        lay.addWidget(btn)
        lay.addWidget(self.timeline_label)

        self.tabs.addTab(w, "Timeline")

    def _infer_dates(self):
        self._log("Date inference started…")
        n, accepted = self.date_infer.run_inference()
        self._log(
            f"Date inference finished. Inferred: {n}, high-confidence accepted: {accepted}.")
        self.timeline_label.setText(
            f"Inferred dates for {n} photos. Accepted high-confidence: {accepted}")

    # ----------------- Enhance Tab -----------------
    def _build_enhance_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        lay.addWidget(QLabel("Enhance Options"))

        btn_gentle = QPushButton("Enhance sample (gentle)")
        btn_gentle.clicked.connect(self._enhance_sample_gentle)
        lay.addWidget(btn_gentle)

        btn_super = QPushButton("Super Enhance sample (AI, x2 + face restore)")
        btn_super.clicked.connect(self._enhance_sample_super)
        lay.addWidget(btn_super)

        self.tabs.addTab(w, "Enhance")

    def _enhance_sample_gentle(self):
        rows = self.db.list_photos(limit=5)
        self._log(f"Gentle enhance: processing {len(rows)} photos…")
        out = 0
        for r in rows:
            try:
                new_path = quick_enhance(r["path"], strength=0.25)
                if new_path:
                    out += 1
                    self._log(
                        f"Gentle enhanced → {os.path.basename(new_path)}")
            except Exception as e:
                self._log(f"Enhance (gentle) error: {e}")
        QMessageBox.information(
            self, "Enhance", f"Gentle enhanced {out} photos (wrote *_enhanced.png).")

    def _enhance_sample_super(self):
        rows = self.db.list_photos(limit=5)
        self._log(f"Super enhance: processing {len(rows)} photos…")
        out = 0
        errs = 0
        for r in rows:
            try:
                new_path = super_enhance(
                    r["path"], scale=2, face_restore=True, tile=256)
                if new_path:
                    out += 1
                    self._log(f"Super enhanced → {os.path.basename(new_path)}")
            except Exception as e:
                errs += 1
                self._log(f"Super Enhance error: {e}")
        QMessageBox.information(
            self, "Super Enhance", f"AI enhanced {out} photos (wrote *_super.png). Errors: {errs}")

    # ----------------- Write-back Tab -----------------
    def _build_writeback_tab(self):
        w = QWidget()
        lay = QVBoxLayout(w)

        btn = QPushButton("Write Back EXIF/XMP (high-confidence only)")
        btn.clicked.connect(self._writeback)
        lay.addWidget(QLabel("Metadata Write-back"))
        lay.addWidget(btn)

        btn_all = QPushButton("Write ALL inferred dates (unsafe)")
        btn_all.clicked.connect(self._writeback_all)
        lay.addWidget(btn_all)

        self.tabs.addTab(w, "Write-back")

    def _writeback(self):
        self._log("Write-back (high-confidence) started…")
        changed = writeback_high_confidence(self.db)
        self._log(f"Write-back complete. Updated {changed} photos.")
        QMessageBox.information(
            self, "Write-back", f"Wrote metadata for {changed} photos (>= threshold).")

    def _writeback_all(self):
        self._log("Write-back (ALL inferred) started…")
        changed = 0
        for row in self.db.iter_all():
            if row["inferred_date"]:
                if write_exif_datetime(row["path"], row["inferred_date"]):
                    changed += 1
        self._log(f"Write-back (ALL) complete. Updated {changed} photos.")
        QMessageBox.information(self, "Write-back (ALL)",
                                f"Wrote metadata for {changed} photos.")

    # ----------------- Tagging Dock Toggle -----------------
    def toggle_tagging_panel(self):
        if self.tagDock.isVisible():
            self.tagDock.hide()
        else:
            self.tagDock.show()
            self.tagDock.raise_()
            self.tagDock.activateWindow()

    # ----------------- Logs -----------------
    def _build_logs_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)

        bar = QHBoxLayout()
        btn_clear = QPushButton("Clear")
        btn_copy = QPushButton("Copy All")
        btn_clear.clicked.connect(self.log_view.clear)
        btn_copy.clicked.connect(lambda: self._copy_logs_to_clipboard())
        bar.addWidget(btn_clear)
        bar.addWidget(btn_copy)
        bar.addStretch(1)

        v.addWidget(QLabel("Application Logs"))
        v.addLayout(bar)
        v.addWidget(self.log_view)

        app_logger.message.connect(self._append_log)

        self.tabs.addTab(w, "Logs")

    def _append_log(self, line: str):
        self.log_view.appendPlainText(line)
        self.statusBar().showMessage(line, 5000)

    def _copy_logs_to_clipboard(self):
        self.log_view.selectAll()
        self.log_view.copy()
        cursor = self.log_view.textCursor()
        cursor.clearSelection()
        self.log_view.setTextCursor(cursor)

    def _log(self, msg: str):
        app_logger.log(msg)
