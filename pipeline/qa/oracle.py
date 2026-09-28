#!/usr/bin/env python3
"""Fast (no-render) oracle: band-quantisation floor for a given (up, bands, minpx).

Paints the luminance bands at `up` scale, downsamples to native res, and scores
against the reference inside the art window.  This is the best any tracer could
do at that resolution/band count, so it ranks candidates cheaply before paying
for potrace + Chrome.

usage: oracle.py <variant> [--ups 1,2,4] [--bands 6,12,24] [--minpx N] [--uniform]
"""
import itertools, os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkart


def band_masks(v, up, bands):
    x0, y0, x1, y1 = mkart.BOX[v]
    a = np.asarray(Image.open(f'{HERE}/ref-{v}.png').convert('RGB')).astype(np.float32)
    sub = a[y0:y1, x0:x1]
    if up != 1:
        sub = np.asarray(Image.fromarray(sub.astype(np.uint8))
                         .resize(((x1-x0)*up, (y1-y0)*up), Image.LANCZOS)).astype(np.float32)
    return sub, sub.mean(axis=2), (x0, y0, x1, y1)


def oracle(v, up, bands, minpx=0, edges_mode='uniform'):
    sub, lum, box = band_masks(v, up, bands)
    lo, hi = np.percentile(lum, 0.5), np.percentile(lum, 99.9)
    if edges_mode == 'uniform':
        edges = np.linspace(lo, hi, bands+1)
    else:  # quantile edges: equal pixel mass per band
        qs = np.linspace(0.5, 99.9, bands+1)
        edges = np.percentile(lum, qs)
    H, W = lum.shape
    canvas = np.zeros((H, W, 3), np.float32)
    prev = np.zeros((H, W), bool)
    for i in range(bands):
        m = (lum >= edges[i]) if i == bands-1 else ((lum >= edges[i]) & (lum < edges[i+1]))
        if minpx and m.sum() < minpx:
            m = np.zeros_like(m)
        col = np.median(sub[m], axis=0) if m.any() else None
        if col is None:
            continue
        canvas[m] = col
    b = box
    ren = np.asarray(Image.fromarray(canvas.clip(0, 255).astype(np.uint8))
                     .resize((b[2]-b[0], b[3]-b[1]), Image.LANCZOS)).astype(np.float32)
    ref = np.asarray(Image.open(f'{HERE}/ref-{v}.png').convert('RGB')).astype(np.float32)[b[1]:b[3], b[0]:b[2]]
    return float(np.abs(ref - ren).mean())


def main():
    v = sys.argv[1]
    def arg(n, d): return sys.argv[sys.argv.index(n)+1] if n in sys.argv else d
    ups = [int(x) for x in arg('--ups', '1,2,4,6,8').split(',')]
    bds = [int(x) for x in arg('--bands', '6,10,16,24,40').split(',')]
    mode = 'quantile' if '--quantile' in sys.argv else 'uniform'
    print(f'{v}  mode={mode}')
    print('   bands ' + ''.join(f'up{u:<7d}' for u in ups))
    for bands in bds:
        row = f'   {bands:5d} '
        for up in ups:
            row += f'{oracle(v, up, bands, edges_mode=mode):8.3f}'
        print(row, flush=True)


if __name__ == '__main__':
    main()
