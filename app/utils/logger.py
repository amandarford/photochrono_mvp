# app/utils/logger.py
from PySide6.QtCore import QObject, Signal, QDateTime


class AppLogger(QObject):
    message = Signal(str)

    def log(self, text: str) -> None:
        ts = QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        self.message.emit(f"[{ts}] {text}")


# Singleton instance you can import anywhere
app_logger = AppLogger()
