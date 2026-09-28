#!/usr/bin/env python3
"""Coordinate-descent tuner over *type* CSS vars for one element window.

Renders `<v>-full.html` with a CSS block that overrides the element's
font-size / top / left / letter-spacing / font-weight / color, scoring the
mean abs diff against the reference over that window (art hidden).

usage: typetune.py <variant> <click> [--iters N] [--no-art]
click = brand|h1|h2|divider|tag|cta
"""
import os, sys, json, itertools
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from geom import render

# selector + window (x0,y0,x1,y1) + tunable defaults per variant/element
SPEC = {
 'a': {'brand':('.brand',(30,100,470,200)),'h1':('h1',(40,235,470,335)),
       'h2':('h2',(40,330,470,395)),'tag':('.content p',(40,390,470,430)),
       'cta':('.cta',(40,435,340,515))},
 'b': {'brand':('.brand',(30,105,470,200)),'h1':('h1',(40,258,470,360)),
       'h2':('h2',(40,355,470,428)),'tag':('.content p',(40,420,470,465)),
       'cta':('.cta',(40,462,340,560))},
 'c': {'brand':('.brand',(40,175,470,230)),'h1':('h1',(40,235,470,330)),
       'h2':('h2',(40,320,470,385)),'divider':('.divider',(40,380,470,412)),
       'tag':('.content p',(40,402,470,455)),'cta':('.cta',(40,458,340,545))},
}

def ref_arr(v):
    return np.asarray(Image.open(f"{HERE}/ref-{v}.png").convert('RGB')).astype(np.float32)

def score_box(ref, arr, box, pad=6):
    x0,y0,x1,y1 = box
    y0=max(0,y0-pad); x0=max(0,x0-pad)
    r = ref[y0:y1+pad, x0:x1+pad]
    t = arr[y0:y1+pad, x0:x1+pad]
    return float(np.abs(r-t).mean())

def css_block(sel, vals):
    lines = []
    for prop, val in vals.items():
        if val is None: continue
        lines.append(f"{prop}:{val}")
    return f"{sel}{{{';'.join(lines)}}}"

def score(v, sel, box, vals, art=False, bg=""):
    css = css_block(sel, vals) + bg + "\n" + ("" if art else ".art{display:none!important}")
    out = render(v, css)
    arr = np.asarray(Image.open(out).convert('RGB')).astype(np.float32)
    return score_box(ref_arr(v), arr, box)

def tune(v, click, iters=3, art=False, extra=""):
    sel, box = SPEC[v][click]
    ref = ref_arr(v)
    grid = {
      'font-size':  [f"{s}px" for s in range(34, 92, 1)],
      'top':        [f"{y}px" for y in range(150, 560, 1)],
      'left':       [f"{x}px" for x in range(40, 90, 1)],
      'letter-spacing': [f"{e}em" for e in (-0.05,-0.04,-0.035,-0.03,-0.025,-0.02,-0.015,-0.01,-0.005,0,0.005,0.01)],
      'font-weight': [300,400,500,600,700],
    }
    # cheap order: position, then size, then spacing, then weight
    base = {'top':None,'left':None,'font-size':None,'letter-spacing':None,'font-weight':None}
    cur = dict(base)
    best = score(v, sel, box, cur, art, extra)
    print(f"start {best:7.3f}")
    for it in range(iters):
        improved=False
        for prop in ('top','left','font-size','letter-spacing','font-weight'):
            bv = cur[prop]
            cands = grid[prop]
            if prop=='top':
                # coarse then fine
                cands = [f"{y}px" for y in range(int(box[1])-20, int(box[3])+20, 1)]
            for c in cands:
                trial = dict(cur); trial[prop]=c
                s = score(v, sel, box, trial, art, extra)
                if s < best-1e-4:
                    best=s; cur=trial; improved=True
                    print(f"   {prop}={c} -> {best:.3f}", flush=True)
        if not improved: break
    print("BEST", f"{best:.3f}", {k:v for k,v in cur.items() if v})
    return best, cur

if __name__=='__main__':
    v=sys.argv[1]; click=sys.argv[2]
    iters=int(sys.argv[3]) if len(sys.argv)>3 else 3
    art = '--art' in sys.argv
    best,cur = tune(v, click, iters, art)
    print(css_block(SPEC[v][click][0], cur))
