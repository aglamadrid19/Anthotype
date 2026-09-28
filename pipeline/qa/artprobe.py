#!/usr/bin/env python3
"""Structural probe of dark-teal art: bright ink masks, tile detection, silhouette rows.

usage: artprobe.py <image.png> [x0 x1] [--tiles] [--rows y0 y1 step]
"""
import sys, numpy as np
from PIL import Image
from scipy import ndimage as ndi

def load(p):
    return np.asarray(Image.open(p).convert('RGB')).astype(np.float32)

def ink_mask(a, bg=None, thr=10):
    lum = a.mean(axis=2)
    if bg is None: bg = np.median(lum[:6,:6])
    return lum > bg + thr

def main():
    p = sys.argv[1]
    a = load(p)
    H,W = a.shape[:2]
    m = ink_mask(a)
    print(f"{p}  {W}x{H}  ink px {m.sum()}")
    ys,xs = np.nonzero(m)
    print(f"  bbox x {xs.min()}-{xs.max()}  y {ys.min()}-{ys.max()}")

    lab, n = ndi.label(m, structure=np.ones((3,3)))
    objs = ndi.find_objects(lab)
    sizes = ndi.sum(m, lab, range(1, n+1))
    order = np.argsort(-sizes)
    print(f"  components {n}; top 14 by area:")
    for i in order[:14]:
        sl = objs[i]
        y0,y1 = sl[0].start, sl[0].stop; x0,x1 = sl[1].start, sl[1].stop
        print(f"    #{i+1:3d} area {int(sizes[i]):6d}  x {x0:4d}-{x1:4d} ({x1-x0:3d})  y {y0:3d}-{y1:3d} ({y1-y0:3d})")

if __name__ == '__main__':
    main()
