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
    if path.lower().endswith(".dng"):
        import rawpy
        with rawpy.imread(path) as r:
            rgb = r.postprocess(half_size=True, gamma=(1, 1), no_auto_bright=True,
                                output_bps=16, use_camera_wb=True)
        return rgb[:, :, ::-1].copy(), "raw"
    return cv2.imread(path, cv2.IMREAD_COLOR), "jpeg"


def to_float255(img):
    return img.astype(np.float64) / (257.0 if img.dtype != np.uint8 else 1.0)


def det8(img):
    """Detection copy: percentile-normalized + gamma so linear raw works too."""
    g = cv2.cvtColor(img if img.dtype == np.uint8 else (img / 257).astype(np.uint8),
                     cv2.COLOR_BGR2GRAY).astype(np.float64)
    top = max(np.percentile(g, 99.5), 1)
    return (np.clip(g / top, 0, 1) ** 0.45 * 255).astype(np.uint8)


def detect(img8):
    corners, ids = reg.detect_multiscale(img8)
    return corners, (ids.ravel() if ids is not None else np.array([], int))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--size", default="640x1136")
    a = ap.parse_args()
    W, H = map(int, a.size.lower().split("x"))
    geo, s, q = generate.fiducial_geometry(W, H)
    pad = s + 2 * q
    outdir = os.path.join(a.folder, "processed")
    os.makedirs(outdir, exist_ok=True)
    rows = []
    for path in sorted(glob.glob(os.path.join(a.folder, "*"))):
        if not path.lower().endswith((".jpg", ".jpeg", ".dng", ".png", ".tif", ".tiff")):
            continue
        t0 = time.time()
        name = os.path.basename(path)
        try:
            img, klass = load(path)
        except Exception as e:
            rows.append((name, "?", "-", 0, f"load failed: {e}"))
            print(f"{name}  load failed: {e}", flush=True)
            continue
        if img is None:
            rows.append((name, klass, "-", 0, "unreadable"))
            continue
        corners, ids = detect(det8(img))
        fids = [int(i) // 4 for i in ids if int(i) < len(NAMES) * 4]
        if not fids:
            rows.append((name, klass, "-", 0, "no fiducials"))
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
            rows.append((name, klass, frame, n, "too few fiducials"))
            print(f"{name}  {klass:5s} {frame:8s} {n}/4  too few fiducials", flush=True)
            continue
        Hm, _ = cv2.findHomography(np.array(src, np.float32), np.array(dst, np.float32), cv2.RANSAC)
        warped = cv2.warpPerspective(img, Hm, (W, H))
        stem = f"{frame}-{klass}-{name.rsplit('.', 1)[0]}"
        cv2.imwrite(os.path.join(outdir, stem + ".reg.png"), warped)
        with open(os.path.join(outdir, stem + ".anchors.json"), "w") as f:
            json.dump(reg.anchors(warped, W, H), f)
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
        if frame == "split":
            lum = f255.mean(axis=2)[int(H * 0.3): int(H * 0.7)]  # avoid fiducial rows
            white = np.median(lum[:, int(W * 0.15): int(W * 0.35)])
            near = np.median(lum[:, int(W * 0.55): int(W * 0.65)])
            far = np.median(lum[:, int(W * 0.70): int(W * 0.80)])
            note += (f" glare white={white:.1f} blk_near={near:.2f} blk_far={far:.2f}"
                     f" veil={far / max(white, 1e-6) * 100:.2f}%")
        rows.append((name, klass, frame, n, note))
        print(f"{name}  {klass:5s} {frame:8s} {n}/4  {note}  ({time.time() - t0:.0f}s)", flush=True)
    print("\nDONE", len(rows), "files")


if __name__ == "__main__":
    main()
