#!/usr/bin/env python3
"""Row-by-row numeric scan of a region: silhouette extents (green ink) and
bright strokes (lum), so geometry can be read instead of eyeballed."""
import sys, os
import numpy as np
from PIL import Image

QA = os.path.dirname(os.path.abspath(__file__))

def scan(name, v, box, step=4):
    x0, y0, x1, y1 = box
    a = np.asarray(Image.open(f"{QA}/{name}-{v}.png").convert('RGB')).astype(np.int16)
    sub = a[y0:y1, x0:x1]
    bg = np.array([0, 10, 7])
    ink = np.abs(sub - bg).sum(axis=2) > 40
    lum = sub.mean(axis=2)
    bright = lum > 170
    rows = []
    for i in range(0, sub.shape[0]):
        ii = ink[i]
        xs = np.nonzero(ii)[0]
        bs = np.nonzero(bright[i])[0]
        if len(xs) == 0:
            rows.append((y0+i, None, None, None, None, 0))
        else:
            rows.append((y0+i, int(xs.min()+x0), int(xs.max()+x0),
                         int(bs.min()+x0) if len(bs) else None,
                         int(bs.max()+x0) if len(bs) else None, int(bright[i].sum())))
    return rows

def main():
    box = tuple(map(int, sys.argv[1:5]))
    v = sys.argv[5] if len(sys.argv) > 5 else 'a'
    step = int(sys.argv[6]) if len(sys.argv) > 6 else 4
    for px in ('ref', 'render'):
        print(f"--- {px}  box={box}   (y, inkX0, inkX1, brightX0, brightX1, nBright)")
        for r in scan(px, v, box, step)[::step]:
            y, a, b, c, d, n = r
            if a is None:
                print(f"  {y:4d}      -")
            else:
                print(f"  {y:4d}  {a:5d} {b:5d}   {str(c):>5} {str(d):>5}   {n:4d}")
        print()

if __name__ == '__main__':
    main()
