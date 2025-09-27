# app/main.py
from __future__ import annotations
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
import pathlib
import sys

# ---- macOS/Qt stability & DPI (must be set before importing PySide6) ----
import os
# layer-backed views; avoids Cocoa flush crashes
os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")   # crisp UI on Retina
# prevent mixing system Qt plugins
os.environ.pop("QT_PLUGIN_PATH", None)


# Support both "python -m app.main" and "python app/main.py"
try:
    from .ui_mainwindow import PhotoChronoWindow
except Exception:
    # Fallback when run as a script from repo root
    sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
    from app.ui_mainwindow import PhotoChronoWindow  # type: ignore


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("PhotoChrono")

    # Optional: set an app/window icon if you place an `icon.png` in app/
    icon_path = pathlib.Path(__file__).with_name("icon.png")
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    win = PhotoChronoWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
