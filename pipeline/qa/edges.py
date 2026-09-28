#!/usr/bin/env python3
"""Edge-structure map: Sobel magnitude + ridge points of the art region.

usage: edges.py <png> <x0> <y0> <x1> <y1> <zoom> <out.png> [thr]
"""
import sys, numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as ndi

p, x0, y0, x1, y1, z, out = sys.argv[1], *map(int, sys.argv[2:7]), sys.argv[7]
thr = float(sys.argv[8]) if len(sys.argv) > 8 else 12.0
a = np.asarray(Image.open(p).convert('RGB')).astype(np.float32)
lum = a[y0:y1, x0:x1].mean(axis=2)
lum = ndi.gaussian_filter(lum, 1.0)
gx = ndi.sobel(lum, 1); gy = ndi.sobel(lum, 0)
mag = np.hypot(gx, gy)
vis = np.clip(mag / max(1e-6, thr) * 255, 0, 255).astype(np.uint8)
im = Image.fromarray(vis, 'L').convert('RGB').resize(((x1-x0)*z, (y1-y0)*z), Image.NEAREST)
d = ImageDraw.Draw(im); f = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 11)
for x in range(x0 - x0 % 20, x1+1, 20):
    X=(x-x0)*z; major = x % 100 == 0
    d.line([(X,0),(X,im.height)], fill=(120,0,0) if major else (40,20,20))
    if major: d.text((X+2,2), str(x), fill=(255,120,120), font=f)
for y in range(y0 - y0 % 20, y1+1, 20):
    Y=(y-y0)*z; major = y % 100 == 0
    d.line([(0,Y),(im.width,Y)], fill=(120,0,0) if major else (40,20,20))
    if major: d.text((3,Y+2), str(y), fill=(255,120,120), font=f)
im.save(out); print(out, im.size)
