#!/usr/bin/env python3
"""How close can the *banded trace* itself get?  Paint the band masks at native
resolution (what potrace reconstructs, minus its curve fitting) and score that
against the reference.  Isolates representation error from browser/blur error.

usage: artrecon.py <variant> [--bands N] [--up K] [--minpx N] [--dump FILE]
                   [--blur S]
"""
import os, sys
import numpy as np
from PIL import Image, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch, mkart

def bands_of(v, bands=None, up=2, minpx=None):
    p = mkart.PARAMS[v]
    bands = bands or p['bands']
    minpx = p.get('minpx') if minpx is None else minpx
    x0, y0, x1, y1 = mkart.BOX[v]
    a = np.asarray(Image.open(f'{HERE}/ref-{v}.png').convert('RGB')).astype(np.float32)
    sub = a[y0:y1, x0:x1]
    if up != 1:
        sub = np.asarray(Image.fromarray(sub.astype(np.uint8))
                         .resize(((x1-x0)*up, (y1-y0)*up), Image.LANCZOS)).astype(np.float32)
    lum = sub.mean(axis=2)
    lo, hi = np.percentile(lum, 0.5), np.percentile(lum, 99.9)
    edges = np.linspace(lo, hi, bands+1)
    minpx = minpx if minpx is not None else 4*up*up
    out = []
    for i in range(bands):
        m = (lum >= edges[i]) if i == bands-1 else ((lum >= edges[i]) & (lum < edges[i+1]))
        if m.sum() < minpx: continue
        out.append((m, np.median(sub[m], axis=0)))
    return sub, out, (x0, y0, x1, y1), up

def paint(shape, bands, up):
    """Composite bands at `up` scale down to native res."""
    h, w = shape
    img = np.zeros(shape + (3,), np.float32)
    for m, col in bands:
        mm = m.reshape(h, m.shape[0]//h, w, m.shape[1]//w).mean(axis=(1, 3))
        wgt = mm[..., None]
        img = img*(1-wgt) + col*wgt
    return img

def main():
    v = sys.argv[1]
    kw = {}
    for k, t in (('--bands', int), ('--up', int), ('--minpx', int)):
        if k in sys.argv: kw[k.lstrip('-')] = t(sys.argv[sys.argv.index(k)+1])
    sub, bands, box, up = bands_of(v, **kw)
    rec_up = paint(sub.shape[:2], bands, up)
    rec = np.asarray(Image.fromarray(rec_up.clip(0, 255).astype(np.uint8))
                     .resize((sub.shape[1]//up, sub.shape[0]//up), Image.LANCZOS)
                     ).astype(np.float32)
    ref_native = np.asarray(Image.fromarray(sub.astype(np.uint8))
                            .resize((sub.shape[1]//up, sub.shape[0]//up), Image.LANCZOS)
                            ).astype(np.float32)
    err = float(np.abs(ref_native - rec).mean())

    # what the *page* actually shows: art painted at native res, then blurred,
    # then composited over the base.  Compare that against the page reference
    # art window to see how much of the page error is representation.
    S = float(sys.argv[sys.argv.index('--blur')+1]) if '--blur' in sys.argv else 1.8
    R = batch.ref(v)
    x0, y0, x1, y1 = box
    pg = R[y0:y1, x0:x1]
    blur = Image.fromarray(rec.clip(0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(S))
    b = np.asarray(blur).astype(np.float32)
    page_err = float(np.abs(pg - b).mean())

    # ...and the render's own art window, for reference
    D = np.asarray(Image.open(f'{HERE}/render-{v}.png').convert('RGB')).astype(np.float32)
    ren_err = float(np.abs(pg - D[y0:y1, x0:x1]).mean())

    print(f'{v}: {len(bands)} bands, up {up}')
    print(f'   band paint vs reference       {err:6.3f}')
    print(f'   blurred paint vs page ref     {page_err:6.3f}')
    print(f'   actual render vs page ref     {ren_err:6.3f}')
    print(f'   => representation floor {err:.3f}, blur+composite floor {page_err:.3f}, '
          f'render overhead {ren_err-page_err:+.3f}')
    if '--dump' in sys.argv:
        f = sys.argv[sys.argv.index('--dump')+1]
        both = np.concatenate([pg, rec, D[y0:y1, x0:x1]], axis=1).clip(0, 255).astype(np.uint8)
        Image.fromarray(both).resize((both.shape[1]//2, both.shape[0]//2),
                                     Image.LANCZOS).save(f)
        print('dump ->', f, '(ref | band-paint | render)')

if __name__ == '__main__':
    main()
