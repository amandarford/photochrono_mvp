# app/main.py
import os, pathlib, PySide6
os.environ.setdefault("QT_MAC_WANTS_LAYER", "1")           # layer-backed NSViews (fixes flush crashes)
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
from PySide6.QtCore import QCoreApplication

qt = pathlib.Path(PySide6.__file__).parent / "Qt"
plugins = qt / "plugins"
frameworks = qt / "lib"

os.environ["QT_QPA_PLATFORM"] = "cocoa"
QCoreApplication.addLibraryPath(str(plugins))
os.environ["DYLD_FRAMEWORK_PATH"] = str(frameworks)
os.environ["DYLD_LIBRARY_PATH"] = str(frameworks)

from PySide6.QtWidgets import 
from .ui import PhotoChronoWindow


def main():
    app = ([])
    win = PhotoChronoWindow()
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
