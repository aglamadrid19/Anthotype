#!/usr/bin/env python3
"""Fit the B hexagon's exact geometry against the reference.

The hexagon is regular geometry, so there is no point making potrace guess at
it (and no point paying for headless Chrome per candidate).  We rasterise the
candidate polygon with PIL -- which is what the browser does, modulo AA -- and
score it against the reference crop.  Hundreds of candidates per second.

usage: hexfit.py [--box x0 y0 x1 y1] [--dump FILE] [--apply]
"""
import json, math, os, sys
import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)
REF = os.path.join(HERE, 'ref-b.png')
OUT = os.path.join(HERE, 'hex-params.json')

SS = 8  # supersample factor for stroke AA

def raster(box, cx, cy, rw, rh, sw, col, bg):
    x0, y0, x1, y1 = box
    W, H = (x1-x0)*SS, (y1-y0)*SS
    img = Image.new('RGB', (W, H), tuple(int(v) for v in bg))
    d = ImageDraw.Draw(img)
    pts = [(cx, cy-rh), (cx+rw, cy-rh/2), (cx+rw, cy+rh/2),
           (cx, cy+rh), (cx-rw, cy+rh/2), (cx-rw, cy-rh/2)]
    pts = [((px-x0)*SS, (py-y0)*SS) for px, py in pts]
    d.polygon(pts, outline=tuple(int(v) for v in col), width=max(1, int(round(sw*SS))))
    return np.asarray(img.resize((x1-x0, y1-y0), Image.LANCZOS)).astype(np.float32)

def main():
    box = (56, 124, 110, 184)
    if '--box' in sys.argv:
        i = sys.argv.index('--box')
        box = tuple(int(x) for x in sys.argv[i+1:i+5])
    x0, y0, x1, y1 = box
    ref = np.asarray(Image.open(REF).convert('RGB')).astype(np.float32)[y0:y1, x0:x1]
    bg = ref[:2, :2].reshape(-1, 3).mean(axis=0)

    def err(**kw):
        return float(np.abs(ref - raster(box, bg=bg, **kw)).mean())

    base = dict(cx=81.5, cy=153.0, rw=20.5, rh=24.5, sw=2.0,
                col=np.array([40., 200., 132.]))
    print(f'baseline {err(**base):.3f}')
    best = (err(**base), dict(base))

    # coarse -> fine
    for step, rounds in ((1.0, 3), (0.5, 2), (0.25, 2)):
        improved = True
        while improved:
            improved = False
            for key, span in (('cx', 3), ('cy', 3), ('rw', 3), ('rh', 3), ('sw', 2)):
                for d in np.arange(-span*step, span*step + 1e-9, step):
                    c = dict(best[1]); c[key] = round(c[key] + float(d), 4)
                    if c[key] <= 0: continue
                    e = err(**c)
                    if e < best[0] - 1e-4:
                        best = (e, c); improved = True
            for dr in (-24, -16, -8, 0, 8, 16, 24):
                for dg in (-24, -16, -8, 0, 8, 16, 24):
                    for db in (-24, -16, -8, 0, 8, 16, 24):
                        c = dict(best[1])
                        c['col'] = np.clip(c['col'] + np.array([dr, dg, db]), 0, 255)
                        e = err(**c)
                        if e < best[0] - 1e-4:
                            best = (e, c); improved = True

    e, c = best
    print(f'best {e:.3f}')
    print(f'  cx {c["cx"]:.2f} cy {c["cy"]:.2f} rw {c["rw"]:.2f} rh {c["rh"]:.2f} '
          f'sw {c["sw"]:.2f} col rgb({c["col"][0]:.0f},{c["col"][1]:.0f},{c["col"][2]:.0f}) bg rgb({bg[0]:.0f},{bg[1]:.0f},{bg[2]:.0f})')
    json.dump({'box': list(box), 'cx': c['cx'], 'cy': c['cy'], 'rw': c['rw'],
               'rh': c['rh'], 'sw': c['sw'], 'col': [float(v) for v in c['col']],
               'err': e}, open(OUT, 'w'), indent=2)
    print('wrote', OUT)
    if '--dump' in sys.argv:
        f = sys.argv[sys.argv.index('--dump')+1]
        cand = raster(box, cx=c['cx'], cy=c['cy'], rw=c['rw'], rh=c['rh'],
                      sw=c['sw'], col=c['col'], bg=bg)
        both = np.concatenate([ref, cand], axis=1).clip(0, 255).astype(np.uint8)
        Image.fromarray(both).resize((both.shape[1]*8, both.shape[0]*8),
                                     Image.NEAREST).save(f)
        print('dump ->', f)

if __name__ == '__main__':
    main()
