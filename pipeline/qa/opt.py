#!/usr/bin/env python3
"""Coordinate-descent optimizer over CSS declarations, scored on a region.

Renders each candidate through qa/batch.py (~340 ms/candidate, many per Chrome
pass) and only accepts a step when the region error drops.  Generic: you give
it a selector, a set of candidate declarations per property, and a window.

usage: opt.py <variant> --win x0 y0 x1 y1 --sel h1 \
         --set font-size=78,79,80,81,82 [--set letter-spacing=-.04em,-.035em] \
         [--base 'h1{top:275px}'] [--rounds 3] [--css qa/o-<v>.css]
"""
import argparse, json, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch

def parse_set(s):
    k, _, v = s.partition('=')
    return k.strip(), [x.strip() for x in v.split(',') if x.strip()]

def css_of(sel, decls):
    if not decls: return ''
    return sel + '{' + ';'.join(f'{k}:{v}' for k, v in decls.items()) + '}'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('variant')
    ap.add_argument('--win', required=True)
    ap.add_argument('--sel', required=True)
    ap.add_argument('--set', action='append', default=[])
    ap.add_argument('--base', default='')
    ap.add_argument('--rounds', type=int, default=3)
    ap.add_argument('--css', default=None)
    a = ap.parse_args()
    v = a.variant
    win = tuple(int(x) for x in a.win.replace(',', ' ').split())
    windows = {'r': win}
    sets = [parse_set(s) for s in a.set]

    decls = {}
    # seed from --base if it targets the same selector
    if a.base:
        body = a.base[a.base.index('{')+1:a.base.rindex('}')]
        for part in body.split(';'):
            if ':' in part:
                k, _, val = part.partition(':')
                decls[k.strip()] = val.strip()

    def score(d):
        ov = (a.base + css_of(a.sel, d)).strip()
        return batch.score(v, [ov], windows=windows)[0]['r']

    best = score(decls)
    print(f'start {best:.3f}  {css_of(a.sel, decls)}')
    for r in range(a.rounds):
        improved = False
        for k, vals in sets:
            for val in vals:
                if decls.get(k) == val: continue
                t = dict(decls); t[k] = val
                s = score(t)
                if s < best - 1e-3:
                    best, decls, improved = s, t, True
                    print(f'  r{r} {k}={val:>12s} -> {best:.3f}')
        if not improved:
            break
    print(f'best  {best:.3f}')
    css = css_of(a.sel, decls)
    print(css)
    if a.css:
        open(a.css, 'w').write(css + '\n')
        print('wrote', a.css)

if __name__ == '__main__':
    main()
