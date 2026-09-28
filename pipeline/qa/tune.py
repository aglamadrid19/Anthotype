#!/usr/bin/env python3
"""Coordinate-descent tuner that goes through the REAL page pipeline.

qa/batch.py renders candidates from the cached `{v}.css` block and can disagree
with `qa.sh`; for load-bearing changes the only trustworthy loop is
`node gen-page.mjs <v> && ./qa.sh <v>`.  This drives that loop directly.

usage: tune.py <variant> <spec.json> [--iters N] [--rounds N]
spec.json = {"base": {"<selector>": {"<prop>": "<value>", ...}},
             "grid": {"<selector>": {"<prop>": ["v1","v2",...]}}}
"""
import json, os, subprocess, sys, itertools
HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)
from _env import NODE, node_env


def score(v, overrides):
    css = '\n'.join(f'{sel}{{{";".join(f"{k}:{x}" for k,x in props.items())}}}'
                    for sel, props in overrides.items())
    env = node_env()
    env['CSS_OVERRIDE'] = css
    subprocess.run([NODE, 'gen-page.mjs', v], cwd=PIPE, check=True,
                   capture_output=True, env=env)
    r = subprocess.run(['./qa.sh', v], cwd=PIPE, capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if line.startswith('OVERALL'):
            return float(line.split()[2])
    raise RuntimeError(r.stdout + r.stderr)


def regenerate_clean():
    """Rebuild {v}-full.html / {v}-static.html with no CSS_OVERRIDE.

    The last scored candidate leaves its test CSS embedded in `{v}-static.html`
    -- and that is the exact file `qa.sh` screenshots -- so the artefact must be
    restored before anything else reads it.  Without this, a tuning run silently
    bakes its final candidate into the shipped page (it once left
    `h1{text-shadow:None}` in a-static.html).
    """
    env = node_env()
    env.pop('CSS_OVERRIDE', None)
    for var in ('a', 'b', 'c'):
        subprocess.run([NODE, 'gen-page.mjs', var], cwd=PIPE, check=True,
                       capture_output=True, env=env)


def main():
    v = sys.argv[1]
    spec = json.load(open(sys.argv[2]))
    base = {k: dict(d) for k, d in spec.get('base', {}).items()}
    grid = spec['grid']
    try:
        best = score(v, base)
        print(f'START {best:.3f}')
        for rnd in range(int(spec.get('rounds', 2))):
            for sel, props in grid.items():
                for prop, vals in props.items():
                    cur = base.setdefault(sel, {}).get(prop)
                    bestv, bests = cur, best
                    for x in vals:
                        if x == cur: continue
                        base[sel][prop] = x
                        sc = score(v, base)
                        if sc < bests - 1e-9:
                            bests, bestv = sc, x
                    base[sel][prop] = bestv
                    if bests < best:
                        print(f'  r{rnd} {sel} {prop} -> {bestv}  {best:.3f} -> {bests:.3f}')
                        best = bests
            print(f'round {rnd}: {best:.3f}')
        print('BEST', json.dumps(base), f'{best:.3f}')
    finally:
        # Always leave a clean {v}-static.html behind, even on Ctrl-C.
        regenerate_clean()
        print('restored {a,b,c}-static.html (CSS_OVERRIDE cleared)')


if __name__ == '__main__':
    main()
