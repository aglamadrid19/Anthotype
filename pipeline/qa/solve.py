#!/usr/bin/env python3
"""Measure-and-solve type fitter.

Renders the page with current CSS and a *candidate* override, measures the ink
band of one element inside a window for both ref and render, then solves
dx/dy/scale and emits corrected CSS.  Iterate 2-3 rounds to converge.

usage: solve.py <variant> <element> [rounds]
element = brand|h1|h2|divider|tag|cta
"""
import os, sys, re
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from geom import render

WIN = {
 'a': {'brand':(30,95,430,205),'h1':(30,230,430,340),'h2':(30,325,430,398),
       'tag':(30,388,430,432),'cta':(40,430,340,520)},
 'b': {'brand':(30,100,430,205),'h1':(30,255,430,362),'h2':(30,352,430,430),
       'tag':(30,418,430,468),'cta':(40,455,340,562)},
 'c': {'brand':(30,170,430,232),'h1':(30,232,430,332),'h2':(30,318,430,388),
       'divider':(30,378,430,414),'tag':(30,404,430,458),'cta':(40,456,340,548)},
}
SEL = {'brand':'.brand','h1':'h1','h2':'h2','divider':'.divider',
       'tag':'.content p','cta':'.cta'}

def band(arr, box, thr):
    x0,y0,x1,y1 = box
    sub = arr[y0:y1, x0:x1]
    m = sub.sum(axis=2) > thr
    if not m.any(): return None
    ys,xs = np.nonzero(m)
    return dict(x0=int(xs.min()+x0), x1=int(xs.max()+x0),
                y0=int(ys.min()+y0), y1=int(ys.max()+y0),
                w=int(xs.max()-xs.min()+1), h=int(ys.max()-ys.min()+1),
                cov=round(100*float(m.mean()),2))

def probe(png, box, thr):
    a = np.asarray(Image.open(png).convert('RGB')).astype(np.float32)
    return band(a, box, thr)

def main():
    v = sys.argv[1]; el = sys.argv[2]
    rounds = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    box = WIN[v][el]
    thr = 190 if el in ('brand','tag','h2','h1') else 120
    ref = probe(f"{HERE}/ref-{v}.png", box, thr)
    print(f"REF  {el}: {ref}")
    css_cur = ""
    for r in range(rounds):
        out = render(v, css_cur + "\n.art{display:none!important}")
        ren = probe(out, box, thr)
        print(f"round {r} REN: {ren}")
        if not ren: break
        dy = ref['y0'] - ren['y0']
        dx = ref['x0'] - ren['x0']
        sc = ref['h'] / max(1, ren['h'])
        print(f"        dy={dy} dx={dx} scale={sc:.4f}")
        # build additive override: translate the element and scale its font
        css_cur += (f"\n{SEL[el]}{{transform:translate({dx}px,{dy}px);}}"
                    if sc > 0.985 and sc < 1.015 else
                    f"\n{SEL[el]}{{transform:translate({dx}px,{dy}px);font-size:calc(var(--fs{el},1)*1em);}}")
        if sc <= 0.985 or sc >= 1.015:
            print("        (scale mismatch — needs font-size change, handle manually)")
        if dx == 0 and dy == 0 and 0.99 < sc < 1.01: break
    print("CSS:", css_cur)

if __name__ == '__main__':
    main()
