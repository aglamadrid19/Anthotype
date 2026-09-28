#!/usr/bin/env python3
"""Trace a variant's brand mark (icon/hex) from the reference and splice the
resulting inline <svg> into content.json's markup for that variant.

The traced SVG keeps its own viewBox + potrace y-flip transform, so it is
dropped in as-is and sized/positioned purely by CSS (`.brand-mark`).

usage: brandglyph.py <variant> --box x0 y0 x1 y1 [--levels N] [--up K]
                     [--selector SPAN_CLASS] [--apply]
"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import glyph

PIPE = os.path.dirname(HERE)
CONTENT = os.path.join(PIPE, 'content.json')

# variant -> (span class used in markup, reference png, default box)
MARKS = {
    'c': ('ant-icon', 'ref-c.png', (56, 188, 94, 220)),
    'b': ('hex',      'ref-b.png', (57, 125, 122, 182)),
}

def main():
    v = sys.argv[1]
    span_cls, png, box = MARKS[v]
    kw = {'up': 6, 'levels': 8, 'bgcut': 10.0, 'turdsize': 2, 'opttol': 0.09,
          'cls': 'brand-mark'}
    if '--box' in sys.argv:
        i = sys.argv.index('--box')
        box = tuple(int(x) for x in sys.argv[i+1:i+5])
    for k, t in (('--up', int), ('--levels', int), ('--turdsize', int)):
        if k in sys.argv: kw[k.lstrip('-')] = t(sys.argv[sys.argv.index(k)+1])
    for k, t in (('--bgcut', float), ('--opttol', float)):
        if k in sys.argv: kw[k.lstrip('-')] = t(sys.argv[sys.argv.index(k)+1])

    svg, n = glyph.build(os.path.join(HERE, png), box, **kw)
    if not svg:
        raise SystemExit('no ink traced')
    html = f'<span class="{span_cls}" aria-hidden="true">{svg}</span>'

    d = json.load(open(CONTENT))
    mk = d[v]['markup']
    pat = rf'<span class="{span_cls}"[^>]*>.*?</span>'
    if not re.search(pat, mk, re.S):
        # self-closing form: <span class="hex" aria-hidden="true"></span>
        pat = rf'<span class="{span_cls}"[^>]*/?></span>'
    new, cnt = re.subn(pat, html.replace('\\', '\\\\'), mk, count=1, flags=re.S)
    if cnt == 0:
        raise SystemExit(f'no <span class="{span_cls}"> in content.json[{v}].markup')
    print(f'{v}: {n} paths, {len(svg)} bytes svg, replaced {cnt} span')
    if '--apply' in sys.argv:
        d[v]['markup'] = new
        json.dump(d, open(CONTENT, 'w'), indent=2)
        open(os.path.join(HERE, f'mark-{v}-{span_cls}.svg'), 'w').write(svg)
        print('applied to content.json')
    else:
        print('dry run (pass --apply)')

if __name__ == '__main__':
    main()
