#!/usr/bin/env python3
"""Coordinate search for an overlay image's (scale, dx, dy) minimising diff to the
reference inside an artwork window.  The overlay is a full-canvas render.

usage: fit.py <ref.png> <overlay.png> <x0 y0 x1 y1> [--from s dx dy]
"""
import sys, numpy as np
from PIL import Image

def load(p, s=1.0, dx=0, dy=0, w=1024, h=768, bg=(0,10,7)):
    im = Image.open(p).convert('RGB')
    if s != 1.0:
        im = im.resize((int(round(im.width*s)), int(round(im.height*s))), Image.LANCZOS)
    canvas = Image.new('RGB', (w, h), bg)
    canvas.paste(im, (int(round(dx)), int(round(dy))))
    return np.asarray(canvas).astype(np.float32)

def score(ref, box, arr):
    x0,y0,x1,y1 = box
    return float(np.abs(ref[y0:y1,x0:x1] - arr[y0:y1,x0:x1]).mean())

if __name__ == '__main__':
    refp, ovp = sys.argv[1], sys.argv[2]
    box = tuple(map(int, sys.argv[3:7]))
    ref = np.asarray(Image.open(refp).convert('RGB')).astype(np.float32)
    best = (1e9, 1.0, 0, 0)
    if '--from' in sys.argv:
        i = sys.argv.index('--from')
        s0, dx0, dy0 = map(float, sys.argv[i+1:i+4])
        sr = np.arange(s0-0.04, s0+0.041, 0.005)
        dr = range(int(dx0)-8, int(dx0)+9, 2)
        dy_r = range(int(dy0)-8, int(dy0)+9, 2)
    else:
        sr = np.arange(0.84, 1.16, 0.03)
        dr = range(-40, 41, 6); dy_r = range(-40, 41, 6)
    for s in sr:
        for dx in dr:
            for dy in dy_r:
                v = score(ref, box, load(ovp, s, dx, dy))
                if v < best[0]: best = (v, s, dx, dy)
    print(f"BEST {best[0]:7.3f}  scale={best[1]:.3f} dx={best[2]:+d} dy={best[3]:+d}")
    # refine
    b0 = best
    for s in np.arange(b0[1]-0.02, b0[1]+0.021, 0.004):
        for dx in range(int(b0[2])-4, int(b0[2])+5):
            for dy in range(int(b0[3])-4, int(b0[3])+5):
                v = score(ref, box, load(ovp, s, dx, dy))
                if v < best[0]: best = (v, s, dx, dy)
    print(f"FINE {best[0]:7.3f}  scale={best[1]:.3f} dx={best[2]:+d} dy={best[3]:+d}")
