#!/usr/bin/env python3
"""Potrace fidelity: rasterise the emitted band paths and compare directly to the
band-paint oracle (both on the same flat background, same resolution).

Splits the art loss into "tracer" (path != mask) and "browser" (page != path).

usage: tracefid.py <variant> [--blur F]
"""
import os, sys
import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkart, svg2png, artfloor


def oracle_paint(v):
    """Band-paint oracle at native res, exactly mkart's mask construction."""
    p = mkart.PARAMS[v]
    up = p['up']
    x0, y0, x1, y1 = mkart.BOX[v]
    ref = np.asarray(Image.open(f'{HERE}/ref-{v}.png').convert('RGB')).astype(np.float32)
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
    orc = np.asarray(Image.fromarray(canvas.clip(0,255).astype(np.uint8))
                     .resize((x1-x0, y1-y0), Image.LANCZOS)).astype(np.float32)
    # place into full page coords
    full = np.zeros(ref.shape, np.float32)
    full[y0:y1, x0:x1] = orc
    return full


def main():
    v = sys.argv[1]
    blur = float(sys.argv[sys.argv.index('--blur')+1]) if '--blur' in sys.argv else 0.0
    x0, y0, x1, y1 = mkart.BOX[v]
    keep = artfloor.keep_mask(v, (768, 1024))[y0:y1, x0:x1]

    mkart.build(v, out='/tmp/tracefid.svg', **mkart.PARAMS[v])
    svg2png.render('/tmp/tracefid.svg', '/tmp/tracefid.png', 1024, 768, '#000000')
    traced = np.asarray(Image.open('/tmp/tracefid.png').convert('RGB')).astype(np.float32)
    if blur:
        traced = np.asarray(Image.fromarray(traced.clip(0,255).astype(np.uint8))
                            .filter(ImageFilter.GaussianBlur(blur))).astype(np.float32)

    orc = oracle_paint(v)
    ref = np.asarray(Image.open(f'{HERE}/ref-{v}.png').convert('RGB')).astype(np.float32)
    ren = np.asarray(Image.open(f'{HERE}/render-{v}.png').convert('RGB')).astype(np.float32)

    t = traced[y0:y1, x0:x1]; o = orc[y0:y1, x0:x1]
    r = ref[y0:y1, x0:x1]; d = ren[y0:y1, x0:x1]
    print(f'{v}: bands={mkart.PARAMS[v]["bands"]} up={mkart.PARAMS[v]["up"]}')
    print(f'   tracer vs oracle (isolated)   {np.abs(t-o).mean(axis=2)[keep].mean():6.3f}')
    print(f'   oracle vs reference           {np.abs(o-r).mean(axis=2)[keep].mean():6.3f}')
    print(f'   traced vs reference           {np.abs(t-r).mean(axis=2)[keep].mean():6.3f}')
    print(f'   page render vs reference      {np.abs(d-r).mean(axis=2)[keep].mean():6.3f}')
    print(f'   page render vs traced         {np.abs(d-t).mean(axis=2)[keep].mean():6.3f}')


if __name__ == '__main__':
    main()
