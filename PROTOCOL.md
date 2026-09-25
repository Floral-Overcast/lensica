# Lensica capture protocol — Target v1 (Phase 0, internal)

One session = one (body, lens, display) triple. ~15 minutes once set up.
The differential trick: shoot two lenses in ONE session without touching the
display, and the display + sensor cancel out of the lens comparison.

## Gear
- Camera with RAW (+JPEG if the body's processing look is wanted too, it's a
  separate measurement class, shoot RAW+JPEG)
- Sturdy tripod, 2s timer or remote (never finger-press)
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
  Never auto-WB. Manual exposure. IBIS/OIS OFF (tripod). Focus by magnified
  live view on a corner fiducial, then switch to MF and don't touch.
- Framing: square to the screen (bubble level), centered, ALL FOUR corner
  fiducials well inside frame with ~5% margin. Closer = more px per stimulus px
  = more confidence.
- Exposure: on the tone frame, expose so the 255 white block sits just under
  clipping (blinkies barely off). Note shutter. Reuse that exposure for every
  color frame in the session.
- Moire check: if live view shows color moire on the organic frame, move back
  ~10% or defocus a hair. Allowed on color frames (organic/spectrum/skin/tone/
  flat), NOT on the edges frame.
- OLED/PWM: keep shutter >= 1/30s. On a tripod in the dark that's natural.

## Shot list (per lens)
| # | frame | aperture | focus | notes |
|---|-------|----------|-------|-------|
| 1 | tone | f/5.6-f/8 | screen | sets session exposure |
| 2 | flat | same | screen | vignetting + display uniformity |
| 3 | split | same | screen | veiling glare: white half's spill into black half |
| 4 | organic | same | screen | the big one; 2nd shot at +1EV optional |
| 5 | spectrum | same | screen | |
| 6 | skin | same | screen | |
| 7 | edges | same | screen | sharpest focus, no defocus allowed |
| 8 | points | wide open | screen | in-focus PSF |
| 9 | points | wide open | racked to MFD | bokeh balls (defocused) |
| 10 | points | 2 stops down | racked to MFD | aperture-shape bokeh |

Brightness anchoring: every frame's corner fiducials ARE a white (quiet zone,
stimulus 255) + black (marker modules, stimulus 0) reference, and register.py
writes them out as `.anchors.json`. So display brightness and exposure
differences normalize out per frame. Keep exposure fixed WITHIN a session
anyway; the anchors are the safety net and the cross-session normalizer, not
an excuse to ride the dials.

Then swap lens, same tripod position (re-frame as needed), repeat 1-9.
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
