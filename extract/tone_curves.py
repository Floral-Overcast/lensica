#!/usr/bin/env python3
"""Extract per-channel response curves from a REGISTERED tone-frame capture.

Reads the known tone-frame layout (see generate.tone): four ramp bands
(Y, R, G, B), 21 gray steps, four level blocks. For each stimulus level it
samples the safe interior of the corresponding region and takes the median,
so blur, moire and fiducials don't contaminate.

Output JSON profile fragment:
  gray_steps: 21 x {stim, rgb}          # from the step patches
  ramps: {Y|R|G|B: 256 x [r,g,b]}       # median response per stimulus level
  levels: {0|16|235|255: rgb}           # broadcast blocks

usage: tone_curves.py <registered.png> --out profile/  [--tag raw|jpeg]
"""
import argparse
import json
import os

import cv2
import numpy as np


def med(img, x0, y0, x1, y1):
    """Median RGB of a region, shrunk 30% to a safe interior."""
    dx, dy = int((x1 - x0) * 0.15), int((y1 - y0) * 0.15)
    r = img[y0 + dy : y1 - dy, x0 + dx : x1 - dx]
    return np.median(r.reshape(-1, 3), axis=0)


def extract(img):
    h, w = img.shape[:2]
    band = h // 8
    # fiducial pads occupy the frame corners; sample each ramp band's central
    # 40% of rows and skip x inside the pad width (same formula as
    # generate.fiducial_geometry)
    s = max(80, min(w, h) // 14)
    pad = s + 2 * (s // 4)
    ramps = {}
    for bi, name in enumerate("YRGB"):
        y0 = bi * band + int(band * 0.3)
        y1 = bi * band + int(band * 0.7)
        rows = img[y0:y1].astype(np.float64)
        resp = np.zeros((256, 3))
        for v in range(256):
            # stimulus ramp: value v occupies x where x*255//(w-1) == v
            xs = np.arange(w)[(np.arange(w) * 255 // (w - 1)) == v]
            xs = xs[(xs > pad) & (xs < w - pad)]
            if len(xs) == 0:
                resp[v] = np.nan
            else:
                resp[v] = np.median(rows[:, xs].reshape(-1, 3), axis=0)
        # fill any gaps by interpolation
        for c in range(3):
            col = resp[:, c]
            bad = np.isnan(col)
            if bad.any():
                col[bad] = np.interp(np.flatnonzero(bad), np.flatnonzero(~bad), col[~bad])
        ramps[name] = resp
    y0 = 4 * band
    steps = []
    for i in range(21):
        v = round(i * 255 / 20)
        rgb = med(img, i * w // 21, y0, (i + 1) * w // 21, y0 + 2 * band)
        steps.append({"stim": v, "rgb": [round(float(x), 2) for x in rgb]})
    y1 = 6 * band
    levels = {}
    for i, v in enumerate((0, 16, 235, 255)):
        levels[str(v)] = [round(float(x), 2) for x in med(img, i * w // 4, y1, (i + 1) * w // 4, h)]
    return {
        "gray_steps": steps,
        "ramps": {k: np.round(v, 2).tolist() for k, v in ramps.items()},
        "levels": levels,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("registered")
    ap.add_argument("--out", default="profile")
    ap.add_argument("--tag", default="raw", choices=["raw", "jpeg"])
    a = ap.parse_args()
    img = cv2.imread(a.registered, cv2.IMREAD_UNCHANGED)
    if img.dtype != np.uint8:
        img = (img.astype(np.float64) / 257.0)
    img = img[:, :, ::-1]  # BGR -> RGB
    prof = extract(np.asarray(img, dtype=np.float64))
    os.makedirs(a.out, exist_ok=True)
    path = os.path.join(a.out, f"tone-{a.tag}.json")
    with open(path, "w") as f:
        json.dump(prof, f)
    print(path)


if __name__ == "__main__":
    main()
