#!/usr/bin/env python3
"""LaMa cleanup worker, run by the optional cleanup environment.

Standalone on purpose: it is invoked by an interpreter that has torch and
`simple-lama-inpainting` (not the studio venv), so it must not import `app`.
Reads a payload JSON `{source, masks, out}`, inpaints the masked rectangles,
composites the original pixels back outside them, and writes a PNG.  Prints a
one-line JSON status.
"""
import json
import sys

import numpy as np
from PIL import Image


def main() -> int:
    payload = json.loads(open(sys.argv[1]).read())
    img = Image.open(payload["source"]).convert("RGB")
    mask = np.zeros((img.height, img.width), np.uint8)
    for x0, y0, x1, y1 in payload["masks"]:
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(img.width, int(x1)), min(img.height, int(y1))
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = 255
    if not mask.any():
        print(json.dumps({"ok": False, "error": "empty mask"}))
        return 2

    import torch
    from simple_lama_inpainting import SimpleLama
    device = torch.device("mps") if torch.backends.mps.is_available() \
        else torch.device("cpu")
    lama = SimpleLama(device=device)
    cleaned = lama(img, Image.fromarray(mask)).convert("RGB")
    # The package pads to a multiple of 8 and returns the padded canvas.
    arr = np.asarray(cleaned)[:img.height, :img.width]
    original = np.asarray(img)
    keep = mask[:img.height, :img.width] == 0
    out = np.where(keep[..., None], original, arr)
    Image.fromarray(out.astype(np.uint8)).save(payload["out"], "PNG")
    print(json.dumps({"ok": True, "device": str(device),
                      "masks": len(payload["masks"]),
                      "size": [img.width, img.height]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
