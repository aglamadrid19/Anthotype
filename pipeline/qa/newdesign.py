#!/usr/bin/env python3
"""Scaffold a complete, buildable design from a NEW reference image.

This is the entry point for turning another design PNG into a site.  One command
produces everything the pipeline needs, and nothing here knows anything about a
particular design -- the name is the only thing you supply (plus, if you want it,
the trace box):

    designs/<name>.json      the per-design config (ref, trace box, text rects, params)
    qa/ref-<name>.png        the reference image, copied in
    content-<name>.json      a standalone text layer you edit with your copy
    sites/variant-<name>/    a ready-to-build Astro project

Then the loop is:

    # edit content-<name>.json (your headline / tagline / CTA markup)
    python qa/mkart.py <name> --out <name>.svg     # trace the artwork
    node gen-page.mjs <name> && node to-astro.mjs <name>
    (cd ../sites/variant-<name> && npm run build)
    ./qa/verify.sh <name>

Only two things are genuinely per-design and worth checking by hand: the **trace
box** (the artwork region, which must not include the DOM text) and the
**text-exclusion rectangles** (the DOM type the art must not bake in).  Both live
in designs/<name>.json.  `qa/textrects.py` derives the rectangles automatically
once your page CSS exists.

usage:
  newdesign.py <name> <ref.png> [--box x0 y0 x1 y1] [--bands N] [--up K] [--port P]
  newdesign.py <name> --text-from <other> [--copy-site <other>]
"""

import _bootstrap  # noqa: F401  (re-exec under the venv python if needed)
import argparse, json, os, re, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)
ROOT = os.path.dirname(PIPE)
TEMPLATE = os.path.join(PIPE, 'site-template')


def infer_box(w, h):
    """Default trace box: a rough starting point the user is told to refine."""
    return [0, int(h * 0.06), w, int(h * 0.97)]


def next_port():
    """A free-ish preview port above the three shipped examples."""
    used = [4173, 4174, 4175]
    return max(used) + 1


def design_names():
    d = os.path.join(PIPE, 'designs')
    if not os.path.isdir(d):
        return []
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith('.json'))


def scaffold_site(name, port, copy_from=None):
    """Create sites/variant-<name>/ from the template (or an existing design)."""
    dst = os.path.join(ROOT, 'sites', f'variant-{name}')
    if os.path.isdir(dst):
        print(f'  site already exists, leaving it alone: {dst}')
        return dst, False
    if copy_from:
        src = os.path.join(ROOT, 'sites', f'variant-{copy_from}')
        if not os.path.isdir(src):
            sys.exit(f'--copy-site: no such site {src}')
        shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
            'node_modules', 'dist', '.astro', 'src'))
        os.makedirs(os.path.join(dst, 'src', 'pages'), exist_ok=True)
    else:
        os.makedirs(os.path.join(dst, 'src', 'pages'), exist_ok=True)
        shutil.copy(os.path.join(TEMPLATE, 'astro.config.mjs'), dst)
        pkg = open(os.path.join(TEMPLATE, 'package.json.tmpl')).read()
        pkg = pkg.replace('__NAME__', name).replace('__PORT__', str(port))
        open(os.path.join(dst, 'package.json'), 'w').write(pkg)
    return dst, True


def content_stub(name, ref_w, ref_h):
    """A minimal page that builds but is obviously a starting point.

    Deliberately plain: the point is that the whole pipeline (trace -> page ->
    astro build -> verify) runs end to end from minute one, so you tune against
    a real render instead of guessing.  Replace the copy and the CSS.

    The shape is a real page -- a header, a hero and a footer in normal flow --
    because that is what this pipeline produces.  The `<!--ART-->` placeholder is
    where `gen-page.mjs` splices the traced artwork in.
    """
    return {
        'title': f'{name} — coming soon',
        'description': 'Built from a design reference.',
        'cta': 'Get started',
        'cta_href': '#top',
        'stage': [ref_w, ref_h],
        'sections': ['header', 'hero', 'footer'],
        'markup': (
            '  <header class="site-header" id="top">\n'
            '    <div class="wrap">\n'
            '      <a class="brand" href="#top">Your Brand</a>\n'
            '      <nav class="site-nav" aria-label="Primary">\n'
            '        <a href="#top">Home</a>\n'
            '        <a href="#top">Contact</a>\n'
            '      </nav>\n'
            '    </div>\n'
            '  </header>\n'
            '  <section class="hero" id="hero">\n'
            '    <div class="hero-art" aria-hidden="true"><!--ART--></div>\n'
            '    <div class="wrap hero-copy">\n'
            '      <h1>Your headline here</h1>\n'
            '      <p class="lede">Replace this with your copy.</p>\n'
            '      <a class="cta" href="#top">Get started</a>\n'
            '    </div>\n'
            '  </section>\n'
            '  <footer class="site-footer" id="footer">\n'
            '    <div class="wrap"><p>© Your Brand</p></div>\n'
            '  </footer>'
        ),
    }


def content_stub_css(stage_w, stage_h):
    """A minimal stylesheet for the stub page (replace it with your own).

    `studio/backend/app/generate.py::build_page_css` is the reference for what a
    full generated stylesheet looks like -- this is only the skeleton.
    """
    return (
        ':root { color-scheme: dark; --bg: #000a07; --ink: #f4fff9;\n'
        '  --muted: #9fb8ad; --accent: #19d283; --accent-ink: #02150f;\n'
        '  --surface: #06120e; --border: #123026; --maxw: 1120px; }\n'
        '* { box-sizing: border-box; margin: 0; padding: 0; }\n'
        'body { background: var(--bg); color: var(--ink);\n'
        '  font-family: Inter, system-ui, sans-serif; line-height: 1.55;\n'
        '  -webkit-font-smoothing: antialiased; }\n'
        'h1, h2, h3 { line-height: 1.1; letter-spacing: -0.02em; }\n'
        '.wrap { width: 100%; max-width: var(--maxw); margin: 0 auto; padding: 0 24px; }\n'
        '.site-header { position: sticky; top: 0; z-index: 20; background: var(--bg);\n'
        '  border-bottom: 1px solid var(--border); }\n'
        '.site-header .wrap { display: flex; align-items: center; justify-content: space-between;\n'
        '  gap: 24px; min-height: 68px; flex-wrap: wrap; }\n'
        '.brand { font-weight: 600; font-size: 18px; text-decoration: none; }\n'
        '.site-nav { display: flex; gap: 22px; }\n'
        '.site-nav a { color: var(--muted); text-decoration: none; font-size: 15px; }\n'
        '.hero { position: relative; overflow: hidden; }\n'
        '.hero-art { position: absolute; inset: 0; z-index: 0; }\n'
        '.hero-art svg { width: 100%; height: 100%; display: block; }\n'
        '.hero-copy { position: relative; z-index: 1; display: grid; gap: 18px;\n'
        '  justify-items: start; padding-top: 104px; padding-bottom: 104px; max-width: 760px; }\n'
        'h1 { font-size: clamp(38px, 6.5vw, 74px); font-weight: 600; }\n'
        '.lede { font-size: clamp(16px, 1.7vw, 20px); color: var(--muted); max-width: 62ch; }\n'
        '.cta { display: inline-flex; align-items: center; padding: 14px 28px; border-radius: 12px;\n'
        '  text-decoration: none; background: var(--accent); color: var(--accent-ink);\n'
        '  font-weight: 600; width: fit-content; }\n'
        '.site-footer { padding: 48px 0; color: var(--muted); }\n'
        '@media (max-width: 620px) { .hero-copy { padding-top: 72px; padding-bottom: 72px; } }\n'
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('name', help='design name; no spaces (used for files and URLs)')
    ap.add_argument('ref', nargs='?', help='the design PNG')
    ap.add_argument('--box', nargs=4, type=int, metavar=('X0', 'Y0', 'X1', 'Y1'))
    ap.add_argument('--bands', type=int, default=48)
    ap.add_argument('--up', type=int, default=2)
    ap.add_argument('--port', type=int, default=None)
    ap.add_argument('--text-from', metavar='OTHER',
                    help='copy text rects + tracing params from an existing design')
    ap.add_argument('--copy-site', metavar='OTHER',
                    help='start the site from an existing design instead of the template')
    ap.add_argument('--no-site', action='store_true', help='config + content only')
    a = ap.parse_args()

    if not re.fullmatch(r'[A-Za-z0-9_-]+', a.name):
        sys.exit('design name must be letters/digits/-/_ only (it becomes a URL path)')
    if a.name in design_names():
        sys.exit(f'design {a.name!r} already exists; pick another name or edit its files')

    port = a.port or next_port()
    cfg = {'name': a.name, 'ref': f'qa/ref-{a.name}.png',
           'site': f'sites/variant-{a.name}', 'content': f'content-{a.name}.json',
           'layout': 'page', 'target': None, 'box': None, 'text': [],
           'params': {'bands': a.bands, 'up': a.up, 'turdsize': 2,
                      'alphamax': 0.0, 'opttol': 0.0, 'minpx': None,
                      'exclude_text': True, 'text_lum_max': 200.0,
                      'cumulative': True}}

    if a.text_from:
        src = os.path.join(PIPE, 'designs', f'{a.text_from}.json')
        if not os.path.isfile(src):
            sys.exit(f'--text-from: no such design config {src}')
        base = json.load(open(src))
        cfg['text'] = base.get('text', [])
        cfg['params'].update(base.get('params', {}))
        print(f'copied text rects + params from designs/{a.text_from}.json')

    w = h = None
    if a.ref:
        if not os.path.isfile(a.ref):
            sys.exit(f'no such reference: {a.ref}')
        dst = os.path.join(HERE, f'ref-{a.name}.png')
        shutil.copy(a.ref, dst)
        print(f'copied {a.ref} -> qa/ref-{a.name}.png')
        try:
            from PIL import Image
            w, h = Image.open(dst).size
        except Exception as e:
            print(f'  (could not read the image size: {e})', file=sys.stderr)
    else:
        print('no reference given: the trace box and stage size will need setting by hand')

    w, h = w or 1024, h or 768
    cfg['box'] = a.box or infer_box(w, h)

    os.makedirs(os.path.join(PIPE, 'designs'), exist_ok=True)
    with open(os.path.join(PIPE, 'designs', f'{a.name}.json'), 'w') as fh:
        json.dump(cfg, fh, indent=2); fh.write('\n')
    print(f'wrote designs/{a.name}.json')

    cpath = os.path.join(PIPE, f'content-{a.name}.json')
    if not os.path.isfile(cpath):
        with open(cpath, 'w') as fh:
            json.dump(content_stub(a.name, w, h), fh, indent=2); fh.write('\n')
        print(f'wrote content-{a.name}.json  (edit this with your copy)')

    cpath_css = os.path.join(PIPE, f'{a.name}.page.css')
    if not os.path.isfile(cpath_css):
        open(cpath_css, 'w').write(content_stub_css(w, h))
        print(f'wrote {a.name}.page.css  (edit this for layout/type)')

    if not a.no_site:
        dst, made = scaffold_site(a.name, port, a.copy_site)
        if made:
            print(f'wrote site: {dst}  (preview port {port})')

    print()
    print('Next:')
    print(f'  1. designs/{a.name}.json -- check `box` covers the artwork and NOT the DOM text')
    print(f'  2. content-{a.name}.json + {a.name}.page.css -- your copy and layout')
    print(f'  3. trace:   python qa/mkart.py {a.name} --out {a.name}.svg')
    print(f'  4. build:   node gen-page.mjs {a.name} && node to-astro.mjs {a.name}')
    print(f'              (cd ../sites/variant-{a.name} && npm install && npm run build)')
    print(f'  5. score:   ./qa/verify.sh {a.name}')


if __name__ == '__main__':
    main()
