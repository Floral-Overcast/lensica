# Lensica

Crowd-sourced lens/camera "look" measurement library + look-recreation filters. Crinacle's IEM database, but for lenses: users photograph a standardized on-screen target suite (tripod, dark room, Apple display), we extract measurements (LUTs, maps, PSF kernels) into an evolving database. This repo = **Target v1** (test-image suite + tooling), the extraction pipeline, and the web MVP.

**Where dev happens (web/)**: active web-UI work runs in worker CT `lensica` (CT228 @ 10.2.1.228 on Seolla), which pushes to `main`. The cloud Canvas checkout stays canonical for target/extract/analysis pipeline work; don't build web features from the cloud checkout while the CT is active. Pull before pipeline edits.

## Product decisions (Matthew, 2026-09-25)
- **Name: Lensica only.** (Korean root 설/Seol lives on in the "Seolette" curve.) Web MVP at **lensica.floralovercast.com**. No seol.* subdomain.
- **Theme is a toggle, one brand:** `op-glass` = light mode, `flora-glass` = dark mode (both originated in the pioneer repo `src/styles.css` [data-theme] blocks; base token families in `~/design/families/{op,flora}` on every CT). Dark = default (Matthew: dark bg white text, de-emphasize via hue, WCAG non-negotiable).
- **Test-chart photos ARE stored** (policy changed from "never store"): archived originals let every methodology/extraction improvement re-process the whole library instead of asking users to re-shoot. Storage is cheap (TBs available); off-site migration is a someday-problem. The moat framing stays "measurements + network effects", not image hoarding. Uploads must be validated as actual image files (decode-or-reject, size caps, never executed, stored outside webroot).
- **Try-a-look uploads are the exception:** users can upload a personal photo to preview a profile/LUT on it; those are processed and discarded (session-only). Source camera matters: read EXIF (Model/LensModel) — if the source rig is profiled, apply true A→B mapping; else assume neutral sRGB and label the result "approximate — profile your camera for accuracy".
- **Public target set excludes the organic frame** until a procedural/licensed replacement exists (done.png is copyrighted collage; see Known gaps).
- The user-facing flow: step-by-step test wizard → QR code opens the target viewer on the display device → upload session → instant per-shot verdicts (frame ID, markers found, reshoot hints) → profile page (report.py-style charts) → library/compare + look-transfer demo.

## Layout
- `source/` (gitignored) — `done.png`, Matthew's 17670x32080 master noise image. THE origin artifact, do not modify; sha256 in `target/master/master-square-v1.json`.
- `analysis/score_windows.py` — one-time search that cut the best 6144x6144 square out of done.png. Re-running it is only valid for a new target version.
- `target/master/master-square-v1.png` (gitignored, on Canvas) + `.json` provenance (tracked) — the locked organic frame. 6144 side covers every Apple display (max width = Pro Display XDR 6016).
- `target/generators/generate.py` — all synthetic frames (spectrum / skin / tone / points / edges), deterministic + parametric by resolution. Code IS the artifact for these; renders are reproducible.
- `target/reference/` (gitignored) — 4096x4096 reference renders.
- `tools/cut.py` — per-display export: deterministic center-crop of the master square at the display's exact native pixels + synthetic frames at that resolution + manifest with sha256s. `--display studio-display` or `--res 2560x1600`.

## Commands (run on SEOLLA, 10.2.1.4 — the pipeline compute host since 2026-09-25)
Cloud (10.2.1.5) only stores /Sata and serves the :8097 viewer + immich; don't
run batch processing there. The repo is NFS-visible on Seolla at the same
path; deps installed on Seolla (numpy/cv2/rawpy/Pillow + exiftool). CT228
ingestion also executes on Seolla hardware by construction (LXC on Seolla).
ML/"insilico" exploration: Seolla CPU for v0 miners, vaio (BC-250) for long
overnight sweeps, SEOL 7900 XTX for image-space network training.
- `python3 analysis/score_windows.py` (one-time, ~5 min, needs ~4GB RAM)
- `python3 target/generators/generate.py all --res 4096x4096 --out target/reference`
- `python3 tools/cut.py --display macbook-pro-14 --out cuts/`
- Viewer: **http://10.2.1.5:8097** on the display device itself (`lensica-serve.service`
  on cloud, `tools/serve.py`). Auto-detects native res, generates + caches the cut
  under `cuts/web/`, tap cycles frames. iOS: Add to Home Screen for fullscreen.
- `python3 extract/selftest.py` (pipeline smoke test, must PASS)
- Deps: Pillow, numpy, opencv-python-headless (installed on cloud via pip --break-system-packages)

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
- **The master square is not shippable as-is.** done.png is a collage containing recognizable copyrighted artwork (manga covers, product/packaging shots, posters). Statistically excellent, legally fine as OUR internal baseline target, NOT distributable to users as the public Target v1 organic frame. Before public launch: replace with original/licensed art or a procedurally generated frame with matched statistics (the scorer defines "matched").
- done.png weaknesses (measured 2026-09-24): yellow-green hue hole (~6% of saturated px in 60-180°), ~2% black-clip + ~4-5% white-clip per channel. The synthetic spectrum/skin/tone frames exist to plug exactly these; clipped regions get masked at fit time.
- Display metamerism: RGB stimulus can't recover full spectral response; profiles are display-referred by design. Tag confidence accordingly.
- Screen-photo gotchas the future protocol must handle: moire (slight defocus ok for color frames), OLED PWM (shutter >= 1/30), RAW-only + locked WB on capture.
