# app/pipelines/enhance.py

try:
    from ..utils.logger import app_logger as _logbus

    def _logmsg(msg: str):
        _logbus.log(msg)

except Exception:

    def _logmsg(msg: str):
        print(msg)


import os, cv2, numpy as np, pathlib, requests
from ..utils.images import unsharp_mask, auto_white_balance

import urllib.request, urllib.error, time

REALESRGAN_URLS = [
    "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.1/RealESRGAN_x2plus.pth",
    "https://huggingface.co/dtarnow/UPscaler/resolve/main/RealESRGAN_x2plus.pth",
    "https://huggingface.co/2kpr/Real-ESRGAN/resolve/main/RealESRGAN_x2plus.pth",
]
GFP_GAN_URLS = [
    "https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.4.pth",
    "https://huggingface.co/gmk123/GFPGAN/resolve/main/GFPGANv1.4.pth",
    "https://huggingface.co/datasets/Gourieff/ReActor/resolve/main/models/facerestore_models/GFPGANv1.4.pth",
]


def _ensure_file_multi(urls, out_path, max_retries=2):
    if os.path.exists(out_path):
        return
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    last_err = None
    for url in urls:
        for attempt in range(1, max_retries + 1):
            try:
                _logmsg(f"[weights] downloading: {url}")
                with urllib.request.urlopen(url, timeout=60) as r, open(out_path, "wb") as f:
                    while True:
                        chunk = r.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                _logmsg(f"[weights] saved: {out_path}")
                return
            except Exception as e:
                last_err = e
                time.sleep(min(1.5 * attempt, 5))
    raise RuntimeError(f"Failed to fetch {out_path} from any mirror: {last_err}")


def _weights_dir():
    return os.path.join(pathlib.Path.home(), ".cache", "photochrono", "weights")


def _clahe_lab(img):
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8))
    l2 = clahe.apply(l)
    lab2 = cv2.merge([l2, a, b])
    return cv2.cvtColor(lab2, cv2.COLOR_LAB2BGR)


def quick_enhance(path: str, strength: float = 0.35) -> str | None:
    """
    Conservative, reversible: light denoise -> AWB -> CLAHE -> light sharpen.
    strength in [0..1] roughly scales sharpening.
    """
    if not os.path.exists(path):
        return None
    img = cv2.imread(path)
    if img is None:
        return None

    # light chroma-preserving denoise
    denoised = cv2.fastNlMeansDenoisingColored(img, None, 2, 2, 7, 15)

    # gentle white balance
    wb = auto_white_balance(denoised)

    # local contrast (very mild)
    local = _clahe_lab(wb)

    # subtle unsharp (scale with strength)
    amount = 0.4 * strength + 0.2  # 0.2..0.6
    sharp = unsharp_mask(local, amount=amount, sigma=1.0, threshold=2)

    root, ext = os.path.splitext(path)
    out = f"{root}_enhanced{ext}"
    cv2.imwrite(out, sharp)
    return out


def super_enhance(
    path: str, scale: int = 2, face_restore: bool = True, tile: int = 0
) -> str | None:
    if not os.path.exists(path):
        return None

    # ---- Shim for newer torchvision (keep this if you already added it) ----
    import sys, types

    try:
        import torchvision.transforms.functional_tensor as _ft  # noqa: F401
    except Exception:
        import torchvision.transforms.functional as _F

        shim = types.ModuleType("torchvision.transforms.functional_tensor")

        def _rgb_to_grayscale(img, num_output_channels: int = 1):
            return _F.rgb_to_grayscale(img, num_output_channels)

        shim.rgb_to_grayscale = _rgb_to_grayscale
        sys.modules["torchvision.transforms.functional_tensor"] = shim
    # -----------------------------------------------------------------------

    import torch
    from realesrgan import RealESRGANer
    from basicsr.archs.rrdbnet_arch import RRDBNet
    from gfpgan import GFPGANer

    # Pick device: prefer MPS, else CPU
    if torch.backends.mps.is_available():
        device = torch.device("mps")
        # let unsupported ops fall back to CPU
        try:
            torch.backends.mps.allow_fallback(True)
        except Exception:
            pass
    else:
        device = torch.device("cpu")

    wdir = _weights_dir()
    sr_w = os.path.join(wdir, "RealESRGAN_x2plus.pth")
    gfp_w = os.path.join(wdir, "GFPGANv1.4.pth")

    _ensure_file_multi(REALESRGAN_URLS, sr_w)
    if face_restore:
        _ensure_file_multi(GFP_GAN_URLS, gfp_w)

    # Build ESRGAN model (x2)
    model = RRDBNet(
        num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=scale
    )

    # Half precision is not stable on MPS; keep False
    upsampler = RealESRGANer(
        scale=scale,
        model_path=sr_w,
        model=model,
        tile=tile,  # try 256 or 128 if you see OOM
        tile_pad=10,
        pre_pad=0,
        half=False,
        device=device,
    )

    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        return None

    if face_restore:
        restorer = GFPGANer(
            model_path=gfp_w,
            upscale=scale,
            arch="clean",
            channel_multiplier=2,
            bg_upsampler=upsampler,
            device=device,
        )
        _, _, restored = restorer.enhance(
            img, has_aligned=False, only_center_face=False, paste_back=True
        )
        out_img = restored
    else:
        out_img, _ = upsampler.enhance(img, outscale=scale)

    root, _ = os.path.splitext(path)
    out = f"{root}_super.png"
    cv2.imwrite(out, out_img)
    return out
