#!/usr/bin/env python3
"""Shared potrace wrapper: returns raw path data plus potrace's own transform.

We never re-write path coordinates.  potrace emits its outline in a
y-up bitmap space and wraps it in `translate(0,H) scale(1,-1)`; that transform is
kept verbatim and composed with the caller's own transform via nested SVG <g>
elements, which is exactly how SVG transform composition is defined.
"""
import os, re, subprocess, sys, tempfile
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # resolves potrace without trusting PATH

_TR = re.compile(r'<g transform="translate\(([-\d.]+),([-\d.]+)\)\s*scale\(([-\d.]+),([-\d.]+)\)"')

def potrace(mask, turdsize=2, alphamax=1.0, opttol=0.16, upscale=1):
    """Trace a boolean mask; returns (paths, tx, ty, sx, sy, width, height)."""
    h, w = mask.shape
    ink = mask.astype(np.uint8) * 255
    if upscale != 1:
        im = Image.fromarray(ink, 'L').resize((w*upscale, h*upscale), Image.LANCZOS)
    else:
        im = Image.fromarray(ink, 'L')
    with tempfile.TemporaryDirectory() as td:
        pbm = os.path.join(td, 'm.pbm')
        im.convert('1').save(pbm)
        svg = os.path.join(td, 'm.svg')
        subprocess.run([_env.potrace_bin(), pbm, '-s', '-o', svg,
                        '--turdsize', str(turdsize), '--alphamax', str(alphamax),
                        '--opttolerance', str(opttol), '--unit', '1'],
                       capture_output=True, check=True)
        data = open(svg).read()
    m = _TR.search(data)
    tx, ty, sx, sy = (float(m.group(i)) for i in (1,2,3,4)) if m else (0,0,1,1)
    ds = re.findall(r'<path[^>]*?\bd="([^"]+)"', data, re.S)
    return ds, tx, ty, sx, sy, w, h

def group(ds, tx, ty, sx, sy, extra_scale=1.0, outer=None, cls=None, fill=None):
    """Compose potrace's transform with (outer) and an optional extra scale."""
    inner = f'translate({tx:.4f},{ty:.4f}) scale({sx:.4f},{sy:.4f})'
    if extra_scale != 1.0:
        inner += f' scale({1/extra_scale:.6f})'
    attrs = f'transform="{inner}"'
    if cls: attrs = f'class="{cls}" ' + attrs
    if fill: attrs += f' fill="{fill}"'
    body = ''.join(f'<path d="{d}"/>' for d in ds)
    g = f'<g {attrs}>{body}</g>'
    return f'<g transform="{outer}">{g}</g>' if outer else g
