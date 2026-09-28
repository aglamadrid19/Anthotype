#!/usr/bin/env python3
"""Build a variant's brand mark as real inline SVG and splice it into content.json.

Two strategies, because the two marks are different animals:

  * `c` (AntSeed ant glyph) -- organic, all detail lives in the raster, so the
    whole mark is recovered with potrace (qa/glyph.py).
  * `b` (Hosting hexagon)   -- a *regular* hexagonal outline plus a small
    organic ant inside.  Tracing the outline reproduces potrace's stair-steps
    (and swallows the outer glow into a frame-filling band), so the outline is
    emitted as exact polygon geometry and only the inner mark is traced and
    nested inside it.

Output is a standalone `<svg class="brand-mark">` whose viewBox matches the
traced reference box; CSS positions/sizes it.  Emitted into content.json's
markup for the variant, and cached as qa/mark-<v>.svg.

usage: mkbrand.py <variant> [--apply] [--dump FILE]
"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import glyph
import numpy as np
from PIL import Image

PIPE = os.path.dirname(HERE)
CONTENT = os.path.join(PIPE, 'content.json')

def _trace(v, box, **kw):
    png = os.path.join(HERE, f'ref-{v}.png')
    opts = dict(up=6, levels=7, bgcut=10.0, turdsize=2, opttol=0.09,
                cls='brand-mark')
    opts.update(kw)
    return glyph.build(png, box, **opts)

def _inner_svg(v, box, **kw):
    """Trace `box` and return (svg_element, nested_svg_attrs)."""
    svg, n = _trace(v, box, **kw)
    if not svg:
        raise SystemExit('inner trace produced no ink')
    vb = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg).groups()
    inner = svg[svg.index('>')+1:svg.rindex('</svg>')]
    h, w = int(vb[1]), int(vb[0])
    return inner, w, h, n

def build_c(box=(56, 188, 94, 220)):
    """Whole-mark trace."""
    svg, n = _trace('c', box, bgcut=8.0, levels=8)
    if not svg:
        raise SystemExit('c trace produced no ink')
    return svg.replace('class="brand-mark"', 'class="brand-mark"'), n

# --- B hexagon: exact geometry -------------------------------------------
# Measured from ref-b: the ink spans x 60..103, y 128..178 -- a squashed
# pointy-top hexagon (the vertical flats run x=60 and x=103 across y 140..166,
# apexes at y=128 / y=178).  So the centreline half-width is 20.5 and the
# half-height 24.5 with a ~2px stroke.  The interior is background-dark
# (median rgb(0,13,8) vs bg rgb(0,11,6)), i.e. there is no fill -- only a thin
# bright stroke plus a glowing ant.  The perimeter is therefore emitted as
# exact polygon geometry and only the ant is traced, nested inside it.
def _hex_params():
    import json
    f = os.path.join(HERE, 'hex-params.json')
    d = json.load(open(f))
    return (d['cx'], d['cy'], d['rw'], d['rh'], d['sw'],
            d['col'], d['box'])
ANT_BOX = (64, 140, 100, 174)

def _hex_vertices(cx, cy, rw, rh):
    return [(cx, cy-rh), (cx+rw, cy-rh/2), (cx+rw, cy+rh/2),
            (cx, cy+rh), (cx-rw, cy+rh/2), (cx-rw, cy-rh/2)]

def build_b(box=None, ant_box=ANT_BOX):
    cx, cy, rw, rh, sw, col, box_ = _hex_params()
    box = tuple(box_) if box is None else box
    x0, y0, x1, y1 = box
    W, H = x1-x0, y1-y0
    pts = ' '.join(f'{px-x0:.3f},{py-y0:.3f}'
                   for px, py in _hex_vertices(cx, cy, rw, rh))
    inner, iw, ih, n = _inner_svg('b', ant_box, bgcut=16.0, levels=7,
                                  maskthr=30.0, lopct=8.0, turdsize=4)
    ix, iy = ant_box[0]-x0, ant_box[1]-y0
    iwid, ihgt = ant_box[2]-ant_box[0], ant_box[3]-ant_box[1]
    stroke = f'rgb({col[0]:.0f},{col[1]:.0f},{col[2]:.0f})'
    pts_glow = f'{" ".join(f"{px-x0:.3f},{py-y0:.3f}" for px,py in _hex_vertices(cx,cy,rw,rh))}'
    svg = (
      f'<svg class="brand-mark" viewBox="0 0 {W} {H}" '
      f'xmlns="http://www.w3.org/2000/svg" aria-hidden="true" '
      f'preserveAspectRatio="xMidYMid meet">'
      f'<defs><filter id="hexglow" x="-60%" y="-60%" width="220%" height="220%">'
      f'<feGaussianBlur stdDeviation="2.6"/></filter></defs>'
      f'<polygon points="{pts_glow}" fill="none" stroke="{stroke}" '
      f'stroke-width="{sw*3.2:.1f}" stroke-linejoin="round" opacity="0.42" '
      f'filter="url(#hexglow)"/>'
      f'<polygon points="{pts}" fill="none" stroke="{stroke}" '
      f'stroke-width="{sw:.2f}" stroke-linejoin="round"/>'
      f'<svg x="{ix}" y="{iy}" width="{iwid}" height="{ihgt}" '
      f'viewBox="0 0 {iw} {ih}" overflow="visible">{inner}</svg>'
      f'</svg>')
    return svg, n

def _perimeter_colour(v, box, thr=60):
    a = _ref(v)
    x0, y0, x1, y1 = box
    sub = a[y0:y1, x0:x1]
    lum = sub.mean(axis=2)
    m = lum > (np.median(lum[:2, :2]) + thr)
    return np.median(sub[m], axis=0) if m.sum() else np.array([40., 200., 130.])

_REFC = {}
def _ref(v):
    if v not in _REFC:
        _REFC[v] = np.asarray(Image.open(os.path.join(HERE, f'ref-{v}.png'))
                              .convert('RGB')).astype(np.float32)
    return _REFC[v]

# B's hexagon: the original hand-written CSS clip-path scores better than any
# trace of it (the rendered reference is a soft glowing thin stroke, which the
# band trace renders as mush) -- so only `c` is generated here.
BUILDERS = {'c': build_c}
SPAN = {'c': 'ant-icon', 'b': 'hex'}

def main():
    v = sys.argv[1]
    svg, n = BUILDERS[v]()
    cls = SPAN[v]
    open(os.path.join(HERE, f'mark-{v}.svg'), 'w').write(svg)
    print(f'{v}: {n} traced paths, {len(svg)} bytes  -> qa/mark-{v}.svg')
    if '--dump' in sys.argv:
        open(sys.argv[sys.argv.index('--dump')+1], 'w').write(svg)
    if '--apply' not in sys.argv:
        print('dry run (pass --apply)')
        return
    d = json.load(open(CONTENT))
    mk = d[v]['markup']
    repl = f'<span class="{cls}" aria-hidden="true">{svg}</span>'
    pat = rf'<span class="{cls}"[^>]*>.*?</span>'
    new, cnt = re.subn(pat, lambda _m: repl, mk, count=1, flags=re.S)
    if cnt == 0:
        raise SystemExit(f'no <span class="{cls}"> in content.json[{v}].markup')
    d[v]['markup'] = new
    json.dump(d, open(CONTENT, 'w'), indent=2)
    print(f'applied to content.json[{v}].markup ({cnt} span)')

if __name__ == '__main__':
    main()
