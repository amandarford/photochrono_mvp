# app/main.py
from __future__ import annotations

# ---- macOS/Qt stability & DPI (must be set before importing PySide6) ----
import os
os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")          # layer-backed views; avoids Cocoa flush crashes
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")   # crisp UI on Retina
os.environ.pop("QT_PLUGIN_PATH", None)                    # prevent mixing system Qt plugins

import sys
import pathlib

# Support both "python -m app.main" and "python app/main.py"
try:
    from .ui import PhotoChronoWindow
except Exception:
    sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
    from app.ui import PhotoChronoWindow  # type: ignore

from PySide6.QtWidgets import QApplication


def main() -> None:
    app = QApplication(sys.argv)
    win = PhotoChronoWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
