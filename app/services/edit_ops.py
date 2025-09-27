# ===== FILE: app/services/edit_ops.py =====
from __future__ import annotations
from pathlib import Path
from typing import Tuple

# Try to use your existing pipelines if available
try:
    # Example: from .pipelines.enhance import basic_enhance, super_enhance
    from ..pipelines.enhance import basic_enhance as repo_basic, super_enhance as repo_super  # type: ignore
except Exception:
    repo_basic = None
    repo_super = None

from PIL import Image, ImageFilter, ImageOps

OUT_SUFFIX_BASIC = "_basic"
OUT_SUFFIX_SUPER = "_super"


def _derive_path(src: Path, suffix: str) -> Path:
    stem = src.stem
    ext = src.suffix or ".jpg"
    return src.with_name(f"{stem}{suffix}{ext}")


def basic_enhance(src: Path) -> Tuple[Path | None, str]:
    """Light-touch enhancement. Uses repo pipeline if present, else Pillow fallback."""
    src = Path(src)
    if repo_basic:
        try:
            out = _derive_path(src, OUT_SUFFIX_BASIC)
            repo_basic(src, out)  # type: ignore
            return out, "(repo basic)"
        except Exception as e:
            return None, f"repo basic failed: {e}"

    try:
        img = Image.open(src).convert("RGB")
        # Auto contrast + modest sharpening
        img = ImageOps.autocontrast(img, cutoff=1)
        img = img.filter(ImageFilter.UnsharpMask(
            radius=1.2, percent=120, threshold=3))
        out = _derive_path(src, OUT_SUFFIX_BASIC)
        img.save(out, quality=92)
        return out, "Auto-contrast + sharpen"
    except Exception as e:
        return None, str(e)


def super_enhance(src: Path) -> Tuple[Path | None, str]:
    """Heavier pass. Uses repo pipeline if present, else upscale + noise reduction + sharpen."""
    src = Path(src)
    if repo_super:
        try:
            out = _derive_path(src, OUT_SUFFIX_SUPER)
            repo_super(src, out)  # type: ignore
            return out, "(repo super)"
        except Exception as e:
            return None, f"repo super failed: {e}"

    try:
        img = Image.open(src).convert("RGB")
        # 1) Gentle denoise
        img = img.filter(ImageFilter.MedianFilter(size=3))
        # 2) Upscale 1.5x for a crisper look, then down to original if desired
        w, h = img.size
        img = img.resize((int(w * 1.5), int(h * 1.5)),
                         Image.Resampling.LANCZOS)
        # 3) Local contrast (unsharp-like) + mild clarity
        img = img.filter(ImageFilter.UnsharpMask(
            radius=1.6, percent=140, threshold=2))
        out = _derive_path(src, OUT_SUFFIX_SUPER)
        img.save(out, quality=94)
        return out, "Denoise + upscale + sharpen"
    except Exception as e:
        return None, str(e)
