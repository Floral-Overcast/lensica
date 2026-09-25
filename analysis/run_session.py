#!/usr/bin/env python3
"""Batch-process a capture session folder (v0).

Auto-identifies each shot's frame from its ArUco ids (id // 4 = frame id),
registers it into stimulus space, writes .reg.png + .anchors.json into
<folder>/processed/, and runs the frame-specific extraction that exists so
far (tone curves, split-frame veiling glare, Laplacian sharpness for all).
DNG = raw class (rawpy, linear, half-size), JPG = jpeg class.

usage: run_session.py <folder> [--size 640x1136]
"""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "target", "generators"))
sys.path.insert(0, os.path.join(ROOT, "extract"))
import generate  # noqa: E402
import register as reg  # noqa: E402
import tone_curves  # noqa: E402

NAMES = {v: k for k, v in generate.FRAME_IDS.items()}


def load(path):
    ext = path.lower().rsplit(".", 1)[-1]
    if ext in ("dng", "arw"):
        import rawpy

        def post(p):
            with rawpy.imread(p) as r:
                return r.postprocess(half_size=True, gamma=(1, 1), no_auto_bright=True,
                                     output_bps=16, use_camera_wb=True)
        try:
            rgb = post(path)
            return rgb[:, :, ::-1].copy(), "raw"
        except Exception:
            pass
        # Samsung's camera app sometimes corrupts the DNG raw stream in-camera
        # (LibRaw: "data corrupted at ..."). dnglab "decodes" those to plausible
        # garbage, so don't try — salvage the embedded full-res camera JPEG,
        # which Samsung writes separately and survives intact (jpeg class)
        # Samsung stores the full-res JPEG under the DNG's PreviewImage tag
        # (JpgFromRaw is empty on these files) — 8160x4592, decodes clean.
        for tag in ("-PreviewImage", "-JpgFromRaw"):
            out = subprocess.run(["exiftool", "-b", tag, path], capture_output=True)
            if len(out.stdout) > 10000:
                arr = cv2.imdecode(np.frombuffer(out.stdout, np.uint8), cv2.IMREAD_COLOR)
                if arr is not None:
                    return arr, "jpeg-preview"
        raise RuntimeError("raw stream corrupt, no usable embedded preview")
    return cv2.imread(path, cv2.IMREAD_COLOR), "jpeg"


def exif_meta(path):
    r = subprocess.run(["exiftool", "-S", "-Model", "-LensModel", "-FNumber",
                        "-ExposureTime", "-ISO", path], capture_output=True, text=True)
    return dict(l.split(": ", 1) for l in r.stdout.splitlines() if ": " in l)


def to_float255(img):
    return img.astype(np.float64) / (257.0 if img.dtype != np.uint8 else 1.0)


def det8(img):
    """Detection copy: percentile-normalized + gamma so linear raw works too."""
    g = cv2.cvtColor(img if img.dtype == np.uint8 else (img / 257).astype(np.uint8),
                     cv2.COLOR_BGR2GRAY).astype(np.float64)
    top = max(np.percentile(g, 99.5), 1)
    return (np.clip(g / top, 0, 1) ** 0.45 * 255).astype(np.uint8)


def detect(img):
    """Plain grayscale first (right for jpeg/display-referred), then the
    normalized+gamma copy (needed for dark linear raw). Keep the better."""
    plain = cv2.cvtColor(img if img.dtype == np.uint8 else (img / 257).astype(np.uint8),
                         cv2.COLOR_BGR2GRAY)
    best = ([], np.array([], int))
    for g in (plain, det8(img)):
        corners, ids = reg.detect_multiscale(g)
        if ids is not None and len(ids) > len(best[1]):
            best = (corners, ids.ravel())
        if len(best[1]) >= 4:
            break
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--size", default="640x1136")
    ap.add_argument("--glob", default="*", help="filename filter, e.g. '20260924_21*'")
    a = ap.parse_args()
    W, H = map(int, a.size.lower().split("x"))
    geo, s, q = generate.fiducial_geometry(W, H)
    pad = s + 2 * q
    outdir = os.path.join(a.folder, "processed")
    os.makedirs(outdir, exist_ok=True)
    rows, skipped = [], []
    for path in sorted(glob.glob(os.path.join(a.folder, a.glob))):
        if not path.lower().endswith((".jpg", ".jpeg", ".dng", ".arw", ".png", ".tif", ".tiff")):
            continue
        t0 = time.time()
        name = os.path.basename(path)
        try:
            img, klass = load(path)
        except Exception as e:
            skipped.append((name, f"load failed: {e}"))
            print(f"{name}  load failed: {e}", flush=True)
            continue
        if img is None:
            skipped.append((name, "unreadable"))
            continue
        corners, ids = detect(img)
        fids = [int(i) // 4 for i in ids if int(i) < len(NAMES) * 4]
        if not fids:
            skipped.append((name, "no fiducials"))
            print(f"{name}  {klass:5s} ---      0/4  no fiducials", flush=True)
            continue
        fid = int(np.bincount(fids).argmax())
        frame = NAMES[fid]
        src, dst = [], []
        for c, i in zip(corners, ids):
            k = int(i) - fid * 4
            if 0 <= k < 4:
                src.extend(c.reshape(4, 2))
                dst.extend(geo[k])
        n = len(src) // 4
        if n < 3:
            m = exif_meta(path)
            rows.append({"file": name, "stem": "", "klass": klass, "frame": frame,
                         "n": n, "sharp": 0.0, "amb": False,
                         "lens": m.get("LensModel") or m.get("Model") or ""})
            print(f"{name}  {klass:5s} {frame:8s} {n}/4  too few fiducials", flush=True)
            continue
        Hm, _ = cv2.findHomography(np.array(src, np.float32), np.array(dst, np.float32), cv2.RANSAC)
        warped = cv2.warpPerspective(img, Hm, (W, H))
        stem = f"{frame}-{klass}-{name.rsplit('.', 1)[0]}"
        cv2.imwrite(os.path.join(outdir, stem + ".reg.png"), warped)
        with open(os.path.join(outdir, stem + ".anchors.json"), "w") as f:
            json.dump(reg.anchors(warped, W, H), f)
        meta = exif_meta(path)
        with open(os.path.join(outdir, stem + ".meta.json"), "w") as f:
            json.dump(meta, f)
        g8 = warped if warped.dtype == np.uint8 else (warped / 257).astype(np.uint8)
        sharp = cv2.Laplacian(cv2.cvtColor(g8, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
        note = f"sharp={sharp:.0f}"
        f255 = to_float255(warped)
        if frame == "tone":
            prof = tone_curves.extract(f255[:, :, ::-1])
            with open(os.path.join(outdir, stem + ".tone.json"), "w") as f:
                json.dump(prof, f)
            gs = prof["gray_steps"]
            note += (f" tone black={np.mean(gs[0]['rgb']):.1f}"
                     f" mid={np.mean(gs[10]['rgb']):.1f} white={np.mean(gs[20]['rgb']):.1f}")
        if frame == "points":
            # ambient/validity floor: the frame is black field + sparse dots, so
            # the median IS the background; high floor = lights on, white
            # borders, or other user improvisation -> PSF/glare tails invalid
            bg = np.median(f255[int(H * 0.25):int(H * 0.75),
                                int(W * 0.25):int(W * 0.75)].mean(axis=2))
            wt = np.mean([np.mean(c["white"]) for c in
                          reg.anchors(warped, W, H).values()]) / (
                257.0 if warped.dtype != np.uint8 else 1.0)
            amb = bg / max(wt, 1e-6) * 100
            note += f" amb={amb:.2f}%" + (" AMBIENT-SUSPECT" if amb > 2.0 else "")
        if frame == "split":
            lum = f255.mean(axis=2)[int(H * 0.3): int(H * 0.7)]  # avoid fiducial rows
            white = np.median(lum[:, int(W * 0.15): int(W * 0.35)])
            near = np.median(lum[:, int(W * 0.55): int(W * 0.65)])
            far = np.median(lum[:, int(W * 0.70): int(W * 0.80)])
            note += (f" glare white={white:.1f} blk_near={near:.2f} blk_far={far:.2f}"
                     f" veil={far / max(white, 1e-6) * 100:.2f}%")
        rows.append({"file": name, "stem": stem, "klass": klass, "frame": frame,
                     "n": n, "sharp": sharp, "amb": "AMBIENT-SUSPECT" in note,
                     "lens": meta.get("LensModel") or meta.get("Model") or ""})
        lens = meta.get("LensModel", "")[:24]
        print(f"{name}  {klass:5s} {frame:8s} {n}/4  {lens:24s} f/{meta.get('FNumber','?')}"
              f" {meta.get('ExposureTime','?')}s ISO{meta.get('ISO','?')}  {note}"
              f"  ({time.time() - t0:.0f}s)", flush=True)

    # take selection: multiple shots of the same frame get ranked, best wins,
    # repeatable-measure frames (flat/split) keep every clean take for
    # averaging, bad takes are marked rejected with a reason
    manifest = {}
    for key in sorted({(r["lens"], r["klass"], r["frame"]) for r in rows}):
        takes = [r for r in rows if (r["lens"], r["klass"], r["frame"]) == key]
        clean = [r for r in takes if r["n"] >= 3 and not r["amb"]]
        clean.sort(key=lambda r: (r["n"], r["sharp"]), reverse=True)
        entry = []
        for r in takes:
            if r in clean:
                if key[2] in ("flat", "split"):
                    status = "use"  # average all clean takes
                else:
                    status = "best" if r is clean[0] else "backup"
            else:
                status = ("rejected: ambient light" if r["amb"]
                          else f"rejected: {r['n']}/4 markers")
            entry.append({"file": r["file"], "stem": os.path.basename(r["stem"]),
                          "n": r["n"], "sharp": round(r["sharp"], 1),
                          "status": status})
        manifest["|".join(key)] = entry
        if len(entry) > 1:
            summ = ", ".join(f"{e['file']}={e['status'].split(':')[0]}" for e in entry)
            print(f"  select {key[2]}-{key[1]} ({key[0][:18]}): {summ}", flush=True)
    if skipped:
        manifest["_unassigned"] = [{"file": n, "status": f"rejected: {r}"}
                                   for n, r in skipped]
    with open(os.path.join(outdir, "session.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    print(f"\nDONE {len(rows) + len(skipped)} files; "
          "take selection in processed/session.json")


if __name__ == "__main__":
    main()
