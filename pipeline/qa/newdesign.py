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
    """
    return {
        'title': f'{name} \u2014 coming soon',
        'description': 'Built from a design reference.',
        'eyebrow': 'Coming soon',
        'tagline': 'Replace this tagline with your copy.',
        'cta': 'Join the waitlist',
        'stage': [ref_w, ref_h],
        'markup': (
            '      <h1 class="white-space">Your <span class="green">Headline</span></h1>\n'
            '      <h2>Coming soon</h2>\n'
            '      <p class="white-space">Replace this tagline with your copy.</p>\n'
            '      <a class="cta" href="#">Join the waitlist</a>'
        ),
    }


def content_stub_css(stage_w, stage_h):
    return (
        ':root { color-scheme: dark; --green: #19d283; --ink: #f4fff9; }\n'
        '* { box-sizing: border-box; margin: 0; padding: 0; }\n'
        'html, body { width: 100%; height: 100%; }\n'
        'body { background: #000a07; font-family: Inter, system-ui, sans-serif;\n'
        '  overflow: hidden; -webkit-font-smoothing: antialiased; }\n'
        f'.stage {{ position: absolute; left: 50%; top: 50%; width: {stage_w}px;'
        f' height: {stage_h}px;\n'
        '  transform-origin: center center; background: #000a07; overflow: hidden; }\n'
        '.content { position: absolute; left: 56px; top: 245px; width: 480px; z-index: 3; }\n'
        '.white-space { white-space: nowrap; }\n'
        'h1 { color: var(--ink); font-size: 80px; font-weight: 400; letter-spacing: -.028em; line-height: 1; }\n'
        'h1 .green { color: var(--green); }\n'
        'h2 { margin-top: 11px; color: var(--green); font-size: 46px; font-weight: 400; line-height: 1; }\n'
        '.content p { margin-top: 16px; color: rgba(240,255,248,.80); font-size: 19.5px; line-height: 1.15; }\n'
        '.cta { display: inline-flex; align-items: center; justify-content: center; width: 250px; height: 55px;\n'
        '  margin-top: 28px; border-radius: 14px; text-decoration: none;\n'
        '  background: linear-gradient(180deg, #18c47c, #13b26e); color: #02150f; font-size: 21px; font-weight: 600; }\n'
        '.art { position: absolute; inset: 0; z-index: 2; }\n'
        f'.art > svg {{ display: block; width: {stage_w}px; height: {stage_h}px; overflow: visible; }}\n'
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
           'target': None, 'box': None, 'text': [],
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
