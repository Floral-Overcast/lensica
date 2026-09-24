#!/usr/bin/env python3
"""Warp a capture back into stimulus pixel space using the corner ArUco
fiducials. Works on 8-bit or 16-bit input; detection runs on an 8-bit copy,
the warp runs on the original bit depth.

usage: register.py <capture.tif|jpg|png> --frame tone --size 3024x1964
                   [--out <capture>.reg.png]
"""
import argparse
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "target", "generators"))
import generate  # noqa: E402


def register(img, frame, w, h, min_markers=3):
    """img: BGR array any depth. Returns (warped stimulus-space image, n_markers)."""
    img8 = img if img.dtype == np.uint8 else (img.astype(np.float32) / 257.0).astype(np.uint8)
    gray = cv2.cvtColor(img8, cv2.COLOR_BGR2GRAY)
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    det = cv2.aruco.ArucoDetector(d, cv2.aruco.DetectorParameters())
    corners, ids, _ = det.detectMarkers(gray)
    if ids is None:
        raise RuntimeError("no fiducials found (too dark, too blurred, or markers cropped out)")
    geo, _, _ = generate.fiducial_geometry(w, h)
    base = generate.FRAME_IDS[frame] * 4
    src, dst = [], []
    for c, i in zip(corners, ids.ravel()):
        k = int(i) - base
        if 0 <= k < 4:
            src.extend(c.reshape(4, 2))
            dst.extend(geo[k])
    n = len(src) // 4
    if n < min_markers:
        raise RuntimeError(f"only {n} of 4 '{frame}' fiducials found, need >= {min_markers}")
    H, _ = cv2.findHomography(np.array(src, np.float32), np.array(dst, np.float32), cv2.RANSAC)
    return cv2.warpPerspective(img, H, (w, h)), n


def anchors(warped, w, h):
    """Per-corner white/black references from the fiducials themselves:
    white = median of the quiet-zone ring (stimulus 255), black = 10th
    percentile inside the marker (stimulus 0). Lets any frame be normalized
    against display brightness / exposure without trusting absolute levels."""
    geo, s, q = generate.fiducial_geometry(w, h)
    out = {}
    for k, pts in geo.items():
        x, y = pts[0]
        pad = warped[y - q : y + s + q, x - q : x + s + q].reshape(-1, warped.shape[2] if warped.ndim == 3 else 1)
        marker = warped[y : y + s, x : x + s].reshape(-1, warped.shape[2] if warped.ndim == 3 else 1)
        ring_mask = np.ones((s + 2 * q, s + 2 * q), bool)
        ring_mask[q : q + s, q : q + s] = False
        ring = warped[y - q : y + s + q, x - q : x + s + q][ring_mask]
        out[str(k)] = {
            "white": np.median(ring.reshape(-1, ring.shape[-1] if ring.ndim > 1 else 1), axis=0).tolist(),
            "black": np.percentile(marker, 10, axis=0).tolist(),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("capture")
    ap.add_argument("--frame", required=True, choices=list(generate.FRAME_IDS))
    ap.add_argument("--size", required=True, help="stimulus WxH, e.g. 3024x1964")
    ap.add_argument("--out")
    a = ap.parse_args()
    w, h = map(int, a.size.lower().split("x"))
    img = cv2.imread(a.capture, cv2.IMREAD_UNCHANGED)
    if img is None:
        sys.exit(f"cannot read {a.capture}")
    warped, n = register(img, a.frame, w, h)
    out = a.out or a.capture.rsplit(".", 1)[0] + ".reg.png"
    cv2.imwrite(out, warped)
    import json
    apath = out.rsplit(".", 1)[0] + ".anchors.json"
    with open(apath, "w") as f:
        json.dump({"fiducials_found": n, "corners_bgr": anchors(warped, w, h)}, f, indent=2)
    print(f"{out}  ({n}/4 fiducials)  + {os.path.basename(apath)}")


if __name__ == "__main__":
    main()
