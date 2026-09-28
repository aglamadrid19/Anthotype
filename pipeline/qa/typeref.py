#!/usr/bin/env python3
"""Measure left-column type bands in a reference/render PNG.

Bands = contiguous runs of rows containing "type ink" inside x < XMAX.
Reports bbox, cap height, dominant colour, and ink coverage per band.

usage: typeref.py <png> [xmax] [thr]
"""
import sys, numpy as np
from PIL import Image

p = sys.argv[1]
XMAX = int(sys.argv[2]) if len(sys.argv) > 2 else 430
THR = float(sys.argv[3]) if len(sys.argv) > 3 else 90.0

a = np.asarray(Image.open(p).convert('RGB')).astype(np.float32)
lum = a.mean(axis=2)
bg = np.median(lum[2:6, 2:6])
m = lum > bg + THR * 0  # placeholder
m = lum > THR
m[:, XMAX:] = False
row = m.sum(axis=1)
rows = np.nonzero(row > 0)[0]
bands = []
if len(rows):
    s = p0 = rows[0]
    for r in rows[1:]:
        if r - p0 > 3:
            bands.append((s, p0)); s = r
        p0 = r
    bands.append((s, p0))

print(f"{p}  bg={bg:.1f}  thr={THR}  x<{XMAX}   bands={len(bands)}")
for (y0, y1) in bands:
    sub = m[y0:y1+1]
    cols = np.nonzero(sub.any(axis=0))[0]
    x0, x1 = int(cols.min()), int(cols.max())
    px = a[y0:y1+1, x0:x1+1][sub[:, x0:x1+1]]
    # brightest 15% mean colour = the glyph core colour
    l = px.mean(axis=1)
    k = max(1, int(len(l)*0.15))
    idx = np.argsort(-l)[:k]
    core = px[idx].mean(axis=0)
    print(f"  y {y0:4d}-{y1:4d} h{y1-y0+1:3d}   x {x0:4d}-{x1:4d} w{x1-x0+1:4d}"
          f"   ink {int(sub.sum()):5d}   core #{int(core[0]):02x}{int(core[1]):02x}{int(core[2]):02x}"
          f"  ({core[0]:.0f},{core[1]:.0f},{core[2]:.0f})")
