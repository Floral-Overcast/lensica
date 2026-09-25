#!/usr/bin/env python3
"""In-silico structure mining v0: where does the documented model fail?

Fits the documented global model (affine color matrix from the spectrum
frame) for a rig pair A -> B, then measures the RESIDUAL - the part of B's
rendering the model cannot explain - on held-out frames, and attributes it:
does the unexplained look concentrate by field radius (undocumented
vignette/cast), by input luminance (tone nonlinearity), by hue (selective
color policy, glass transmission tint), or by saturation (compression)?

A high concentration ratio on some axis = "there is structure here the
documented decomposition doesn't capture" - the pointer for what to model
or measure next. Vintage-glass signatures are expected to surface as hue
concentration (transmission tint) and radius x channel coupling (dispersion
-> lateral CA). Overnight mode sweeps every rig pair in a session set.

usage: residual_miner.py --a-dir <processed> --a-match SG-image
                         --b-dir <processed> --b-match "iPhone 5s"
                         [--frames skin,organic]
"""
import argparse
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lookmatch as lm  # noqa: E402


def grab(d, frame, match):
    return [im for p in lm.find(d, frame, match)
            if (im := lm.load_norm(p)) is not None]


def attribution(a, b, pred):
    """Bin |residual| by radius / luminance / hue / saturation of the input."""
    H, W, _ = a.shape
    res = np.linalg.norm(cv2.GaussianBlur(b - pred, (0, 0), 4), axis=2)
    yy, xx = np.mgrid[0:H, 0:W]
    radius = (np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2))
              / np.sqrt(2)).ravel()
    a8 = (np.clip(a, 0, 1) * 255).astype(np.uint8)
    hsv = cv2.cvtColor(a8, cv2.COLOR_RGB2HSV).reshape(-1, 3).astype(np.float64)
    hue, sat = hsv[:, 0] * 2.0, hsv[:, 1] / 255.0  # deg, 0-1
    lum = a.mean(axis=2).ravel()
    r = res.ravel()
    out = {}

    def bins(vals, edges, labels, mask=None):
        m = np.ones_like(r, bool) if mask is None else mask
        means = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            sel = m & (vals >= lo) & (vals < hi)
            means.append(r[sel].mean() if sel.sum() > 500 else np.nan)
        return dict(zip(labels, means))

    out["radius"] = bins(radius, [0, .2, .4, .6, .8, 1.01],
                         ["r0-.2", "r.2-.4", "r.4-.6", "r.6-.8", "r.8-1"])
    out["luminance"] = bins(lum, [0, .1, .25, .5, .75, 1.01],
                            ["shadow", "low", "mid", "high", "highlight"])
    out["hue"] = bins(hue, [0, 60, 120, 180, 240, 300, 360.1],
                      ["red-yel", "yel-grn", "grn-cyn", "cyn-blu",
                       "blu-mag", "mag-red"], mask=sat > 0.25)
    out["saturation"] = bins(sat, [0, .15, .4, .7, 1.01],
                             ["neutral", "muted", "sat", "vivid"])
    return out, float(res.mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a-dir", required=True)
    ap.add_argument("--b-dir", required=True)
    ap.add_argument("--a-match", required=True)
    ap.add_argument("--b-match", required=True)
    ap.add_argument("--frames", default="skin,organic")
    a = ap.parse_args()

    train = [(lm.interior(x, 4), lm.interior(y, 4))
             for x in grab(a.a_dir, "spectrum", a.a_match)
             for y in grab(a.b_dir, "spectrum", a.b_match)]
    if not train:
        sys.exit("no spectrum overlap")
    M = lm.fit_matrix(train)

    # model quality on training domain
    ta, tb = train[0]
    base = lm.rms(lm.gain_align(ta, tb), tb)
    fit = lm.rms(lm.gain_align(lm.apply_matrix(M, ta), tb), tb)
    print(f"pair: {a.a_match} -> {a.b_match}")
    print(f"documented model on spectrum: raw diff {base:.2f} -> {fit:.2f} RMS "
          f"({(1 - fit / max(base, 1e-9)) * 100:.0f}% explained)\n")

    agg = {}
    for fr in a.frames.split(","):
        A = grab(a.a_dir, fr, a.a_match)
        B = grab(a.b_dir, fr, a.b_match)
        if not A or not B:
            continue
        ia, ib = lm.interior(A[0], 8), lm.interior(B[0], 8)
        pred = lm.gain_align(lm.apply_matrix(M, ia), ib)
        att, mean_res = attribution(ia, ib, pred)
        print(f"[{fr}] mean residual {mean_res * 255:.2f}/255 - concentration:")
        for axis, d in att.items():
            vals = {k: v for k, v in d.items() if not np.isnan(v)}
            if not vals:
                continue
            mu = np.mean(list(vals.values()))
            hot = max(vals, key=vals.get)
            ratio = vals[hot] / max(mu, 1e-9)
            flag = "  <-- STRUCTURE" if ratio > 1.5 else ""
            print(f"  {axis:10s} hot={hot:9s} {ratio:.2f}x mean "
                  f"({', '.join(f'{k}={v * 255:.1f}' for k, v in vals.items())})"
                  f"{flag}")
            agg.setdefault(axis, []).append(ratio)
        print()
    if agg:
        print("summary (mean concentration across frames):")
        for axis, rs in sorted(agg.items(), key=lambda kv: -np.mean(kv[1])):
            print(f"  {axis:10s} {np.mean(rs):.2f}x")


if __name__ == "__main__":
    main()
