#!/usr/bin/env python3
"""Overlay a labelled coordinate grid on a crop of ref/render, for reading geometry."""
import sys, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

QA = os.path.dirname(os.path.abspath(__file__))
FONT = "/System/Library/Fonts/Menlo.ttc"

def main():
    which = sys.argv[1]          # ref | render | both
    box = tuple(map(int, sys.argv[2:6]))
    Z = int(sys.argv[6]) if len(sys.argv) > 6 else 6
    step = int(sys.argv[7]) if len(sys.argv) > 7 else 10
    v = sys.argv[8] if len(sys.argv) > 8 else 'a'
    x0, y0, x1, y1 = box
    w, h = x1-x0, y1-y0
    names = ['ref', 'render'] if which == 'both' else [which]
    tiles = []
    for name in names:
        im = Image.open(f"{QA}/{name}-{v}.png").convert('RGB').crop(box).resize((w*Z, h*Z), Image.NEAREST)
        d = ImageDraw.Draw(im)
        f = ImageFont.truetype(FONT, 13)
        for gx in range(x0 - x0 % step + step, x1, step):
            X = (gx-x0)*Z
            major = gx % 50 == 0
            d.line([(X, 0), (X, h*Z)], fill=(255, 60, 120) if major else (70, 90, 90), width=2 if major else 1)
            if major:
                d.text((X+3, 3), str(gx), fill=(255, 120, 160), font=f)
                d.text((X+3, h*Z-18), str(gx), fill=(255, 120, 160), font=f)
        for gy in range(y0 - y0 % step + step, y1, step):
            Y = (gy-y0)*Z
            major = gy % 50 == 0
            d.line([(0, Y), (w*Z, Y)], fill=(255, 60, 120) if major else (70, 90, 90), width=2 if major else 1)
            if major:
                d.text((3, Y+2), str(gy), fill=(255, 120, 160), font=f)
                d.text((w*Z-40, Y+2), str(gy), fill=(255, 120, 160), font=f)
        tiles.append(im)
    out = Image.new('RGB', (w*Z, (h*Z+4)*len(tiles)), (0, 0, 0))
    for i, t in enumerate(tiles):
        out.paste(t, (0, i*(h*Z+4)))
    p = f"{QA}/grid-{which}.png"
    out.save(p)
    print(p, out.size)

if __name__ == '__main__':
    main()
