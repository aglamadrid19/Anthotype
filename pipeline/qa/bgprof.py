#!/usr/bin/env python3
"""Background gradient profile: compare ref vs render luminance on a coarse grid.

usage: bgprof.py <variant> [step]
"""
import sys, numpy as np, os
from PIL import Image
HERE=os.path.dirname(os.path.abspath(__file__))
v=sys.argv[1]; S=int(sys.argv[2]) if len(sys.argv)>2 else 64
a=np.asarray(Image.open(f"{HERE}/ref-{v}.png").convert('RGB')).astype(np.float32)
b=np.asarray(Image.open(f"{HERE}/render-{v}.png").convert('RGB')).astype(np.float32)
H,W=a.shape[:2]
print(f"{v} bg grid step {S}:  ref_lum | ren_lum | dR dG dB")
xs=list(range(0,W-S+1,S))
print('     '+''.join(f"{x:>17d}" for x in xs))
for y in range(0,H-S+1,S):
    cells=[]
    for x in xs:
        ra=a[y:y+S,x:x+S].reshape(-1,3).mean(axis=0)
        rb=b[y:y+S,x:x+S].reshape(-1,3).mean(axis=0)
        d=rb-ra
        cells.append(f"{ra.mean():5.1f}/{rb.mean():5.1f} {d[0]:+4.0f}{d[1]:+4.0f}{d[2]:+4.0f}")
    print(f"{y:4d} "+''.join(cells))
