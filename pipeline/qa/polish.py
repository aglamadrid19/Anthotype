#!/usr/bin/env python3
"""Full-frame polish pass: tune colour / weight / spacing / shadow of one element.

Starts from the page's current CSS (plus any existing tuned block) and searches a
small grid on the true full-frame objective, so a change is only kept when the
rendered page as a whole gets closer to the reference.

usage: polish.py <variant> <element|all> [--rounds N] [--scale 1|2]
Writes qa/p{v}.css with accepted blocks.
"""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch

SEL = {'brand':'.brand','h1':'h1','h2':'h2','divider':'.divider',
       'tag':'.content p','cta':'.cta'}
ELS = {'a':['h1','h2','tag','cta'],'b':['brand','h1','h2','tag','cta'],
       'c':['brand','h1','h2','divider','tag','cta']}

# candidate values per property, per element kind
def candidates(el):
    c = {
      'font-weight': [300,350,375,400,425,450,500,550,600],
      'letter-spacing': [f"{e:.4f}em" for e in (-.05,-.045,-.04,-.035,-.03,-.025,-.02,-.015,-.01,-.005,0,.005)],
      'opacity': ['0.7','0.8','0.85','0.9','0.95','1'],
      'text-shadow': ['none'],
      'font-synthesis': ['none'],
    }
    if el in ('h1','h2'):
        c['-webkit-text-stroke'] = ['0px','0.2px','0.3px','0.4px','0.5px']
    return c

def block(sel, d):
    return "" if not d else sel + "{" + ";".join(f"{k}:{v}" for k,v in d.items()) + "}"

def polish(v, el, cur, rounds=2, scale=2, verbose=True):
    sel = SEL[el]
    best = batch.score(v, [cur], None, False, scale=scale)[0]
    if verbose: print(f"  {el}: start {best:.3f}")
    for r in range(rounds):
        improved = False
        for prop, vals in candidates(el).items():
            cands, seen = [], set()
            base_d = dict(ACC.get(el, {}))
            for val in vals:
                d = dict(base_d); d[prop] = val
                sig = json.dumps(d, sort_keys=True)
                if sig in seen: continue
                seen.add(sig); cands.append(d)
            if len(cands) < 2: continue
            ovs = [cur + "\n" + block(sel, d) for d in cands]
            sc = batch.score(v, ovs, None, False, scale=scale)
            o = int(np.argmin(sc))
            if sc[o] < best - 2e-3:
                best = sc[o]; ACC[el] = cands[o]; improved = True
                if verbose: print(f"    {prop}={cands[o][prop]} -> {best:.3f}", flush=True)
        if not improved: break
    return best, ACC.get(el, {})

ACC = {}

if __name__ == '__main__':
    v = sys.argv[1]
    which = sys.argv[2] if len(sys.argv) > 2 else 'all'
    scale = int(sys.argv[sys.argv.index('--scale')+1]) if '--scale' in sys.argv else 2
    rounds = int(sys.argv[sys.argv.index('--rounds')+1]) if '--rounds' in sys.argv else 2
    els = ELS[v] if which == 'all' else [which]
    blocks = []
    cur = ""
    tot = batch.score(v, [''], None, False, scale=scale)[0]
    print(f"{v}: baseline {tot:.3f}")
    for e in els:
        s, d = polish(v, e, cur, rounds, scale)
        if d:
            blocks.append(block(SEL[e], d))
            cur = "\n".join(blocks)
            print(f"  cumulative {batch.score(v, [cur], None, False, scale=scale)[0]:.3f}")
    open(f"{HERE}/p{v}.css",'w').write(cur + "\n")
    print("wrote qa/p%s.css" % v)
    print(cur)
