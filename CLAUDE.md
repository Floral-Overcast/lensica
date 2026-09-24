# Lensica

Crowd-sourced lens/camera "look" measurement library + look-recreation filters. Crinacle's IEM database, but for lenses: users photograph a standardized on-screen target suite (tripod, dark room, Apple display), we extract measurements only (LUTs, maps, PSF kernels), never store their photos. This repo = **Target v1**, the test-image suite + tooling. Website/Android app come later.

## Layout
- `source/` (gitignored) — `done.png`, Matthew's 17670x32080 master noise image. THE origin artifact, do not modify; sha256 in `target/master/master-square-v1.json`.
- `analysis/score_windows.py` — one-time search that cut the best 6144x6144 square out of done.png. Re-running it is only valid for a new target version.
- `target/master/master-square-v1.png` (gitignored, on Canvas) + `.json` provenance (tracked) — the locked organic frame. 6144 side covers every Apple display (max width = Pro Display XDR 6016).
- `target/generators/generate.py` — all synthetic frames (spectrum / skin / tone / points / edges), deterministic + parametric by resolution. Code IS the artifact for these; renders are reproducible.
- `target/reference/` (gitignored) — 4096x4096 reference renders.
- `tools/cut.py` — per-display export: deterministic center-crop of the master square at the display's exact native pixels + synthetic frames at that resolution + manifest with sha256s. `--display studio-display` or `--res 2560x1600`.

## Commands (run on cloud, files are local there)
- `python3 analysis/score_windows.py` (one-time, ~5 min, needs ~4GB RAM)
- `python3 target/generators/generate.py all --res 4096x4096 --out target/reference`
- `python3 tools/cut.py --display macbook-pro-14 --out cuts/`

## Iron rules (the whole product depends on these)
- **Pixel-exact or invalid.** A target frame is only a valid stimulus displayed 1:1, native resolution, no OS scaling. Never ship a "fullscreen and let it scale" flow.
- **Version lock.** Frames are content-addressed (sha256 in manifests). Any pixel change = new target version; measurements are tagged with target version and never compared across versions without a bridge measurement.
- **Stimulus files are lossless PNG only.** Never JPEG on the stimulus side.
- **Capture side is two measurement classes:** RAW (lens+sensor) and camera-JPEG (lens+sensor+maker processing). Both are first-class, tagged separately; RAW earns higher confidence.

## Conventions
- Python + Pillow + numpy only for target tooling; no heavier deps.
- sRGB 8-bit everywhere in v1 (P3/HDR is a future target version).
- Repo is seol-owned on Canvas; after root edits `chown -R seol:seol .`; push manually at milestones (no autopush on cloud).

## Known gaps / context
- done.png weaknesses (measured 2026-09-24): yellow-green hue hole (~6% of saturated px in 60-180°), ~2% black-clip + ~4-5% white-clip per channel. The synthetic spectrum/skin/tone frames exist to plug exactly these; clipped regions get masked at fit time.
- Display metamerism: RGB stimulus can't recover full spectral response; profiles are display-referred by design. Tag confidence accordingly.
- Screen-photo gotchas the future protocol must handle: moire (slight defocus ok for color frames), OLED PWM (shutter >= 1/30), RAW-only + locked WB on capture.
