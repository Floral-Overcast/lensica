#!/usr/bin/env python3
"""Slanted-edge MTF (ISO 12233 style) from a registered edges frame.

The edges frame has a 3x3 grid of 5-degree slanted squares at the quarter
positions. For each square we take a patch over its left (near-vertical)
edge, locate the sub-pixel edge crossing per row, project pixels onto the
edge normal to build a 4x-oversampled ESF, differentiate to the LSF, and
FFT to the MTF. Frequencies are cycles per STIMULUS pixel: display-referred
resolution, directly comparable across rigs shooting the same target.

Registration warp resampling costs a little MTF everywhere, equally for
every lens shot through the same pipeline, so comparisons hold; absolute
numbers are slightly pessimistic.
"""
import numpy as np


def _esf_to_mtf(esf, sub=4):
    lsf = np.gradient(esf)
    lsf = lsf * np.hanning(len(lsf))
    m = np.abs(np.fft.rfft(lsf))
    if m[0] == 0:
        return None, None
    m = m / m[0]
    freq = np.fft.rfftfreq(len(lsf), d=1.0 / sub)  # cycles / stimulus px
    return freq, m


def edge_patch_mtf(gray, cx, cy, half_h, half_w=28, sub=4):
    """MTF across the near-vertical edge at (cx, cy). Returns
    (freq, mtf, mtf50, edge_x_by_row) or None if the edge isn't usable."""
    y0, y1 = int(cy - half_h), int(cy + half_h)
    x0, x1 = int(cx - half_w), int(cx + half_w)
    if y0 < 0 or x0 < 0 or y1 > gray.shape[0] or x1 > gray.shape[1]:
        return None
    p = gray[y0:y1, x0:x1].astype(np.float64)
    # sub-pixel edge crossing per row from the gradient centroid
    g = np.abs(np.diff(p, axis=1))
    rows, xs, ok = [], [], g.max(axis=1) > (p.max() - p.min()) * 0.08
    if ok.sum() < half_h:
        return None
    idx = np.arange(g.shape[1])
    for r in np.nonzero(ok)[0]:
        w = g[r] ** 2
        xs.append((idx * w).sum() / w.sum())
        rows.append(r)
    rows, xs = np.array(rows), np.array(xs)
    slope, inter = np.polyfit(rows, xs, 1)  # ~tan(5 deg) if clean
    resid = xs - (slope * rows + inter)
    keep = np.abs(resid) < 2.0
    if keep.sum() < half_h:
        return None
    slope, inter = np.polyfit(rows[keep], xs[keep], 1)
    # project every pixel onto the edge-normal axis, bin at 1/sub px
    yy, xx = np.mgrid[0:p.shape[0], 0:p.shape[1]]
    dist = (xx - (slope * yy + inter)) / np.sqrt(1 + slope * slope)
    lo, hi = -half_w + 6, half_w - 6
    sel = (dist >= lo) & (dist < hi)
    bins = np.floor((dist[sel] - lo) * sub).astype(int)
    n = int((hi - lo) * sub)
    esf = np.bincount(bins, weights=p[sel], minlength=n)
    cnt = np.bincount(bins, minlength=n)
    if (cnt == 0).any():
        return None
    esf = esf / cnt
    if esf[:sub * 4].mean() > esf[-sub * 4:].mean():  # normalize dark->light
        esf = esf[::-1]
    freq, m = _esf_to_mtf(esf, sub)
    if freq is None:
        return None
    # MTF50 by linear interpolation, searched below Nyquist (0.5 cy/px)
    valid = freq <= 0.5
    f, mm = freq[valid], m[valid]
    mtf50 = None
    for i in range(1, len(mm)):
        if mm[i] < 0.5 <= mm[i - 1]:
            mtf50 = float(f[i - 1] + (f[i] - f[i - 1]) * (mm[i - 1] - 0.5) / (mm[i - 1] - mm[i]))
            break
    return {"freq": f, "mtf": mm, "mtf50": mtf50, "slope": float(slope)}


def grid_positions(w, h):
    """Center of the left edge of each of the 9 slanted squares."""
    side = min(w, h) // 8
    out = {}
    for iy in range(3):
        for ix in range(3):
            px, py = (ix + 1) * w // 4, (iy + 1) * h // 4
            out[(ix, iy)] = (px - side // 2, py, side)
    return out


def extract(gray, w, h):
    """Per-position MTF from a registered (stimulus-space) edges frame.
    gray: float or uint 2D array already in stimulus space, w x h."""
    res = {}
    for (ix, iy), (ex, ey, side) in grid_positions(w, h).items():
        r = edge_patch_mtf(gray, ex, ey, half_h=side // 3)
        if r:
            res[f"{ix}{iy}"] = r
    return res
