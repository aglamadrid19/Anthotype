#!/usr/bin/env python3
"""Measurement-based type fitter.

Each round: one render (2x) -> ink bbox of the element in a TIGHT window, then
update a translate() plus font-size so that the rendered ink bbox matches the
reference's.  Scaling uses the ink WIDTH (robust to ascender/descender
differences between ref raster and real font).  A second stage tunes
letter-spacing / font-weight / colour by direct scoring.

usage: met.py <variant> <element|all> [rounds] [--no-art] [--scale 1|2]
Writes qa/m<variant>.css
"""
import os, sys, json
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch

SEL = {'brand':'.brand','h1':'h1','h2':'h2','divider':'.divider',
       'tag':'.content p','cta':'.cta'}
# A's content is an in-flow column: elements are shifted with margins, not transforms
MARGIN = {'a': {'h1':'margin-top','h2':'margin-top','tag':'margin-top','cta':'margin-top'}}

# element -> (window, threshold, kind)
#   kind 'type' scales with width, 'box' only translates
SPEC = {
 'a': {'h1':((40,236,480,318),150,'type'),
       'h2':((40,336,400,364),110,'type'),   'tag':((40,392,420,420),105,'type'),
       'cta':((45,440,330,512),85,'box')},
 'b': {'brand':((40,120,340,190),150,'box'), 'h1':((40,282,480,346),150,'type'),
       'h2':((40,368,345,406),105,'type'),   'tag':((40,430,420,448),100,'type'),
       'cta':((45,478,330,548),75,'box')},
 'c': {'brand':((40,186,300,222),150,'box'), 'h1':((40,246,480,312),150,'type'),
       'h2':((40,330,340,372),110,'type'),   'divider':((40,388,300,402),55,'box'),
       'tag':((40,416,340,442),100,'type'),  'cta':((45,469,320,532),75,'box')},
}
BASE_FS = {'a':{'h1':80,'h2':46,'tag':19.5},'b':{'h1':84,'h2':47,'tag':19},
           'c':{'h1':82,'h2':46,'tag':22}}

def build(sel, st):
    d = []
    dx, dy = st.get('dx',0), st.get('dy',0)
    if abs(dx) > 0.05 or abs(dy) > 0.05:
        d.append(f"transform:translate({dx:.1f}px,{dy:.1f}px)")
    if st.get('fs'): d.append(f"font-size:{st['fs']:.2f}px")
    for k, f in (('color','color'),('ls','letter-spacing'),
                 ('fw','font-weight'),('lh','line-height'),('ts','text-shadow')):
        if st.get(k): d.append(f"{f}:{st[k]}")
    return "" if not d else sel + "{" + ";".join(d) + "}"

def bbox(arr, win, thr):
    x0,y0,x1,y1 = win
    sub = arr[y0:y1, x0:x1]
    m = sub.sum(axis=2) > thr
    if m.sum() < 4: return None
    ys,xs = np.nonzero(m)
    return dict(x0=int(xs.min()+x0), x1=int(xs.max()+x0), y0=int(ys.min()+y0), y1=int(ys.max()+y0),
                w=int(xs.max()-xs.min()+1), h=int(ys.max()-ys.min()+1), n=int(m.sum()))

def fit(v, el, rounds=5, hide_art=True, scale=2, verbose=True):
    win, thr, kind = SPEC[v][el]
    sel = SEL[el]
    rb = bbox(batch.ref(v), win, thr)
    st = {}
    if verbose: print(f"  REF {el}: x{rb['x0']:4d}-{rb['x1']:4d} w{rb['w']:4d} y{rb['y0']:4d}-{rb['y1']:4d} n{rb['n']}")
    prev = None
    for r in range(rounds):
        im = batch.render_candidates(v, [build(sel, st)], hide_art, scale=scale)[0]
        mb = bbox(np.asarray(im).astype(np.float32), win, thr)
        if not mb:
            if verbose: print(f"    r{r}: NOT FOUND"); break
        ddx, ddy = rb['x0']-mb['x0'], rb['y0']-mb['y0']
        sc = (rb['w']/mb['w']) if kind == 'type' else 1.0
        if verbose:
            print(f"    r{r} ren x{mb['x0']:4d}-{mb['x1']:4d} w{mb['w']:4d} y{mb['y0']:4d}-{mb['y1']:4d}  "
                  f"dx={ddx:+3d} dy={ddy:+3d} wsc={sc:.4f}")
        if prev == (ddx, ddy, round(sc,3)): break
        prev = (ddx, ddy, round(sc,3))
        st['dx'] = st.get('dx',0)+ddx
        st['dy'] = st.get('dy',0)+ddy
        if kind == 'type':
            cur = st.get('fs') or BASE_FS[v][el]
            st['fs'] = round(cur*sc, 2)
    return st

def polish(v, el, st, rounds=2, hide_art=True, scale=2, verbose=True):
    """Direct-score pass over letter-spacing / weight / colour / shadow."""
    sel = SEL[el]
    grid = []
    base_ls = st.get('ls')
    for ls in ['-0.05em','-0.045em','-0.04em','-0.035em','-0.03em','-0.025em','-0.02em','-0.015em','-0.01em','0em']:
        grid.append(('ls', ls))
    for fw in (300,350,400,450,500):
        grid.append(('fw', fw))
    grid.append(('shadow','none'))
    best = batch.score(v, [build(sel, st)], None, hide_art, scale=scale)[0]
    if verbose: print(f"    polish start {best:.3f}")
    for k, val in grid:
        t = dict(st); t[k] = val
        s = batch.score(v, [build(sel, t)], None, hide_art, scale=scale)[0]
        if s < best - 2e-3:
            best, st = s, t
            if verbose: print(f"      {k}={val} -> {best:.3f}")
    return st, best

if __name__ == '__main__':
    v = sys.argv[1]; which = sys.argv[2]
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 and sys.argv[3].isdigit() else 5
    hide = not ('--no-art' in sys.argv)
    scale = int(sys.argv[sys.argv.index('--scale')+1]) if '--scale' in sys.argv else 2
    do_polish = '--polish' in sys.argv
    els = list(SPEC[v]) if which == 'all' else [which]
    out = {}
    for e in els:
        print(f"== {v}/{e} ==")
        st = fit(v, e, rounds, hide, scale)
        if do_polish: st, sc = polish(v, e, st, hide_art=hide, scale=scale)
        out[e] = st
        print("   ", build(SEL[e], st))
    txt = "\n".join(build(SEL[e], st) for e, st in out.items() if build(SEL[e], st))
    open(f"{HERE}/m{v}.css",'w').write(txt+"\n")
    print(txt)
    print(f"wrote qa/m{v}.css")
