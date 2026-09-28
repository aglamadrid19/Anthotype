#!/usr/bin/env python3
"""Fit a small set of radial gradients to the page background, then *emit CSS
and verify it empirically* -- the trick bgfit.py missed, which is that stacked
CSS radial-gradients composite (src-over) rather than add, so a least-squares
field fit does not survive the round-trip to CSS.

Model actually rendered by the browser for one layer over base b:
    out = c*a(f) + b*(1-a(f))
With a near-black base this is just  c*a(f)  -- i.e. a single layer can
reproduce an arbitrary *radial* profile exactly by putting the amplitude in
the alpha stops and the hue in the rgb.  We therefore fit one dominant layer
(from the residual field's centre of mass) plus a second, weaker one, and
accept the result only if a real render improves.

usage: bgfit2.py <variant> [--k 2] [--apply]
"""
import json, math, os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch

BASE = {'a': (0, 10, 7), 'b': (0, 10, 6), 'c': (0, 10, 7)}
# windows that are pure background in every variant
BG_WIN = {'bgTL': (0, 0, 300, 240), 'bgR': (850, 0, 1024, 768),
          'bgB': (0, 690, 1024, 768), 'all': (0, 0, 1024, 768)}

def residual_field(v):
    R = np.asarray(Image.open(f'{HERE}/ref-{v}.png').convert('RGB')).astype(np.float32)
    D = np.asarray(Image.open(f'{HERE}/render-{v}.png').convert('RGB')).astype(np.float32)
    return R - D

def fit_layer(res, cx, cy, sigma, base):
    """Least-squares per-channel gain of shape a=exp(-r^2/2s^2), returned as
    (rgb, alpha_scale) for `out = rgb * a * alpha_scale`."""
    H, W = res.shape[:2]
    yy, xx = np.mgrid[0:H, 0:W]
    a = np.exp(-(((xx-cx)**2 + (yy-cy)**2)) / (2*sigma*sigma))
    # out = c * a  =>  c = <res, a> / <a, a>
    den = (a*a).sum()
    c = (res * a[..., None]).sum(axis=(0, 1)) / den
    # clamp: channel up to 255, and reproduce via rgb + alpha stops
    peak = max(1e-6, float(np.abs(c).max()))
    col = np.clip(c, 0, 255)
    return col, a

def stops_for(col, amp, n=9, ratio=2.5, gamma=1.0):
    """Emit alpha stops so that col*alpha(f) traces the fitted profile."""
    out = []
    for i in range(n):
        f = i/(n-1)
        g = math.exp(-(f*ratio)**2/2.0)
        al = min(1.0, amp*g)
        out.append(f'rgba({col[0]:.1f},{col[1]:.1f},{col[2]:.1f},{al:.4f}) {f*100:.1f}%')
    return ', '.join(out)

def main():
    v = sys.argv[1]
    k = int(sys.argv[sys.argv.index('--k')+1]) if '--k' in sys.argv else 2
    res = residual_field(v)
    H, W = res.shape[:2]
    base = BASE[v]

    # centre of mass of the (positive) residual, restricted to background-ish
    # pixels so bright art does not drag the centre around
    lum = res.mean(axis=2)
    yy, xx = np.mgrid[0:H, 0:W]
    # ignore the art half of the frame where our art may be wrong
    m = (lum > 0) & (xx < 1024)
    for bx0, by0, bx1, by1 in BG_WIN.values():
        pass
    w = np.clip(lum, 0, None) * m
    cx = float((w*xx).sum()/w.sum()); cy = float((w*yy).sum()/w.sum())
    # spread
    sx = math.sqrt(float((w*(xx-cx)**2).sum()/w.sum()))
    sy = math.sqrt(float((w*(yy-cy)**2).sum()/w.sum()))
    print(f'{v}: residual CoM ({cx:.0f},{cy:.0f}) spread ({sx:.0f},{sy:.0f}) '
          f'mean {lum.mean():.2f} peak {lum.max():.1f}')

    layers = []
    cur = np.zeros_like(res)
    for i in range(k):
        col, a = fit_layer(res - cur, cx, cy, max(60.0, (sx+sy)/2), base)
        layers.append((cx, cy, max(60.0, (sx+sy)/2), col))
        cur = cur + a[..., None]*col
    print('  layers:', [(f'({c[0]:.0f},{c[1]:.0f})', f's{c[2]:.0f}',
                         f'rgb({c[3][0]:.0f},{c[3][1]:.0f},{c[3][2]:.0f})') for c in layers])

    # emit CSS: dominant layer last-ish so weaker ones tint on top
    css_layers = []
    for (cx_, cy_, s_, col) in sorted(layers, key=lambda L: -float(np.abs(L[3]).max())):
        amp = float(np.abs(col).max())/255.0
        rx = s_*2.5/W*100; ry = s_*2.5/H*100
        css_layers.append(f'radial-gradient(ellipse {rx:.1f}% {ry:.1f}% at '
                          f'{cx_/W*100:.1f}% {cy_/H*100:.1f}%, '
                          + stops_for(col, 1.0) + ')')
    ov = '.stage{background:' + ', '.join(css_layers) + f', rgb({base[0]} {base[1]} {base[2]})}}'
    open(f'{HERE}/bg2-{v}.css', 'w').write(ov + '\n')

    scores = batch.score(v, ['', ov], windows=BG_WIN)
    print(f'  base  all {scores[0]["all"]:6.3f}  bgTL {scores[0]["bgTL"]:6.3f} '
          f'bgR {scores[0]["bgR"]:6.3f}  bgB {scores[0]["bgB"]:6.3f}')
    print(f'  fit   all {scores[1]["all"]:6.3f}  bgTL {scores[1]["bgTL"]:6.3f} '
          f'bgR {scores[1]["bgR"]:6.3f}  bgB {scores[1]["bgB"]:6.3f}')
    gain = scores[0]['all'] - scores[1]['all']
    print(f'  {"ACCEPT" if gain > 0.005 else "reject"} (all gain {gain:+.3f})')
    if '--apply' in sys.argv and gain > 0.005:
        print('wrote', f'{HERE}/bg2-{v}.css')

if __name__ == '__main__':
    main()
