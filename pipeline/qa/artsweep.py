#!/usr/bin/env python3
"""Sweep vectorization parameters and score each against the reference."""
import os, sys, subprocess, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch, mkart

def score_variant(v, **kw):
    svg = f"/tmp/sweep-{v}.svg"
    mkart.build(v, out=svg, **{k: val for k, val in kw.items()})
    png = f"/tmp/sweep-{v}.png"
    batch.__dict__  # noop
    sys.path.insert(0, HERE)
    from svg2png import render
    render(svg, png, 1024, 768, '#000a07')
    a = np.asarray(batch.Image.open(png).convert('RGB')).astype(np.float32)
    # splice the art into a real page render by overriding the art layer
    return float(np.abs(a - batch.ref(v)).mean())

if __name__ == '__main__':
    v = sys.argv[1]
    box = mkart.BOX[v]
    R = batch.ref(v)
    x0,y0,x1,y1 = box
    for bands, up, turd, opttol in [(16,2,3,0.2),(20,2,3,0.2),(26,2,3,0.16),
                                    (32,2,3,0.16),(40,2,3,0.16),(26,3,3,0.16),
                                    (32,3,3,0.16),(40,3,3,0.16),(48,3,2,0.14)]:
        svg = f"/tmp/sw-{v}.svg"; png = f"/tmp/sw-{v}.png"
        mkart.build(v, bands=bands, up=up, turdsize=turd, opttol=opttol, out=svg)
        from svg2png import render
        render(svg, png, 1024, 768, '#000a07')
        a = np.asarray(batch.Image.open(png).convert('RGB')).astype(np.float32)
        d = np.abs(a[y0:y1,x0:x1]-R[y0:y1,x0:x1]).mean()
        sz = os.path.getsize(svg)/1024
        print(f"  bands={bands:3d} up={up} turd={turd} opttol={opttol}  art {d:6.3f}  {sz:6.0f} KB", flush=True)
