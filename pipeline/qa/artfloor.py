#!/usr/bin/env python3
"""True art-only floor: band-paint oracle vs the real render, both masked to the
art window and *excluding* the live-text rectangles (so glyph rasterisation can
neither flatter nor penalise the trace).

usage: artfloor.py <variant> [--blur F] [--dump FILE]
"""
import os, sys
import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkart


def keep_mask(v, shape):
    x0, y0, x1, y1 = mkart.BOX[v]
    m = np.zeros(shape, bool)
    m[y0:y1, x0:x1] = True
    for (a0, b0, a1, b1) in mkart.TEXT[v]:
        m[max(0, b0):b1, max(0, a0):a1] = False
    return m


def main():
    v = sys.argv[1]
    blur = float(sys.argv[sys.argv.index('--blur')+1]) if '--blur' in sys.argv else 0.0
    p = mkart.PARAMS[v]
    x0, y0, x1, y1 = mkart.BOX[v]
    up = p.get('up', 1)
    ref = np.asarray(Image.open(f'{HERE}/ref-{v}.png').convert('RGB')).astype(np.float32)
    ren = np.asarray(Image.open(f'{HERE}/render-{v}.png').convert('RGB')).astype(np.float32)

    # oracle: band paint at native res (this is mkart's own mask construction)
    sub = ref[y0:y1, x0:x1]
    if up != 1:
        sub = np.asarray(Image.fromarray(sub.astype(np.uint8))
                         .resize(((x1-x0)*up, (y1-y0)*up), Image.LANCZOS)).astype(np.float32)
    lum = sub.mean(axis=2)
    lo, hi = np.percentile(lum, 0.5), np.percentile(lum, 99.9)
    edges = np.linspace(lo, hi, p['bands']+1)
    minpx = p.get('minpx') or 4*up*up
    H2, W2 = lum.shape
    in_text = np.zeros((H2, W2), bool)
    for (tx0, ty0, tx1, ty1) in mkart.TEXT[v]:
        ax0, ay0 = max(0, tx0-x0)*up, max(0, ty0-y0)*up
        ax1, ay1 = (min(x1, tx1)-x0)*up, (min(y1, ty1)-y0)*up
        if ax1 > ax0 and ay1 > ay0:
            in_text[ay0:ay1, ax0:ax1] = True
    canvas = np.zeros((H2, W2, 3), np.float32)
    for i in range(p['bands']):
        m = (lum >= edges[i]) if i == p['bands']-1 else ((lum >= edges[i]) & (lum < edges[i+1]))
        if m.sum() < minpx:
            continue
        col = np.median(sub[m], axis=0)
        if col.mean() > p['text_lum_max']:
            m = m & ~in_text
            if m.sum() < minpx:
                continue
            col = np.median(sub[m], axis=0)
        canvas[m] = col
    orc = np.asarray(Image.fromarray(canvas.clip(0, 255).astype(np.uint8))
                     .resize((x1-x0, y1-y0), Image.LANCZOS)).astype(np.float32)
    if blur:
        orc = np.asarray(Image.fromarray(orc.clip(0, 255).astype(np.uint8))
                         .filter(ImageFilter.GaussianBlur(blur))).astype(np.float32)
    keep = keep_mask(v, ref.shape[:2])
    do = np.abs(ref[y0:y1, x0:x1] - orc).mean(axis=2)
    dr = np.abs(ref[y0:y1, x0:x1] - ren[y0:y1, x0:x1]).mean(axis=2)
    keep = keep[y0:y1, x0:x1]
    print(f'{v}: blur={blur}')
    print(f'   oracle floor (art, no text)  {do[keep].mean():6.3f}')
    print(f'   actual render (art, no text) {dr[keep].mean():6.3f}')
    print(f'   trace overhead               {dr[keep].mean()-do[keep].mean():+6.3f}')
    if '--dump' in sys.argv:
        f = sys.argv[sys.argv.index('--dump')+1]
        both = np.concatenate([ref[y0:y1, x0:x1], orc, ren[y0:y1, x0:x1]], axis=1)
        Image.fromarray(both.clip(0, 255).astype(np.uint8)).resize(
            (both.shape[1]//2, both.shape[0]//2), Image.LANCZOS).save(f)
        print('dump ->', f)


if __name__ == '__main__':
    main()
