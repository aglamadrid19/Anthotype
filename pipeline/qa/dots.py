#!/usr/bin/env python3
"""Detect bright vertex dots (blobs) inside a region of the reference render."""
import sys, os
import numpy as np
from PIL import Image

QA = os.path.dirname(os.path.abspath(__file__))

def blobs(x0, y0, x1, y1, v='a', px='ref', thr=150, minsep=2):
    a = np.asarray(Image.open(f"{QA}/{px}-{v}.png").convert('RGB')).astype(np.float32)
    sub = a[y0:y1, x0:x1]
    lum = sub.mean(axis=2)
    m = lum > thr
    seen = np.zeros_like(m)
    out = []
    ys, xs = np.nonzero(m)
    order = np.argsort(-lum[ys, xs])
    for k in order:
        y, x = ys[k], xs[k]
        if seen[y, x]: continue
        # flood fill this blob
        stack = [(y, x)]; cells = []
        seen[y, x] = True
        while stack:
            cy, cx = stack.pop(); cells.append((cy, cx))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = cy+dy, cx+dx
                    if 0 <= ny < m.shape[0] and 0 <= nx < m.shape[1] and m[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True; stack.append((ny, nx))
        if len(cells) < minsep: continue
        arr = np.array(cells)
        w = np.clip(lum[arr[:, 0], arr[:, 1]] - thr, 0, None)
        cyc = (arr[:, 0] * w).sum() / w.sum()
        cxc = (arr[:, 1] * w).sum() / w.sum()
        out.append((float(cxc + x0), float(cyc + y0), len(cells), float(lum[arr[:, 0], arr[:, 1]].max())))
    out.sort(key=lambda t: -t[2])
    return out

if __name__ == '__main__':
    box = tuple(map(int, sys.argv[1:5]))
    v = sys.argv[5] if len(sys.argv) > 5 else 'a'
    thr = int(sys.argv[6]) if len(sys.argv) > 6 else 150
    for px in ('ref', 'render'):
        ds = blobs(*box, v=v, px=px, thr=thr)
        print(f"{px}: {len(ds)} blobs (>=2px)")
        for x, y, n, mx in ds[:80]:
            print(f"   ({x:7.2f},{y:7.2f}) area {n:4d} peak {mx:5.1f}")
        print()
