# Lensica — Target v1

Measurement target suite for the Lensica lens/camera look library.

Six frames per display, always rendered 1:1 at native pixels in a dark room:

1. **organic** — center-crop of the master square (cut from Matthew's 567MP noise image): dense real-texture color coverage, ~76% of the RGB cube
2. **spectrum** — smooth color-cube sweep (`--pages` mode covers all 16,777,216 RGB values exactly once)
3. **skin** — skin-tone locus grid, anchors, gradient
4. **tone** — Y/R/G/B ramps, 21-step grays, level blocks
5. **points** — point lights on black (PSF / bokeh / flare)
6. **edges** — slanted squares + distortion grid

See `CLAUDE.md` for layout, commands, and the iron rules (pixel-exact display, version lock, PNG-only stimulus, RAW + camera-JPEG as separate measurement classes).
