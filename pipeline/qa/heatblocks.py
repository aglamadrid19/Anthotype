#!/usr/bin/env python3
"""Block-wise diff heatmap (text) between ref and render.

usage: heatblocks.py <variant> [block]
"""
import sys, numpy as np
from PIL import Image
import os
HERE = os.path.dirname(os.path.abspath(__file__))
v = sys.argv[1]
B = int(sys.argv[2]) if len(sys.argv) > 2 else 32
a = np.asarray(Image.open(f"{HERE}/ref-{v}.png").convert('RGB')).astype(np.float32)
b = np.asarray(Image.open(f"{HERE}/render-{v}.png").convert('RGB')).astype(np.float32)
d = np.abs(a-b).mean(axis=2)
H, W = d.shape
rows = H//B; cols = W//B
print(f"{v}: block={B}  overall mean {d.mean():.2f}")
hdr = '     ' + ''.join(f"{c*B:>5d}" for c in range(cols))
print(hdr)
tot = []
for r in range(rows):
    line = f"{r*B:4d} "
    for c in range(cols):
        m = d[r*B:(r+1)*B, c*B:(c+1)*B].mean()
        line += f"{m:5.0f}"
        tot.append((m, r*B, c*B))
    print(line)
tot.sort(reverse=True)
print("\ntop 20 blocks (mean, y, x):")
for m, y, x in tot[:20]:
    print(f"  {m:6.2f}  y={y:4d} x={x:4d}")
