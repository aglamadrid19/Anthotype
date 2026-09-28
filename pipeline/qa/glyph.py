#!/usr/bin/env python3
"""Trace a small glyph region of a reference into a standalone inline SVG.

Emits a self-contained `<svg>` whose viewBox matches the traced bitmap, so
potrace's own y-flip transform stays valid and no coordinate rewriting is
needed.  The result is real vector geometry that can be positioned/sized by CSS
and re-coloured by CSS variables.

usage: glyph.py <png> <x0 y0 x1 y1> [--up K] [--levels L] [--bgcut C]
                [--class NAME] [--out FILE] [--show] [--turdsize N]
"""
import os, re, sys
import numpy as np
from PIL import Image
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from potrace_util import potrace

# ---- path subpath handling -------------------------------------------------
# potrace emits one `d` per band containing *several* subpaths: the frame-filling
# outline first, then the real contours.  We need to drop only the former, which
# means walking the path and tracking the current point so relative commands stay
# correct after the removal.
_ARGN = {'M':2,'L':2,'T':2,'H':1,'V':1,'C':6,'S':4,'Q':4,'A':7,'Z':0}

def _split_subpaths(d):
    """Return [(cmd_letter, numbers)] segments, one per `M`/`m`."""
    toks = re.findall(r'[MmLlCcSsQqTtAaZzHhVv]|-?\d*\.?\d+(?:e[-+]?\d+)?', d)
    segs, cur, cmd = [], [], None
    i = 0
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            c = t
            if c in 'Mm':
                if cur: segs.append((cmd, cur)); cur = []
                cmd = c
                i += 1
                continue
            if c in 'Zz':
                cur.append(c); cmd = cmd if cmd else 'M'; i += 1; continue
            cmd = c; i += 1; continue
        cur.append(t); i += 1
    if cur: segs.append((cmd, cur))
    return segs

def _subpath_bbox(cmd, nums, start):
    """Absolute bbox of one subpath whose implicit origin is `start`."""
    rel = cmd.islower()
    cx, cy = start
    ox, oy = (cx, cy) if rel else (0.0, 0.0)
    xs, ys = [], []
    k = 0
    while k < len(nums):
        ch = cmd
        need = 2
        # potrace only emits M/L/C; be liberal for anything else
        if ch in 'Ll': need = 2
        elif ch in 'Cc': need = 6
        elif ch in 'Ss': need = 4
        elif ch in 'Qq': need = 4
        elif ch in 'Hh': need = 1
        elif ch in 'Vv': need = 1
        vals = []
        while k < len(nums) and len(vals) < need:
            try: vals.append(float(nums[k]))
            except ValueError: break
            k += 1
        if len(vals) < need: break
        if ch in 'Mm':
            cx = vals[0] + (ox if rel else 0.0)
            cy = vals[1] + (oy if rel else 0.0)
            xs += [cx]; ys += [cy]
        elif ch in 'Ll':
            cx = vals[0] + (ox if rel else 0.0); cy = vals[1] + (oy if rel else 0.0)
            xs += [cx]; ys += [cy]
        elif ch in 'Cc':
            for j in range(0, 6, 2):
                xs.append(vals[j] + (ox if rel else 0.0))
                ys.append(vals[j+1] + (oy if rel else 0.0))
            cx, cy = xs[-1], ys[-1]
        elif ch in 'Hh':
            cx = vals[0] + (ox if rel else 0.0); xs.append(cx); ys.append(cy)
        elif ch in 'Vv':
            cy = vals[0] + (oy if rel else 0.0); ys.append(cy); xs.append(cx)
        else:
            break
    if not xs: return None, (cx, cy)
    return (min(xs), min(ys), max(xs), max(ys)), (cx, cy)

def strip_frame_subpaths(d, w, h, tol=0.97):
    """Rewrite `d` with any frame-spanning subpath removed.

    A subpath covering >=97% of both axes is a background plate, not artwork;
    leaving it in paints an opaque rectangle over everything beneath.
    """
    segs = _split_subpaths(d)
    if len(segs) < 2: return d
    keep, pos, dropped = [], (0.0, 0.0), 0
    for i, (cmd, nums) in enumerate(segs):
        bb, npos = _subpath_bbox(cmd, nums, pos)
        if i == 0 and bb and (bb[2]-bb[0]) >= tol*w and (bb[3]-bb[1]) >= tol*h:
            dropped += 1
            pos = npos
            continue
        keep.append(cmd + ' '.join(nums))
        pos = npos
    if not dropped: return d
    return ' '.join(keep)


def build(png, box, up=4, levels=5, bgcut=10.0, turdsize=1, cls='glyph',
          alphamax=1.0, opttol=0.12, lopct=25.0, maskthr=None):
    x0, y0, x1, y1 = box
    a = np.asarray(Image.open(png).convert('RGB')).astype(np.float32)
    sub = a[y0:y1, x0:x1]
    W, H = (x1-x0)*up, (y1-y0)*up
    big = np.asarray(Image.fromarray(sub.astype(np.uint8)).resize((W, H), Image.LANCZOS)).astype(np.float32)
    lum = big.mean(axis=2)
    bg = float(np.median(lum[:2, :2]))
    ink = lum > bg + bgcut
    if ink.sum() < up*up*2: return None, 0
    # A weak outer glow can survive `bgcut` and form a frame-filling band.
    # Anchor the band range to the *core* of the mark instead: discard ink that
    # falls outside the dilated core mask when `maskthr` is given, and start the
    # lowest band at `lopct` of the remaining ink luminance.
    if maskthr is not None:
        core = lum > float(maskthr)
        from scipy import ndimage as ndi
        core = ndi.binary_dilation(core, iterations=max(2, up))
        core = ndi.binary_fill_holes(core)
        ink = ink & core
    if ink.sum() < up*up*2: return None, 0
    lo, hi = np.percentile(lum[ink], lopct), np.percentile(lum[ink], 99.7)
    edges = np.linspace(lo, hi, levels+1)
    groups, npath = [], 0
    for i in range(levels):
        m = ink & ((lum >= edges[i]) if i == levels-1 else ((lum >= edges[i]) & (lum < edges[i+1])))
        if m.sum() < up*up: continue
        col = np.median(big[m], axis=0)
        # A band masking almost the whole frame is the background/glow, not a
        # shape: potrace turns it into one giant rectangle that then paints an
        # opaque block over everything else.  Drop those.
        if m.mean() > 0.985: continue
        ds, tx, ty, sx, sy, w, h = potrace(m, turdsize=turdsize, alphamax=alphamax, opttol=opttol)
        if not ds: continue
        # ...and strip any subpath inside a band that spans the whole frame
        # (potrace's "everything except the mark" plate).
        ds = [d for d in (strip_frame_subpaths(x, w, h) for x in ds) if d]
        if not ds: continue
        npath += len(ds)
        groups.append(
            f'<g fill="rgb({col[0]:.0f},{col[1]:.0f},{col[2]:.0f})" '
            f'transform="translate({tx:.4f},{ty:.4f}) scale({sx:.4f},{sy:.4f})">'
            + ''.join(f'<path d="{d}"/>' for d in ds) + '</g>')
    if not groups: return None, 0
    svg = (f'<svg class="{cls}" viewBox="0 0 {W} {H}" '
           f'xmlns="http://www.w3.org/2000/svg" aria-hidden="true" '
           f'preserveAspectRatio="xMidYMid meet">' + ''.join(groups) + '</svg>')
    return svg, npath

if __name__ == '__main__':
    png = sys.argv[1]; box = tuple(map(int, sys.argv[2:6]))
    kw = {}
    for k, t in (('--up', int), ('--levels', int), ('--turdsize', int)):
        if k in sys.argv: kw[k.lstrip('-')] = t(sys.argv[sys.argv.index(k)+1])
    for k, t in (('--bgcut', float), ('--alphamax', float), ('--opttol', float),
                 ('--lopct', float), ('--maskthr', float)):
        if k in sys.argv: kw[k.lstrip('-')] = t(sys.argv[sys.argv.index(k)+1])
    if '--class' in sys.argv: kw['cls'] = sys.argv[sys.argv.index('--class')+1]
    svg, n = build(png, box, **kw)
    print(f"{n} paths, {len(svg or '')} bytes")
    if '--out' in sys.argv and svg: open(sys.argv[sys.argv.index('--out')+1], 'w').write(svg)
    if '--show' in sys.argv and svg: print(svg)
