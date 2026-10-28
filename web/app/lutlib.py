"""Read side of the LUT library: the /luts page and its downloads.

Storage is the plain directory the ingest script writes (tools/lut_ingest.py):
/srv/lensica/luts/ with manifest.json, the .cube files, and previews/. No DB.
We only read here; nothing is generated on request.
"""
import json
import os

LUT_DIR = "/srv/lensica/luts"
MANIFEST = os.path.join(LUT_DIR, "manifest.json")

LICENSE_URL = {
    "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
    "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
}


def list_luts():
    """Manifest entries for display, measured first, then by name. Skips any
    entry flagged by the ingest validator. Adds a license_url for the link."""
    if not os.path.exists(MANIFEST):
        return []
    try:
        with open(MANIFEST) as f:
            luts = json.load(f).get("luts", [])
    except (OSError, ValueError):
        return []
    luts = [l for l in luts if not l.get("flagged")]
    for l in luts:
        l["license_url"] = LICENSE_URL.get(l.get("license", ""))
    luts.sort(key=lambda l: (0 if l.get("provenance") == "measured" else 1,
                             l.get("name", "")))
    return luts


def _get(lut_id):
    for l in list_luts():
        if l["id"] == lut_id:
            return l
    return None


def cube_path(lut_id):
    """Absolute path to a LUT's .cube, or None. Guards against traversal by
    matching the manifest id rather than trusting the request path."""
    l = _get(lut_id)
    if not l:
        return None
    p = os.path.join(LUT_DIR, os.path.basename(l["file"]))
    return p if os.path.exists(p) else None


def cube_filename(lut_id):
    """Download filename for a LUT: <id>.cube."""
    return f"{lut_id}.cube"


def preview_path(fname):
    """Absolute path to a preview image under previews/, or None."""
    p = os.path.join(LUT_DIR, "previews", os.path.basename(fname))
    return p if os.path.exists(p) else None
