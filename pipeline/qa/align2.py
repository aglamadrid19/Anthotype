#!/usr/bin/env python3
"""Search (scale, dx, dy) mapping src image region onto dst region to minimise diff.
usage: align2.py <src.png> <dst.png> <x0 y0 x1 y1> [coarse]
"""
import sys, numpy as np
from PIL import Image

def load(p): return np.asarray(Image.open(p).convert('RGB')).astype(np.float32)

def best(src, dst, box, srange, drange):
    x0,y0,x1,y1 = box
    H,W = y1-y0, x1-x0
    ref = dst[y0:y1, x0:x1]
    out=[]
    for s in srange:
        sh, sw = int(H*s), int(W*s)
        cx0, cy0 = (x0+x1)//2, (y0+y1)//2
        im = Image.fromarray(src.astype(np.uint8))
        # crop a region of src at scale about centre
        crop = im.transform((W,H), Image.AFFINE,
            (1/s, 0, cx0-(cx0)*0, 0, 1/s, cy0-(cy0)*0), resample=Image.BILINEAR)
        a = np.asarray(crop).astype(np.float32)
        for dx in drange:
            for dy in drange:
                b = np.roll(np.roll(a, dy, axis=0), dx, axis=1)
                out.append((float(np.abs(ref-b).mean()), s, dx, dy))
    out.sort()
    return out[:10]

if __name__ == '__main__':
    a = sys.argv[1]; b = sys.argv[2]
    box = tuple(map(int, sys.argv[3:7]))
    coarse = sys.argv[7:] if len(sys.argv) > 7 else None
    src = load(a); dst = load(b)
    if not coarse:
        res = best(src, dst, box, [0.9,0.95,1.0,1.05,1.1], range(-40,41,8))
        print('COARSE'); 
        for r in res: print(f'  {r[0]:6.2f}  s={r[1]:.3f} dx={r[2]:+d} dy={r[3]:+d}')
        _, s0, dx0, dy0 = res[0]
        srange = np.arange(s0-0.035, s0+0.036, 0.01)
        dr = sorted(set(list(range(dx0-8,dx0+9,2)) + list(range(dy0-8,dy0+9,2))))
        print('FINE')
        for r in best(src, dst, box, srange, dr)[:6]: print(f'  {r[0]:6.2f}  s={r[1]:.3f} dx={r[2]:+d} dy={r[3]:+d}')
