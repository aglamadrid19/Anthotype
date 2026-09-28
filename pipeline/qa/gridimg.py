#!/usr/bin/env python3
"""Overlay a labelled coordinate grid on an image crop for manual reading.

usage: gridimg.py <img> <x0> <y0> <x1> <y1> <zoom> <out.png> [step]
"""
import sys
from PIL import Image, ImageDraw, ImageFont
img, x0, y0, x1, y1, z, out = sys.argv[1], *map(int, sys.argv[2:7]), sys.argv[7]
step = int(sys.argv[8]) if len(sys.argv) > 8 else 20
im = Image.open(img).convert('RGB').crop((x0, y0, x1, y1))
im = im.resize((im.width*z, im.height*z), Image.NEAREST)
d = ImageDraw.Draw(im)
f = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 11)
for x in range(x0 - x0 % step, x1 + 1, step):
    X = (x - x0) * z
    major = (x % 100 == 0)
    d.line([(X, 0), (X, im.height)], fill=(255, 90, 90) if major else (90, 40, 40), width=1)
    if major: d.text((X + 2, 2), str(x), fill=(255, 160, 160), font=f)
    if major: d.text((X + 2, im.height - 14), str(x), fill=(255, 160, 160), font=f)
for y in range(y0 - y0 % step, y1 + 1, step):
    Y = (y - y0) * z
    major = (y % 100 == 0)
    d.line([(0, Y), (im.width, Y)], fill=(255, 90, 90) if major else (90, 40, 40), width=1)
    if major:
        d.text((3, Y + 2), str(y), fill=(255, 160, 160), font=f)
        d.text((im.width - 40, Y + 2), str(y), fill=(255, 160, 160), font=f)
im.save(out)
print(out, im.size)
