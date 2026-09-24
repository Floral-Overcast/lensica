#!/usr/bin/env python3
"""Lensica Target v1 synthetic frames. Deterministic, parametric by resolution:
the code is the locked artifact, renders are reproducible byte-for-byte
(fixed Pillow encode settings, no randomness anywhere).

Frames:
  spectrum  color-cube sweep (fills the LUT where the organic frame is thin);
            --pages emits N frames that together show EVERY 8-bit RGB value
            exactly once at the given resolution
  skin      skin-tone locus grid + anchor swatches + gradient strip
  tone      smooth luma/R/G/B ramps + 21-step grays + broadcast-level blocks
  points    point lights on black (PSF/bokeh/flare; white grid + RGB triads + flare disk)
  edges     5-degree slanted squares (MTF/CA) + 1px distortion grid on mid-gray
  flat      uniform 50% gray (vignetting + display uniformity)

Every frame gets 4 corner ArUco fiducials (DICT_4X4_50, id = frame_id*4+corner,
corners ordered TL,TR,BR,BL) so extraction can warp captures back into stimulus
pixel space. fiducial_geometry() is the single source of truth for their
stimulus coordinates; extract/register.py imports it.

usage: generate.py {spectrum|skin|tone|points|edges|flat|all} [--res 4096x4096]
                   [--out target/reference] [--pages]
"""
import argparse
import hashlib
import os

import numpy as np
from PIL import Image, ImageDraw

VERSION = "v1"

FRAME_IDS = {"organic": 0, "spectrum": 1, "skin": 2, "tone": 3, "points": 4, "edges": 5, "flat": 6, "split": 7}


def fiducial_geometry(w, h):
    """Marker corner coords in stimulus space: {corner_key: 4x(x,y) TL,TR,BR,BL}.
    corner_key 0=TL 1=TR 2=BR 3=BL of the frame."""
    s = max(80, min(w, h) // 14)
    q = s // 4
    p = s + 2 * q
    pads = {0: (0, 0), 1: (w - p, 0), 2: (w - p, h - p), 3: (0, h - p)}
    geo = {}
    for k, (px, py) in pads.items():
        x, y = px + q, py + q
        geo[k] = [(x, y), (x + s, y), (x + s, y + s), (x, y + s)]
    return geo, s, q


def add_fiducials(img, frame_name):
    import cv2
    w, h = img.size
    geo, s, q = fiducial_geometry(w, h)
    d = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    base = FRAME_IDS[frame_name] * 4
    for k, pts in geo.items():
        m = cv2.aruco.generateImageMarker(d, base + k, s)
        pad = np.full((s + 2 * q, s + 2 * q), 255, np.uint8)
        pad[q : q + s, q : q + s] = m
        img.paste(Image.fromarray(pad).convert("RGB"), (pts[0][0] - q, pts[0][1] - q))
    return img


def save(img, out, name, w, h):
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"{name}-{w}x{h}-{VERSION}.png")
    img.save(path)
    sha = hashlib.sha256(open(path, "rb").read()).hexdigest()
    print(f"{path}  sha256={sha[:16]}...")
    return path


def spectrum(w, h):
    """Tiled color-cube sweep: within each tile x drives R, y drives G; the tile
    index drives B. Smooth per-pixel gradients so lens blur barely contaminates."""
    tiles = 8  # 8x8 tiles -> 64 blue levels in the single-frame version
    tw, th = w // tiles, h // tiles
    x = np.arange(w)
    y = np.arange(h)
    r = ((x % tw) * 255 // max(tw - 1, 1)).astype(np.uint8)[None, :].repeat(h, 0)
    g = ((y % th) * 255 // max(th - 1, 1)).astype(np.uint8)[:, None].repeat(w, 1)
    tix = (y[:, None] // th).clip(0, tiles - 1) * tiles + (x[None, :] // tw).clip(0, tiles - 1)
    b = (tix * 255 // (tiles * tiles - 1)).astype(np.uint8)
    return Image.fromarray(np.dstack([r, g, b]))


def spectrum_pages(w, h, out):
    """Every 24-bit RGB value exactly once across ceil(2^24 / (w*h)) frames.
    Linear order r-fastest, so horizontal neighbors differ by 1 in red."""
    total = 1 << 24
    per = w * h
    npages = -(-total // per)
    paths = []
    for p in range(npages):
        i = np.arange(p * per, p * per + per, dtype=np.int64)
        i = np.minimum(i, total - 1)  # last page padding repeats white-adjacent tail
        arr = np.dstack([(i % 256), (i // 256 % 256), (i // 65536)]).astype(np.uint8).reshape(h, w, 3)
        paths.append(save(Image.fromarray(arr), out, f"spectrum-page{p:02d}of{npages}", w, h))
    return paths


# sRGB anchors spanning light to deep skin (Fitzpatrick-ish spread)
SKIN_ANCHORS = [
    (255, 224, 196), (246, 204, 176), (241, 194, 167), (224, 172, 138),
    (210, 158, 124), (198, 134, 94), (161, 102, 66), (141, 85, 36),
    (110, 66, 40), (80, 51, 32), (59, 36, 22), (40, 25, 16),
]


def hsv_rgb(hdeg, s, v):
    import colorsys
    return tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(hdeg / 360.0, s, v))


def skin(w, h):
    """Top 3/4: three saturation blocks (0.20/0.35/0.55), each a hue(10-45deg) x
    value(0.15-0.97) grid over the skin locus. Bottom 1/4: anchor swatches + a
    smooth deep-to-light gradient through the anchors."""
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    hues = np.linspace(10, 45, 12)
    vals = np.linspace(0.15, 0.97, 16)
    block_h = (h * 3 // 4) // 3
    for bi, s in enumerate((0.20, 0.35, 0.55)):
        for r_i, v in enumerate(vals):
            for c_i, hu in enumerate(hues):
                x0 = c_i * w // 12
                y0 = bi * block_h + r_i * block_h // 16
                d.rectangle([x0, y0, (c_i + 1) * w // 12 - 1, bi * block_h + (r_i + 1) * block_h // 16 - 1],
                            fill=hsv_rgb(hu, s, v))
    strip_y = h * 3 // 4
    sw = w // len(SKIN_ANCHORS)
    for i, c in enumerate(SKIN_ANCHORS):
        d.rectangle([i * sw, strip_y, (i + 1) * sw - 1, strip_y + h // 8 - 1], fill=c)
    # smooth gradient through anchors
    gy0 = strip_y + h // 8
    anch = np.array(SKIN_ANCHORS, dtype=np.float64)
    t = np.linspace(0, len(anch) - 1, w)
    i0 = np.floor(t).astype(int).clip(0, len(anch) - 2)
    f = (t - i0)[:, None]
    grad = (anch[i0] * (1 - f) + anch[i0 + 1] * f).astype(np.uint8)
    ga = np.repeat(grad[None, :, :], h - gy0, axis=0)
    img.paste(Image.fromarray(ga), (0, gy0))
    return img


def tone(w, h):
    """Four smooth horizontal ramps (Y, R, G, B), then 21-step gray patches,
    then broadcast-level check blocks (0/16/235/255)."""
    img = Image.new("RGB", (w, h), (0, 0, 0))
    ramp = (np.arange(w) * 255 // (w - 1)).astype(np.uint8)
    band = h // 8
    rows = {0: (1, 1, 1), 1: (1, 0, 0), 2: (0, 1, 0), 3: (0, 0, 1)}
    for i, m in rows.items():
        arr = np.dstack([ramp * m[0], ramp * m[1], ramp * m[2]]).astype(np.uint8)
        img.paste(Image.fromarray(np.repeat(arr, band, axis=0)), (0, i * band))
    d = ImageDraw.Draw(img)
    y0 = 4 * band
    for i in range(21):
        v = round(i * 255 / 20)
        d.rectangle([i * w // 21, y0, (i + 1) * w // 21 - 1, y0 + 2 * band - 1], fill=(v, v, v))
    y1 = y0 + 2 * band
    for i, v in enumerate((0, 16, 235, 255)):
        d.rectangle([i * w // 4, y1, (i + 1) * w // 4 - 1, h - 1], fill=(v, v, v))
    return img


def points(w, h):
    """Black field, white point grid (r=4px, 320px pitch) for PSF/bokeh across the
    frame; RGB triads near center for chromatic PSF; one big disk for flare."""
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    for y in range(160, h, 320):
        for x in range(160, w, 320):
            d.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(255, 255, 255))
    cx, cy = w // 2, h // 2
    for i, c in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255))):
        x = cx - 96 + i * 96
        d.ellipse([x - 4, cy + 156, x + 4, cy + 164], fill=c)
    fx, fy = w * 3 // 4, h // 4
    d.ellipse([fx - 24, fy - 24, fx + 24, fy + 24], fill=(255, 255, 255))
    return img


def edges(w, h):
    """Mid-gray field, 1px black grid every 128px (distortion), 3x3 field positions
    of 5-degree slanted squares, alternating black/white (MTF + CA, both polarities)."""
    img = Image.new("RGB", (w, h), (118, 118, 118))
    d = ImageDraw.Draw(img)
    for x in range(0, w, 128):
        d.line([x, 0, x, h], fill=(0, 0, 0), width=1)
    for y in range(0, h, 128):
        d.line([0, y, w, y], fill=(0, 0, 0), width=1)
    side = min(w, h) // 8
    for iy in range(3):
        for ix in range(3):
            col = (0, 0, 0) if (ix + iy) % 2 == 0 else (255, 255, 255)
            sq = Image.new("RGB", (side, side), col)
            rot = sq.rotate(5, expand=True, fillcolor=(118, 118, 118))
            x = (ix + 1) * w // 4 - rot.width // 2
            y = (iy + 1) * h // 4 - rot.height // 2
            img.paste(rot, (x, y))
    return img


def flat(w, h):
    return Image.new("RGB", (w, h), (128, 128, 128))


def split(w, h):
    """Left half 255 white, right half 0 black: veiling-glare / flare-contrast
    frame. The white half's spill into the black half measures the lens's
    global contrast character."""
    img = Image.new("RGB", (w, h), (0, 0, 0))
    ImageDraw.Draw(img).rectangle([0, 0, w // 2 - 1, h - 1], fill=(255, 255, 255))
    return img


FRAMES = {"spectrum": spectrum, "skin": skin, "tone": tone, "points": points, "edges": edges, "flat": flat, "split": split}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("frame", choices=list(FRAMES) + ["all"])
    ap.add_argument("--res", default="4096x4096")
    ap.add_argument("--out", default="target/reference")
    ap.add_argument("--pages", action="store_true", help="spectrum only: full 2^24 coverage pages")
    a = ap.parse_args()
    w, h = map(int, a.res.lower().split("x"))
    names = list(FRAMES) if a.frame == "all" else [a.frame]
    for n in names:
        if n == "spectrum" and a.pages:
            for p in spectrum_pages(w, h, a.out):
                add_fiducials(Image.open(p), "spectrum").save(p)
        else:
            save(add_fiducials(FRAMES[n](w, h), n), a.out, n, w, h)


if __name__ == "__main__":
    main()
