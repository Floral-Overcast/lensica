"""Canonical display names for rigs: the name people recognize, never the
EXIF serial. Single source of truth for the web app, reports, and figures.
Unknown models pass through unchanged (better a serial than a wrong guess)."""

MODELS = {
    "XQ-CT54": "Sony Xperia 1 IV",
    "ILCE-7CM2": "Sony A7C II",
    "DSC-T7": "Sony Cyber-shot DSC-T7",
    "Galaxy S25 Ultra": "Samsung Galaxy S25 Ultra",
    "SM-S938U": "Samsung Galaxy S25 Ultra",
    "iPhone 5s": "Apple iPhone 5s",
    "X-H2S": "Fujifilm X-H2S",
}

LENSES = {
    "TTARTISAN 40mm F2.0": "TTArtisan 40mm F2",
    "SG-image 35mm F2.2 FE": "SG-image 35mm F2.2",
}


def rig_name(model=None, lens=None):
    """Friendly rig label from EXIF Model / LensModel.
    Fixed-lens devices (phone lens strings restate the model, or no lens at
    all) show just the device; interchangeable rigs show body + lens."""
    model = (model or "").strip()
    lens = (lens or "").strip()
    friendly = MODELS.get(model, model)
    if not lens or (model and lens.lower().startswith(model.lower())):
        return friendly or lens
    lens_f = LENSES.get(lens, lens)
    return f"{friendly} + {lens_f}" if friendly else lens_f


def from_meta(meta):
    return rig_name(meta.get("Model"), meta.get("LensModel"))
