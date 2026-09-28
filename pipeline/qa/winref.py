#!/usr/bin/env python3
"""Print reference window geometry for a variant (same windows as geom.py)."""
import sys, os, numpy as np
from PIL import Image
HERE=os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0,HERE)
from geom import WIN, win_geom
v=sys.argv[1]
arr=np.asarray(Image.open(f'{HERE}/ref-{v}.png').convert('RGB'))
for label,box in WIN.items():
    r=win_geom(arr,box)
    if r: print(f"  {label:>8} x{r['x0']:4d}-{r['x1']:4d} y{r['y0']:4d}-{r['y1']:4d}  w{r['w']:4d} h{r['h']:3d} cov{r['cov']:6.2f}")
    else: print(f"  {label:>8} (none)")
