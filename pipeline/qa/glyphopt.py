#!/usr/bin/env python3
"""End-to-end optimizer for a traced brand glyph.

The band-paint proxy in glyphfit.py ignores two things that decide the final
score: the browser's own rasterisation, and the `filter: blur()` the page
applies to the art.  So score candidates the way the page actually renders
them -- generate the SVG, inject it into a live page copy, screenshot it with
qa/batch.py, compare against the reference window.

usage: glyphopt.py <variant> [--span ant-icon] [--win x0 y0 x1 y1]
                   [--box x0 y0 x1 y1] [--apply]
"""
import argparse, json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import batch, glyph

WIN = {'c': (40, 178, 300, 228), 'b': (30, 110, 340, 195)}
BOX = {'c': (56, 188, 94, 220), 'b': (64, 140, 100, 174)}
SPAN = {'c': 'ant-icon', 'b': 'hex'}

def inject(v, span, svg, idx):
    """A page override that swaps the traced mark for `svg`.

    The SVG goes into a scratch .svg next to the batch page and is referenced
    by a *relative* URL, because a `data:` URI would choke on the `#` in the
    fill colours (`#` ends a URL fragment unless %-escaped).
    """
    name = f"glyphopt-{v}-{idx:03d}.svg"
    open(os.path.join(SCRATCH, name), 'w').write(svg)
    return (f'.{span} .brand-mark{{display:none}}'
            f'.{span}::after{{content:"";display:block;width:100%;height:100%;'
            f'background-image:url("{name}");'
            f'background-size:100% 100%;background-repeat:no-repeat}}')

SCRATCH = "/tmp"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('variant')
    ap.add_argument('--span', default=None)
    ap.add_argument('--win', default=None)
    ap.add_argument('--box', default=None)
    ap.add_argument('--apply', action='store_true')
    a = ap.parse_args()
    v = a.variant
    span = a.span or SPAN[v]
    win = tuple(int(x) for x in a.win.replace(',', ' ').split()) if a.win else WIN[v]
    box = tuple(int(x) for x in a.box.replace(',', ' ').split()) if a.box else BOX[v]
    png = f'{HERE}/ref-{v}.png'

    cands = []
    for up in (6, 8):
        for levels in (6, 7, 8, 9):
            for bgcut in (4.0, 6.0, 9.0, 13.0):
                for lopct in (4.0, 8.0, 14.0):
                    for tt in (2, 3):
                        cands.append(dict(up=up, levels=levels, bgcut=bgcut,
                                          lopct=lopct, turdsize=tt, opttol=0.09))
    print(f'{len(cands)} candidates')
    ovs, kept = [], []
    for c in cands:
        svg, n = glyph.build(png, box, cls='brand-mark', **c)
        if not svg: continue
        ovs.append(inject(v, span, svg, len(ovs)))
        kept.append((c, svg, n))
    windows = {'r': win}
    res = batch.score(v, [''] + ovs, windows=windows)
    base = res[0]['r']
    order = sorted(range(len(ovs)), key=lambda i: res[i+1]['r'])
    print(f'base {base:.3f}')
    for i in order[:8]:
        c, svg, n = kept[i]
        print(f'  {res[i+1]["r"]:7.3f}  {n:3d} paths {len(svg):6d}B  {c}')
    gain = base - res[order[0]+1]['r']
    print(f'best gain {gain:+.3f}')
    if a.apply and gain > 0.05:
        c, svg, n = kept[order[0]]
        open(f'{HERE}/glyph-{v}.svg', 'w').write(svg)
        json.dump(c, open(f'{HERE}/glyph-{v}-params.json', 'w'), indent=2)
        print(f'wrote qa/glyph-{v}.svg + params ({n} paths)')
        for f in os.listdir(SCRATCH):
            if f.startswith(f'glyphopt-{v}-'):
                os.remove(os.path.join(SCRATCH, f))

if __name__ == '__main__':
    main()
