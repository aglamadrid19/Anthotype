#!/usr/bin/env python3
"""Coarse-grained (cell) diff heatmap with the worst cells ranked."""
import sys, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

QA = os.path.dirname(os.path.abspath(__file__))

def main():
    v = sys.argv[1]
    CW = int(sys.argv[2]) if len(sys.argv) > 2 else 32
    a = np.asarray(Image.open(f"{QA}/ref-{v}.png").convert('RGB')).astype(np.float32)
    b = np.asarray(Image.open(f"{QA}/render-{v}.png").convert('RGB')).astype(np.float32)
    H, W = a.shape[:2]
    d = np.abs(a-b).mean(axis=2)
    gh, gw = H//CW, W//CW
    cells = d[:gh*CW, :gw*CW].reshape(gh, CW, gw, CW).mean(axis=(1, 3))
    ch = " .:oO#@"
    print(f"cell={CW}px  ({gw}x{gh})  legend {' .:oO#@'}  (=0..70+)")
    for gy in range(gh):
        print('  ' + ''.join(ch[min(6, int(cells[gy, gx]/10))] for gx in range(gw)))
    print()
    flat = [(cells[gy, gx], gx, gy) for gy in range(gh) for gx in range(gw)]
    flat.sort(reverse=True)
    print("worst cells:")
    for val, gx, gy in flat[:18]:
        print(f"  {val:6.1f}  cell({gx:2d},{gy:2d})  px({gx*CW:4d},{gy*CW:4d})-({(gx+1)*CW:4d},{(gy+1)*CW:4d})")

if __name__ == '__main__':
    main()
