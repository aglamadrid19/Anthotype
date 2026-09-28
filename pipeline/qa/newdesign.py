#!/usr/bin/env python3
"""Scaffold a design config for a NEW reference image.

This is the entry point for turning another design PNG into a site.  It writes
`designs/<name>.json` with sensible defaults plus the two things that are
genuinely per-design and worth checking: the **trace box** and the
**text-exclusion rectangles**.

  ref    path to the reference PNG (copied into qa/ref-<name>.png)
  box    the region containing artwork.  Everything inside is repainted by
         traced bands, so it must not include the DOM text.  Set it by hand if
         the layout is not "art on the right"; `--box x0 y0 x1 y1`.
  text   rectangles the artwork must NOT bake in.  Leaving these empty makes the
         traced art contain a rasterised copy of the headline -- it looks right
         until the copy changes, at which point a ghost of the old text remains.
         qa/textrects.py derives them automatically from a DOM-only render once
         the page CSS exists.

usage:
  newdesign.py <name> <ref.png> [--box x0 y0 x1 y1] [--bands N] [--up K]
  newdesign.py <name> --text-from <variant>    # copy tuned text rects/bands
"""
import argparse, json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)


def infer_box(w, h, art_side):
    """Default trace box: a rough starting point, meant to be refined."""
    if art_side == 'right':
        return [int(w * 0.40), 0, w, int(h * 0.97)]
    return [0, int(h * 0.06), w, int(h * 0.97)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('name')
    ap.add_argument('ref', nargs='?')
    ap.add_argument('--box', nargs=4, type=int, metavar=('X0', 'Y0', 'X1', 'Y1'))
    ap.add_argument('--bands', type=int, default=48)
    ap.add_argument('--up', type=int, default=2)
    ap.add_argument('--text-from', metavar='VARIANT',
                    help='copy text rects + bands/up from an existing design')
    a = ap.parse_args()

    cfg = {'name': a.name, 'ref': f'qa/ref-{a.name}.png', 'box': None, 'text': [],
           'params': {'bands': a.bands, 'up': a.up, 'turdsize': 2,
                      'alphamax': 0.0, 'opttol': 0.0, 'minpx': None,
                      'exclude_text': True, 'text_lum_max': 200.0,
                      'cumulative': True}}

    if a.text_from:
        src = os.path.join(PIPE, 'designs', f'{a.text_from}.json')
        if not os.path.isfile(src):
            sys.exit(f'no such design config: {src}')
        with open(src) as fh:
            base = json.load(fh)
        cfg['text'] = base.get('text', [])
        cfg['params'].update(base.get('params', {}))
        print(f'copied text rects + params from designs/{a.text_from}.json')

    if a.ref:
        if not os.path.isfile(a.ref):
            sys.exit(f'no such reference: {a.ref}')
        dst = os.path.join(HERE, f'ref-{a.name}.png')
        if os.path.abspath(a.ref) != os.path.abspath(dst):
            shutil.copy(a.ref, dst)
            print(f'copied {a.ref} -> qa/ref-{a.name}.png')
        try:
            from PIL import Image
            w, h = Image.open(dst).size
        except Exception:
            w, h = 1024, 768
    else:
        w, h = 1024, 768
        print('no reference given; assuming 1024x768')
        print('NOTE: the reference is genuinely required -- ref is used to read art geometry')

    cfg['box'] = a.box or infer_box(w, h, 'right')

    out = os.path.join(PIPE, 'designs', f'{a.name}.json')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w') as fh:
        json.dump(cfg, fh, indent=2)
        fh.write('\n')

    print(f'wrote {out}  ({w}x{h})')
    print()
    print('Next:')
    print(f'  1. Check `box` -- it should cover the artwork and NOT the DOM text.')
    print(f'  2. Fill `text` with one rect per line of DOM type, or run')
    print(f'     `python qa/textrects.py {a.name} --grow 4` once the page CSS exists.')
    print(f'  3. Trace:  python qa/mkart.py {a.name}')


if __name__ == '__main__':
    main()
