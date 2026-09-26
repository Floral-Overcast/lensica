# Lensica

Measure the look of any camera and lens by photographing a standardized
on-screen target suite in a dark room. Lensica extracts the real numbers
(tone, color response, sharpness, vignette, veiling glare, PSF/bokeh) from
the shots, turns them into a shareable profile, and grows a public library
out of everyone's sessions. The audiophile world has had shared measurement
databases for years; photography never got one. This is an attempt.

Live site and library: https://lensica.floralovercast.com

## How it works

- The target suite is a set of frames (tone ramps, flat gray, white/black
  split, color spectrum, skin-tone grid, slanted edges, point lights) always
  rendered 1:1 at the display's native pixels. Every frame carries ArUco
  corner markers, so software warps each photo back onto the target pixel for
  pixel. Framing, tilt, and brightness stop mattering, and the marker zones
  double as white and black anchors.
- Test shots are taken of an Apple display. Not brand loyalty: they are
  mass-produced with tight factory calibration, which is the closest thing we
  have to everyone photographing the exact same picture. iPhones are fine.
- Capture splits into two measurement classes, kept separate on purpose:
  RAW (lens plus sensor) and camera JPEG (adds the maker's processing).
  They genuinely disagree, and both are first-class.
- Targets are versioned and content-addressed (sha256 manifests). Every
  measurement is tagged with its target version; the site rejects captures of
  stale or altered targets.
- Sessions tolerate real-world shooting: handheld is fine, multiple takes are
  encouraged, and ingestion keeps the best take per frame and reports what it
  rejected and why (blur, missing markers, ambient light).

Measurements are display-referred by design. That is a ceiling we can live
with, since everything anyone watches is on a display anyway.

## Repo layout

- `target/generators/` deterministic synthetic target frames; the code is the
  artifact, renders are reproducible at any resolution
- `tools/cut.py` per-display target export with sha256 manifest
- `tools/serve.py` the target viewer; open it on the display device, it
  auto-detects native resolution, tap cycles frames
- `extract/` registration, MTF, and measurement extraction
- `analysis/` session runner, report generation, look matching, residual
  mining
- `web/` the FastAPI app behind the live site (wizard, ingestion, profiles,
  library, try-a-look)
- `PROTOCOL.md` the shooting protocol and its reasoning

One target frame (a dense organic texture) is not in the public suite yet:
its source image contains copyrighted material, so it stays internal until a
procedural replacement with matched statistics ships. The synthetic frames
are fully reproducible from this repo.

## Run it

Python 3 with numpy, Pillow, opencv-python-headless, rawpy, and exiftool on
the path.

```
python3 target/generators/generate.py all --res 2560x1600 --out cuts/demo
python3 tools/serve.py            # target viewer for the display device
python3 extract/selftest.py       # pipeline smoke test, must print PASS
python3 analysis/run_session.py --help
cd web && python3 -m uvicorn web.server:app  # the site, locally
```

## License

- Code: AGPL-3.0 (see `LICENSE`)
- Target suite and `PROTOCOL.md`: CC BY-SA 4.0
- Library measurement data: CC BY 4.0 as it grows

## Credit

Created by Matthew Noh, a UX and Product Designer bridging infrastructure
and design.

If Lensica earns a place in your camera bag, there is a Patreon:
https://patreon.com/FloralOvercast
