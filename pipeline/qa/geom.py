#!/usr/bin/env python3
"""Render <variant>-full.html with a CSS override and report left-column ink
bands + per-window element geometry.  Fast iteration loop for type metrics.

usage: geom.py <variant> [cssfile]
"""
import os, shutil, subprocess, sys, uuid
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SRGB = "/System/Library/ColorSync/Profiles/sRGB Profile.icc"

def render(v, css="", w=1024, h=768, out=None, bg="body"):
    full = open(os.path.join(PIPE, f"{v}-full.html")).read()
    static = full.replace('</body>', f"<style>{css}</style><style>*{{animation:none !important;transition:none !important}}</style></body>")
    tmp = os.path.join(PIPE, "geom-tmp.html")
    open(tmp, "w").write(static)
    out = out or f"/tmp/geom-{v}.png"
    raw = f"/tmp/geom-{uuid.uuid4().hex}.png"
    for i in range(4):
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=2", "--force-color-profile=srgb",
                        "--no-first-run", "--no-default-browser-check",
                        f"--window-size={w},{h}", "--virtual-time-budget=4000",
                        "--disable-http-cache", "--incognito", "--allow-file-access-from-files",
                        f"--screenshot={raw}", f"file://{tmp}?cb={uuid.uuid4().hex}"],
                       capture_output=True, timeout=40)
        if os.path.exists(raw) and os.path.getsize(raw) > 2000:
            s = raw + ".s.png"
            subprocess.run(["sips", "--matchTo", SRGB, raw, "--out", s], capture_output=True)
            from PIL import Image as _I
            _I.open(s).convert("RGB").resize((w, h), _I.LANCZOS).save(out)
            if os.path.exists(out) and os.path.getsize(out) > 1000:
                for f in (raw, s):
                    if os.path.exists(f): os.remove(f)
                return out
    raise RuntimeError("render failed")

def bands(arr, x0=20, x1=470, thr=170, gap=8, minrows=3):
    sub = arr[:, x0:x1]; m = (sub.sum(axis=2) > thr)
    rows = np.nonzero(m.sum(axis=1) >= minrows)[0]
    if len(rows) == 0: return []
    out = []; s = rows[0]; p = rows[0]
    for r in rows[1:]:
        if r - p > gap: out.append((s, p)); s = r
        p = r
    out.append((s, p))
    res = []
    for (y0, y1) in out:
        mm = (arr[y0:y1+1, x0:x1].sum(axis=2) > thr)
        xs = np.nonzero(mm.any(axis=0))[0]
        res.append(dict(y0=y0, y1=y1, h=y1-y0+1, x0=int(xs.min()+x0), x1=int(xs.max()+x0), w=int(xs.max()-xs.min()+1)))
    return res

WIN = {
  'brand':   (30, 100, 400, 200),
  'h1':      (30, 220, 400, 350),
  'h2':      (30, 350, 400, 400),
  'divider': (30, 385, 400, 410),
  'tag':     (30, 400, 400, 470),
  'cta':     (30, 465, 400, 560),
}
def win_geom(arr, box, thr=170):
    x0, y0, x1, y1 = box
    sub = arr[y0:y1, x0:x1]
    m = sub.sum(axis=2) > thr
    if not m.any(): return None
    ys, xs = np.nonzero(m)
    return dict(x0=int(xs.min()+x0), x1=int(xs.max()+x0), y0=int(ys.min()+y0), y1=int(ys.max()+y0),
                w=int(xs.max()-xs.min()+1), h=int(ys.max()-ys.min()+1), cov=round(100*float(m.mean()),2))

if __name__ == "__main__":
    v = sys.argv[1]
    css = open(sys.argv[2]).read() if len(sys.argv) > 2 and not sys.argv[2].startswith('-') else ""
    if '--hide-art' in sys.argv: css += "\n.art{display:none!important}"
    out = render(v, css)
    shutil.copy(out, os.path.join(HERE, f"geom-{v}.png"))
    arr = np.asarray(Image.open(out).convert('RGB'))
    print(f"render -> {out}")
    for name in sys.argv:
        if name.startswith('--win='):
            print(f"-- window {name[6:]}")
    for label, box in WIN.items():
        r = win_geom(arr, box)
        if r: print(f"  {label:>8} x{r['x0']:4d}-{r['x1']:4d} y{r['y0']:4d}-{r['y1']:4d}  w{r['w']:4d} h{r['h']:3d} cov{r['cov']:6.2f}")
        else: print(f"  {label:>8} (none)")
