"""Profile data + themed charts for the web MVP.

Reuses analysis/report.py's extraction functions as a module (MTF, vignette,
glare, PSF, tone). The SVG-chart approach is lifted from report.py but re-themed
so grid/axis/tick colors come from CSS variables (works in both light + dark);
series keep their data colors, which are chosen to read on either theme.

A "profile" = one (Model, LensModel) group, aggregated across the configured
processed session dirs. Data source dirs are set in PROFILE_DIRS.
"""
import glob
import hashlib
import json
import os
import re
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "analysis"))
sys.path.insert(0, os.path.join(ROOT, "extract"))
import report  # noqa: E402  (reuse extraction: collect/radial_profile/glare/mtf_fields/psf_thumbs)
import rignames  # noqa: E402  (canonical device display names; single source of truth)

# Where profiled sessions live. Real captures at stimulus 1640x2360 (per BRIEF).
PROFILE_DIRS = [
    "/Sata/temp/A7cii2/processed",
    "/Sata/temp/new sets/processed",
    "/Sata/temp/xperia/processed",
    "/Sata/temp/s25u-ipad/processed",
    "/Sata/temp/Iphone 5s/processed",
    "/Sata/temp/cybershot DSC-T7/processed",
]
STIMULUS = (1640, 2360)

# series palettes (validated; readable on both themes) — from report.py
SLOTS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"]
CH = {"r": "#e66767", "g": "#2fae5a", "b": "#3987e5"}
ORDINAL = ["#6da7ec", "#2a78d6", "#8a5cd6"]  # center / mid / corner


def existing_dirs():
    return [d for d in PROFILE_DIRS if os.path.isdir(d)]


# ---------- rig photos (card + header visual) ----------
# Curated photos are Matthew's own shots, committed under web/static/rigs/.
# Keyed by the canonical rignames display name via its slug, so the card visual
# tracks whatever name the UI shows. Filenames are abbreviated by hand, so the
# map is explicit rather than a blind slugify(name)+".jpg". No entry (e.g. the
# Samsung S25U) just falls back to the placeholder card look.
RIGS_DIR = os.path.join(ROOT, "web", "static", "rigs")
# Where wizard device-photo sessions land (mirrors ingestion.UPLOAD_ROOT).
UPLOAD_ROOT = "/Sata/temp/lensica-uploads"

CURATED_RIG_PHOTOS = {
    "Sony A7C II + SG-image 35mm F2.2": "sony-a7c-ii-sg-image-35.jpg",
    "Sony A7C II + TTArtisan 40mm F2": "sony-a7c-ii-ttartisan-40.jpg",
    "Apple iPhone 5s": "apple-iphone-5s.jpg",
    "Sony Xperia 1 IV": "sony-xperia-1-iv.jpg",
    "Sony Cyber-shot DSC-T7": "sony-cyber-shot-dsc-t7.jpg",
}


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


# curated map keyed by slug so lookup is name-driven, not exact-string
_CURATED_BY_SLUG = {slugify(k): v for k, v in CURATED_RIG_PHOTOS.items()}


def _session_photo_for(name):
    """Device photo from an upload session whose recorded rig matches this
    profile name. Returns a servable URL (/api/device-photo/<sid>) or None.
    Curated repo photos win, so this is only consulted as a fallback."""
    want = slugify(name)
    if not os.path.isdir(UPLOAD_ROOT):
        return None
    for sid in sorted(os.listdir(UPLOAD_ROOT)):
        mpath = os.path.join(UPLOAD_ROOT, sid, "session.json")
        if not os.path.isfile(mpath):
            continue
        try:
            man = json.load(open(mpath))
        except Exception:
            continue
        if man.get("device_photo") and slugify(man.get("name", "")) == want:
            return "/api/device-photo/" + sid
    return None


def rig_photo(prof):
    """Card/header image URL for a profile, or None (placeholder look).
    Curated repo photo wins; else a session-supplied device photo."""
    fname = _CURATED_BY_SLUG.get(slugify(prof.get("name", "")))
    if fname and os.path.isfile(os.path.join(RIGS_DIR, fname)):
        return "/static/rigs/" + fname
    return _session_photo_for(prof.get("name", ""))


def profile_id(model, lens):
    key = f"{model}|{lens}".encode()
    return hashlib.sha1(key).hexdigest()[:12]


def list_profiles():
    """Group processed rows into profiles: one per (Model, LensModel)."""
    dirs = existing_dirs()
    if not dirs:
        return []
    rows = report.collect(dirs)
    # report.collect keys 'group' off LensModel; we need Model too, re-read meta
    groups = {}
    for r in rows:
        meta = r["meta"]
        model = (meta.get("Model") or "?").strip()
        lens = (meta.get("LensModel") or meta.get("Model") or "?").strip()
        pid = profile_id(model, lens)
        # EXIF strings (model/lens) stay the grouping keys; the *_disp fields are
        # display-only, from the canonical helper. fixed = lens restates the body
        # (phones/compacts), so the card shows just the device.
        fixed = (not lens) or lens.lower().startswith(model.lower())
        g = groups.setdefault(pid, {
            "id": pid, "model": model, "lens": lens,
            "model_disp": rignames.MODELS.get(model, model),
            "lens_disp": rignames.LENSES.get(lens, lens),
            "name": rignames.rig_name(model, lens), "fixed": fixed,
            "frames": set(), "classes": set(), "n": 0})
        g["frames"].add(r["frame"])
        g["classes"].add(r["klass"])
        g["n"] += 1
    out = []
    for g in groups.values():
        g["frames"] = sorted(g["frames"])
        g["classes"] = sorted(g["classes"])
        out.append(g)
    out.sort(key=lambda g: (g["model"], g["lens"]))
    for g in out:
        g["photo"] = rig_photo(g)
    return out


def get_profile(pid):
    for p in list_profiles():
        if p["id"] == pid:
            return p
    return None


# ---------- themed SVG chart (adapted from report.svg_chart) ----------
def svg_chart(series, xmax, ymax, xlab, ylab, cw=560, chh=330, yfmt="%.2f", xfmt="%.2f"):
    pl, pr, pt, pb = 52, 116, 14, 40
    iw, ih = cw - pl - pr, chh - pt - pb

    def X(v):
        return pl + v / xmax * iw

    def Y(v):
        return pt + (1 - v / ymax) * ih
    p = ['<svg viewBox="0 0 %d %d" class="ch" preserveAspectRatio="xMidYMid meet">' % (cw, chh)]
    for i in range(5):
        gy = Y(ymax * i / 4)
        p.append('<line class="gl" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>' % (pl, gy, pl + iw, gy))
        p.append('<text x="%d" y="%.1f" class="tk" text-anchor="end">%s</text>'
                 % (pl - 6, gy + 4, yfmt % (ymax * i / 4)))
    for i in range(6):
        gx = X(xmax * i / 5)
        p.append('<text x="%.1f" y="%d" class="tk" text-anchor="middle">%s</text>'
                 % (gx, pt + ih + 16, xfmt % (xmax * i / 5)))
    p.append('<line class="ax" x1="%d" y1="%.1f" x2="%d" y2="%.1f"/>'
             % (pl, pt + ih, pl + iw, pt + ih))
    p.append('<text x="%.1f" y="%d" class="lab" text-anchor="middle">%s</text>'
             % (pl + iw / 2, chh - 6, xlab))
    p.append('<text x="14" y="%.1f" class="lab" text-anchor="middle" '
             'transform="rotate(-90 14 %.1f)">%s</text>' % (pt + ih / 2, pt + ih / 2, ylab))
    for s in series:
        pts = " ".join("%.1f,%.1f" % (X(x), Y(min(y, ymax))) for x, y in zip(s["x"], s["y"]))
        dash = ' stroke-dasharray="6 4"' if s.get("dash") else ""
        p.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2"%s/>'
                 % (pts, s["color"], dash))
        p.append('<text x="%.1f" y="%.1f" class="dl" fill="%s">%s</text>'
                 % (X(s["x"][-1]) + 5, Y(min(s["y"][-1], ymax)) + 4, s["color"], s["name"]))
    p.append('<line class="cross" x1="0" y1="%d" x2="0" y2="%d" stroke="currentColor" '
             'opacity="0.4" visibility="hidden"/>' % (pt, pt + ih))
    p.append("</svg>")
    blob = {"xmax": xmax, "ymax": ymax, "pl": pl, "pr": pr, "pt": pt, "pb": pb,
            "w": cw, "h": chh,
            "series": [{"name": s["name"], "color": s["color"],
                        "x": [round(float(v), 4) for v in s["x"]],
                        "y": [round(float(v), 4) for v in s["y"]]} for s in series]}
    table = ['<details><summary>data table</summary><table class="data"><tr><th>%s</th>' % xlab]
    table += ["<th>%s</th>" % s["name"] for s in series]
    table.append("</tr>")
    xs = series[0]["x"]
    step = max(1, len(xs) // 24)
    for i in range(0, len(xs), step):
        table.append("<tr><td>" + (xfmt % xs[i]) + "</td>")
        for s in series:
            table.append("<td>%s</td>" % (yfmt % s["y"][i] if i < len(s["y"]) else ""))
        table.append("</tr>")
    table.append("</table></details>")
    return ('<div class="chart"><script type="application/json">%s</script>%s'
            '<div class="tip" hidden></div>%s</div>'
            % (json.dumps(blob), "".join(p), "".join(table)))


TIP_JS = """
document.querySelectorAll('.chart').forEach(function(ch){
  var cfg=JSON.parse(ch.querySelector('script').textContent);
  var svg=ch.querySelector('svg'),tip=ch.querySelector('.tip');
  var cross=ch.querySelector('.cross');
  var iw=cfg.w-cfg.pl-cfg.pr;
  svg.addEventListener('mousemove',function(ev){
    var r=svg.getBoundingClientRect();
    var mx=(ev.clientX-r.left)*cfg.w/r.width;
    var xv=(mx-cfg.pl)/iw*cfg.xmax;
    if(xv<0||xv>cfg.xmax){tip.hidden=true;cross.setAttribute('visibility','hidden');return;}
    var rows=[];
    cfg.series.forEach(function(s){
      var best=0,bd=1e9;
      for(var i=0;i<s.x.length;i++){var d=Math.abs(s.x[i]-xv);if(d<bd){bd=d;best=i;}}
      rows.push('<span style="color:'+s.color+'">\\u25cf</span> '+s.name+' '+s.y[best].toFixed(3));
    });
    cross.setAttribute('x1',mx);cross.setAttribute('x2',mx);
    cross.setAttribute('visibility','visible');
    tip.innerHTML='x = '+xv.toFixed(3)+'<br>'+rows.join('<br>');
    tip.hidden=false;
    tip.style.left=Math.min(ev.clientX-r.left+14,r.width-160)+'px';
    tip.style.top=(ev.clientY-r.top+10)+'px';
  });
  svg.addEventListener('mouseleave',function(){tip.hidden=true;
    cross.setAttribute('visibility','hidden');});
});
"""


def _pick(rows, model, lens, klass, frame):
    return [r for r in rows if (r["meta"].get("Model") or "?").strip() == model
            and (r["meta"].get("LensModel") or r["meta"].get("Model") or "?").strip() == lens
            and r["klass"] == klass and r["frame"] == frame]


def render_sections(prof):
    """Return list of {title, note, html} sections for a profile page."""
    W, H = STIMULUS
    dirs = existing_dirs()
    rows = report.collect(dirs)
    model, lens = prof["model"], prof["lens"]
    sections = []

    def pick(klass, frame):
        return _pick(rows, model, lens, klass, frame)

    # ---- MTF ----
    cands = []
    for klass in ("raw", "jpeg"):
        for r in pick(klass, "edges"):
            m = report.mtf_fields(r["stem"] + ".reg.png", W, H)
            if m:
                cands.append((np.median([v["mtf50"] for v in m.values()]), m, klass))
    if cands:
        _, best, klass = max(cands, key=lambda t: t[0])
        series, tiles = [], []
        for i, name in enumerate(["center", "mid", "corner"]):
            if name in best:
                series.append({"name": "%s %.2f" % (name, best[name]["mtf50"]),
                               "color": ORDINAL[i], "x": best[name]["freq"],
                               "y": best[name]["mtf"]})
                tiles.append((name, best[name]["mtf50"]))
        chart = svg_chart(series, 0.5, 1.0, "cycles / stimulus px", "MTF")
        tile_html = "".join("<div class='tile'><div class='v'>%.3f</div>"
                            "<div class='k'>MTF50 %s</div></div>" % (v, n) for n, v in tiles)
        sections.append({"title": "Resolution — slanted-edge MTF", "klass": klass,
                         "note": "Higher curve = more contrast kept at that detail "
                         "frequency. MTF50 is the practical sharpness number; the "
                         "center-to-corner spread is the lens's field character.",
                         "html": "<div class='tiles' style='margin-bottom:14px'>%s</div>"
                         "<div class='card tight'>%s</div>" % (tile_html, chart)})

    # ---- tone curves ----
    series = []
    for klass, dash in (("raw", False), ("jpeg", True)):
        cand = []
        for r in pick(klass, "tone"):
            tp = r["stem"] + ".tone.json"
            if os.path.exists(tp):
                t = json.load(open(tp))
                white = np.mean(t["gray_steps"][20]["rgb"])
                cand.append((white, t))
        if not cand:
            continue
        _, t = max(cand, key=lambda c: c[0])
        xs = list(range(0, 256, 4))
        for ch_name, comp in (("R", 0), ("G", 1), ("B", 2)):
            ramp = t.get("ramps", {}).get(ch_name)
            if ramp is None:
                continue
            series.append({"name": ch_name + (" jpg" if dash else " raw"),
                           "color": CH[ch_name.lower()], "dash": dash,
                           "x": xs, "y": [ramp[i][comp] for i in xs]})
    if series:
        sections.append({"title": "Tone response — per-channel transfer",
                         "note": "Stimulus level in, measured level out (tone-frame "
                         "ramps). Raw solid, camera-JPEG dashed; the gap is the body's "
                         "processing. Raw is linear-decoded, so it looks dark — that "
                         "linearity is the point.",
                         "html": "<div class='card tight'>%s</div>"
                         % svg_chart(series, 255, 255, "stimulus level", "measured level",
                                     yfmt="%.0f", xfmt="%.0f")})

    # ---- vignette ----
    xs = [0.1, 0.3, 0.5, 0.7, 0.875]
    profs = [pp for r in pick("raw", "flat")
             if (pp := report.radial_profile(r["stem"] + ".reg.png", W, H))]
    if not profs:
        profs = [pp for r in pick("jpeg", "flat")
                 if (pp := report.radial_profile(r["stem"] + ".reg.png", W, H))]
    if profs:
        series = [{"name": "illumination", "color": SLOTS[0], "x": xs,
                   "y": np.mean(profs, axis=0).tolist()}]
        sections.append({"title": "Vignette — illumination falloff",
                         "note": "Relative to center. Includes display non-uniformity, "
                         "identical for every lens on the same display.",
                         "html": "<div class='card tight' style='max-width:640px'>%s</div>"
                         % svg_chart(series, 1.0, 1.05, "field radius", "relative illumination")})

    # ---- glare tiles ----
    tile_html = ""
    for klass in ("raw", "jpeg"):
        vals = [v for r in pick(klass, "split")
                if (v := report.glare(r["stem"] + ".reg.png", W, H)) is not None]
        if vals:
            tile_html += ("<div class='tile'><div class='v'>%.2f%%</div>"
                          "<div class='k'>veiling glare · %s (n=%d)</div></div>"
                          % (float(np.mean(vals)), klass, len(vals)))
    if tile_html:
        sections.append({"title": "Veiling glare (haze)",
                         "note": "Black-side spill far from the white half of the split "
                         "frame, as % of white. Lower = clearer shadows.",
                         "html": "<div class='tiles'>%s</div>" % tile_html})

    # ---- PSF ----
    psf_html = ""
    for klass in ("raw", "jpeg"):
        for r in pick(klass, "points")[:1]:
            th = report.psf_thumbs(r["stem"] + ".reg.png", W, H)
            if th:
                psf_html = "".join("<figure><img src='data:image/png;base64,%s'>"
                                   "<figcaption>%s</figcaption></figure>" % (b, n)
                                   for n, b in th)
        if psf_html:
            break
    if psf_html:
        sections.append({"title": "PSF — point-light kernels",
                         "note": "Actual photographed point sources (gamma-lifted, 4x "
                         "nearest-neighbor). Shape and tails are the bokeh/glow signature.",
                         "html": "<div class='card tight'><div class='psf'>%s</div></div>" % psf_html})

    return sections
