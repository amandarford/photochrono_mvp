from __future__ import annotations
from pathlib import Path
from typing import Tuple
from PIL import Image
import piexif
import json
import sqlite3

# Optional HEIC support
try:
    import pillow_heif  # type: ignore
    pillow_heif.register_heif_opener()
except Exception:
    pass


def _open_conn(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def fetch_people_and_date(conn: sqlite3.Connection, photo_id: int) -> Tuple[list[str], str | None]:
    """Return (people_names, iso_date) for a given photo_id from photo_tags."""
    # People
    people_rows = conn.execute("""
        SELECT p.display_name
        FROM photo_tags pt
        JOIN people p ON pt.tag_type='person'
                      AND CAST(pt.tag_value AS INTEGER)=p.person_id
        WHERE pt.photo_id=?
    """, (photo_id,)).fetchall()
    people = [r["display_name"] for r in people_rows]

    # Date
    date_row = conn.execute("""
        SELECT tag_value
        FROM photo_tags
        WHERE photo_id=? AND tag_type='date'
        ORDER BY created_at DESC
        LIMIT 1
    """, (photo_id,)).fetchone()
    iso_date = date_row["tag_value"] if date_row else None
    return people, iso_date


def writeback_metadata(item, db_path: str | Path = "data/photochrono.db") -> Tuple[bool, str]:
    """
    Persist tags back into the image file using EXIF fields where possible.

    - Title   -> 0th.ImageDescription
    - Date    -> Exif.DateTimeOriginal
    - People  -> JSON inside UserComment
    - Keywords, rating, color, notes -> also in UserComment JSON
    """
    path = Path(item.path)
    try:
        img = Image.open(path)
        exif = piexif.load(img.info.get("exif", b"")) if img.info.get("exif") else {
            "0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None
        }

        # Connect to DB to get people + date
        conn = _open_conn(db_path)
        people, date_val = fetch_people_and_date(conn, item.photo_id)

        tags = item.tags or {}

        # 1) Title
        if "title" in tags:
            exif["0th"][piexif.ImageIFD.ImageDescription] = tags["title"].encode(
                "utf-8", "ignore")

        # 2) Date
        if date_val:
            # EXIF requires YYYY:MM:DD HH:MM:SS
            exif_date = f"{date_val.replace('-', ':')} 00:00:00"
            exif["Exif"][piexif.ExifIFD.DateTimeOriginal] = exif_date.encode(
                "utf-8")

        # 3) UserComment JSON
        payload = {
            "people": people,
            "keywords": tags.get("keywords", []),
            "rating": int(tags.get("rating", 0)),
            "color": tags.get("color", "None"),
            "notes": tags.get("notes", ""),
            "date": date_val or tags.get("date", ""),
        }
        exif["Exif"][piexif.ExifIFD.UserComment] = (
            "UNICODE\x00" + json.dumps(payload)
        ).encode("utf-16le")

        exif_bytes = piexif.dump(exif)
        img.save(path, exif=exif_bytes)
        return True, ""
    except Exception as e:
        return False, str(e)
