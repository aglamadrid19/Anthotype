#!/usr/bin/env python3
"""Fast multi-candidate renderer for QA/tuning.

Renders K CSS-override candidates of a variant page in as few headless-Chrome
passes as possible, laying the 1024x768 stages out on a 2D grid so one
screenshot returns many candidates.  Candidates are grouped into jobs which
run in parallel processes.

    from batch import render_candidates
    imgs = render_candidates('c', ['', 'h2{top:380px}', ...])
"""
import os, subprocess, sys, uuid, shutil, json
from concurrent.futures import ThreadPoolExecutor
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SRGB = "/System/Library/ColorSync/Profiles/sRGB Profile.icc"
CW, CH = 1024, 768
COLS = 3
JOBS = 4
MAX_ROWS = 4

def _split(html):
    i = html.index('<body>') + len('<body>')
    j = html.index('</body>')
    body = html[i:j]
    k = body.index('</main>') + len('</main>')
    return body[:k], body[k:]

def _scope(css, cls):
    """Prefix every top-level selector in `css` with `.<cls>`, brace-aware."""
    out = []
    i = 0
    n = len(css)
    buf = ''
    while i < n:
        ch = css[i]
        if ch == '/' and i+1 < n and css[i+1] == '*':
            j = css.find('*/', i+2)
            j = n if j < 0 else j+2
            buf += css[i:j]; i = j; continue
        if ch == '{':
            # buf holds the selector list; find matching close brace
            depth = 1; j = i+1
            while j < n and depth:
                if css[j] == '{': depth += 1
                elif css[j] == '}': depth -= 1
                j += 1
            inner = css[i:j]
            sel = buf.strip()
            buf = ''
            if sel.startswith('@'):
                out.append(sel + inner)
            else:
                sels = []
                for x in sel.split(','):
                    x = x.strip()
                    if not x: continue
                    sels.append(f".{cls} {x}")
                out.append(','.join(sels) + inner)
            i = j; continue
        if ch == '}':
            buf += ch; i += 1; continue
        buf += ch; i += 1
    if buf.strip(): out.append(buf)
    return ''.join(out)

_CACHE = {}

def _page(v):
    if v in _CACHE: return _CACHE[v]
    full = open(os.path.join(PIPE, f"{v}-full.html")).read()
    stage, _ = _split(full)
    style = full[full.index('<style is:global>')+len('<style is:global>'):full.index('</style>')]
    stage = stage.replace('id="stage"', '')
    _CACHE[v] = (stage, style)
    return _CACHE[v]

def build_html(v, overrides, hide_art=False):
    stage, style = _page(v)
    cols = min(COLS, max(1, len(overrides)))
    cells = []
    for i, ov in enumerate(overrides):
        cls = f"c{i}"
        scoped = _scope(ov, cls) if ov.strip() else ""
        cells.append(
          f'<div class="{cls}" style="position:relative;width:{CW}px;height:{CH}px;'
          f'overflow:hidden;background:#000a07;display:inline-block;vertical-align:top">'
          f'<style>{scoped}'
          f'.{cls} .stage{{position:absolute!important;left:0!important;top:0!important;'
          f'transform:none!important;width:{CW}px!important;height:{CH}px!important}}'
          f'</style>'
          f'<div style="position:absolute;left:0;top:0;width:{CW}px;height:{CH}px;'
          f'transform:none">{stage}</div></div>')
    rows = (len(overrides) + cols - 1)//cols
    hide = '.art{display:none!important}' if hide_art else ''
    return (f'<!doctype html><html><head><meta charset="utf-8">'
            f'<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">'
            f'</head><body style="margin:0;background:#000;width:{cols*CW}px">'
            f'<style is:global>{style}</style><style>{hide}</style>'
            f'<div style="font-size:0;line-height:0">' + ''.join(cells) + '</div></body></html>')

def _shoot(html, cols, rows, scale=2, timeout=120, tries=3):
    tmp = f"/tmp/batch-{uuid.uuid4().hex}.html"
    open(tmp, 'w').write(html)
    raw = tmp + ".png"
    W, H = cols*CW, rows*CH
    for a in range(tries):
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        f"--force-device-scale-factor={scale}", "--force-color-profile=srgb",
                        "--no-first-run", "--no-default-browser-check",
                        f"--window-size={W},{H}", "--virtual-time-budget=5000",
                        "--disable-http-cache", "--incognito",
                        f"--screenshot={raw}", f"file://{tmp}?cb={uuid.uuid4().hex}"],
                       capture_output=True, timeout=timeout)
        if os.path.exists(raw) and os.path.getsize(raw) > 5000:
            s = raw + ".s.png"
            subprocess.run(["sips", "--matchTo", SRGB, raw, "--out", s], capture_output=True)
            im = Image.open(s).convert('RGB')
            if im.size != (W, H): im = im.resize((W, H), Image.LANCZOS)
            for f in (tmp, raw, s):
                if os.path.exists(f): os.remove(f)
            return im
        print(f"  shoot retry {a+1}", flush=True)
    raise RuntimeError("batch render failed")

def render_candidates(v, overrides, hide_art=False, per_pass=12, scale=2, jobs=JOBS):
    """Return list of PIL images, one per override (1024x768)."""
    per_pass = min(per_pass, COLS*MAX_ROWS)
    if scale == 1: per_pass = min(per_pass, COLS*8)
    chunks = [overrides[i:i+per_pass] for i in range(0, len(overrides), per_pass)]
    results = [None]*len(chunks)
    def work(k):
        ch = chunks[k]
        cols = min(COLS, max(1, len(ch)))
        rows = (len(ch) + cols - 1)//cols
        html = build_html(v, ch, hide_art)
        im = _shoot(html, cols, rows, scale)
        results[k] = [im.crop(((i % cols)*CW, (i//cols)*CH, (i % cols)*CW + CW, (i//cols)*CH + CH))
                      for i in range(len(ch))]
    with ThreadPoolExecutor(max_workers=min(jobs, len(chunks))) as ex:
        list(ex.map(work, range(len(chunks))))
    return [im for ch in results for im in ch]

# ---- scoring -------------------------------------------------------------
_REFS = {}
def ref(v):
    if v not in _REFS:
        _REFS[v] = np.asarray(Image.open(f"{HERE}/ref-{v}.png").convert('RGB')).astype(np.float32)
    return _REFS[v]

def score(v, overrides, windows=None, hide_art=False, per_pass=12, scale=2):
    """windows: {name:(x0,y0,x1,y1)} or None for whole-frame mean."""
    R = ref(v)
    out = []
    for im in render_candidates(v, overrides, hide_art, per_pass, scale):
        a = np.asarray(im).astype(np.float32)
        d = np.abs(R - a).mean(axis=2)
        if windows is None:
            out.append(float(d.mean()))
        else:
            o = {k: float(d[y0:y1, x0:x1].mean()) for k, (x0, y0, x1, y1) in windows.items()}
            o['__all__'] = float(d.mean())
            out.append(o)
    return out

def save(imgs, outdir):
    os.makedirs(outdir, exist_ok=True)
    for i, im in enumerate(imgs): im.save(os.path.join(outdir, f"cand-{i:02d}.png"))
    return outdir
