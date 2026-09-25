"""Benchy looks demo: the CC0 3DBenchy photo rendered through each profiled
rig's measured colour mapping.

Method mirrors /Sata/temp/benchy_looks.py (Matthew's reference): an affine
colour matrix fitted from the rig's spectrum-frame capture vs the known sRGB
stimulus we generated, then gain-aligned to the source so what you see is
colour and tone shape, not exposure. Matrix-only for now; tone / sharpening
layers come later.

The source is an unprofiled sRGB photo, so this is an honest approximation of
each rig's colour rendering, not a true A->B mapping. Images are pre-rendered
once and cached under web/cuts/benchy/ (gitignored); served as ~1400px jpegs.
"""
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "target", "generators"))
import generate  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import lookmatch  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "extract"))
import rignames  # noqa: E402  (canonical device display names)

SRC = "/Sata/temp/benchy-v45.jpg"
CACHE = os.path.join(ROOT, "web", "cuts", "benchy")
STIM_W, STIM_H = 1640, 2360      # stimulus size the rigs were captured against
MAXPX = 1400                     # serve ~1400px jpegs
JPEG_Q = 88
CREDIT = "3DBenchy by Creative Tools, CC0"
NOTE = ("These are measured colour mappings (matrix-only for now; tone and "
        "sharpening layers to come) applied to an unprofiled source photo, so "
        "treat them as an honest approximation of each rig's colour rendering.")

# Each rig: its processed-capture dir, the EXIF match string, and the raw
# Model/LensModel we feed rignames for the canonical display name. Order is the
# order shown in the switcher.
RIGS = [
    {"slug": "a7cii-sg", "dir": "/Sata/temp/A7cii2/processed",
     "match": "SG-image", "model": "ILCE-7CM2", "lens": "SG-image 35mm F2.2 FE"},
    {"slug": "s25u", "dir": "/Sata/temp/s25u-ipad/processed",
     "match": "Galaxy S25", "model": "Galaxy S25 Ultra", "lens": ""},
    {"slug": "xperia", "dir": "/Sata/temp/xperia/processed",
     "match": "XQ-CT54", "model": "XQ-CT54", "lens": ""},
    {"slug": "iphone5s", "dir": "/Sata/temp/Iphone 5s/processed",
     "match": "iPhone 5s", "model": "iPhone 5s",
     "lens": "iPhone 5s back camera 4.15mm f/2.2"},
    {"slug": "dsct7", "dir": "/Sata/temp/cybershot DSC-T7/processed",
     "match": "DSC-T7", "model": "DSC-T7", "lens": ""},
]

_LOOKS = None  # memoised metadata list, built on first request


def _name(rig):
    return rignames.rig_name(rig["model"], rig["lens"])


def _save(path, rgb01):
    bgr = (np.clip(rgb01[:, :, ::-1], 0, 1) * 255).astype(np.uint8)
    cv2.imwrite(path, bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])


def _render(rig, src_img, stim_i):
    """Fit the rig's colour matrix from its spectrum capture, apply + gain-align
    to the source. Returns rgb01 or None if the rig has no usable capture."""
    caps = [im for p in lookmatch.find(rig["dir"], "spectrum", rig["match"])
            if (im := lookmatch.load_norm(p)) is not None]
    if not caps:
        return None
    M = lookmatch.fit_matrix([(stim_i, lookmatch.interior(caps[0], 4))])
    out = lookmatch.apply_matrix(M, src_img)
    g = src_img.mean() / max(out.mean(), 1e-6)
    return np.clip(out * g, 0, 1)


def _build():
    """Render original + every available rig once into CACHE. Idempotent."""
    if not os.path.exists(SRC):
        return []
    os.makedirs(CACHE, exist_ok=True)

    src = cv2.imread(SRC, cv2.IMREAD_COLOR)
    if src is None:
        return []
    h, w = src.shape[:2]
    scale = min(1.0, float(MAXPX) / max(h, w))
    if scale < 1.0:
        src = cv2.resize(src, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    src_rgb = src[:, :, ::-1].astype(np.float64) / 255.0

    stim = np.asarray(generate.spectrum(STIM_W, STIM_H), np.float64)[:, :, :3] / 255.0
    stim_i = lookmatch.interior(stim, 4)

    looks = [{"slug": "original", "name": "Original (CC0)"}]
    _save(os.path.join(CACHE, "original.jpg"), src_rgb)
    for rig in RIGS:
        try:
            out = _render(rig, src_rgb, stim_i)
        except Exception:
            out = None
        if out is None:
            continue
        _save(os.path.join(CACHE, f"{rig['slug']}.jpg"), out)
        looks.append({"slug": rig["slug"], "name": _name(rig)})
    return looks


def looks():
    """Metadata for the switcher: [{slug, name}, ...], original first.
    Builds the cache on first call; cheap on subsequent calls."""
    global _LOOKS
    if _LOOKS is not None:
        return _LOOKS
    # already-cached fast path: files present, no re-render needed
    if os.path.exists(os.path.join(CACHE, "original.jpg")):
        out = [{"slug": "original", "name": "Original (CC0)"}]
        for rig in RIGS:
            if os.path.exists(os.path.join(CACHE, f"{rig['slug']}.jpg")):
                out.append({"slug": rig["slug"], "name": _name(rig)})
        _LOOKS = out
        return out
    _LOOKS = _build()
    return _LOOKS


def image_path(slug):
    """Absolute path to a cached jpeg, or None. Builds cache if missing."""
    looks()  # ensure built
    p = os.path.join(CACHE, os.path.basename(slug) + ".jpg")
    return p if os.path.exists(p) else None
