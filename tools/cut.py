#!/usr/bin/env python3
"""Export a Lensica Target v1 set for one display: a deterministic center-crop of
the master square at the display's EXACT native pixels, plus every synthetic frame
rendered at that resolution, plus a manifest with sha256 of each file.

usage: cut.py --display macbook-pro-14 --out cuts/
       cut.py --res 2560x1600 --out cuts/
"""
import argparse
import hashlib
import json
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "target", "generators"))
import generate  # noqa: E402

MASTER = "target/master/master-square-v1.png"
MASTER_JSON = "target/master/master-square-v1.json"

# native panel pixels; landscape unless the device only makes sense portrait
DISPLAYS = {
    "pro-display-xdr": (6016, 3384),
    "studio-display": (5120, 2880),
    "imac-24": (4480, 2520),
    "macbook-pro-16": (3456, 2234),
    "macbook-pro-14": (3024, 1964),
    "macbook-air-13": (2560, 1664),
    "ipad-pro-13": (2752, 2064),
    "ipad-pro-11": (2420, 1668),
    "iphone-pro-max": (1320, 2868),
    "iphone-pro": (1206, 2622),
    "iphone-5s": (640, 1136),
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 24), b""):
            h.update(chunk)
    return h.hexdigest()


def build(w, h, out_parent, label):
    """Generate the full frame set for one resolution. Returns manifest path."""
    Image.MAX_IMAGE_PIXELS = None
    m = Image.open(os.path.join(os.path.dirname(__file__), "..", MASTER))
    if w > m.width or h > m.height:
        raise ValueError(f"display {w}x{h} exceeds master square {m.size}")
    outdir = os.path.join(out_parent, label)
    os.makedirs(outdir, exist_ok=True)

    x0, y0 = (m.width - w) // 2, (m.height - h) // 2
    organic = os.path.join(outdir, f"organic-{w}x{h}-v1.png")
    generate.add_fiducials(m.crop((x0, y0, x0 + w, y0 + h)), "organic").save(organic)
    print(f"{organic} (master center-crop at {x0},{y0})")

    files = {os.path.basename(organic): sha256(organic)}
    for name, fn in generate.FRAMES.items():
        path = generate.save(generate.add_fiducials(fn(w, h), name), outdir, name, w, h)
        files[os.path.basename(path)] = sha256(path)

    manifest = {
        "target_version": "v1",
        "display": label,
        "resolution": [w, h],
        "master_sha256": sha256(os.path.join(os.path.dirname(__file__), "..", MASTER)),
        "master_crop_origin_xy": [x0, y0],
        "files": files,
        "display_rule": "render 1:1 native pixels, fullscreen, no OS scaling, dark room",
    }
    mp = os.path.join(outdir, "manifest.json")
    with open(mp, "w") as f:
        json.dump(manifest, f, indent=2)
    print(mp)
    return mp


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--display", choices=sorted(DISPLAYS))
    g.add_argument("--res")
    ap.add_argument("--out", default="cuts")
    a = ap.parse_args()
    if a.display:
        w, h = DISPLAYS[a.display]
        label = a.display
    else:
        w, h = map(int, a.res.lower().split("x"))
        label = f"{w}x{h}"
    try:
        build(w, h, a.out, label)
    except ValueError as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
