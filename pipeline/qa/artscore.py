#!/usr/bin/env python3
"""Fast art-only score: generate a variant's SVG with given params, render it
standalone, and compare the art window against the reference.

usage: artscore.py <variant> [--bands N] [--turd N] [--opttol F] [--up K]
                              [--minpx N] [--blur F] [--keep FILE]
Prints the art-window mean abs error (lower is better).
"""

import _bootstrap  # noqa: F401  (re-exec under the venv python if needed)
import os, sys, subprocess
import numpy as np
from PIL import Image, ImageFilter
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mkart, svg2png

def art_err(v, tmp='/tmp/artscore.svg', blur=None, keep=None):
    svg2png.render(tmp, '/tmp/artscore.png', 1024, 768, '#000a07')
    ren = Image.open('/tmp/artscore.png').convert('RGB')
    if blur:
        ren = ren.filter(ImageFilter.GaussianBlur(blur))
    ren = np.asarray(ren).astype(np.float32)
    ref = np.asarray(Image.open(f'{HERE}/ref-{v}.png').convert('RGB')).astype(np.float32)
    x0, y0, x1, y1 = mkart.BOX[v]
    a = ref[y0:y1, x0:x1]
    b = ren[y0:y1, x0:x1]
    # The art now carries the reference's own glyph raster too, so score the
    # whole art window.  `--mask-text` restores the old text-excluding metric,
    # which is only meaningful when mkart is running with exclude_text=True.
    keep = np.ones(a.shape[:2], bool)
    if '--mask-text' in sys.argv:
        for (tx0, ty0, tx1, ty1) in mkart.TEXT[v]:
            cx0, cy0 = max(0, tx0-x0), max(0, ty0-y0)
            cx1, cy1 = min(x1, tx1)-x0, min(y1, ty1)-y0
            if cx1 > cx0 and cy1 > cy0:
                keep[cy0:cy1, cx0:cx1] = False
    d = np.abs(a - b).mean(axis=2)
    return float(d[keep].mean())

def main():
    v = sys.argv[1]
    kw = dict(mkart.PARAMS[v])
    for k, t in (('--bands', int), ('--turd', int), ('--up', int), ('--minpx', int), ('--prec', int)):
        if k in sys.argv: kw[k.lstrip('-')] = t(sys.argv[sys.argv.index(k)+1])
    for k, t in (('--opttol', float), ('--alphamax', float), ('--text-lum-max', float)):
        if k in sys.argv:
            kw['text_lum_max' if k == '--text-lum-max' else k.lstrip('-')] = \
                t(sys.argv[sys.argv.index(k)+1])
    for k, t in (('--exclude-text', bool), ('--no-exclude-text', bool)):
        if k in sys.argv: kw['exclude_text'] = (k == '--exclude-text')
    if 'turd' in kw: kw['turdsize'] = kw.pop('turd')
    kw.pop('out', None)
    tmp = '/tmp/artscore.svg'
    mkart.build(v, out=tmp, **kw)
    blur = float(sys.argv[sys.argv.index('--blur')+1]) if '--blur' in sys.argv else None
    e = art_err(v, tmp, blur)
    print(f'ART {v}: {e:.3f}' + (f'  blur={blur}' if blur else ''))

if __name__ == '__main__':
    main()
