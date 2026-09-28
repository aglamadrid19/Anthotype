#!/usr/bin/env python3
"""Per-element geometry comparison (text blocks + CTA), using windows that
avoid the artwork so measurements are not contaminated by pod/route glow."""
import sys, os
import numpy as np
from PIL import Image

QA = os.path.dirname(os.path.abspath(__file__))

# name: (window, threshold)  -- window chosen to exclude artwork on the right
ELEMENTS = {
    'h1':      ((30, 236, 470, 334), 90),
    'h2':      ((30, 334, 370, 400), 90),
    'tagline': ((30, 400, 375, 436), 70),
    'cta':     ((30, 436, 335, 516), 60),
}

def img(name, v):
    return np.asarray(Image.open(f"{QA}/{name}-{v}.png").convert('RGB')).astype(np.int16)

def mask(a, thr):
    bg = np.array([0, 10, 7])
    return (np.abs(a - bg).sum(axis=2) > thr * 3)

def measure(a, box, thr):
    x0, y0, x1, y1 = box
    sub = a[y0:y1, x0:x1]
    m = mask(sub, thr)
    if not m.any():
        return None
    ys, xs = np.nonzero(m)
    px = sub[m]
    lum = px.sum(axis=1)
    k = max(1, int(len(px) * 0.05))
    core = px[np.argsort(lum)[-k:]].mean(axis=0)
    return dict(x0=int(xs.min()+x0), x1=int(xs.max()+x0),
                y0=int(ys.min()+y0), y1=int(ys.max()+y0),
                cov=100.0 * m.mean(), core=tuple(core.round().astype(int)))

def main():
    v = sys.argv[1]
    print(f"{'element':>8} {'':>2} {'x0':>5} {'x1':>5} {'y0':>5} {'y1':>5} {'w':>5} {'h':>4} {'cov%':>6}  core")
    for name, (box, thr) in ELEMENTS.items():
        r = measure(img('ref', v), box, thr)
        s = measure(img('render', v), box, thr)
        for tag, m in (('ref', r), ('render', s)):
            if not m:
                print(f"{name:>8} {tag:>6}  (no ink)")
                continue
            print(f"{name:>8} {tag:>6} {m['x0']:5d} {m['x1']:5d} {m['y0']:5d} {m['y1']:5d} "
                  f"{m['x1']-m['x0']+1:5d} {m['y1']-m['y0']+1:4d} {m['cov']:6.2f}  {m['core']}")
        if r and s:
            print(f"{'':>8} {'DELTA':>6} {s['x0']-r['x0']:+5d} {s['x1']-r['x1']:+5d} "
                  f"{s['y0']-r['y0']:+5d} {s['y1']-r['y1']:+5d} "
                  f"{(s['x1']-s['x0'])-(r['x1']-r['x0']):+5d} {(s['y1']-s['y0'])-(r['y1']-r['y0']):+4d} "
                  f"{s['cov']-r['cov']:+6.2f}")
        print()

if __name__ == '__main__':
    main()
