#!/usr/bin/env python3
"""Reference-vs-render comparison with per-region metrics + side-by-side + heatmap.

usage:
  compare.py <variant> [--crop x y w h [zoom]] [--regions]
"""
import sys, os, json
from PIL import Image, ImageChops, ImageDraw, ImageFont
import numpy as np

QA = os.path.dirname(os.path.abspath(__file__))
FONT = "/System/Library/Fonts/Menlo.ttc"
# Per-variant windows, derived from ink-band measurements of each reference so
# every region contains real content for that variant.
REGIONS = {}
REGIONS['a'] = {
    'title':   (40, 240, 470, 338),
    'coming':  (40, 338, 470, 392),
    'tagline': (40, 392, 470, 430),
    'cta':     (40, 440, 340, 512),
    'ant':     (500, 180, 830, 580),
    'pods':    (390, 60, 1024, 690),
    'bgTL':    (0, 0, 300, 240),
    'bgR':     (850, 0, 1024, 768),
    'bgB':     (0, 690, 1024, 768),
}
REGIONS['b'] = {
    'brand':   (30, 110, 340, 195),
    'title':   (40, 265, 470, 358),
    'coming':  (40, 358, 470, 424),
    'tagline': (40, 424, 470, 462),
    'cta':     (40, 468, 340, 558),
    'ant':     (600, 360, 830, 580),
    'pods':    (430, 60, 1024, 700),
    'bgTL':    (0, 0, 300, 240),
    'bgR':     (850, 0, 1024, 768),
    'bgB':     (0, 690, 1024, 768),
}
REGIONS['c'] = {
    'brand':   (40, 178, 300, 228),
    'title':   (40, 238, 470, 328),
    'coming':  (40, 324, 470, 380),
    'divider': (40, 380, 470, 408),
    'tagline': (40, 406, 470, 448),
    'cta':     (40, 462, 340, 542),
    'ant':     (600, 240, 830, 400),
    'pods':    (430, 60, 1024, 710),
    'bgTL':    (0, 0, 300, 240),
    'bgR':     (850, 0, 1024, 768),
    'bgB':     (0, 690, 1024, 768),
}

def load(path):
    return np.asarray(Image.open(path).convert('RGB')).astype(np.float32)

def region_metrics(a, b):
    d = np.abs(a - b).mean(axis=2)
    return d.mean(), 100.0 * (d > 30).mean()

def label(img, text):
    w, h = img.size
    out = Image.new('RGB', (w, h + 22), (20, 20, 20))
    out.paste(img, (0, 22))
    d = ImageDraw.Draw(out)
    f = ImageFont.truetype(FONT, 13)
    d.text((8, 5), text, fill=(130, 255, 205), font=f)
    return out

def main():
    v = sys.argv[1]
    a = load(f"{QA}/ref-{v}.png")
    b = load(f"{QA}/render-{v}.png")
    assert a.shape == b.shape, f"size mismatch {a.shape} vs {b.shape}"
    H, W = a.shape[:2]

    args = sys.argv[2:]
    if '--crop' in args:
        i = args.index('--crop')
        x, y, w, h = map(int, args[i+1:i+5])
        Z = int(args[i+5]) if len(args) > i+5 else 3
        box = (x, y, x+w, y+h)
        ca = Image.open(f"{QA}/ref-{v}.png").convert('RGB').crop(box).resize((w*Z, h*Z), Image.NEAREST)
        cb = Image.open(f"{QA}/render-{v}.png").convert('RGB').crop(box).resize((w*Z, h*Z), Image.NEAREST)
        dd = ImageChops.difference(Image.open(f"{QA}/ref-{v}.png").convert('RGB'),
                                   Image.open(f"{QA}/render-{v}.png").convert('RGB'))
        cd = dd.crop(box).resize((w*Z, h*Z), Image.NEAREST)
        out = Image.new('RGB', (w*Z*3 + 16, h*Z + 22), (20, 20, 20))
        for k, im in enumerate((label(ca, 'REF'), label(cb, 'RENDER'), label(cd, 'DIFF'))):
            out.paste(im, (k*(w*Z+8), 0))
        out.save(f"{QA}/crop-{v}.png")
        print(f"{QA}/crop-{v}.png")
        return

    mean, over = region_metrics(a, b)
    print(f"OVERALL  mean {mean:6.2f}  pct>30 {over:5.2f}%")
    regions = REGIONS.get(v, REGIONS['a'])
    if '--regions' in args or not args:
        for name, (x0, y0, x1, y1) in regions.items():
            m, o = region_metrics(a[y0:y1, x0:x1], b[y0:y1, x0:x1])
            bar = '#' * int(min(40, m))
            print(f"  {name:>8}  mean {m:6.2f}  pct>30 {o:5.2f}%  {bar}")

    ra = Image.open(f"{QA}/ref-{v}.png").convert('RGB')
    rb = Image.open(f"{QA}/render-{v}.png").convert('RGB')
    diff = ImageChops.difference(ra, rb).point(lambda p: min(255, p*4))
    side = Image.new('RGB', (W*3 + 16, H + 22), (20, 20, 20))
    for k, im in enumerate((label(ra, f'REFERENCE {v}'), label(rb, f'RENDER {v}'), label(diff, 'DIFF x4'))):
        side.paste(im, (k*(W+8), 0))
    side = side.resize((2048, int(side.height*2048/side.width)), Image.LANCZOS)
    side.save(f"{QA}/side-{v}.png")
    print(f"saved {QA}/side-{v}.png")

if __name__ == '__main__':
    main()
