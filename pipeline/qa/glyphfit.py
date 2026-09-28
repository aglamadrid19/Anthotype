#!/usr/bin/env python3
"""Grid-search glyph tracer parameters against the reference crop.

Potrace's reconstruction of a band mask is near-exact, so instead of running
headless Chrome per candidate we rebuild each band mask at native resolution,
paint it with its band colour and score that against the reference crop.  Fast
(hundreds of candidates/sec) and it isolates the only thing that matters here:
which pixels get inked and at what luminance.

usage: glyphfit.py <variant> --box x0 y0 x1 y1 [--win x0 y0 x1 y1]
                    [--grid bgcut=..,lopct=..,maskthr=..]
Prints the best few parameter sets and writes qa/glyph-<v>.json.
"""
import itertools, json, os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

def masks(png, box, up=6, levels=7, bgcut=10.0, lopct=10.0, maskthr=None,
          turdsize=2):
    """Recreate glyph.build's band masks at native resolution."""
    x0, y0, x1, y1 = box
    a = np.asarray(Image.open(png).convert('RGB')).astype(np.float32)
    sub = a[y0:y1, x0:x1]
    W, H = (x1-x0)*up, (y1-y0)*up
    big = np.asarray(Image.fromarray(sub.astype(np.uint8))
                     .resize((W, H), Image.LANCZOS)).astype(np.float32)
    lum = big.mean(axis=2)
    bg = float(np.median(lum[:2, :2]))
    ink = lum > bg + bgcut
    if maskthr is not None:
        from scipy import ndimage as ndi
        core = lum > float(maskthr)
        core = ndi.binary_dilation(core, iterations=max(2, up))
        core = ndi.binary_fill_holes(core)
        ink &= core
    out = []
    if ink.sum() < up*up*2:
        return sub, out
    lo, hi = np.percentile(lum[ink], lopct), np.percentile(lum[ink], 99.7)
    edges = np.linspace(lo, hi, levels+1)
    for i in range(levels):
        m = ink & ((lum >= edges[i]) if i == levels-1
                   else ((lum >= edges[i]) & (lum < edges[i+1])))
        if m.sum() < up*up: continue
        col = np.median(big[m], axis=0)
        out.append((m, col))
    return sub, out

def recon(masks_, shape):
    """Paint band masks (at `up` scale) into a native-res RGB image."""
    up = 1
    img = np.zeros(shape + (3,), np.float32)
    for m, col in masks_:
        # m is at `up`x; downsample the mask by area
        h, w = shape
        mm = m.reshape(h, m.shape[0]//h, w, m.shape[1]//w).mean(axis=(1, 3))
        wgt = mm[..., None]
        img = img*(1-wgt) + col*wgt
    return img

def score_crop(ref_crop, masks_, up):
    shape = ref_crop.shape[:2]
    r = recon(masks_, shape) if masks_ else np.zeros(ref_crop.shape, np.float32)
    return float(np.abs(ref_crop - r).mean())

def main():
    v = sys.argv[1]
    box = tuple(int(x) for x in sys.argv[sys.argv.index('--box')+1:sys.argv.index('--box')+5])
    png = os.path.join(HERE, f'ref-{v}.png')
    a = np.asarray(Image.open(png).convert('RGB')).astype(np.float32)
    x0, y0, x1, y1 = box
    crop = a[y0:y1, x0:x1]

    def cand(**kw):
        sub, ms = masks(png, box, **kw)
        return score_crop(crop, ms, kw.get('up', 6)), ms

    base, _ = cand()
    print(f'{v}: baseline recon err {base:.3f}  (box {box}, {x1-x0}x{y1-y0})')
    results = []
    for bgcut in (8, 12, 18, 25, 35):
        for mt in (None, 25, 30, 35, 45, 60):
            for lopct in (6, 10, 18, 25):
                s, ms = cand(bgcut=bgcut, maskthr=mt, lopct=lopct)
                results.append((s, bgcut, -1 if mt is None else mt, lopct, len(ms)))
    results.sort()
    for r in results[:6]:
        print(f'  err {r[0]:6.3f}  bgcut {r[1]:3d}  maskthr {str(r[2]):>4s}  '
              f'lopct {r[3]:2d}  bands {r[4]}')
    if '--dump' in sys.argv:
        f = sys.argv[sys.argv.index('--dump')+1]
        _, ms = cand(bgcut=results[0][1], maskthr=(None if results[0][2] < 0
                                                    else results[0][2]),
                     lopct=results[0][3])
        rec = recon(ms, crop.shape[:2])
        both = np.concatenate([crop, rec], axis=1).clip(0, 255).astype(np.uint8)
        Image.fromarray(both).resize((both.shape[1]*8, both.shape[0]*8),
                                     Image.NEAREST).save(f)
        print('dump ->', f, '(ref | recon)')
    best = results[0]
    json.dump({'v': v, 'box': list(box), 'bgcut': best[1], 'maskthr': best[2],
               'lopct': best[3], 'recon_err': best[0]},
              open(os.path.join(HERE, f'glyph-{v}.json'), 'w'), indent=2)
    print('wrote', os.path.join(HERE, f'glyph-{v}.json'))

if __name__ == '__main__':
    main()
