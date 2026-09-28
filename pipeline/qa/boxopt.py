#!/usr/bin/env python3
"""Sweep the art trace box (and re-trace) for a variant, scoring in-page.

The art BOX is a hard cut: everything left of x0 is never traced, even when the
reference has real artwork there (A's ring extends to x~363).  Widening it is
cheap -- the trace is band-based, so it reproduces whatever is in the box -- and
text repaints on top at a higher z-index.

usage: boxopt.py <variant> [--x0 300,360,418] [--top 0] [--apply]
"""
import argparse, os, subprocess, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import batch, mkart

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('variant')
    ap.add_argument('--x0', default='300,340,360,380,400,418')
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    v = a.variant
    xs = [int(x) for x in a.x0.split(',')]
    cur = list(mkart.BOX[v])
    results = []
    for x0 in xs:
        box = (x0, cur[1], cur[2], cur[3])
        svg = f'/tmp/boxopt-{v}.svg'
        mkart.build(v, out=svg, box=box, **mkart.PARAMS[v])
        # splice into a page override: replace the whole art svg
        open(f'{PIPE}/{v}.svg', 'w').write(open(svg).read())
        subprocess.run(['node', f'{PIPE}/gen-page.mjs', v], cwd=PIPE, check=True,
                       capture_output=True)
        batch._CACHE.pop(v, None)
        s = batch.score(v, [''], windows={'art': (x0, cur[1], 1024, cur[3]),
                                          'all': (0, 0, 1024, 768)})
        results.append((s[0]['all'], s[0]['art'], x0, os.path.getsize(svg)))
        print(f'  x0 {x0:4d}: all {s[0]["all"]:6.3f}  art {s[0]["art"]:6.3f}  '
              f'{os.path.getsize(svg)/1024:6.0f} KB', flush=True)
    results.sort()
    print(f'best x0 {results[0][2]}  all {results[0][0]:.3f}')
    if a.apply:
        best = results[0][2]
        mkart.BOX[v] = (best, cur[1], cur[2], cur[3])
        # persist into mkart.py
        src = open(f'{HERE}/mkart.py').read()
        old = f"BOX = {{'a': {mkart.BOX['a']}, 'b': {mkart.BOX['b']}, 'c': {mkart.BOX['c']}}}"
        print('NOTE update BOX manually:', {k: v_ for k, v_ in
                                           zip('abc', [mkart.BOX[k] for k in 'abc'])})

if __name__ == '__main__':
    main()
