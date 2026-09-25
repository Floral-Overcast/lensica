#!/usr/bin/env python3
"""Visual profile report from processed session folders.

Reads the .reg.png / .tone.json / .meta.json outputs of run_session.py and
renders one self-contained dark HTML page: per-channel tone curves, slanted-
edge MTF (frequency response) by field position, vignette falloff, veiling
glare, and PSF crops from the points frames. Charts are inline SVG with a
shared hover tooltip and a data table per chart.

usage: report.py <processed-dir> [<processed-dir> ...] --size 1640x2360
                 [--out report.html]
"""
import argparse
import base64
import glob
import json
import os
import sys

import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "extract"))
import mtf  # noqa: E402
import rignames  # noqa: E402

# palette (dark mode steps, validated set)
SURFACE, PAGE = "#1a1a19", "#0d0d0d"
INK, INK2, MUTED = "#ffffff", "#c3c2b7", "#898781"
GRID, AXIS = "#2c2c2a", "#383835"
SLOTS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"]  # per lens
CH = {"r": "#e66767", "g": "#008300", "b": "#3987e5", "y": "#c3c2b7"}
ORDINAL = ["#6da7ec", "#2a78d6", "#184f95"]  # center / mid / corner


def to8(img):
    return img if img.dtype == np.uint8 else (img / 257.0).astype(np.uint8)


def f255(img):
    return img.astype(np.float64) / (257.0 if img.dtype != np.uint8 else 1.0)


def collect(dirs):
    """rows: {group, klass, frame, stem, reg, meta}"""
    rows = []
    for d in dirs:
        for mp in sorted(glob.glob(os.path.join(d, "*.meta.json"))):
            stem = mp[:-10]
            base = os.path.basename(stem)
            frame = base.split("-")[0]
            klass = "raw" if "-raw-" in base else "jpeg"
            meta = json.load(open(mp))
            rows.append({"group": rignames.from_meta(meta) or "?", "klass": klass,
                         "frame": frame, "stem": stem, "meta": meta})
    return rows


def radial_profile(path, W, H):
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None:
        return None
    L = im.astype(np.float64).mean(axis=2)
    m = 200
    ctr = L[H // 2 - 150:H // 2 + 150, W // 2 - 150:W // 2 + 150].mean()
    if ctr <= 0:
        return None
    yy, xx = np.mgrid[0:H, 0:W]
    r = np.hypot((xx - W / 2) / (W / 2), (yy - H / 2) / (H / 2)) / np.sqrt(2)
    prof = []
    for lo, hi in [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, .95)]:
        mask = (r >= lo) & (r < hi)
        mask[:m, :m] = mask[:m, -m:] = mask[-m:, :m] = mask[-m:, -m:] = False
        prof.append(L[mask].mean() / ctr)
    return prof


def glare(path, W, H):
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None:
        return None
    lum = f255(im).mean(axis=2)[int(H * 0.3):int(H * 0.7)]
    white = np.median(lum[:, int(W * 0.15):int(W * 0.35)])
    far = np.median(lum[:, int(W * 0.70):int(W * 0.80)])
    if white < 5:
        return None
    return far / white * 100.0


def mtf_fields(path, W, H):
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None:
        return None
    g = f255(im).mean(axis=2)
    res = mtf.extract(g, W, H)
    if not res:
        return None
    fields = {"center": ["11"], "mid": ["01", "10", "21", "12"],
              "corner": ["00", "20", "02", "22"]}
    out = {}
    for name, keys in fields.items():
        curves = [res[k] for k in keys if k in res and res[k]["mtf50"]]
        if not curves:
            continue
        n = min(len(c["freq"]) for c in curves)
        freq = curves[0]["freq"][:n]
        avg = np.mean([c["mtf"][:n] for c in curves], axis=0)
        out[name] = {"freq": freq.tolist(), "mtf": avg.tolist(),
                     "mtf50": float(np.mean([c["mtf50"] for c in curves]))}
    return out or None


def psf_thumbs(path, W, H):
    im = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if im is None:
        return []
    L = f255(im)
    gx = [160 + 320 * k for k in range((W - 160) // 320 + 1)]
    gy = [160 + 320 * k for k in range((H - 160) // 320 + 1)]

    def nearest(tx, ty):
        return (min(gx, key=lambda v: abs(v - tx)), min(gy, key=lambda v: abs(v - ty)))
    spots = {"center": nearest(W // 2, H // 2), "edge": nearest(int(W * 0.9), H // 2),
             "corner": nearest(int(W * 0.85), int(H * 0.15))}
    thumbs = []
    for name, (x, y) in spots.items():
        c = L[max(0, y - 44):y + 44, max(0, x - 44):x + 44]
        if c.size == 0:
            continue
        top = max(np.percentile(c, 99.9), 1e-3)
        c = np.clip(c / top, 0, 1) ** 0.5 * 255
        c = cv2.resize(c.astype(np.uint8), None, fx=4, fy=4,
                       interpolation=cv2.INTER_NEAREST)
        ok, buf = cv2.imencode(".png", c)
        if ok:
            thumbs.append((name, base64.b64encode(buf.tobytes()).decode()))
    return thumbs


def svg_chart(series, xmax, ymax, xlab, ylab, cw=560, chh=330, yfmt="%.2f", xfmt="%.2f"):
    """series: [{name,color,dash,x:[...],y:[...]}]; shared hover via JSON blob."""
    pl, pr, pt, pb = 52, 110, 14, 40
    iw, ih = cw - pl - pr, chh - pt - pb

    def X(v):
        return pl + v / xmax * iw

    def Y(v):
        return pt + (1 - v / ymax) * ih
    p = ['<svg viewBox="0 0 %d %d" class="ch">' % (cw, chh)]
    for i in range(5):
        gy = Y(ymax * i / 4)
        p.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>'
                 % (pl, gy, pl + iw, gy, GRID))
        p.append('<text x="%d" y="%.1f" class="tk" text-anchor="end">%s</text>'
                 % (pl - 6, gy + 4, yfmt % (ymax * i / 4)))
    for i in range(6):
        gx = X(xmax * i / 5)
        p.append('<text x="%.1f" y="%d" class="tk" text-anchor="middle">%s</text>'
                 % (gx, pt + ih + 16, xfmt % (xmax * i / 5)))
    p.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="%s"/>'
             % (pl, pt + ih, pl + iw, pt + ih, AXIS))
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
    p.append('<line class="cross" x1="0" y1="%d" x2="0" y2="%d" stroke="%s" '
             'visibility="hidden"/>' % (pt, pt + ih, MUTED))
    p.append("</svg>")
    blob = {"xmax": xmax, "ymax": ymax, "pl": pl, "pr": pr, "pt": pt, "pb": pb,
            "w": cw, "h": chh,
            "series": [{"name": s["name"], "color": s["color"],
                        "x": [round(float(v), 4) for v in s["x"]],
                        "y": [round(float(v), 4) for v in s["y"]]} for s in series]}
    table = ['<details><summary>data table</summary><table><tr><th>%s</th>' % xlab]
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
    tip.style.left=Math.min(ev.clientX-r.left+14,r.width-150)+'px';
    tip.style.top=(ev.clientY-r.top+10)+'px';
  });
  svg.addEventListener('mouseleave',function(){tip.hidden=true;
    cross.setAttribute('visibility','hidden');});
});
"""

CSS = """
body{background:%s;color:%s;font:15px system-ui,-apple-system,"Segoe UI",sans-serif;
margin:0;padding:28px;max-width:1240px;margin:auto}
h1{font-size:22px}h2{font-size:17px;margin:34px 0 6px}
p.n{color:%s;margin:2px 0 14px;max-width:64em}
.grid{display:flex;flex-wrap:wrap;gap:18px}
.card{background:%s;border:1px solid rgba(255,255,255,.10);border-radius:10px;
padding:14px 16px}
.card h3{margin:0 0 8px;font-size:14px;color:%s;font-weight:600}
svg.ch{display:block}
.tk{font-size:11px;fill:%s}.lab{font-size:12px;fill:%s}.dl{font-size:12px;font-weight:600}
.chart{position:relative}
.tip{position:absolute;background:#000;color:%s;border:1px solid rgba(255,255,255,.15);
border-radius:6px;padding:6px 9px;font-size:12px;pointer-events:none;white-space:nowrap}
details{margin-top:6px;color:%s;font-size:12px}summary{cursor:pointer;color:%s}
table{border-collapse:collapse;margin-top:6px}
td,th{border:1px solid %s;padding:2px 8px;text-align:right;
font-variant-numeric:tabular-nums}
.tiles{display:flex;flex-wrap:wrap;gap:14px}
.tile{background:%s;border:1px solid rgba(255,255,255,.10);border-radius:10px;
padding:12px 18px;min-width:150px}
.tile .v{font-size:26px;font-weight:650}.tile .k{color:%s;font-size:12px;margin-top:2px}
.psf{display:flex;gap:10px;align-items:flex-end}
.psf figure{margin:0}.psf img{display:block;border:1px solid %s;border-radius:4px;
image-rendering:pixelated;width:176px}
.psf figcaption{color:%s;font-size:11px;text-align:center;margin-top:3px}
footer{color:%s;font-size:12px;margin-top:40px;border-top:1px solid %s;padding-top:12px}
""" % (PAGE, INK, INK2, SURFACE, INK2, MUTED, MUTED, INK, INK2, INK2, AXIS,
       SURFACE, MUTED, AXIS, MUTED, MUTED, GRID)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dirs", nargs="+")
    ap.add_argument("--size", required=True)
    ap.add_argument("--out", default="report.html")
    a = ap.parse_args()
    W, H = map(int, a.size.lower().split("x"))
    rows = collect(a.dirs)
    groups = sorted({r["group"] for r in rows})
    color = {g: SLOTS[i % len(SLOTS)] for i, g in enumerate(groups)}

    def pick(group, klass, frame):
        return [r for r in rows if r["group"] == group and r["klass"] == klass
                and r["frame"] == frame]

    html = ["<!doctype html><html><head><meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width,initial-scale=1'>",
            "<title>Lensica profile report</title><style>", CSS, "</style></head><body>",
            "<h1>Lensica profile report</h1>",
            "<p class='n'>Sessions: %s &middot; stimulus %dx%d &middot; frequencies are "
            "cycles per stimulus pixel (display-referred)</p>" % (
                ", ".join(os.path.basename(os.path.dirname(d.rstrip('/'))) for d in a.dirs), W, H)]

    # ---- MTF ----
    html.append("<h2>Resolution &mdash; slanted-edge MTF by field position</h2>"
                "<p class='n'>Raw class. Higher curve = more contrast kept at that "
                "detail frequency; MTF50 is the practical sharpness number. Corner vs "
                "center spread is the lens's field character.</p><div class='grid'>")
    mtf50_tiles = []
    for g in groups:
        cands = []
        for r in pick(g, "raw", "edges") or pick(g, "jpeg", "edges"):
            m = mtf_fields(r["stem"] + ".reg.png", W, H)
            if m:
                cands.append((np.median([v["mtf50"] for v in m.values()]), m, r["klass"]))
        if not cands:
            continue
        _, best, klass = max(cands, key=lambda t: t[0])
        series = []
        for i, name in enumerate(["center", "mid", "corner"]):
            if name in best:
                series.append({"name": "%s %.2f" % (name, best[name]["mtf50"]),
                               "color": ORDINAL[i],
                               "x": best[name]["freq"], "y": best[name]["mtf"]})
                mtf50_tiles.append((g, name, best[name]["mtf50"]))
        html.append("<div class='card'><h3>%s (%s)</h3>%s</div>"
                    % (g, klass, svg_chart(series, 0.5, 1.0,
                       "cycles / stimulus px", "MTF")))
    html.append("</div>")

    # ---- tone curves ----
    html.append("<h2>Tone response &mdash; per-channel transfer curves</h2>"
                "<p class='n'>Stimulus level in, measured level out, from the tone "
                "frame ramps. Raw solid, camera-JPEG dashed; the gap between them is "
                "the body's processing.</p><div class='grid'>")
    for g in groups:
        series = []
        for klass, dash in (("raw", False), ("jpeg", True)):
            cands = []
            for r in pick(g, klass, "tone"):
                tp = r["stem"] + ".tone.json"
                if os.path.exists(tp):
                    t = json.load(open(tp))
                    white = np.mean(t["gray_steps"][20]["rgb"])
                    cands.append((white, t))
            if not cands:
                continue
            _, t = max(cands, key=lambda c: c[0])
            xs = list(range(0, 256, 4))
            # ramps: {"Y"|"R"|"G"|"B": [[r,g,b] per input level 0..255]};
            # plot each color ramp's own channel component
            for ch_name, comp in (("R", 0), ("G", 1), ("B", 2)):
                ramp = t.get("ramps", {}).get(ch_name)
                if ramp is None:
                    continue
                series.append({"name": ch_name + (" jpg" if dash else " raw"),
                               "color": CH[ch_name.lower()], "dash": dash,
                               "x": xs, "y": [ramp[i][comp] for i in xs]})
        if series:
            html.append("<div class='card'><h3>%s</h3>%s</div>"
                        % (g, svg_chart(series, 255, 255, "stimulus level",
                           "measured level", yfmt="%.0f", xfmt="%.0f")))
    html.append("</div>")

    # ---- vignette ----
    html.append("<h2>Vignette &mdash; illumination falloff</h2>"
                "<p class='n'>Raw flat frames, relative to center. Includes display "
                "non-uniformity, which is identical for every lens on the same "
                "display, so the spread BETWEEN curves is pure lens.</p>")
    xs = [0.1, 0.3, 0.5, 0.7, 0.875]
    series = []
    for g in groups:
        profs = [p for r in pick(g, "raw", "flat")
                 if (p := radial_profile(r["stem"] + ".reg.png", W, H))]
        if profs:
            series.append({"name": g.split()[0], "color": color[g],
                           "x": xs, "y": np.mean(profs, axis=0).tolist()})
    if series:
        html.append("<div class='card' style='max-width:640px'>%s</div>"
                    % svg_chart(series, 1.0, 1.05, "field radius", "relative illumination"))

    # ---- glare ----
    html.append("<h2>Veiling glare (haze)</h2>"
                "<p class='n'>Black-side spill far from the white half of the split "
                "frame, as % of white. Lower = clearer shadows; classic uncoated-lens "
                "milkiness lives here.</p><div class='tiles'>")
    for g in groups:
        for klass in ("raw", "jpeg"):
            vals = [v for r in pick(g, klass, "split")
                    if (v := glare(r["stem"] + ".reg.png", W, H)) is not None]
            if vals:
                html.append("<div class='tile'><div class='v'>%.2f%%</div>"
                            "<div class='k'>%s &middot; %s (n=%d)</div></div>"
                            % (float(np.mean(vals)), g, klass, len(vals)))
    html.append("</div>")

    # ---- PSF ----
    html.append("<h2>PSF &mdash; point-light kernels</h2>"
                "<p class='n'>Actual photographed point sources (gamma-lifted, "
                "4x nearest-neighbor). Shape and tails ARE the bokeh/glow signature; "
                "watch the corner kernel deform.</p><div class='grid'>")
    for g in groups:
        for r in (pick(g, "raw", "points") or pick(g, "jpeg", "points"))[:1]:
            th = psf_thumbs(r["stem"] + ".reg.png", W, H)
            if th:
                figs = "".join("<figure><img src='data:image/png;base64,%s'>"
                               "<figcaption>%s</figcaption></figure>" % (b, n)
                               for n, b in th)
                html.append("<div class='card'><h3>%s (%s)</h3>"
                            "<div class='psf'>%s</div></div>" % (g, r["klass"], figs))
    html.append("</div>")

    if mtf50_tiles:
        html.append("<h2>MTF50 summary</h2><div class='tiles'>")
        for g, name, v in mtf50_tiles:
            html.append("<div class='tile'><div class='v'>%.3f</div>"
                        "<div class='k'>%s &middot; %s</div></div>" % (v, g, name))
        html.append("</div>")

    html.append("<footer>Registration warp resampling costs a little MTF equally for "
                "every capture through this pipeline: compare curves, treat absolute "
                "values as slightly pessimistic. Raw class is linear-decoded "
                "(gamma 1.0), so raw tone curves LOOK dark; that linearity is the "
                "point.</footer>")
    html.append("<script>%s</script></body></html>" % TIP_JS)
    with open(a.out, "w") as f:
        f.write("".join(html))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
