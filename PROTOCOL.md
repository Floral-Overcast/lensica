# Lensica capture protocol: Target v1 (Phase 0, internal)

One session = one (body, lens, display) triple. ~15 minutes once set up.
The differential trick: shoot two lenses in ONE session without touching the
display, and the display + sensor cancel out of the lens comparison.

Treat it like an event: plan every body + lens combo you want to measure,
gather them all, then take one windowless room, kill the lights, put an Apple
device on, and run the combos back to back. One evening gets you several
profiles.

## Gear
- Camera with RAW (+JPEG if the body's processing look is wanted too, it's a
  separate measurement class, shoot RAW+JPEG)
- No tripod needed. Handheld is fine: registration warps every shot back onto
  the target pixel-for-pixel, so framing and tilt don't matter. Just take your
  clearest shot.
- Apple display, any from the cut.py table; note the exact model
- Pitch-black room: no windows leaking, no LEDs (tape over camera/monitor
  status lights), wear dark clothes (you reflect)

## Display prep (do once, don't touch again mid-session)
1. True Tone OFF, Night Shift OFF, auto-brightness OFF (macOS, iOS, and\n   iPadOS alike). Measured, not theoretical: True Tone on an iPad Air M2\n   shifted the display white ~6% redder / ~6.5% less blue at a Sony\n   sensor, and it drifts with ambient light, so it silently breaks\n   cross-session comparability.
2. Brightness to a fixed notch, roughly 2/3. Note the notch. Never change it mid-session.
3. Generate the cut for the display: `python3 tools/cut.py --display <model> --out cuts/`
4. Show each frame at exactly 1:1 native pixels, fullscreen, no UI. Preview.app:
   View > Actual Size, then fullscreen (verify no scaling: the frame's edge
   fiducials must sit at the screen edges). A dedicated fullscreen viewer
   replaces this step later.
5. Let the panel warm up ~15 min before the first frame (backlight drift).

## Camera setup
- RAW (+JPEG). Base ISO. White balance LOCKED to any fixed preset (note which).
  Never auto-WB. Manual exposure. Handheld, so leave IBIS/OIS on. Focus by
  magnified live view on a corner marker, then switch to MF and don't touch.
- Aperture: wide open (lowest f-number) by default. That's where a lens shows
  its character - vignette, glare, soft corners, and especially bokeh on the
  points frame; by f/8 most lenses converge on their best behaviour and hide
  it. A stopped-down profile is a second session, not a stricter first one.
  Phones and fixed-lens compacts: skip this, the camera decides.
- Framing: get ALL FOUR corner markers in the frame with a little margin -
  that's what registration needs. Framing and tilt don't matter beyond that;
  closer (more px per stimulus px) is more confidence.
- Exposure: on the tone frame, expose so the 255 white block sits just under
  clipping (blinkies barely off). Bracket freely from there (see shot list).
- Moire check: if live view shows color moire on the organic frame, move back
  ~10% or defocus a hair. Allowed on color frames (organic/spectrum/skin/tone/
  flat), NOT on the edges frame.
- OLED/PWM: keep shutter >= 1/30s. In a dark room that's easy handheld.

## Shot list (per lens)
| # | frame | aperture | focus | notes |
|---|-------|----------|-------|-------|
| 1 | tone | wide open | corner marker | sets session exposure |
| 2 | flat | wide open | corner marker | vignetting + display uniformity |
| 3 | split | wide open | corner marker | veiling glare: white half's spill into black half |
| 4 | organic | wide open | corner marker | the big one |
| 5 | spectrum | wide open | corner marker | |
| 6 | skin | wide open | corner marker | |
| 7 | edges | wide open | corner marker | sharpest focus, no defocus |
| 8 | points | wide open | corner marker | in-focus PSF |

Bracket freely: take a bunch of shots per frame at different shutter speeds
until the set feels repeatable and complete. Ingestion keeps the best take per
frame automatically and reports what it rejected, so multiple takes are good,
not a mistake. (A deliberately defocused bokeh set is a future protocol
addition; for now every frame, points included, is in focus.)

Brightness anchoring: every frame's corner fiducials ARE a white (quiet zone,
stimulus 255) + black (marker modules, stimulus 0) reference, and register.py
writes them out as `.anchors.json`. So display brightness and exposure
differences normalize out per frame. Keep exposure fixed WITHIN a session
anyway; the anchors are the safety net and the cross-session normalizer, not
an excuse to ride the dials.

Focusing on the points frame: AF hunts on a black field with sparse dots,
especially on phones. Do NOT add room light for it (that contaminates PSF
tails and glare). Acquire focus on the previous bright frame (flat/edges),
then lock it (iPhone/Samsung: long-press AE/AF lock; or pro-mode manual
focus) and cycle to points without refocusing; the display distance is
unchanged, so the lock is exact. A dim light BEHIND the camera, aimed away,
is a last resort for framing only; kill it before the exposure.

Then swap lens and repeat 1-8 (re-frame as needed).
Darkness check: one exposure with the display showing pure black; anything
visible in it is light leak, fix the room.

## Session folder
`captures/<yyyy-mm-dd>_<body>_<lens>_<display>/` containing the raws/jpegs named
`01-tone.RAF`, `02-flat.RAF`, ... plus `notes.txt`: body, lens (exact, incl.
adapter), display model + brightness notch, WB preset, distance, anything odd.
Never delete the raws; the pipeline stores measurements, but re-extraction
needs the originals until the profile format is stable.

## Extraction (v0)
Convert RAW to 16-bit TIFF with NO corrections (or feed camera JPEG for the
jpeg-pipeline class), then per frame:
`python3 extract/register.py <capture> --frame tone --cut cuts/<display>/` then
`python3 extract/tone_curves.py <registered.png> --out profile/`
Self-test without a camera: `python3 extract/selftest.py` (simulates a capture
and must recover the injected curve).
