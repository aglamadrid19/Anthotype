#!/usr/bin/env python3
"""Tile detector v2: tiles have a bright outline ring; use luminance peaks."""
import sys, numpy as np
from PIL import Image
from scipy import ndimage as ndi

p = sys.argv[1]; x0 = int(sys.argv[2]); thr = float(sys.argv[3]) if len(sys.argv)>3 else 55
a = np.asarray(Image.open(p).convert('RGB')).astype(np.float32)
lum = a.mean(axis=2)
bg = np.median(lum[2:6,2:6])
m = lum > bg + thr
m[:, :x0] = False
lab, n = ndi.label(m, np.ones((3,3)))
objs = ndi.find_objects(lab)
res = []
for i, sl in enumerate(objs):
    if sl is None: continue
    y0,y1 = sl[0].start, sl[0].stop; xa,xb = sl[1].start, sl[1].stop
    h=y1-y0; w=xb-xa
    area = int((lab[sl]==i+1).sum())
    if area < 300: continue
    res.append((area,xa,xb,y0,y1,w,h))
res.sort(key=lambda t: -t[0])
print(f"{p} thr={thr}: {len(res)} blobs")
for area,xa,xb,y0,y1,w,h in res[:18]:
    print(f"  c=({(xa+xb)/2:7.1f},{(y0+y1)/2:6.1f}) x{xa:4d}-{xb:4d} y{y0:3d}-{y1:3d} {w}x{h} a{area}")
