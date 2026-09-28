#!/usr/bin/env python3
"""Where does the traced render lose to the band-paint oracle?

Classifies each art-window pixel by its reference luminance and shows the render
error and the oracle error per luminance bucket, so the loss can be attributed
to bright specks vs flat fields.

usage: artgap.py <variant> [--bins 12]
"""
import os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkart, artfloor


def main():
    v = sys.argv[1]
    x0, y0, x1, y1 = mkart.BOX[v]
    ref = np.asarray(Image.open(f'{HERE}/ref-{v}.png').convert('RGB')).astype(np.float32)
    ren = np.asarray(Image.open(f'{HERE}/render-{v}.png').convert('RGB')).astype(np.float32)
    R = ref[y0:y1, x0:x1]; D = ren[y0:y1, x0:x1]
    keep = artfloor.keep_mask(v, ref.shape[:2])[y0:y1, x0:x1]
    lum = R.mean(axis=2)
    d_ren = np.abs(R - D).mean(axis=2)
    p = mkart.PARAMS[v]
    up = p['up']
    sub = np.asarray(Image.fromarray(R.astype(np.uint8))
                     .resize(((x1-x0)*up, (y1-y0)*up), Image.LANCZOS)).astype(np.float32)
    print(f'{v}: art window {x1-x0}x{y1-y0}')
    edges = np.percentile(lum, np.linspace(0, 100, 11))
    for i in range(10):
        m = keep & (lum >= edges[i]) & (lum < edges[i+1] if i < 9 else lum <= edges[i+1])
        if m.sum() < 20:
            continue
        print(f'   lum {edges[i]:6.1f}-{edges[i+1]:6.1f}  {m.sum():7d}px ({m.mean()*100:5.1f}%)  '
              f'render err {d_ren[m].mean():6.2f}  contrib {d_ren[m].sum():9.0f}')
    # highest-error pixels: what luminance are they?
    print('   top-1% error pixels by reference luminance:')
    thr = np.percentile(d_ren[keep], 99)
    hm = keep & (d_ren >= thr)
    print(f'      {hm.sum()} px, mean err {d_ren[hm].mean():.1f}, '
          f'mean lum {lum[hm].mean():.1f}, p90 lum {np.percentile(lum[hm],90):.1f}')


if __name__ == '__main__':
    main()
