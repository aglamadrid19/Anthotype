#!/usr/bin/env python3
"""Tight stacked (REF / RENDER / DIFF) zooms for each page element."""
import sys, os
import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFont

QA = os.path.dirname(os.path.abspath(__file__))
FONT = "/System/Library/Fonts/Menlo.ttc"

# name: (box, zoom)
CROPS = {
    'title':   ((45, 245, 465, 335), 4),
    'coming':  ((50, 333, 350, 390), 5),
    'tagline': ((50, 396, 350, 424), 6),
    'cta':     ((50, 440, 325, 512), 5),
    'ant':     ((505, 185, 825, 575), 2),
    'pod-tl':  ((425, 55, 545, 180), 5),
    'pod-br':  ((875, 310, 995, 435), 5),
}

def load(name, v):
    return Image.open(f"{QA}/{name}-{v}.png").convert('RGB')

def label(img, text):
    w, h = img.size
    out = Image.new('RGB', (w, h + 24), (22, 22, 22))
    out.paste(img, (0, 24))
    d = ImageDraw.Draw(out)
    d.text((8, 6), text, fill=(130, 255, 205), font=ImageFont.truetype(FONT, 14))
    return out

def compare(which, v):
    box, Z = CROPS[which]
    x0, y0, x1, y1 = box
    w, h = x1-x0, y1-y0
    ref, ren = load('ref', v), load('render', v)
    ca = ref.crop(box).resize((w*Z, h*Z), Image.NEAREST)
    cb = ren.crop(box).resize((w*Z, h*Z), Image.NEAREST)
    cd = ImageChops.difference(ref, ren).crop(box).point(lambda p: min(255, p*3)).resize((w*Z, h*Z), Image.NEAREST)
    d = np.abs(np.asarray(ref.crop(box), np.float32) - np.asarray(ren.crop(box), np.float32)).mean()
    W = w*Z
    out = Image.new('RGB', (W, (h*Z+24)*3), (22, 22, 22))
    out.paste(label(ca, f'REF {which} {box} mean={d:.1f}'), (0, 0))
    out.paste(label(cb, f'RENDER {which}'), (0, h*Z+24))
    out.paste(label(cd, 'DIFF x3'), (0, (h*Z+24)*2))
    p = f"{QA}/elem-{which}.png"
    out.save(p)
    return p, d

if __name__ == '__main__':
    v = sys.argv[1]
    names = sys.argv[2:] or list(CROPS)
    for n in names:
        p, d = compare(n, v)
        print(f"{n:>8} mean {d:6.2f}  {p}")
