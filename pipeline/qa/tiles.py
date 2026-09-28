#!/usr/bin/env python3
"""Detect bright rounded-square provider tiles in an art region.

A tile = local blob of pixels that are (a) much brighter than bg and
(b) green/cyan dominant, with bbox roughly square and 40..110 px.
"""
import sys, numpy as np
from PIL import Image
from scipy import ndimage as ndi

p = sys.argv[1]
x0 = int(sys.argv[2]) if len(sys.argv) > 2 else 430
a = np.asarray(Image.open(p).convert('RGB')).astype(np.float32)
lum = a.mean(axis=2)
bg = np.median(lum[2:6,2:6])
g = a[:,:,1]
m = (lum > bg + 40) & (g >= a[:,:,0] + 6) & (np.arange(a.shape[1])[None,:] >= x0)
m = ndi.binary_closing(m, np.ones((3,3)))
lab, n = ndi.label(m, np.ones((3,3)))
objs = ndi.find_objects(lab)
out = []
for i, sl in enumerate(objs):
    if sl is None: continue
    y0,y1 = sl[0].start, sl[0].stop; xa,xb = sl[1].start, sl[1].stop
    h = y1-y0; w = xb-xa
    if not (34 <= w <= 130 and 34 <= h <= 130): continue
    if not (0.6 <= w/h <= 1.7): continue
    area = int((lab[sl] == i+1).sum())
    if area < 500: continue
    out.append((area, xa, xb, y0, y1, w, h))
out.sort(key=lambda t: (t[3], t[1]))
print(f"{p}: {len(out)} tile candidates")
for area,xa,xb,y0,y1,w,h in out:
    print(f"  c=({(xa+xb)/2:7.1f},{(y0+y1)/2:6.1f})  x {xa:4d}-{xb:4d} y {y0:3d}-{y1:3d}  {w}x{h}  area {area}")
