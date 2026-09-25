"""Session upload validation + ingestion.

Uploads are stored under UPLOAD_ROOT/<session-id>/ (a shared fleet-visible drop
folder), then analysis/run_session.py is run on the folder and its per-shot
output is parsed into structured verdicts for the page. Test-chart uploads are
KEPT (project storage decision).

Hard validation before anything touches disk: extension whitelist, size cap,
and decode-or-reject (images via OpenCV/Pillow, raw via an exiftool format
sniff). Nothing uploaded is ever executed.
"""
import json
import os
import re
import subprocess
import uuid

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_ROOT = "/Sata/temp/lensica-uploads"

ALLOWED = {"jpg", "jpeg", "png", "tif", "tiff", "dng", "arw"}
RAW_EXT = {"dng", "arw"}
RAW_FILETYPES = {"DNG", "ARW", "TIFF", "TIF"}
SIZE_CAP = 80 * 1024 * 1024  # 80 MB / file

SIZES = ["1640x2360", "1206x2622", "1320x2868", "3024x1964", "2560x1600", "640x1136"]
DEFAULT_SIZE = "1640x2360"

_SAFE = re.compile(r"[^A-Za-z0-9._-]")


def safe_name(name):
    base = os.path.basename(name or "file")
    base = _SAFE.sub("_", base).lstrip(".") or "file"
    return base[:120]


def _exiftool_filetype(data):
    try:
        r = subprocess.run(["exiftool", "-s3", "-FileType", "-"], input=data,
                           capture_output=True, timeout=30)
        return r.stdout.decode("ascii", "ignore").strip().upper()
    except Exception:
        return ""


def validate(filename, data):
    """Return (ok: bool, reason: str). Decode-or-reject, no execution."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in ALLOWED:
        return False, f"extension .{ext or '?'} not allowed"
    if len(data) == 0:
        return False, "empty file"
    if len(data) > SIZE_CAP:
        return False, f"{len(data) // (1024 * 1024)}MB exceeds 80MB cap"
    if ext in RAW_EXT:
        ft = _exiftool_filetype(data)
        if ft not in RAW_FILETYPES:
            return False, f"not a valid raw file (sniffed {ft or 'unknown'})"
        return True, "raw ok"
    # image: must actually decode
    arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if arr is None:
        try:
            from PIL import Image
            import io
            Image.open(io.BytesIO(data)).verify()
            return True, "image ok"
        except Exception:
            return False, "does not decode as an image"
    return True, "image ok"


def new_session():
    sid = uuid.uuid4().hex[:12]
    folder = os.path.join(UPLOAD_ROOT, sid)
    os.makedirs(folder, exist_ok=True)
    return sid, folder


def session_folder(sid):
    if not re.fullmatch(r"[0-9a-f]{12}", sid or ""):
        return None
    folder = os.path.join(UPLOAD_ROOT, sid)
    return folder if os.path.isdir(folder) else None


# ---- session manifest + device photo ----
# The device photo is a snapshot of the rig itself (taken with any other
# device), weak verification + a public visual. Stored beside the capture files
# as device-photo.<ext> and recorded in session.json so a profile built from
# this session can use it as the entry thumbnail.
MANIFEST = "session.json"
PHOTO_EXT = {"jpg", "jpeg", "png", "tif", "tiff"}  # a real photo, not a raw file


def read_manifest(folder):
    path = os.path.join(folder, MANIFEST)
    if os.path.isfile(path):
        try:
            return json.load(open(path))
        except Exception:
            pass
    return {}


def write_manifest(folder, **fields):
    man = read_manifest(folder)
    man.update({k: v for k, v in fields.items() if v is not None})
    with open(os.path.join(folder, MANIFEST), "w") as f:
        json.dump(man, f, indent=2)
    return man


def save_device_photo(folder, filename, data):
    """Validate + store a rig snapshot as device-photo.<ext>. Returns
    (ok, reason, stored_name). Photos only (no raw), same hard checks."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if ext not in PHOTO_EXT:
        return False, "device photo must be jpg/png/tiff", None
    ok, reason = validate(filename, data)
    if not ok:
        return False, reason, None
    stored = "device-photo." + ext
    with open(os.path.join(folder, stored), "wb") as out:
        out.write(data)
    return True, "ok", stored


def device_photo_path(folder):
    for ext in PHOTO_EXT:
        p = os.path.join(folder, "device-photo." + ext)
        if os.path.isfile(p):
            return p
    return None


# ---- run_session streaming + parsing ----
_COUNT = re.compile(r"(\S+)\s+(\d)/4")
_KLASS = re.compile(r"\b(raw|jpeg-preview|jpeg)\b")


def parse_line(line):
    """Turn one run_session stdout line into a verdict dict, or None."""
    line = line.rstrip("\n")
    if not line.strip() or line.startswith("DONE"):
        return None
    name = line.split()[0]
    if "load failed" in line or "unreadable" in line:
        return {"name": name, "frame": "?", "markers": 0, "ok": False,
                "note": line.split("  ", 1)[-1].strip(),
                "hint": "File did not decode. Re-export or re-shoot."}
    m = _COUNT.search(line)
    if not m:
        return {"name": name, "frame": "?", "markers": 0, "ok": False,
                "note": line, "hint": ""}
    frame = m.group(1)
    n = int(m.group(2))
    km = _KLASS.search(line)
    klass = km.group(1) if km else "?"
    note = line[m.end():].strip()
    ok = n >= 3 and frame not in ("---", "?")
    hint = _hint(frame, n, note, ok)
    return {"name": name, "frame": frame if frame != "---" else "unidentified",
            "klass": klass, "markers": n, "ok": ok, "note": note, "hint": hint}


def _hint(frame, n, note, ok):
    if n == 0:
        return ("No markers found. Get all four corner fiducials fully in frame, "
                "square to the screen, and confirm the display is showing a Lensica frame.")
    if n < 3:
        return ("Only %d/4 markers. Move back a touch so every corner marker is "
                "inside the frame with margin." % n)
    if frame == "points":
        # sharpness lives in note as sharp=NNN
        sm = re.search(r"sharp=(\d+)", note)
        if sm and int(sm.group(1)) < 40:
            return ("Points frame looks soft. Use the focus-lock trick: acquire focus "
                    "on the previous bright frame, lock it, then cycle to points "
                    "without refocusing.")
    return "Looks good."


def run_session_cmd(folder, size):
    if not re.fullmatch(r"\d{3,4}x\d{3,4}", size or ""):
        size = DEFAULT_SIZE
    return ["python3", "-u", os.path.join(ROOT, "analysis", "run_session.py"),
            folder, "--size", size]
