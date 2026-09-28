#!/usr/bin/env python3
"""Coordinate-descent tuner (variant-generic) using geom.render.

usage: tune2.py <variant> <objective>  [--start k=v,...] [--iters N]
objective: name of a box in WIN2, or 'all'
"""
import os, sys, itertools
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from geom import render

# per-element windows chosen to isolate the left column text, art hidden
WIN2 = {
  'a': {'brand':(30,120,470,200),'h1':(40,240,470,335),'h2':(40,332,400,398),
        'tag':(40,398,470,425),'cta':(40,440,340,515),
        'all':(30,100,470,560)},
  'b': {'brand':(30,110,470,195),'h1':(40,265,470,352),'h2':(40,358,420,420),
        'tag':(40,424,470,458),'cta':(40,470,340,556),
        'all':(30,100,470,560)},
  'c': {'brand':(40,180,470,228),'h1':(40,238,470,326),'h2':(40,326,420,382),
        'divider':(40,382,420,410),'tag':(40,410,470,448),'cta':(40,462,340,542),
        'all':(30,170,470,560)},
}

def score(v, region, arr, css_has_art=True):
    ref = np.asarray(Image.open(f"{HERE}/ref-{v}.png").convert('RGB')).astype(np.float32)
    x0, y0, x1, y1 = WIN2[v][region]
    m = 6
    r = ref[max(0,y0-m):y1+m, max(0,x0-m):x1+m]
    t = arr[max(0,y0-m):y1+m, max(0,x0-m):x1+m]
    return float(np.abs(r - t).mean())

def run(v, css, region, art_hidden=True):
    c = css + ("\n.art{display:none!important}" if art_hidden else "")
    out = render(v, c)
    arr = np.asarray(Image.open(out).convert('RGB')).astype(np.float32)
    return score(v, region, arr)

def tune(v, region, base, params, iters=2, art_hidden=True, verbose=True):
    cur = dict(base)
    keys = {p[0] for p in params}
    def css_of(d):
        merged = {k: d.get(k) for k in keys}
        merged.update({k: v for k, v in d.items()})
        return "\n".join(fmt.format(**merged) for _, fmt, _ in params)
    best = run(v, css_of(cur), region, art_hidden)
    if verbose: print(f"start {best:7.3f}")
    for it in range(iters):
        improved = False
        for name, fmt, cands in params:
            bv = cur[name]
            for c in cands:
                trial = dict(cur); trial[name] = c
                s = run(v, css_of(trial), region, art_hidden)
                if verbose: print(f"  {name}={c!r:>12}  {s:7.3f}{'  *' if s < best - 1e-4 else ''}", flush=True)
                if s < best - 1e-4:
                    best = s; cur = trial; improved = True
            if cur[name] != bv and verbose: print(f"  keep {name}={cur[name]!r} -> {best:.3f}")
        if not improved: break
    if verbose: print("BEST", best, cur)
    return best, cur, css_of(cur)

if __name__ == "__main__":
    import json
    v = sys.argv[1]
    region = sys.argv[2] if len(sys.argv) > 2 else 'all'
    spec = json.load(open(sys.argv[3]))
    params = [(p['name'], p['fmt'], p['vals']) for p in spec['params']]
    base = spec.get('base', {})
    best, cur, css = tune(v, region, base, params, iters=spec.get('iters', 2))
    open(f"{HERE}/../{v}.tuned.css", 'w').write(css)
    print("wrote", f"{v}.tuned.css")
