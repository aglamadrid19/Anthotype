#!/usr/bin/env python3
"""Auto-derive the mkart text-exclusion rectangles from a DOM-only render.

Renders the page with `.art` hidden, finds the row bands that contain DOM type
in the left column, and prints one (x0,y0,x1,y1) rect per band, grown by
`--grow N` px.  mkart's TEXT table is these rects: the artwork must not bake in
the rasterised words, or a later copy edit would leave a ghost of the old text.

usage: textrects.py <variant> [--grow N] [--xmax N] [--thr N]
"""

import _bootstrap  # noqa: F401  (re-exec under the venv python if needed)
import os, subprocess, sys
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)
from _env import node_env


def dom_render(v):
    env = node_env()
    env['CSS_OVERRIDE'] = '.content h1,.content h2,.content p,.brand{visibility:visible}.art{visibility:hidden}'
    subprocess.run(['node', 'gen-page.mjs', v],
                   cwd=PIPE, check=True, capture_output=True, env=env)
    subprocess.run(['./qa.sh', v], cwd=PIPE, check=True, capture_output=True, env=env)
    return np.asarray(Image.open(f'{HERE}/render-{v}.png').convert('L')).astype(np.float32)


def main():
    v = sys.argv[1]
    grow = int(sys.argv[sys.argv.index('--grow')+1]) if '--grow' in sys.argv else 4
    xmax = int(sys.argv[sys.argv.index('--xmax')+1]) if '--xmax' in sys.argv else 520
    thr = float(sys.argv[sys.argv.index('--thr')+1]) if '--thr' in sys.argv else 12.0
    d = dom_render(v)
    bg = float(np.median(d[:5, :5]))
    m = d > bg + thr
    m[:, xmax:] = False
    rows = np.nonzero(m.sum(axis=1) > 0)[0]
    rects = []
    if len(rows):
        s = p0 = rows[0]
        for r in rows[1:]:
            if r - p0 > 4:
                rects.append((s, p0)); s = r
            p0 = r
        rects.append((s, p0))
    out = []
    for (a, b) in rects:
        cols = np.nonzero(m[a:b+1].any(axis=0))[0]
        out.append((max(0, int(cols.min())-grow), max(0, a-grow),
                    int(cols.max())+1+grow, b+1+grow))
    print(f"'{v}': {out},")


if __name__ == '__main__':
    main()
