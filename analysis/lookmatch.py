#!/usr/bin/env python3
"""v0 look transfer: learn rig A -> rig B color/tone mapping from their
registered captures of the SAME stimulus frames, validate on held-out frames.

Both captures are anchored to their own fiducial white/black references
(display-relative units), so exposure and display brightness cancel; what the
model learns is the difference in RENDERING - color science, tone curve, white
balance policy - which is the shareable "look".

Findings from the first real pair (A7CII+SG jpeg -> Xperia 1 IV, 2026-09-24):
- default model = affine 3x4 color matrix; robust from sparse data
- a 33^3 LUT from ONE spectrum shot covers ~13% of the cube and the
  diffusion fill invents hues on held-out frames -> needs multi-page
  spectrum captures before --model lut is trustworthy
- tone frames poison training (gray-heavy, mixed clipping) - excluded
- per-pixel RMS is dominated by sharpness/noise/registration, not color;
  judge with the gain-aligned + smoothed numbers and the side-by-sides

usage: lookmatch.py --a-dir <processed> --b-dir <processed> --a-match SG-image
                    --b-match XQ-CT54 --size 1640x2360 [--out looks/a2b]
                    [--model matrix|lut] [--field]
"""
import argparse
import glob
import json
import os

import cv2
import numpy as np

N = 33  # LUT lattice
MARGIN = 220  # skip fiducial corners


def find(d, frame, match):
    out = []
    for p in sorted(glob.glob(os.path.join(d, f"{frame}-jpeg-*.reg.png"))):
        mp = p[:-8] + ".meta.json"
        meta = json.load(open(mp)) if os.path.exists(mp) else {}
        ident = (meta.get("LensModel") or "") + " " + (meta.get("Model") or "")
        if match.lower() in ident.lower():
            out.append(p)
    return out


def load_norm(path):
    """Registered capture -> display-relative float RGB [0,1], anchored to its
    own fiducial white/black."""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        return None
    a = json.load(open(path[:-8] + ".anchors.json"))
    corners = a.get("corners_bgr", a)
    white = np.mean([c["white"] for c in corners.values()], axis=0)
    black = np.mean([c["black"] for c in corners.values()], axis=0)
    f = (img.astype(np.float64) - black) / np.maximum(white - black, 1.0)
    return np.clip(f[:, :, ::-1], 0, 1)  # RGB


def interior(img, ds):
    c = img[MARGIN:-MARGIN, MARGIN:-MARGIN]
    return cv2.resize(c, (c.shape[1] // ds, c.shape[0] // ds),
                      interpolation=cv2.INTER_AREA)


def build_lut(pairs):
    """pairs: list of (A_norm, B_norm) same-size RGB float images."""
    ssum = np.zeros((N, N, N, 3))
    cnt = np.zeros((N, N, N))
    for a, b in pairs:
        ai = np.clip((a * (N - 1)).round().astype(int), 0, N - 1).reshape(-1, 3)
        bv = b.reshape(-1, 3)
        idx = ai[:, 0] * N * N + ai[:, 1] * N + ai[:, 2]
        for ch in range(3):
            ssum.reshape(-1, 3)[:, ch] += np.bincount(idx, weights=bv[:, ch],
                                                      minlength=N ** 3)
        cnt.reshape(-1)[:] += np.bincount(idx, minlength=N ** 3)
    lut = np.zeros((N, N, N, 3))
    filled = cnt > 4
    lut[filled] = ssum[filled] / cnt[filled][:, None]
    # fill holes by diffusion from filled neighbors
    for _ in range(N * 2):
        holes = ~filled
        if not holes.any():
            break
        k = np.zeros_like(cnt)
        s = np.zeros_like(lut)
        for ax in range(3):
            for sh in (1, -1):
                fm = np.roll(filled, sh, axis=ax)
                lm = np.roll(lut, sh, axis=ax)
                edge = [slice(None)] * 3
                edge[ax] = 0 if sh == 1 else N - 1
                fm[tuple(edge)] = False
                k += fm
                s += lm * fm[..., None]
        upd = holes & (k > 0)
        lut[upd] = s[upd] / k[upd][:, None]
        filled = filled | upd
    return lut, float((cnt > 4).mean())


def apply_lut(lut, img):
    """Trilinear interpolation of the 33^3 LUT over an RGB [0,1] image."""
    x = np.clip(img, 0, 1) * (N - 1)
    i0 = np.floor(x).astype(int)
    i1 = np.minimum(i0 + 1, N - 1)
    f = (x - i0)[..., None]
    out = np.zeros_like(img)
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    r1, g1, b1 = i1[..., 0], i1[..., 1], i1[..., 2]
    fr, fg, fb = f[..., 0, :], f[..., 1, :], f[..., 2, :]
    out = (lut[r0, g0, b0] * (1 - fr) * (1 - fg) * (1 - fb)
           + lut[r1, g0, b0] * fr * (1 - fg) * (1 - fb)
           + lut[r0, g1, b0] * (1 - fr) * fg * (1 - fb)
           + lut[r0, g0, b1] * (1 - fr) * (1 - fg) * fb
           + lut[r1, g1, b0] * fr * fg * (1 - fb)
           + lut[r1, g0, b1] * fr * (1 - fg) * fb
           + lut[r0, g1, b1] * (1 - fr) * fg * fb
           + lut[r1, g1, b1] * fr * fg * fb)
    return out


def rms(a, b):
    return float(np.sqrt(((a - b) ** 2).mean()) * 255)


def fit_matrix(pairs):
    A = np.concatenate([p[0].reshape(-1, 3) for p in pairs])
    B = np.concatenate([p[1].reshape(-1, 3) for p in pairs])
    X = np.hstack([A, np.ones((len(A), 1))])
    M, _, _, _ = np.linalg.lstsq(X, B, rcond=None)
    return M  # 4x3 affine


def apply_matrix(M, img):
    return np.clip(img.reshape(-1, 3) @ M[:3] + M[3], 0, 1).reshape(img.shape)


def gain_align(p, t):
    g = [(t[..., c] * p[..., c]).sum() / max((p[..., c] ** 2).sum(), 1e-9)
         for c in range(3)]
    return np.clip(p * np.array(g), 0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a-dir", required=True)
    ap.add_argument("--b-dir", required=True)
    ap.add_argument("--a-match", required=True)
    ap.add_argument("--b-match", required=True)
    ap.add_argument("--size", required=True)
    ap.add_argument("--out", default="/tmp/lookmatch")
    ap.add_argument("--model", choices=["matrix", "lut"], default="matrix")
    ap.add_argument("--field", action="store_true",
                    help="apply flat-frame field ratio (hurts held-out frames "
                         "until per-shot exposure anchoring improves)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    def grab(d, frame, match):
        return [im for p in find(d, frame, match)
                if (im := load_norm(p)) is not None]

    # tone frames poison the LUT (mostly gray/black at mixed clipping, they
    # outvote the spectrum pairs and the cube gets diffusion-filled from
    # grays); spectrum only, verified better on held-out frames
    train = [(interior(ia, 4), interior(ib, 4))
             for ia in grab(a.a_dir, "spectrum", a.a_match)
             for ib in grab(a.b_dir, "spectrum", a.b_match)]
    if not train:
        raise SystemExit("no overlapping spectrum frames")
    if a.model == "lut":
        lut, cov = build_lut(train)
        np.save(os.path.join(a.out, "lut.npy"), lut)
        print(f"LUT from {len(train)} pair(s), direct cube coverage {cov * 100:.1f}%")
        model = lambda img: apply_lut(lut, img)  # noqa: E731
    else:
        M = fit_matrix(train)
        np.save(os.path.join(a.out, "matrix.npy"), M)
        print(f"affine color matrix from {len(train)} pair(s)")
        model = lambda img: apply_matrix(M, img)  # noqa: E731

    ratio = None
    if a.field:
        FA = grab(a.a_dir, "flat", a.a_match)
        FB = grab(a.b_dir, "flat", a.b_match)
        if FA and FB:
            fa = cv2.GaussianBlur(np.mean([interior(x, 8) for x in FA], axis=0), (0, 0), 9)
            fb = cv2.GaussianBlur(np.mean([interior(x, 8) for x in FB], axis=0), (0, 0), 9)
            ratio = fb / np.maximum(model(fa), 0.02)
            np.save(os.path.join(a.out, "field_ratio.npy"), ratio)

    for fr in ("skin", "organic", "flat"):
        A = grab(a.a_dir, fr, a.a_match)
        B = grab(a.b_dir, fr, a.b_match)
        if not A or not B:
            continue
        ia, ib = interior(A[0], 8), interior(B[0], 8)
        pred = model(ia)
        if ratio is not None:
            pred = np.clip(pred * ratio, 0, 1)
        # gain-align both so per-shot auto-exposure differences don't score;
        # smooth so sharpness/noise/registration don't either - color only
        def col(p):
            return rms(cv2.GaussianBlur(gain_align(p, ib), (0, 0), 6),
                       cv2.GaussianBlur(ib, (0, 0), 6))
        print(f"{fr:8s} color RMS (gain-aligned, smoothed): "
              f"A vs B {col(ia):6.2f}  ->  mapped {col(pred):6.2f}")
        strip = np.concatenate([ia, pred, ib], axis=1)
        cv2.imwrite(os.path.join(a.out, f"compare-{fr}.png"),
                    (np.clip(strip[:, :, ::-1], 0, 1) * 255).astype(np.uint8))
    print("side-by-sides (A | A->B mapped | B actual) in", a.out)


if __name__ == "__main__":
    main()
