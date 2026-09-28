#!/usr/bin/env python3
"""Coarse-to-fine coordinate-descent CSS tuner (full-frame objective).

usage: ftune.py <variant> <element> [--art] [--rounds N] [--scale 1|2]
       ftune.py <variant> all            # tune every element in sequence
Writes t<v>-<el>.css containing the winning override block.
"""
import os, sys, json
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch

SEL = {'brand':'.brand','h1':'h1','h2':'h2','divider':'.divider',
       'tag':'.content p','cta':'.cta'}
EL_ORDER = {
 'a': ['brand','h1','h2','tag','cta'],
 'b': ['brand','h1','h2','tag','cta'],
 'c': ['brand','h1','h2','divider','tag','cta'],
}

def css(sel, d):
    return "" if not d else sel + "{" + ";".join(f"{k}:{vv}" for k, vv in d.items()) + "}"

def score_full(v, overrides, hide_art, scale):
    return batch.score(v, overrides, None, hide_art, scale=scale)

def gen(key, cur, box):
    c = cur.get(key)
    def num():
        return float(str(c).replace('px','').replace('em','')) if c is not None else None
    if key == 'top':
        b = int(num()) if c else box[1]
        return [f"{y}px" for y in range(max(0,b-28), b+29, 2)]
    if key == 'left':
        b = int(num()) if c else 58
        return [f"{x}px" for x in range(max(0,b-12), b+13)]
    if key == 'font-size':
        b = int(num()) if c else 60
        return [f"{s}px" for s in range(max(8,b-12), b+13)]
    if key == 'letter-spacing':
        b = num() if c is not None else -0.03
        return [f"{e:.4f}em" for e in np.arange(b-0.016, b+0.0161, 0.002)]
    if key == 'font-weight':
        return [300,350,400,450,500,600,700]
    if key == 'line-height':
        return ['0.94','0.97','1','1.03','1.06','1.1']
    return None

def tune_one(v, el, cur, box, hide_art, scale, rounds, verbose=True):
    sel = SEL[el]
    best = score_full(v, [css(sel, cur)], hide_art, scale)[0]
    if verbose: print(f"  {el}: start {best:.3f}  {cur}")
    order = ['top','font-size','left','letter-spacing','font-weight','line-height']
    for it in range(rounds):
        improved = False
        for key in order:
            vals = gen(key, cur, box)
            if not vals: continue
            cands, seen = [], set()
            for vv in vals:
                d = dict(cur); d[key] = vv
                sig = json.dumps(d, sort_keys=True)
                if sig in seen: continue
                seen.add(sig); cands.append(d)
            if len(cands) < 2: continue
            sc = score_full(v, [css(sel, c) for c in cands], hide_art, scale)
            o = int(np.argmin(sc))
            if sc[o] < best - 2e-3:
                best = sc[o]; cur = cands[o]; improved = True
                if verbose: print(f"    {key}={cur[key]} -> {best:.3f}", flush=True)
        if not improved: break
    if verbose: print(f"  {el}: BEST {best:.3f}  {cur}")
    return best, cur

def main():
    v = sys.argv[1]
    el = sys.argv[2]
    rounds = int(sys.argv[sys.argv.index('--rounds')+1]) if '--rounds' in sys.argv else 3
    scale = int(sys.argv[sys.argv.index('--scale')+1]) if '--scale' in sys.argv else 1
    hide = not ('--art' in sys.argv)
    from ftune_win import BOX
    box = BOX[v]
    els = EL_ORDER[v] if el == 'all' else [el]
    overrides = {}
    tot = score_full(v, [''], hide, scale)[0]
    print(f"{v}: baseline full {tot:.3f}  (scale {scale}, art_hidden={hide})")
    for e in els:
        s, cur = tune_one(v, e, overrides.get(e, {}), box[e], hide, scale, rounds)
        overrides[e] = cur
        acc = score_full(v, ["\n".join(css(SEL[k], c) for k, c in overrides.items())], hide, scale)[0]
        print(f"  cumulative after {e}: {acc:.3f}")
        open(f"{HERE}/t{v}.css", 'w').write("\n".join(css(SEL[k], c) for k, c in overrides.items() if c) + "\n")
    print("wrote", f"t{v}.css")

if __name__ == '__main__':
    main()
