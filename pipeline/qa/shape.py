#!/usr/bin/env python3
"""Row-wise ink extent + luminance profile of an art region."""
import sys, numpy as np
from PIL import Image

p = sys.argv[1]
x0,x1 = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv)>3 else (380,1024)
y0,y1 = (int(sys.argv[4]), int(sys.argv[5])) if len(sys.argv)>5 else (100,768)
step = int(sys.argv[6]) if len(sys.argv)>6 else 8
a = np.asarray(Image.open(p).convert('RGB')).astype(np.float32)
lum = a.mean(axis=2)
bg = np.median(lum[2:6,2:6])
sub = lum[y0:y1, x0:x1]
m = sub > bg+9
print(f"{p} bg={bg:.1f} region x{x0}-{x1} y{y0}-{y1}")
for i in range(0, sub.shape[0], step):
    y = y0+i
    row = np.nonzero(m[i])[0]
    if len(row)==0:
        print(f"y={y:3d}   -")
        continue
    xa, xb = row.min()+x0, row.max()+x0
    # green channel dominance at widest
    print(f"y={y:3d}  x {xa:4d}-{xb:4d}  w {xb-xa:4d}  n {len(row):4d}  peaklum {sub[i].max():6.1f}")
