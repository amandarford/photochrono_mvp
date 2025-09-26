# PhotoChrono (MVP)
Local-first desktop app to help tag a small subset of photos with people and approximate dates, infer dates for the rest, do face clustering, and apply light, reversible enhancements. Built with PySide6 (Qt).

## Quick Start (macOS, Apple Silicon)
1) **Install system deps**
   - Install Homebrew if you don't have it: https://brew.sh
   - `brew install exiftool`  # for robust metadata write-back
   - (Optional) `brew install ffmpeg`  # for any future video support

2) **Create a virtual environment**
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

> If you hit build issues with `hdbscan`, try: `pip install cython` first, then `pip install hdbscan`. On Apple Silicon, set `export SYSTEM_VERSION_COMPAT=1` before pip-installing if needed.

3) **Run the app**
```bash
python -m app.main
```

4) **What works in this MVP**
- Import a folder to index file paths into a local SQLite DB
- Perceptual de-dup (pHash) placeholder
- Face detection/embedding *stubs* (replace with InsightFace ONNX models later)
- Clustering (HDBSCAN/DBSCAN) over embeddings (will operate on stubs unless you point to a real ONNX model)
- Active Tagging wizard UI (people & rough date ranges) — minimal
- Simple date inference ensemble (EXIF + FS date + guessed age range)
- Basic non-destructive “Enhance” (OpenCV: denoise, unsharp mask, gentle color balance)
- Metadata write-back via ExifTool (EXIF DateTimeOriginal, XMP PersonInImage) or XMP sidecars

5) **Next steps / Model hooks**
- Drop ONNX face embedding model under `models/face/` and set its path in Settings -> Models.
- Add Real-ESRGAN / GFPGAN binaries for higher-quality restoration (hooks exist in `app/pipelines/enhance.py`).

## Project layout
```
photochrono_mvp/
  README.md
  requirements.txt
  app/
    __init__.py
    main.py
    ui.py
    state.py
    utils/
      __init__.py
      db.py
      images.py
      exif.py
    pipelines/
      __init__.py
      face.py
      date_infer.py
      metadata.py
      enhance.py
  data/
    .gitkeep
  models/
    face/
      .gitkeep
```

## Notes
- This is a working scaffold with conservative defaults. Critical bits (face embeddings, advanced restoration) are wired but **not shipped** to keep the bundle light. You can plug in models later.
- The app writes an SQLite DB at `data/photochrono.db` and never overwrites originals. Enhancements export to a sibling `*_enhanced` file.
- Write-back uses sidecars by default for safety; switch to in-file EXIF once you’re confident.
