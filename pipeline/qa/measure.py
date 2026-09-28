#!/usr/bin/env python3
"""Measure ink bounding boxes in given windows for ref/render of a variant."""
import sys, os
import numpy as np
from PIL import Image
QA = os.path.dirname(os.path.abspath(__file__))

def ink(a, thr=90):
    return np.abs(a.astype(np.int16) - np.array([0,10,7])).sum(axis=2) > thr*3

def bbox(a, box, thr=90):
    x0,y0,x1,y1 = box
    sub = a[y0:y1, x0:x1]
    m = ink(sub, thr)
    if not m.any(): return None
    ys,xs = np.nonzero(m)
    return dict(x0=int(xs.min()+x0), x1=int(xs.max()+x0), y0=int(ys.min()+y0), y1=int(ys.max()+y0),
                w=int(xs.max()-xs.min()+1), h=int(ys.max()-ys.min()+1), cov=round(100*float(m.mean()),2))

WIN = {
  'brand':   (30, 100, 470, 240),
  'h1':      (30, 230, 470, 340),
  'h2':      (30, 328, 400, 400),
  'divider': (30, 388, 400, 412),
  'tag':     (30, 400, 400, 470),
  'cta':     (30, 455, 400, 560),
}
def main():
    v = sys.argv[1]
    for src in ('ref','render'):
        a = np.asarray(Image.open(f'{QA}/{src}-{v}.png').convert('RGB'))
        print(f'--- {src} ---')
        for name, box in WIN.items():
            b = bbox(a, box)
            if b: print(f"  {name:>8}  x{b['x0']:4d}-{b['x1']:4d} y{b['y0']:4d}-{b['y1']:4d}  w{b['w']:4d} h{b['h']:3d} cov{b['cov']:6.2f}")
            else: print(f"  {name:>8}  (none)")
if __name__=='__main__': main()
