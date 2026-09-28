#!/usr/bin/env python3
"""Greedy element-wise acceptance on the full-frame objective.

Given candidate override blocks per element (e.g. from met.py), try each one
against the current best and keep it only when the full-frame mean improves.

usage: greedy.py <variant> <cssfile-with-blocks>   # blocks separated by blank lines
       greedy.py <variant> --from-met
"""
import os, sys, json
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch

def blocks_from(path):
    txt = open(path).read()
    return [b.strip() for b in txt.split('\n\n') if b.strip() and not b.strip().startswith('#')]

def accept(v, blocks, scale=2, hide_art=False, verbose=True):
    cur = []
    best = batch.score(v, [''], None, hide_art, scale=scale)[0]
    if verbose: print(f"{v}: start {best:.3f}")
    for b in blocks:
        cand = "\n".join(cur + [b])
        s = batch.score(v, [cand], None, hide_art, scale=scale)[0]
        ok = s < best - 5e-4
        if verbose: print(f"  {'KEEP ' if ok else 'drop '}{b[:70]:72} {s:7.3f}")
        if ok: best, cur = s, cur + [b]
    if verbose: print(f"{v}: final {best:.3f}")
    return best, "\n".join(cur)

if __name__ == '__main__':
    v = sys.argv[1]
    scale = int(sys.argv[sys.argv.index('--scale')+1]) if '--scale' in sys.argv else 2
    if '--from-met' in sys.argv:
        src = f"{HERE}/m{v}.css"
    else:
        src = sys.argv[2]
    blocks = blocks_from(src)
    best, css = accept(v, blocks, scale)
    open(f"{HERE}/g{v}.css", 'w').write(css + "\n")
    print("wrote", f"qa/g{v}.css")
