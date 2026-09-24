#!/usr/bin/env python3
"""One-time: find the best 6144x6144 square in source/done.png, export it as the
Target v1 master square. 6144 covers every Apple display dimension (max width =
Pro Display XDR 6016). Search on an 8x-reduced copy, verify finalists full-res.

Run from the repo root on cloud (~4GB free RAM, ~5 min).
"""
import hashlib
import json
import time

import numpy as np
from PIL import Image, ImageFilter

SRC = "source/done.png"
OUT_PNG = "target/master/master-square-v1.png"
OUT_JSON = "target/master/master-square-v1.json"
SIDE = 6144
RED = 8
WR = SIDE // RED      # window side in reduced px
STRIDE = 64           # reduced px = 512 full-res px
FINALISTS = 8

Image.MAX_IMAGE_PIXELS = None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def integral(a):
    return np.pad(a, ((1, 0), (1, 0))).cumsum(0, dtype=np.float64).cumsum(1)


def winsum(ii, y, x, s):
    return ii[y + s, x + s] - ii[y, x + s] - ii[y + s, x] + ii[y, x]


def cube_bins(rgb):
    r = rgb[:, :, 0].astype(np.int32)
    g = rgb[:, :, 1].astype(np.int32)
    b = rgb[:, :, 2].astype(np.int32)
    return (r >> 3) * 1024 + (g >> 3) * 32 + (b >> 3)


def main():
    t0 = time.time()
    im = Image.open(SRC)
    im.load()
    print(f"loaded {im.size} in {time.time()-t0:.0f}s")

    a = np.asarray(im.reduce(RED).convert("RGB"), dtype=np.uint8)
    rh, rw = a.shape[:2]
    bins = cube_bins(a)
    # reduction averages extremes inward, so use looser clip thresholds here
    clip = ((a <= 4) | (a >= 251)).any(axis=2).astype(np.float64)
    luma = a @ np.array([0.2126, 0.7152, 0.0722])
    blur = np.asarray(
        Image.fromarray(luma.astype(np.uint8)).filter(ImageFilter.GaussianBlur(2)),
        dtype=np.float64,
    )
    hp2 = (luma - blur) ** 2
    ii_clip, ii_hp2 = integral(clip), integral(hp2)
    ii_l, ii_l2 = integral(luma), integral(luma**2)

    rows = []
    n = WR * WR
    for y in range(0, rh - WR + 1, STRIDE):
        for x in range(0, rw - WR + 1, STRIDE):
            cov = len(np.unique(bins[y : y + WR, x : x + WR]))
            cl = winsum(ii_clip, y, x, WR) / n
            hp = np.sqrt(winsum(ii_hp2, y, x, WR) / n)
            m = winsum(ii_l, y, x, WR) / n
            v = max(winsum(ii_l2, y, x, WR) / n - m * m, 0)
            rows.append((y, x, cov, cl, hp, np.sqrt(v)))
    r = np.array(rows)
    print(f"scored {len(r)} windows in {time.time()-t0:.0f}s")

    def z(c):
        return (c - c.mean()) / (c.std() + 1e-9)

    score = z(r[:, 2]) + 0.5 * z(r[:, 4]) + 0.5 * z(r[:, 5]) - 1.5 * z(r[:, 3])

    picked = []
    for i in np.argsort(-score):
        y, x = r[i, 0], r[i, 1]
        if all(abs(y - py) >= WR // 2 or abs(x - px) >= WR // 2 for py, px in picked):
            picked.append((y, x))
        if len(picked) == FINALISTS:
            break

    best = None
    for y, x in picked:
        fx, fy = int(x) * RED, int(y) * RED
        c = np.asarray(im.crop((fx, fy, fx + SIDE, fy + SIDE)).convert("RGB"), dtype=np.uint8)
        cov = len(np.unique(cube_bins(c))) / 32768
        cl = float(((c <= 2) | (c >= 253)).any(axis=2).mean())
        lstd = float((c @ np.array([0.2126, 0.7152, 0.0722])).std())
        s = cov - 1.5 * cl + 0.3 * (lstd / 128)
        print(f"finalist ({fx:5d},{fy:5d}): coverage={cov:.1%} clip={cl:.1%} lumastd={lstd:.0f} -> {s:.3f}")
        if best is None or s > best["score"]:
            best = {"score": s, "x": fx, "y": fy, "coverage": cov, "clip": cl, "luma_std": lstd}

    print(f"winner: ({best['x']},{best['y']})")
    im.crop((best["x"], best["y"], best["x"] + SIDE, best["y"] + SIDE)).convert("RGB").save(OUT_PNG)
    meta = {
        "target_version": "v1",
        "frame": "master-square",
        "side_px": SIDE,
        "source_file": SRC,
        "source_sha256": sha256(SRC),
        "crop_origin_xy": [best["x"], best["y"]],
        "full_res_stats": {k: best[k] for k in ("coverage", "clip", "luma_std", "score")},
        "master_sha256": sha256(OUT_PNG),
        "note": "colorspace sRGB 8-bit; display 1:1 only, never scaled",
    }
    with open(OUT_JSON, "w") as f:
        json.dump(meta, f, indent=2)
    print(f"wrote {OUT_PNG} + provenance, total {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
