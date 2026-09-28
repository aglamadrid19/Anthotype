#!/usr/bin/env python3
"""Per-glyph column segmentation of a text band: fit font-size / letter-spacing.

Segments a rasterised text line into glyphs by finding ink column runs, then
reports each glyph's x-extent so the required advance scale and tracking can be
solved analytically instead of searched.

usage: glyphbox.py <png> <x0> <y0> <x1> <y1> [--thr N] [--minrun N]
"""
import sys
import numpy as np
from PIL import Image


def seg(ink, minrun=2, gap=1):
    col = ink.sum(axis=0)
    on = col > 0
    runs, i, n = [], 0, len(on)
    while i < n:
        if on[i]:
            j = i
            while j < n and (on[j] or (j + gap < n and on[j:j+gap+1].any())):
                j += 1
            if j - i >= minrun:
                runs.append((i, j - 1))
            i = j
        else:
            i += 1
    return runs


def main():
    p = sys.argv[1]
    x0, y0, x1, y1 = (int(v) for v in sys.argv[2:6])
    thr = int(sys.argv[sys.argv.index('--thr')+1]) if '--thr' in sys.argv else 120
    minrun = int(sys.argv[sys.argv.index('--minrun')+1]) if '--minrun' in sys.argv else 2
    a = np.asarray(Image.open(p).convert('L')).astype(np.float32)[y0:y1, x0:x1]
    ink = a > thr
    rows = np.nonzero(ink.sum(axis=1) > 0)[0]
    cols = np.nonzero(ink.sum(axis=0) > 0)[0]
    if not len(cols):
        print('no ink'); return
    runs = seg(ink, minrun)
    print(f'{p} window x{x0}-{x1} y{y0}-{y1} thr{thr}')
    print(f'  ink bbox  x {x0+cols.min()}..{x0+cols.max()} (w {cols.max()-cols.min()+1})'
          f'  y {y0+rows.min()}..{y0+rows.max()} (h {rows.max()-rows.min()+1})')
    print(f'  {len(runs)} glyph runs:')
    for (s, e) in runs:
        print(f'    x {x0+s:4d}..{x0+e:4d}  w {e-s+1:3d}  cx {x0+(s+e)/2:7.1f}')
    if len(runs) > 1:
        cx = np.array([x0+(s+e)/2 for s, e in runs])
        d = np.diff(cx)
        print(f'  advances: {np.round(d,2).tolist()}')
        print(f'  mean advance {d.mean():.3f}  first cx {cx[0]:.1f} last cx {cx[-1]:.1f} span {cx[-1]-cx[0]:.1f}')


if __name__ == '__main__':
    main()
