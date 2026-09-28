#!/usr/bin/env python3
"""Trace a small glyph region of a reference into a compact inline SVG snippet.

usage: traceicon.py <png> <x0 y0 x1 y1> [--levels L] [--prec N] [--out f.svg] [--bgcut N]
"""
import os, re, sys, subprocess, tempfile
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))

_NUM = re.compile(r'[MmLlCcSsQqTtAaZzHhVv]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')

def _potrace(mask, turdsize=1, alphamax=1.0, opttol=0.15):
    with tempfile.TemporaryDirectory() as td:
        pbm = os.path.join(td, 'm.pbm')
        Image.fromarray((mask*255).astype(np.uint8), 'L').convert('1').save(pbm)
        svg = os.path.join(td, 'm.svg')
        subprocess.run(['potrace', pbm, '-s', '-o', svg, '--turdsize', str(turdsize),
                        '--alphamax', str(alphamax), '--opttolerance', str(opttol),
                        '--unit', '1'], capture_output=True, check=True)
        data = open(svg).read()
    m = re.search(r'<g transform="translate\(([-\d.]+),([-\d.]+)\) scale\(([-\d.]+),([-\d.]+)\)"', data)
    tx, ty, sx, sy = (float(m.group(i)) for i in (1,2,3,4)) if m else (0,0,1,1)
    return [(d, tx, ty, sx, sy) for d in re.findall(r'<path[^>]*?\bd="([^"]+)"', data, re.S)]

def fmt(d, tx, ty, sx, sy, k=1.0, prec=2):
    toks = _NUM.findall(d); out = []; axis = 0; first = None
    for t in toks:
        if t[0].isalpha():
            out.append(t)
            if t in 'Zz': first = None
            axis = 0; continue
        v = (tx + float(t)*sx) if axis == 0 else (ty + float(t)*sy)
        axis = 1-axis
        q = v*k
        s = f"{q:.{prec}f}".rstrip('0').rstrip('.')
        out.append(s if s not in ('','-0') else '0')
    return ' '.join(out).replace(' -', '-')

def build(png, box, levels=4, prec=2, bgcut=8.0, turdsize=1, scale=1.0):
    x0,y0,x1,y1 = box
    a = np.asarray(Image.open(png).convert('RGB')).astype(np.float32)
    sub = a[y0:y1, x0:x1]
    lum = sub.mean(axis=2)
    bg = np.median(lum[:3,:3])
    ink = lum > bg + bgcut
    if ink.sum() < 8: return None, 0
    lo, hi = np.percentile(lum[ink], 20), np.percentile(lum[ink], 99.5)
    edges = np.linspace(lo, hi, levels+1)
    out, npath = [], 0
    for i in range(levels):
        m = ink & ((lum >= edges[i]) if i == levels-1 else ((lum >= edges[i]) & (lum < edges[i+1])))
        if m.sum() < 4: continue
        col = np.median(sub[m], axis=0)
        ds = _potrace(m, turdsize)
        if not ds: continue
        npath += len(ds)
        out.append(f'<g fill="rgb({col[0]:.0f},{col[1]:.0f},{col[2]:.0f})">')
        for (d,tx,ty,sx,sy) in ds:
            out.append(f'<path d="{fmt(d,tx,ty,sx,sy,scale,prec)}"/>')
        out.append('</g>')
    return ''.join(out), npath

if __name__ == '__main__':
    png = sys.argv[1]; box = tuple(map(int, sys.argv[2:6]))
    kw = {}
    for k,t in (('--levels',int),('--prec',int),('--bgcut',float),('--scale',float)):
        if k in sys.argv: kw[k.lstrip('-')] = t(sys.argv[sys.argv.index(k)+1])
    g, n = build(png, box, **kw)
    print(f"{n} paths, {len(g)} bytes")
    print(g[:400])
    if '--out' in sys.argv: open(sys.argv[sys.argv.index('--out')+1],'w').write(g)
