# app/pipelines/metadata.py
from __future__ import annotations
from PIL import Image, ExifTags
from ..utils.exif import write_exif_datetime, write_xmp_people_sidecar

# Map EXIF tag names to IDs once
_EXIF_TAGS = {v: k for k, v in ExifTags.TAGS.items()}


def extract_exif_datetime(path: str) -> str | None:
    """
    Return EXIF DateTimeOriginal as 'YYYY:MM:DD HH:MM:SS' if present.
    """
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            if not exif:
                return None
            dto_tag = _EXIF_TAGS.get("DateTimeOriginal")
            if dto_tag in exif:
                val = exif.get(dto_tag)
                # Pillow often returns already as 'YYYY:MM:DD HH:MM:SS'
                if isinstance(val, str) and len(val) >= 19:
                    return val[:19]
    except Exception:
        return None
    return None


def writeback_high_confidence(db) -> int:
    changed = 0
    for row in db.iter_all():
        if row["inferred_date"] and (row["confidence"] or 0) >= 0.75:
            ok = write_exif_datetime(row["path"], row["inferred_date"])
            if ok:
                changed += 1
    return changed
