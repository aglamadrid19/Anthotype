#!/usr/bin/env python3
"""Measure the brand row's ink bboxes in ref and render and report offsets.

usage: brandfit.py <variant>
"""
import os, sys
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))

SPLIT = {'a': 60, 'b': 112, 'c': 96}
WIN = {'a': (30, 300, 460, 360), 'b': (30, 110, 340, 195), 'c': (40, 178, 320, 228)}

def ink(p, win, thr=35):
    a = np.asarray(Image.open(p).convert('RGB')).astype(np.float32)
    x0, y0, x1, y1 = win
    lum = a[y0:y1, x0:x1].mean(axis=2)
    m = lum > np.median(lum[:3, :3]) + thr
    ys, xs = np.nonzero(m)
    if not len(xs): return None
    return (int(x0+xs.min()), int(y0+ys.min()), int(x0+xs.max()), int(y0+ys.max()))

def main():
    v = sys.argv[1]
    win = WIN[v]; sp = SPLIT[v]
    for tag, path in (('ref', f'{HERE}/ref-{v}.png'), ('ren', f'{HERE}/render-{v}.png')):
        wm = (win[0], win[1], sp, win[3])
        ww = (sp, win[1], win[2], win[3])
        i = ink(path, wm); w = ink(path, ww)
        print(f'{tag} mark {i}  word {w}')

if __name__ == '__main__':
    main()
