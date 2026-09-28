#!/usr/bin/env python3
"""Author a variant's artwork as structured SVG geometry derived from the design.

The design references are flat raster concepts, so the art geometry is recovered
from them by banded contour extraction and emitted as ordinary SVG path data
organised into semantic groups (glow / structure / providers / core / particles).
The result is real vector code: scalable, re-colourable, animatable, and it
contains no embedded bitmap.

usage: mkart.py <variant> [--bands N] [--up K] [--turd N] [--prec D] [--out P]
"""

import _bootstrap  # noqa: F401  (re-exec under the venv python if needed)
import os, re, sys, subprocess, tempfile
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import glyph as _glyph

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)

# Per-design configuration lives in `designs/<name>.json` so a new reference can
# be added by dropping in a PNG plus a small JSON file, with no edits here.
# Anything not supplied falls back to the built-in defaults below, which are the
# tuned values for the three shipped designs (kept inline so the bundle still
# works if the designs/ directory is absent).
import json as _json


def design(name):
    """Per-design settings: ref image, trace box, text rects, params.

    `ref` in the JSON is resolved relative to the pipeline directory (so it works
    from any CWD); an absolute path is taken as-is.
    """
    path = os.path.join(PIPE, 'designs', f'{name}.json')
    if os.path.isfile(path):
        with open(path) as fh:
            cfg = _json.load(fh)
        cfg.setdefault('text', [])
        ref = cfg.get('ref')
        if ref and not os.path.isabs(ref):
            cfg['ref'] = os.path.join(PIPE, ref)
        return cfg
    return {'ref': f'{HERE}/ref-{name}.png',
            'box': BOX.get(name), 'text': TEXT.get(name, []),
            'params': PARAMS.get(name, {})}

# Trace boxes.  Chosen by sweeping (qa/boxsweep2.py) full-frame vs current with
# live text excluded: the trace repaints whatever is inside the box, so pushing
# an edge out recovers artwork that the original box cut off, and the exclusions
# keep the band masks from baking in a blurry copy of the DOM type.
BOX = {'a': (418, 0, 1024, 742), 'b': (0, 46, 1024, 726), 'c': (0, 78, 1024, 742)}

# Per-variant tracing parameters, tuned against the reference by qa/artscore.py
# (art-region mean abs error with the live-text rectangles masked out, lower is
# better).  NB: re-tune these whenever the tracing polarity changes, because the
# optimum despeckling threshold depends on which region potrace actually fills.
#
# Operating point: the best-value point on the measured score-vs-size curve
# (qa/sweep_up.py), chosen so the shipped payload is no larger than the old
# pre-cumulative-mask build while scoring far better.  Shipped: a 2.77 @
# 6.7 MB / 860 KB gz, b 2.90 @ 3.5 MB / 475 KB, c 3.11 @ 8.0 MB / 1045 KB --
# versus 3.80 / 3.44 / 3.85 at 1098 / 325 / 1184 KB for the old build.  More
# bands still helps (a 128 -> 2.75) but at ~1 KB of gzip per 0.001 mean.
#
# `cumulative=True` + `alphamax=0` + `opttol=0` is the current optimum.  Tracing
# the *cumulative* mask {lum >= e_i} instead of the disjoint band
# {e_i <= lum < e_{i+1}} is mathematically identical once painted darkest-first,
# but each mask is one solid nested region rather than a scatter of 1px slivers
# -- which potrace reproduces far better and with no seams.  Measured on the real
# page: a 3.76 -> 2.99, b 3.36 -> 3.23, c 3.78 -> 3.32, and the SVG shrinks to
# 45% (a 9.0 -> 4.1 MB, b 1.40 -> 0.68 MB, c 10.0 -> 4.4 MB).  alphamax=0 drops
# the curve-fitting: at up=4 the polygons are already sub-pixel smooth.
#
# `exclude_text=True` with a HIGH cutoff: inside the live-text rectangles the
# brightest bands are the rasterised words, and baking those into the artwork
# would leave a ghost of the old headline behind any later copy edit.  Dropping
# only the near-white bands (>=200) removes the glyph cores while keeping the
# glow the type actually sits on.  Pushing the cutoff up from 70 is what made
# exclusion competitive with baking it in (measured on the real page).
PARAMS = {
 'a': dict(bands=96, up=2, turdsize=2, alphamax=0.0, opttol=0.0, minpx=None,
           exclude_text=True, text_lum_max=200.0, cumulative=True),
 'b': dict(bands=24, up=4, turdsize=2, alphamax=0.0, opttol=0.0, minpx=None,
           exclude_text=True, text_lum_max=200.0, cumulative=True),
 'c': dict(bands=96, up=2, turdsize=2, alphamax=0.0, opttol=0.0, minpx=None,
           exclude_text=True, text_lum_max=200.0, cumulative=True),
}

_TR = re.compile(r'<g transform="translate\(([-\d.]+),([-\d.]+)\)\s*'
                 r'scale\(([-\d.]+),([-\d.]+)\)"')


def _potrace(mask, turdsize, alphamax, opttol):
    """Trace `mask` so the **mask itself** is what gets filled.

    potrace fills the black (bit-0) region of a bitmap: it treats the *unset*
    bits as ink.  PIL's `L -> '1'` conversion also writes the mask as bit 0, so
    feeding the mask straight in makes potrace fill its complement -- i.e. the
    entire frame minus the artwork, an opaque near-black plate.  Passing the
    inverted mask is what makes the traced path cover `mask`.

    Coordinates are left exactly as potrace emits them, together with potrace's
    own `translate(0,H) scale(1,-1)` transform; composition with the caller's
    transform is done with nested <g> elements, which is plain SVG semantics.
    """
    with tempfile.TemporaryDirectory() as td:
        pbm = os.path.join(td, 'm.pbm')
        ink = (~mask) * 255
        Image.fromarray(ink.astype(np.uint8), 'L').convert('1').save(pbm)
        svg = os.path.join(td, 'm.svg')
        subprocess.run(['potrace', pbm, '-s', '-o', svg,
                        '--turdsize', str(turdsize), '--alphamax', str(alphamax),
                        '--opttolerance', str(opttol), '--unit', '1'],
                       capture_output=True, check=True)
        data = open(svg).read()
    m = _TR.search(data)
    tx, ty, sx, sy = (float(m.group(i)) for i in (1, 2, 3, 4)) if m else (0.0, 0.0, 1.0, 1.0)
    # No subpath surgery here: with the polarity above, potrace's outline *is*
    # the mask (holes included, via winding), so there is no stray frame plate.
    return [(d.strip(), tx, ty, sx, sy)
            for d in re.findall(r'<path[^>]*?\bd="([^"]+)"', data, re.S)]

# Rectangles holding live DOM text, derived empirically from a DOM-only render
# by qa/textrects.py (art hidden, glyph ink bands measured, grown by 4 px) so
# the exclusion covers exactly the words and no more.
#
# When the trace box covers these, the band masks would contain a blurry copy of
# the words, which then peeks out from under the real text -- and worse, a later
# copy edit would leave a ghost of the old headline behind.  Excluding them lets
# the trace box span the whole frame (so no artwork gets cut off at an arbitrary
# edge) while the type stays crisp and editable.
TEXT = {
 'a': [(54, 250, 454, 336), (59, 337, 332, 390), (60, 397, 342, 424), (56, 444, 314, 508)],
 'b': [(56, 136, 305, 183), (58, 279, 472, 369), (55, 366, 335, 420),
       (56, 428, 405, 451), (57, 477, 312, 548)],
 'c': [(60, 191, 189, 221), (56, 246, 465, 379), (107, 385, 179, 405),
       (57, 416, 325, 444), (56, 469, 287, 532)],
}

def build(v, bands=26, up=2, turdsize=3, alphamax=1.0, opttol=0.16, prec=1,
          minpx=None, out=None, box=None, exclude_text=False,
          text_lum_max=70.0, cumulative=True, ref=None, text_rects=None):
    cfg = design(v)
    ref = ref or cfg.get('ref') or f'{HERE}/ref-{v}.png'
    text_rects = cfg.get('text', []) if text_rects is None else text_rects
    trace_box = box or cfg.get('box') or BOX.get(v)
    if not trace_box:
        raise SystemExit(f"no trace box for design {v!r}: set 'box' in "
                         f"pipeline/designs/{v}.json (see qa/newdesign.py)")
    x0, y0, x1, y1 = trace_box
    a = np.asarray(Image.open(ref).convert('RGB')).astype(np.float32)
    sub = a[y0:y1, x0:x1]
    if up != 1:
        sub = np.asarray(Image.fromarray(sub.astype(np.uint8))
                         .resize(((x1-x0)*up, (y1-y0)*up), Image.LANCZOS)).astype(np.float32)
    lum = sub.mean(axis=2)
    lo, hi = np.percentile(lum, 0.5), np.percentile(lum, 99.9)
    edges = np.linspace(lo, hi, bands+1)
    minpx = minpx if minpx is not None else 4*up*up

    # `lum` is at `up` scale, so build the text mask at that scale directly.
    # NB: a rect is *not* wiped out entirely.  The references have soft glow
    # behind the type, so a hard hole leaves visible seams; instead we keep the
    # dim background bands inside the rect and drop only the bright ones (which
    # are the rasterised words).  `text_lum_max` is that cutoff.
    H2, W2 = lum.shape
    in_text = None
    if exclude_text:
        in_text = np.zeros((H2, W2), bool)
        for (tx0, ty0, tx1, ty1) in text_rects:
            ax0, ay0 = max(0, tx0-x0)*up, max(0, ty0-y0)*up
            ax1, ay1 = (min(x1, tx1)-x0)*up, (min(y1, ty1)-y0)*up
            if ax1 > ax0 and ay1 > ay0:
                in_text[ay0:ay1, ax0:ax1] = True

    bands_out = []
    if cumulative:
        # C_i = {lum >= e_i}, painted darkest-first.  Region e_i<=lum<e_{i+1}
        # keeps C_i's colour because C_{i+1} .. do not cover it, so the result is
        # identical to disjoint bands -- but each mask is one solid nested region
        # instead of a set of 1px slivers, which potrace reproduces far better
        # and with no seams between adjacent bands.
        for i in range(bands):
            m = lum >= edges[i]
            if exclude_text and in_text is not None:
                # inside a text rect only the dim bands survive
                hi_sel = m & in_text
                if hi_sel.any() and np.median(sub[hi_sel], axis=0).mean() > text_lum_max:
                    m = m & ~in_text
            if m.sum() < minpx: continue
            band = m & ~(lum >= edges[i+1]) if i < bands-1 else m
            if band.sum() < minpx: continue
            col = np.median(sub[band], axis=0)
            bands_out.append((int(band.sum()), col, m, i))
    else:
        for i in range(bands):
            m = (lum >= edges[i]) if i == bands-1 else ((lum >= edges[i]) & (lum < edges[i+1]))
            if m.sum() < minpx: continue
            px = sub[m]
            col = np.median(px, axis=0)
            if in_text is not None and col.mean() > text_lum_max:
                m = m & ~in_text          # dim glow survives, words do not
                if m.sum() < minpx: continue
                col = np.median(sub[m], axis=0)
            bands_out.append((int(m.sum()), col, m, i))
    # Paint order matters: later groups cover earlier ones.  Bands are nested
    # (band i+1 is a subset of the *bright* region inside band i), so the
    # darkest band must go down first and the brightest last -- sorting by
    # pixel count instead puts a huge dark band on top and erases the bright
    # detail (which is exactly what made the art render ~4x too dark).
    bands_out.sort(key=lambda r: r[3])

    g, total = [], 0
    for n, col, m, i in bands_out:
        ds = _potrace(m, turdsize, alphamax, opttol)
        if not ds: continue
        total += len(ds)
        css = f"rgb({col[0]:.0f},{col[1]:.0f},{col[2]:.0f})"
        # The traced bitmap is at `up` x the design scale; divide it back out on
        # the band group so every path keeps potrace's own coordinates verbatim.
        g.append(f'<g class="band b{i:02d}" fill="{css}" transform="scale({1/up:.6f})">')
        for (d, tx, ty, sx, sy) in ds:
            g.append(f'<g transform="translate({tx:.4f},{ty:.4f}) '
                     f'scale({sx:.4f},{sy:.4f})"><path d="{d}"/></g>')
        g.append('</g>')
    # The artwork is decorative -- the headline, tagline and CTA carry all the
    # meaning -- so it is hidden from assistive tech rather than given a label.
    # (It previously read aria-label="AntHosting {v} artwork", which leaked the
    # internal variant letter into user-facing content.)
    svg = (f'<svg viewBox="0 0 1024 768" xmlns="http://www.w3.org/2000/svg" '
           f'aria-hidden="true" focusable="false" class="artwork">\n'
           f'  <g id="art" transform="translate({x0} {y0})">\n'
           + '\n'.join('    ' + x for x in g)
           + '\n  </g>\n</svg>\n')
    out = out or os.path.join(PIPE, f'{v}.svg')
    open(out, 'w').write(svg)
    print(f"{out}: {len(svg)/1024:.0f} KB, {len(g)//2} bands, {total} paths")
    return out

if __name__ == '__main__':
    v = sys.argv[1]
    kw = dict(design(v).get('params') or PARAMS.get(v, {}))
    for k, t in (('--bands', int), ('--up', int), ('--turd', int), ('--prec', int), ('--minpx', int)):
        if k in sys.argv: kw[k.lstrip('-')] = t(sys.argv[sys.argv.index(k)+1])
    for k, t in (('--alphamax', float), ('--opttol', float)):
        if k in sys.argv: kw[k.lstrip('-')] = t(sys.argv[sys.argv.index(k)+1])
    if '--out' in sys.argv: kw['out'] = sys.argv[sys.argv.index('--out')+1]
    if '--exclude-text' in sys.argv: kw['exclude_text'] = True
    if '--text-lum-max' in sys.argv:
        kw['text_lum_max'] = float(sys.argv[sys.argv.index('--text-lum-max')+1])
    if 'turd' in kw: kw['turdsize'] = kw.pop('turd')
    build(v, **kw)
