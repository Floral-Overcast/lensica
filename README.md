# Lensica — Target v1

Measurement target suite for the Lensica lens/camera look library.

Eight frames per display, always rendered 1:1 at native pixels in a dark room,
each carrying corner ArUco fiducials that double as white/black anchors:

1. **tone** — Y/R/G/B ramps, 21-step grays, level blocks
2. **flat** — uniform 50% gray (vignetting + display uniformity)
3. **split** — half white / half black (veiling glare)
4. **organic** — center-crop of the master square (cut from Matthew's 567MP collage): dense real-texture color coverage, ~80% of the RGB cube
5. **spectrum** — smooth color-cube sweep (`--pages` mode covers all 16,777,216 RGB values exactly once)
6. **skin** — skin-tone locus grid, anchors, gradient
7. **edges** — slanted squares + distortion grid
8. **points** — point lights on black (PSF / bokeh / flare)

Viewer: `http://10.2.1.5:8097` on the display device itself (auto-detects resolution).

See `CLAUDE.md` for layout, commands, and the iron rules (pixel-exact display, version lock, PNG-only stimulus, RAW + camera-JPEG as separate measurement classes).
