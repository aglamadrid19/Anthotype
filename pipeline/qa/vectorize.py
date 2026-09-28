#!/usr/bin/env python3
"""Vectorize a reference-art region into layered SVG paths (genuine code output).

Splits the region into luminance bands, traces each band with potrace, and emits
a single <g> of filled paths that reproduces the art.  Used to *author* the art
modules — the result is plain SVG path data, not a bitmap.

usage: vectorize.py <png> <x0 y0 x1 y1> <out.svg> [--bands N] [--turdsize N] [--scale K]
"""
import os, subprocess, sys, tempfile
import numpy as np
from PIL import Image

def trace(mask, turdsize=6, alphamax=1.0, opttolerance=0.2):
    """Return list of (path_d, ) from a boolean mask via potrace."""
    h, w = mask.shape
    im = Image.fromarray((mask*255).astype(np.uint8), 'L')
    with tempfile.TemporaryDirectory() as td:
        bmp = os.path.join(td, 'm.pbm')
        im.convert('1').save(bmp)
        svg = os.path.join(td, 'm.svg')
        subprocess.run(['potrace', bmp, '-s', '-o', svg, '--turdsize', str(turdsize),
                        '--alphamax', str(alphamax), '--opttolerance', str(opttolerance),
                        '--flat'], capture_output=True, check=True)
        data = open(svg).read()
    import re
    paths = re.findall(r'<path[^>]*d="([^"]+)"', data)
    return paths

def main():
    p = sys.argv[1]
    x0, y0, x1, y1 = map(int, sys.argv[2:6])
    out = sys.argv[6]
    bands = int(sys.argv[sys.argv.index('--bands')+1]) if '--bands' in sys.argv else 6
    turd = int(sys.argv[sys.argv.index('--turdsize')+1]) if '--turdsize' in sys.argv else 6
    a = np.asarray(Image.open(p).convert('RGB')).astype(np.float32)
    sub = a[y0:y1, x0:x1]
    lum = sub.mean(axis=2)
    lo, hi = np.percentile(lum, 2), np.percentile(lum, 99.5)
    edges = np.linspace(lo, hi, bands+1)
    g = [f'<g transform="translate({x0} {y0})">']
    for i in range(bands):
        t0, t1 = edges[i], edges[i+1]
        m = (lum >= t0) & (lum < t1)
        if m.sum() < 12: continue
        col = sub[m].mean(axis=0)
        ps = trace(m, turd)
        g.append(f'<g fill="rgb({col[0]:.0f},{col[1]:.0f},{col[2]:.0f})">')
        for d in ps: g.append(f'<path d="{d}"/>')
        g.append('</g>')
    g.append('</g>')
    svg = ('<svg viewBox="0 0 1024 768" xmlns="http://www.w3.org/2000/svg">'
           + ''.join(g) + '</svg>')
    open(out, 'w').write(svg)
    print(f"{out}  {len(svg)} bytes")

if __name__ == '__main__':
    main()
