#!/usr/bin/env python3
"""Fit the page background field: solve additive radial gradients from residual.

Model:  render_bg(x,y) + sum_i A_i * exp(-d_i^2 / (2 s_i^2))   ~=  ref

For every pixel that is "background" in the render (close to the page base
colour) we have a linear system in the per-channel amplitudes A_i.  Solve by
least squares, then emit CSS radial-gradient layers.

usage: bgfit.py <variant> [--k N] [--render path]
"""
import os, sys, json
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)

BASE = {'a': (0.0, 10.0, 7.0), 'b': (0.0, 10.0, 6.0), 'c': (0.0, 10.0, 7.0)}

def load(v, png):
    return np.asarray(Image.open(png).convert('RGB')).astype(np.float32)

def background_mask(ren, base, tol=3.0):
    d = np.linalg.norm(ren - np.array(base, np.float32), axis=2)
    return d < tol

def fit(v, k=4, render=None, tol=3.0, verbose=True):
    render = render or f"{HERE}/render-{v}.png"
    R = load(v, f"{HERE}/ref-{v}.png")
    D = load(v, render)
    H, W = R.shape[:2]
    base = BASE[v]
    mask = background_mask(D, base, tol)
    if verbose: print(f"{v}: {mask.mean()*100:.1f}% of pixels are pure background in the render")
    ys, xs = np.nonzero(mask)
    # candidate centres on a coarse grid over the frame
    cands = [(x, y) for y in range(60, H, 110) for x in range(60, W, 110)]
    sigmas = [90., 150., 230., 330.]
    # greedy forward selection of (centre, sigma) pairs minimising residual
    res = (R - D)                     # residual we want the gradients to explain
    resm = res[mask]                  # (N,3)
    chosen = []
    cur = np.zeros_like(resm)
    for step in range(k):
        best = None
        for (cx, cy) in cands:
            g = np.exp(-(((xs-cx)**2 + (ys-cy)**2)[:, None]) / (2*150.0**2))
            # least squares scalar per channel for this basis
            num = (resm - cur) * g
            den = (g*g).sum()
            A = num.sum(axis=0) / den
            pred = cur + g * A
            err = np.abs(resm - pred).mean()
            if best is None or err < best[0]:
                best = (err, (cx, cy), 150.0, A)
        err, (cx, cy), s, A = best
        # local sigma refinement
        for ss in (60., 80., 110., 150., 200., 260., 340., 440.):
            g = np.exp(-(((xs-cx)**2 + (ys-cy)**2)[:, None]) / (2*ss*ss))
            num = (resm - cur) * g
            den = (g*g).sum()
            A2 = num.sum(axis=0)/den
            pred = cur + g*A2
            e2 = np.abs(resm - pred).mean()
            if e2 < err: err, s, A = e2, ss, A2
        g = np.exp(-(((xs-cx)**2 + (ys-cy)**2)[:, None]) / (2*s*s))
        cur = cur + g*A
        chosen.append(dict(cx=cx, cy=cy, sigma=s, A=[float(x) for x in A]))
        if verbose:
            print(f"  + centre ({cx},{cy}) sigma {s:.0f}  A=({A[0]:+.2f},{A[1]:+.2f},{A[2]:+.2f})  resid {err:.3f}")
    if verbose:
        print(f"  final residual (background px only) {np.abs(resm-cur).mean():.3f}")
        # global effect
        full = np.zeros_like(R)
        yy, xx = np.mgrid[0:H, 0:W]
        sub = []
        for c in chosen:
            g = np.exp(-(((xx-c['cx'])**2 + (yy-c['cy'])**2)) / (2*c['sigma']**2))
            sub.append(g[..., None] * np.array(c['A'], np.float32))
        field = sum(sub)
        newd = np.clip(D + field, 0, 255)
        print(f"  overall would go {np.abs(R-D).mean():.3f} -> {np.abs(R-newd).mean():.3f}")
    return chosen

def _stops(r, g, b, sigma_ratio=2.5, n=9):
    """Emit colour stops approximating a Gaussian of the given amplitude."""
    r = max(0.0, r); g = max(0.0, g); b = max(0.0, b)
    out = []
    for i in range(n):
        f = i/(n-1)
        # position in the gradient, radius R = sigma_ratio*sigma
        a = float(np.exp(-(f*sigma_ratio)**2/2.0))
        pct = f*100.0
        out.append(f"rgba({r:.2f},{g:.2f},{b:.2f},{a:.3f}) {pct:.1f}%")
    return ", ".join(out)

def css(v, chosen, base=None, sigma_ratio=2.5):
    base = base or BASE[v]
    W, H = 1024, 768
    layers = []
    for c in sorted(chosen, key=lambda c: -max(c['A'])):
        rx = c['sigma']*sigma_ratio/W*100
        ry = c['sigma']*sigma_ratio/H*100
        px = c['cx']/W*100; py = c['cy']/H*100
        layers.append(f"radial-gradient(ellipse {rx:.1f}% {ry:.1f}% at {px:.1f}% {py:.1f}%, "
                      + _stops(*c['A']) + ")")
    return ",\n    ".join(layers) + f",\n    rgb({base[0]:.0f} {base[1]:.0f} {base[2]:.0f})"

if __name__ == '__main__':
    v = sys.argv[1]
    k = int(sys.argv[sys.argv.index('--k')+1]) if '--k' in sys.argv else 4
    render = sys.argv[sys.argv.index('--render')+1] if '--render' in sys.argv else None
    ch = fit(v, k, render)
    print()
    print(css(v, ch))
    json.dump(ch, open(f"{HERE}/bg-{v}.json", 'w'), indent=1)
