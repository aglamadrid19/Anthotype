#!/usr/bin/env python3
"""Channel overlay: reference ink -> magenta, render ink -> green.
Perfect alignment reads as neutral grey/white; offsets show as colour fringes.
usage: overlay.py <variant> <x0> <y0> <x1> <y1> [zoom] [grey|ink]
"""
import sys, os
import numpy as np
from PIL import Image

QA = os.path.dirname(os.path.abspath(__file__))

def ink(a, thr=40):
    bg = np.array([0, 10, 7])
    return np.clip((np.abs(a.astype(np.int16) - bg).sum(axis=2) - thr) / 80.0, 0, 1)

def main():
    v = sys.argv[1]
    x0, y0, x1, y1 = map(int, sys.argv[2:6])
    Z = int(sys.argv[6]) if len(sys.argv) > 6 else 5
    mode = sys.argv[7] if len(sys.argv) > 7 else 'ink'
    a = np.asarray(Image.open(f"{QA}/ref-{v}.png").convert('RGB'))
    b = np.asarray(Image.open(f"{QA}/render-{v}.png").convert('RGB'))
    if mode == 'grey':
        ma = a[y0:y1, x0:x1].mean(axis=2) / 255.0
        mb = b[y0:y1, x0:x1].mean(axis=2) / 255.0
    else:
        ma = ink(a[y0:y1, x0:x1])
        mb = ink(b[y0:y1, x0:x1])
    out = np.zeros(ma.shape + (3,), np.float32)
    out[:, :, 0] = ma           # reference -> red
    out[:, :, 2] = ma           # reference -> also blue (magenta)
    out[:, :, 1] = mb           # render -> green
    im = Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8))
    w, h = im.size
    im = im.resize((w*Z, h*Z), Image.NEAREST)
    p = f"{QA}/overlay-{v}.png"
    im.save(p)
    d = np.abs(ma - mb)
    print(f"overlay {mode} box=({x0},{y0},{x1},{y1}) zoom x{Z}  mismatch mean {d.mean():.4f}  "
          f"pct>0.35 {100*(d>0.35).mean():.2f}%")
    print(p)

if __name__ == '__main__':
    main()
