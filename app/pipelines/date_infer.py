from __future__ import annotations
from ..utils.db import DB
import datetime as dt


def _unix_to_date_str(unix_str: str | None) -> str | None:
    if not unix_str:
        return None
    try:
        ts = int(unix_str)
        d = dt.datetime.fromtimestamp(ts)
        return d.strftime("%Y:%m:%d %H:%M:%S")
    except Exception:
        return None


class DateInfer:
    def __init__(self, db: DB):
        self.db = db

    def run_inference(self) -> tuple[int, int]:
        total, accepted = 0, 0
        for row in self.db.iter_all():
            total += 1
            # Very simple heuristic:
            exif = row["exif_date"]
            fs = _unix_to_date_str(row["fs_date"])
            inferred = exif or fs or "1990:07:01 12:00:00"  # fallback mid-1990 as placeholder
            conf = 0.9 if exif else (0.6 if fs else 0.3)
            self.db.update_inferred(row["id"], inferred, conf)
            if conf >= 0.75:
                accepted += 1
        return total, accepted
