#!/usr/bin/env python3
"""Find the scale/offset that best maps a large-canvas render onto a reference.

Uses an ink-weighted metric (structure overlap) instead of raw MSE, which is
degenerate when most of the frame is background.
"""
import sys, os
import numpy as np
from PIL import Image

def ink(a, thr=55):
    bg = np.array([0, 10, 7])
    return np.abs(a - bg).sum(axis=2) > thr

def score(ref, cand, refink, candink):
    """Symmetric structure agreement + colour error where both have ink."""
    inter = np.logical_and(refink, candink).sum()
    union = np.logical_or(refink, candink).sum()
    iou = inter / union if union else 0.0
    both = np.logical_and(refink, candink)
    col = np.abs(ref[both] - cand[both]).mean() if both.any() else 255.0
    return iou, col

def main():
    v = sys.argv[1]
    big = sys.argv[2]
    ref = np.asarray(Image.open(f"qa/ref-{v}.png").convert('RGB')).astype(np.float32)
    im = Image.open(big).convert('RGB')
    refink = ink(ref)
    print(f"ref ink px {refink.sum()}  ({100*refink.mean():.2f}% of frame)")
    best = []
    for s in np.arange(0.55, 1.15, 0.01):
        out = (int(round(im.width*s)), int(round(im.height*s)))
        r = np.asarray(im.resize(out, Image.LANCZOS)).astype(np.float32)
        ri = ink(r)
        for ox in range(-300, 300, 10):
            for oy in range(-200, 250, 10):
                canv = np.zeros((768, 1024, 3), np.float32)
                ci = np.zeros((768, 1024), bool)
                x0, y0 = max(0, ox), max(0, oy)
                sx0, sy0 = max(0, -ox), max(0, -oy)
                w = min(out[0]-sx0, 1024-x0); h = min(out[1]-sy0, 768-y0)
                if w <= 0 or h <= 0: continue
                canv[y0:y0+h, x0:x0+w] = r[sy0:sy0+h, sx0:sx0+w]
                ci[y0:y0+h, x0:x0+w] = ri[sy0:sy0+h, sx0:sx0+w]
                iou, col = score(ref, canv, refink, ci)
                best.append((-iou, col, round(s,2), ox, oy))
    best.sort()
    print("best by structure IoU (higher is better):")
    for b in best[:12]:
        print(f"   IoU {-b[0]:.4f}  colour {b[1]:6.2f}  scale {b[2]:.2f}  offset ({b[3]:+4d},{b[4]:+4d})")

if __name__ == '__main__':
    main()
