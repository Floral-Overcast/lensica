#!/usr/bin/env python3
"""Ingest a .cube LUT into the public Lensica LUT library.

Storage is a plain directory, no database:

    /srv/lensica/luts/
        manifest.json      one entry per LUT (served by the /luts page)
        <id>.cube          the LUT itself
        previews/          before/after jpegs rendered here, once, at ingest

What this script does for one .cube + its metadata:
  1. read and sanity-check the cube (size, in-range, right line count),
  2. render a before/after preview on a fixed reference photo (the CC0 benchy),
  3. if a reference model is given (our measured looks), validate the exported
     cube by applying it trilinearly vs the model directly on a held-out real
     photo and recording the max/mean delta,
  4. append or replace the entry in manifest.json.

Two ways in:
  --seed            build our own measured looks (web/app/looks.py) into cubes
                    and ingest them with model validation. This is the only
                    seed content: our own exports, explicitly CC0.
  --cube FILE ...   ingest one externally supplied .cube (community path). No
                    model to validate against, so fit_error stays null.

Community submissions later come through this same script; there is no upload
form. We do not scrape or rehost third-party "free LUT" packs with unclear
terms.
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "analysis"))
import lookmatch  # noqa: E402

LUT_DIR = "/srv/lensica/luts"
PREVIEW_DIR = os.path.join(LUT_DIR, "previews")
MANIFEST = os.path.join(LUT_DIR, "manifest.json")

# Fixed reference photo for previews + validation. A real photo (not a
# spectrum frame), so the validation delta reflects held-out behaviour.
REF_PHOTO = "/srv/lensica/benchy-v45.jpg"
PREVIEW_PX = 760      # long edge of the rendered preview jpegs
VALID_PX = 520        # smaller copy used only for the numeric validation
JPEG_Q = 88
N = 33                # lattice size for cubes we export


# ---------------- .cube read / write ----------------
def write_cube(path, grid, title):
    """grid: (N,N,N,3) float RGB in [0,1], indexed [r,g,b]. Writes a standard
    Adobe .cube with R varying fastest (the conventional order)."""
    n = grid.shape[0]
    lines = [f'TITLE "{title}"', f"LUT_3D_SIZE {n}",
             "DOMAIN_MIN 0.0 0.0 0.0", "DOMAIN_MAX 1.0 1.0 1.0", ""]
    for b in range(n):
        for g in range(n):
            for r in range(n):
                v = grid[r, g, b]
                lines.append(f"{v[0]:.6f} {v[1]:.6f} {v[2]:.6f}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def read_cube(path):
    """Parse a .cube into (size, grid[r,g,b,3] float). Raises ValueError on a
    malformed file. Accepts only 3D cubes in the [0,1] domain."""
    size = None
    dmin, dmax = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0]
    rows = []
    with open(path, "r", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            key = line.split()[0].upper()
            if key == "LUT_3D_SIZE":
                size = int(line.split()[1])
            elif key == "LUT_1D_SIZE":
                raise ValueError("1D LUTs are not supported, need a 3D .cube")
            elif key == "DOMAIN_MIN":
                dmin = [float(x) for x in line.split()[1:4]]
            elif key == "DOMAIN_MAX":
                dmax = [float(x) for x in line.split()[1:4]]
            elif key in ("TITLE",):
                continue
            else:
                parts = line.split()
                if len(parts) == 3:
                    try:
                        rows.append([float(x) for x in parts])
                    except ValueError:
                        raise ValueError(f"bad data row: {line!r}")
    if size is None:
        raise ValueError("no LUT_3D_SIZE")
    if len(rows) != size ** 3:
        raise ValueError(f"expected {size**3} rows, got {len(rows)}")
    if dmin != [0.0, 0.0, 0.0] or dmax != [1.0, 1.0, 1.0]:
        raise ValueError("only the [0,1] domain is supported in v1")
    arr = np.asarray(rows, np.float64)
    if arr.min() < -0.01 or arr.max() > 1.01:
        raise ValueError("values fall outside [0,1]")
    arr = np.clip(arr, 0, 1)
    # rows are R-fastest: index = r + g*size + b*size*size -> reshape [b,g,r,3]
    grid = arr.reshape(size, size, size, 3).transpose(2, 1, 0, 3)
    return size, grid


# ---------------- image helpers ----------------
def _load_rgb(path, long_edge):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"could not read reference photo {path}")
    h, w = img.shape[:2]
    s = min(1.0, float(long_edge) / max(h, w))
    if s < 1.0:
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img[:, :, ::-1].astype(np.float64) / 255.0


def _save_jpg(path, rgb01):
    bgr = (np.clip(rgb01[:, :, ::-1], 0, 1) * 255).astype(np.uint8)
    cv2.imwrite(path, bgr, [cv2.IMWRITE_JPEG_QUALITY, JPEG_Q])


# ---------------- previews + validation ----------------
def render_previews(lut_id, grid):
    """Render the shared source + this LUT's after image onto the reference
    photo. Returns {"before": relpath, "after": relpath}."""
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    src = _load_rgb(REF_PHOTO, PREVIEW_PX)
    before_rel = "previews/_source.jpg"
    before_abs = os.path.join(LUT_DIR, before_rel)
    if not os.path.exists(before_abs):
        _save_jpg(before_abs, src)
    after_rel = f"previews/{lut_id}.jpg"
    _save_jpg(os.path.join(LUT_DIR, after_rel), lookmatch.apply_lut(grid, src))
    return {"before": before_rel, "after": after_rel}


def validate_against_model(grid, model_fn):
    """Apply the cube (trilinear) vs the model directly on a held-out real
    photo. Returns a fit_error note string with max/mean delta in 0-255 units,
    or None if the reference photo is missing."""
    if not os.path.exists(REF_PHOTO):
        return None
    img = _load_rgb(REF_PHOTO, VALID_PX)
    via_cube = lookmatch.apply_lut(grid, img)
    via_model = model_fn(img)
    delta = np.abs(via_cube - via_model) * 255.0
    return float(delta.max()), float(delta.mean())


# ---------------- manifest ----------------
def load_manifest():
    if os.path.exists(MANIFEST):
        with open(MANIFEST) as f:
            return json.load(f)
    return {"luts": []}


def save_manifest(m):
    os.makedirs(LUT_DIR, exist_ok=True)
    with open(MANIFEST, "w") as f:
        json.dump(m, f, indent=2)
        f.write("\n")


def upsert(entry):
    m = load_manifest()
    m["luts"] = [e for e in m["luts"] if e["id"] != entry["id"]] + [entry]
    save_manifest(m)


# ---------------- ingest ----------------
def ingest(grid, meta, model_fn=None):
    """grid: (N,N,N,3). meta: id/name/license/provenance/description/rig.
    Renders previews, validates against model_fn if given, writes the cube and
    the manifest entry. Returns the entry."""
    os.makedirs(LUT_DIR, exist_ok=True)
    lut_id = meta["id"]
    size = grid.shape[0]
    cube_file = f"{lut_id}.cube"
    write_cube(os.path.join(LUT_DIR, cube_file), grid, meta["name"])

    fit_error = None
    suspicious = False
    if model_fn is not None:
        res = validate_against_model(grid, model_fn)
        if res is not None:
            mx, mean = res
            fit_error = (f"cube vs model on a held-out photo: max {mx:.1f}/255, "
                         f"mean {mean:.2f}/255. Affine colour model only "
                         f"(no tone or sharpening); approximate on unprofiled "
                         f"sources.")
            # affine-through-grid should round-trip tightly; a large delta means
            # the export misrepresents the model. Flag instead of publishing.
            if mx > 12.0:
                suspicious = True
    elif meta.get("provenance") == "measured":
        fit_error = meta.get("fit_error")

    previews = render_previews(lut_id, grid)
    entry = {
        "id": lut_id,
        "name": meta["name"],
        "file": cube_file,
        "license": meta.get("license", "CC0-1.0"),
        "provenance": meta.get("provenance", "community"),
        "description": meta.get("description", ""),
        "rig": meta.get("rig"),
        "preview": previews,
        "fit_error": fit_error,
        "size": size,
    }
    if suspicious:
        entry["flagged"] = ("validation delta exceeds threshold; export may "
                            "misrepresent the model, held for review")
        print(f"  ! FLAGGED {lut_id}: {fit_error}", file=sys.stderr)
    upsert(entry)
    return entry


# ---------------- seed: our own measured looks ----------------
def seed():
    """Export each look in web/app/looks.py through its affine model onto an
    identity 33^3 grid, then ingest with model validation. LUT output then
    matches what the /try page does."""
    from web.app import looks

    # rig (body + lens) the look emulates = the B rig of the A->B mapping.
    SEED = {
        "xperia": {
            "id": "sony-xperia-1-iv",
            "name": "Sony Xperia 1 IV rendering",
            "rig": "Sony Xperia 1 IV",
            "description": ("Sony's phone colour science and tone, learned as an "
                            "A7C II to Xperia 1 IV mapping and exported as a 3D "
                            "LUT. Apply to a neutral sRGB photo."),
        },
        "a7cii": {
            "id": "sony-a7cii-sg35",
            "name": "Sony A7C II rendering",
            "rig": "Sony A7C II + SG-image 35mm F2.2",
            "description": ("Full-frame body colour rendering, learned as an "
                            "Xperia 1 IV to A7C II mapping and exported as a 3D "
                            "LUT. Apply to a neutral sRGB photo."),
        },
    }

    # identity lattice, indexed [r,g,b]
    ax = np.linspace(0.0, 1.0, N)
    R, G, B = np.meshgrid(ax, ax, ax, indexing="ij")
    identity = np.stack([R, G, B], axis=-1)

    done = []
    for look in looks.LOOKS:
        meta = SEED.get(look["id"])
        if meta is None or not looks._available(look):
            print(f"  skip {look['id']} (no data / not seeded)")
            continue
        M = looks.get_matrix(look)
        grid = lookmatch.apply_matrix(M, identity)  # affine + clip, [r,g,b,3]
        entry = ingest(grid, {**meta, "license": "CC0-1.0",
                              "provenance": "measured"},
                       model_fn=lambda img, M=M: lookmatch.apply_matrix(M, img))
        print(f"  seeded {entry['id']}  {entry['fit_error']}")
        done.append(entry["id"])
    return done


def main():
    ap = argparse.ArgumentParser(description="Ingest a .cube into the LUT library")
    ap.add_argument("--seed", action="store_true",
                    help="build + ingest our own measured looks")
    ap.add_argument("--cube", help="path to a .cube to ingest (community)")
    ap.add_argument("--id")
    ap.add_argument("--name")
    ap.add_argument("--license", default="CC0-1.0")
    ap.add_argument("--provenance", default="community",
                    choices=["measured", "community"])
    ap.add_argument("--description", default="")
    ap.add_argument("--rig", default=None)
    a = ap.parse_args()

    if a.seed:
        ids = seed()
        print(f"seeded {len(ids)} LUT(s): {', '.join(ids)}")
        return
    if a.cube:
        if not (a.id and a.name):
            ap.error("--cube needs --id and --name")
        size, grid = read_cube(a.cube)
        entry = ingest(grid, {"id": a.id, "name": a.name, "license": a.license,
                              "provenance": a.provenance,
                              "description": a.description, "rig": a.rig})
        print(f"ingested {entry['id']} (size {size})")
        return
    ap.error("nothing to do: pass --seed or --cube")


if __name__ == "__main__":
    main()
