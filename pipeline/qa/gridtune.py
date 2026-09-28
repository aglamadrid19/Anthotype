#!/usr/bin/env python3
"""Fast grid tuner using batch rendering (one Chrome pass per 8 candidates).

usage: gridtune.py <variant> <element> [--art] [--rounds N]
element = brand|h1|h2|divider|tag|cta
Writes t<variant>.css with the best override block.
"""
import os, sys, itertools, json
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch

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

def ref(v):
    return np.asarray(Image.open(f"{HERE}/ref-{v}.png").convert('RGB')).astype(np.float32)

def css(sel, d):
    return sel + "{" + ";".join(f"{k}:{vv}" for k,vv in d.items()) + "}"

def eval_variants(v, sel, box, cands, hide_art=True):
    overrides = [css(sel, d) for d in cands]
    imgs = batch.render(v, overrides, hide_art=hide_art)
    R = ref(v); x0,y0,x1,y1 = box
    scores = []
    for im in imgs:
        a = np.asarray(im).astype(np.float32)
        scores.append(float(np.abs(R[y0:y1,x0:x1]-a[y0:y1,x0:x1]).mean()))
    return scores

def d1(v, el, key, vals, base, box, hide_art, topk=3):
    sel = SEL[el]
    cands = []
    for vv in vals:
        d = dict(base); d[key] = vv; cands.append(d)
    sc = eval_variants(v, sel, box, cands, hide_art)
    order = np.argsort(sc)
    print(f"  {key}: " + "  ".join(f"{vals[i]}={sc[i]:.2f}" for i in order[:6]))
    best = [cands[i] for i in order[:topk]]
    return best, sc[order[0]]

def tune(v, el, rounds=3, hide_art=True):
    sel = SEL[el]; box = WIN[v][el]
    cur = {}
    best = eval_variants(v, sel, box, [cur], hide_art)[0]
    print(f"{v}/{el} start {best:.3f}")
    grids = [
      ('top',    [f"{y}px" for y in range(box[1]-14, box[3]+8, 2)]),
      ('left',   [f"{x}px" for x in range(50, 76, 1)]),
      ('font-size', [f"{s}px" for s in range(20, 100, 1)]),
      ('letter-spacing', [f"{e}em" for e in (-.05,-.045,-.04,-.035,-.03,-.025,-.02,-.015,-.01,-.005,0)]),
      ('font-weight', [300,400,500,600,700]),
    ]
    seen = set()
    for it in range(rounds):
        improved = False
        for key, vals in grids:
            cands = []
            for vv in vals:
                d = dict(cur); d[key] = vv
                sig = json.dumps(d, sort_keys=True)
                if sig in seen: continue
                seen.add(sig); cands.append(d)
            if not cands: continue
            sc = eval_variants(v, sel, box, cands, hide_art)
            o = int(np.argmin(sc))
            if sc[o] < best - 1e-4:
                best = sc[o]; cur = cands[o]; improved = True
                print(f"  -> {key}={cur[key]}  {best:.3f}")
        if not improved: break
    print(f"BEST {v}/{el} {best:.3f}  {cur}")
    return best, cur

if __name__ == '__main__':
    v, el = sys.argv[1], sys.argv[2]
    rounds = int(sys.argv[sys.argv.index('--rounds')+1]) if '--rounds' in sys.argv else 3
    hide = not ('--art' in sys.argv)
    best, cur = tune(v, el, rounds, hide)
    open(f"{HERE}/t{v}-{el}.css", 'w').write(css(SEL[el], cur) + "\n")
    print("wrote", f"t{v}-{el}.css")
