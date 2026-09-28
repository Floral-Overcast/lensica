"""Try-a-look: preview a target rig's rendering on a personal photo.

Uses analysis/lookmatch.py's matrix model. A "look" is an affine colour matrix
learned from two rigs' spectrum captures of the same stimulus (A -> B). We cache
the matrix, then apply it to an uploaded sRGB photo.

Source-camera rule (project decision): read EXIF Model. If the upload came from
the look's profiled source rig, it is a true A->B mapping; otherwise we still
preview it but badge it "approximate — source camera not profiled". Uploaded
photos are session-only and deleted right after processing.
"""
import io
import os
import subprocess
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import lookmatch  # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "extract"))
import rignames  # noqa: E402  (canonical device display names)

CACHE = os.path.join(ROOT, "web", "cuts", "looks")
STIMULUS = (1640, 2360)

# Looks learned from the sample sessions. a_model = EXIF Model of the source rig.
LOOKS = [
    {"id": "xperia", "name": "Sony Xperia 1 IV rendering",
     "desc": "Sony's phone colour science and tone (learned A7C II → Xperia 1 IV).",
     "a_dir": "/srv/lensica/A7cii2/processed", "a_match": "SG-image",
     "b_dir": "/srv/lensica/xperia/processed", "b_match": "XQ-CT54",
     "a_model": "ILCE-7CM2"},
    {"id": "a7cii", "name": "Sony A7C II rendering",
     "desc": "Full-frame body look (learned Xperia 1 IV → A7C II).",
     "a_dir": "/srv/lensica/xperia/processed", "a_match": "XQ-CT54",
     "b_dir": "/srv/lensica/A7cii2/processed", "b_match": "SG-image",
     "a_model": "XQ-CT54"},
]


def list_looks():
    return [{"id": l["id"], "name": l["name"], "desc": l["desc"]}
            for l in LOOKS if _available(l)]


def _available(l):
    return (os.path.isdir(l["a_dir"]) and os.path.isdir(l["b_dir"])
            and bool(lookmatch.find(l["a_dir"], "spectrum", l["a_match"]))
            and bool(lookmatch.find(l["b_dir"], "spectrum", l["b_match"])))


def _get(look_id):
    for l in LOOKS:
        if l["id"] == look_id:
            return l
    return None


def get_matrix(look):
    """Fit (and cache) the affine colour matrix for a look."""
    os.makedirs(CACHE, exist_ok=True)
    mp = os.path.join(CACHE, f"{look['id']}.npy")
    if os.path.exists(mp):
        return np.load(mp)
    train = [(lookmatch.interior(ia, 4), lookmatch.interior(ib, 4))
             for pa in lookmatch.find(look["a_dir"], "spectrum", look["a_match"])
             if (ia := lookmatch.load_norm(pa)) is not None
             for pb in lookmatch.find(look["b_dir"], "spectrum", look["b_match"])
             if (ib := lookmatch.load_norm(pb)) is not None]
    if not train:
        raise RuntimeError("no overlapping spectrum frames for this look")
    M = lookmatch.fit_matrix(train)
    np.save(mp, M)
    return M


def exif_model(data):
    try:
        r = subprocess.run(["exiftool", "-s3", "-Model", "-LensModel", "-"],
                           input=data, capture_output=True, timeout=30)
        lines = [x.strip() for x in r.stdout.decode("ascii", "ignore").splitlines()]
        model = lines[0] if lines else ""
        lens = lines[1] if len(lines) > 1 else ""
        return model, lens
    except Exception:
        return "", ""


def _to_png_datauri(img_rgb01):
    bgr = (np.clip(img_rgb01[:, :, ::-1], 0, 1) * 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
    import base64
    return "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode()


def apply_look(look_id, data):
    """Return {before, after, profiled, model, lens, look} for an uploaded photo.

    before/after are JPEG data URIs. Session-only: caller keeps nothing.
    """
    look = _get(look_id)
    if look is None:
        raise ValueError("unknown look")
    model, lens = exif_model(data)
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode image")
    # cap the working size so preview stays snappy
    h, w = img.shape[:2]
    scale = min(1.0, 1400.0 / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    rgb = img[:, :, ::-1].astype(np.float64) / 255.0
    M = get_matrix(look)
    out = lookmatch.apply_matrix(M, rgb)
    profiled = bool(model) and model.strip().lower() == look["a_model"].lower()
    # profiled check uses the raw EXIF model above; the badge shows the friendly name
    return {"before": _to_png_datauri(rgb), "after": _to_png_datauri(out),
            "profiled": profiled, "model": rignames.rig_name(model, lens) or "unknown",
            "lens": lens, "look": look["name"]}
