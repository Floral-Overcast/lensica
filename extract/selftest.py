#!/usr/bin/env python3
"""Prove the extraction pipeline without a camera.

Renders the tone frame, simulates a capture (perspective tilt, per-channel
gains, gamma, vignette, blur, sensor noise), then runs registration + tone
extraction and checks the recovered gray-step curve matches the injected
transform at the frame center.

Run from repo root: python3 extract/selftest.py
"""
import os
import sys

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "target", "generators"))
import generate  # noqa: E402
from register import register  # noqa: E402
from tone_curves import extract  # noqa: E402

W, H = 1600, 1000
GAINS = np.array([0.92, 1.00, 1.08])
GAMMA = 1.18
VIG = 0.35


def simulate(stim_rgb):
    """stimulus RGB uint8 -> simulated capture BGR uint8 on a bigger canvas."""
    f = stim_rgb.astype(np.float64) / 255.0
    f = np.clip(f * GAINS, 0, 1) ** GAMMA
    yy, xx = np.mgrid[0:H, 0:W]
    r2 = ((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2
    f *= (1 - VIG * r2 / 2)[..., None]
    img = (np.clip(f, 0, 1) * 255).astype(np.uint8)
    cw, ch = 2200, 1500
    src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
    dst = np.float32([[260, 210], [1965, 240], [1930, 1300], [285, 1275]])
    M = cv2.getPerspectiveTransform(src, dst)
    warped = cv2.warpPerspective(img[:, :, ::-1], M, (cw, ch), borderValue=(8, 8, 8))
    warped = cv2.GaussianBlur(warped, (0, 0), 1.0)
    noise = np.random.default_rng(7).normal(0, 1.5, warped.shape)
    return np.clip(warped.astype(np.float64) + noise, 0, 255).astype(np.uint8)


def expected(v, cx, cy):
    """Injected transform at stimulus position (cx, cy), vignette included."""
    r2 = ((cx - W / 2) / (W / 2)) ** 2 + ((cy - H / 2) / (H / 2)) ** 2
    return 255 * (np.clip(v / 255 * GAINS, 0, 1) ** GAMMA) * (1 - VIG * r2 / 2)


def main():
    stim = np.asarray(generate.add_fiducials(generate.tone(W, H), "tone"))
    cap = simulate(stim)
    reg, n = register(cap, "tone", W, H)
    print(f"registered with {n}/4 fiducials")
    prof = extract(reg[:, :, ::-1].astype(np.float64))
    errs = []
    band = H // 8
    for i, stp in enumerate(prof["gray_steps"]):
        v = stp["stim"]
        if 16 <= v <= 235:  # skip extremes (clipping + border effects)
            cx, cy = (i + 0.5) * W / 21, 5 * band
            errs.append(np.abs(np.array(stp["rgb"]) - expected(v, cx, cy)))
    errs = np.array(errs)
    print(f"gray-step recovery error vs injected curve: mean={errs.mean():.2f} max={errs.max():.2f} (0-255 scale)")
    assert n >= 3, "registration lost fiducials"
    assert errs.mean() < 3.0, "mean error too high"
    assert errs.max() < 8.0, "max error too high"
    print("PASS: pipeline recovers a known synthetic 'lens+sensor' transform")


if __name__ == "__main__":
    main()
