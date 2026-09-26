# Lensica

Crowd-sourced lens/camera "look" measurement library + look-recreation filters. Crinacle's IEM database, but for lenses: users photograph a standardized on-screen target suite (dark room, Apple display), we extract measurements (LUTs, maps, PSF kernels) into an evolving database. This repo = **Target v1** (test-image suite + tooling), the extraction pipeline, and the web MVP.

**Where dev happens (web/)**: active web-UI work runs in the project's worker container, which pushes to `master`. The private Canvas checkout stays canonical for target/extract/analysis pipeline work; don't build web features from that checkout while the worker is active. Pull before pipeline edits. Host/IP specifics and service topology live in the private ops notes (worker memory), not in this repo.

## Product decisions (Matthew, 2026-09-25)
- **Name: Lensica only.** (Korean root 설/Seol lives on in the "Seolette" curve.) Web MVP at **lensica.floralovercast.com**. No seol.* subdomain.
- **Theme is a toggle, one brand:** `op-glass` = light mode, `flora-glass` = dark mode. Dark = default (Matthew: dark bg white text, de-emphasize via hue, WCAG non-negotiable).
- **Test-chart photos ARE stored** (policy changed from "never store"): archived originals let every methodology/extraction improvement re-process the whole library instead of asking users to re-shoot. Storage is cheap; off-site migration is a someday-problem. The moat framing stays "measurements + network effects", not image hoarding. Uploads must be validated as actual image files (decode-or-reject, size caps, never executed, stored outside webroot).
- **Try-a-look uploads are the exception:** users can upload a personal photo to preview a profile/LUT on it; those are processed and discarded (session-only). Source camera matters: read EXIF (Model/LensModel). If the source rig is profiled, apply true A→B mapping; else assume neutral sRGB and label the result "approximate - profile your camera for accuracy".
- **Public target set excludes the organic frame** until a procedural/licensed replacement exists (done.png is copyrighted collage; see Known gaps).
- **Open source (Matthew, 2026-09-26):** repo is public on GitHub. Code AGPL-3.0 (premium/dual-license stays possible; Patreon is the ask). Target suite + PROTOCOL.md CC BY-SA 4.0; library data CC BY 4.0 as it grows. Keep infra topology (IPs, hostnames, container numbers, service ports) OUT of tracked files; ops details belong in the private worker memory.
- The user-facing flow: step-by-step test wizard → QR code opens the target viewer on the display device → upload session → instant per-shot verdicts (frame ID, markers found, reshoot hints) → profile page (report.py-style charts) → library/compare + look-transfer demo.

## Copy style (applies to everything a visitor reads)
Templates, docs (README/PROTOCOL), badge/status strings, section titles: all of it.
- **No em-dashes (U+2014).** Restructure instead: comma, colon, period, or parentheses. A plain hyphen with spaces " - " is fine sparingly. Title separators use " · " (e.g. "Lensica · library"). Range hyphens (f/2-f/8, 2005-2026) are plain hyphens, always fine.
- **Plain and descriptive, never salesy.** Copy describes what the thing does; it doesn't perform or sell.
- **No "it's not X, it's Y" contrastive snaps** and no drama fragments like "X or invalid". State the requirement plainly.
- **No insight-announcements** ("here's the thing", "that's the whole point", "the reality is").
- Write like a person who did the thing giving practical advice. When unsure, the smallest edit that removes the tell wins; keep Matthew's register, don't rewrite voice wholesale.

## Layout
- `source/` (gitignored) - `done.png`, Matthew's 17670x32080 master noise image. THE origin artifact, do not modify; sha256 in `target/master/master-square-v1.json`.
- `analysis/score_windows.py` - one-time search that cut the best 6144x6144 square out of done.png. Re-running it is only valid for a new target version.
- `target/master/master-square-v1.png` (gitignored, private) + `.json` provenance (tracked) - the locked organic frame. 6144 side covers every Apple display (max width = Pro Display XDR 6016).
- `target/generators/generate.py` - all synthetic frames (spectrum / skin / tone / points / edges), deterministic + parametric by resolution. Code IS the artifact for these; renders are reproducible.
- `target/reference/` (gitignored) - 4096x4096 reference renders.
- `tools/cut.py` - per-display export: deterministic center-crop of the master square at the display's exact native pixels + synthetic frames at that resolution + manifest with sha256s. `--display studio-display` or `--res 2560x1600`.

## Commands (pipeline host; see private ops notes for topology)
- `python3 analysis/score_windows.py` (one-time, ~5 min, needs ~4GB RAM)
- `python3 target/generators/generate.py all --res 4096x4096 --out target/reference`
- `python3 tools/cut.py --display macbook-pro-14 --out cuts/`
- Viewer: `tools/serve.py` (runs as a systemd service on the storage host). Open it on the display device itself; it auto-detects native res, generates + caches the cut, tap cycles frames. iOS: Add to Home Screen for fullscreen.
- `python3 extract/selftest.py` (pipeline smoke test, must PASS)
- Deps: Pillow, numpy, opencv-python-headless, rawpy + exiftool for capture ingest

## Iron rules (the whole product depends on these)
- **Pixel-exact only.** A target frame is only a valid stimulus displayed 1:1, native resolution, no OS scaling. Never ship a "fullscreen and let it scale" flow.
- **Version lock.** Frames are content-addressed (sha256 in manifests). Any pixel change = new target version; measurements are tagged with target version and never compared across versions without a bridge measurement.
- **Stimulus files are lossless PNG only.** Never JPEG on the stimulus side.
- **Capture side is two measurement classes:** RAW (lens+sensor) and camera-JPEG (lens+sensor+maker processing). Both are first-class, tagged separately; RAW earns higher confidence.

## Conventions
- Python + Pillow + numpy only for target tooling; no heavier deps.
- sRGB 8-bit everywhere in v1 (P3/HDR is a future target version).
- Push manually at milestones from the canonical checkout; the worker container pushes its own web/ commits.

## Known gaps / context
- **The master square is not shippable as-is.** done.png is a collage containing recognizable copyrighted artwork (manga covers, product/packaging shots, posters). Statistically excellent, legally fine as OUR internal baseline target, NOT distributable to users as the public Target v1 organic frame. Before it ever ships: replace with original/licensed art or a procedurally generated frame with matched statistics (the scorer defines "matched").
- done.png weaknesses (measured 2026-09-24): yellow-green hue hole (~6% of saturated px in 60-180°), ~2% black-clip + ~4-5% white-clip per channel. The synthetic spectrum/skin/tone frames exist to plug exactly these; clipped regions get masked at fit time.
- Display metamerism: RGB stimulus can't recover full spectral response; profiles are display-referred by design. Tag confidence accordingly.
- Screen-photo gotchas the protocol handles: moire (slight defocus ok for color frames), OLED PWM (shutter >= 1/30), RAW + locked WB preferred on capture.
