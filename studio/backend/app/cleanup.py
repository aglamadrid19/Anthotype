"""Optional external masked-inpainting cleanup for a scene hero.

The studio's own prepared image fills removed copy with a nearest-neighbour
fill.  That is right for small glyphs, but on a large interface element it
leaves ghost strokes and replicated edges -- the measured dashboard backdrop had
a pill/dot remnant, button outlines and rectangular smears.  When an external
LaMa environment is available, this module cleans the **original upload**
instead: the masks cover the complete interface elements, and the result is
composited back so every pixel outside them is the original byte-for-byte.

The cleaner is optional and deliberately external (torch is gigabytes; the
studio venv stays numpy/PIL).  `find_python` looks for `STUDIO_CLEANUP_PYTHON`,
then `studio/.cleanup-venv/bin/python`.  When it is missing the caller keeps
the tracer's fill and says so -- see `runner._hero_art`.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from .config import STUDIO_DIR

WORKER = Path(__file__).with_name("cleanup_lama.py")

# How far a component's mask may grow beyond the tracer's own rect (source px).
# A full interface element (a pill's dot, a button's plate and shadow) sits
# within this; anything further away is illustration content and must not be
# swallowed.  The dashboard's pill needs ~30 px, its plates ~10.
MAX_GROW = 48
# Growth on the copy blocks (their rects are already the full text box).
COPY_PAD = 3
# Local-contrast threshold (0-255) for "this pixel is part of the element".
CONTRAST = 12.0


def find_python() -> str | None:
    """The interpreter of the optional cleanup environment, or None."""
    env = os.environ.get("STUDIO_CLEANUP_PYTHON")
    if env and Path(env).is_file():
        return env
    cand = STUDIO_DIR / ".cleanup-venv" / "bin" / "python"
    return str(cand) if cand.is_file() else None


def component_masks(arr: np.ndarray, rects: list[list[int]],
                    max_grow: int = MAX_GROW, pad: int = 4) -> list[list[int]]:
    """Grow each tracer rect to the complete element it belongs to.

    The element is found from the pixels themselves -- whatever leaves a local
    median background -- but only the area **connected to the rect** (4-way
    flood within the search window).  A bbox of *all* contrasting pixels in the
    window also catches unrelated artwork: a rack edge or a glow entering the
    window becomes part of the mask even though it has nothing to do with the
    component.  Connection to the seed is what separates "this button's plate
    and its shadow" from "the illustration next to it".

    The union is padded by `pad` so the element's anti-aliased edge/glow is
    inside the hole, then hard-capped at `max_grow` (the pad is applied before
    the cap) so a component can never reach an illustration beyond the window.
    Pure numpy/PIL (the studio venv has no scipy), so the guard test runs
    everywhere.
    """
    h, w = arr.shape[:2]
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    bg = np.asarray(img.filter(ImageFilter.MedianFilter(size=31)), np.int16)
    region = np.abs(np.asarray(img, np.int16) - bg).max(axis=2) > CONTRAST
    out: list[list[int]] = []
    for r in rects:
        x0, y0, x1, y1 = (int(round(v)) for v in r)
        ex0, ey0 = max(0, x0 - max_grow), max(0, y0 - max_grow)
        ex1 = min(w, max(x1, x0 + 1) + max_grow)
        ey1 = min(h, max(y1, y0 + 1) + max_grow)
        win = region[ey0:ey1, ex0:ex1]
        seed = np.zeros_like(win)
        sx0, sy0 = max(0, x0 - ex0), max(0, y0 - ey0)
        sx1, sy1 = min(win.shape[1], x1 - ex0), min(win.shape[0], y1 - ey0)
        seed[sy0:sy1, sx0:sx1] = True
        reach = win & seed
        if not reach.any():
            out.append([x0, y0, x1, y1])
            continue
        while True:                       # 4-connected flood inside the window
            grown = reach.copy()
            grown[1:, :] |= reach[:-1, :]
            grown[:-1, :] |= reach[1:, :]
            grown[:, 1:] |= reach[:, :-1]
            grown[:, :-1] |= reach[:, 1:]
            grown &= win
            new = grown & ~reach
            if not new.any():
                break
            reach = grown
        ys, xs = np.nonzero(reach)
        bx0, by0 = ex0 + int(xs.min()), ey0 + int(ys.min())
        bx1, by1 = ex0 + int(xs.max()) + 1, ey0 + int(ys.max()) + 1
        # Union with the tracer's rect, pad for anti-aliasing, clamp to the cap.
        nx0 = max(ex0, min(bx0, x0) - pad)
        ny0 = max(ey0, min(by0, y0) - pad)
        nx1 = min(ex1, max(bx1, x1) + pad)
        ny1 = min(ey1, max(by1, y1) + pad)
        out.append([max(0, nx0), max(0, ny0), min(w, nx1), min(h, ny1)])
    return out


def copy_masks(source: np.ndarray, rects: list[list[int]],
               pad: int = COPY_PAD) -> list[list[int]]:
    """The copy boxes, only lightly grown (their rects are already full boxes).

    Expanding copy rects with `component_masks` would let the headline box's
    local contrast reach the rack beside it; the text boxes are already the
    complete block, so a small pad for anti-aliasing is all they need.
    """
    h, w = source.shape[:2]
    return [[max(0, int(round(x0)) - pad), max(0, int(round(y0)) - pad),
             min(w, int(round(x1)) + pad), min(h, int(round(y1)) + pad)]
            for x0, y0, x1, y1 in rects]


def subtract_rects(masks: list[list[int]],
                   cuts: list[list[int]]) -> tuple[list[list[int]], int]:
    """Remove every `cut` rectangle from every mask; `(masks, cuts_applied)`.

    Labels are protected content: a cleanup mask must never remove one, so the
    artwork-label rects are subtracted from the masks before the cleaner runs
    (the masks are built to avoid illustration content already; this is the
    hard guarantee).
    """
    applied = 0
    for cut in cuts:
        cx0, cy0, cx1, cy1 = (int(round(v)) for v in cut)
        out: list[list[int]] = []
        for r in masks:
            x0, y0, x1, y1 = (int(round(v)) for v in r)
            ix0, iy0 = max(x0, cx0), max(y0, cy0)
            ix1, iy1 = min(x1, cx1), min(y1, cy1)
            if ix1 <= ix0 or iy1 <= iy0:
                out.append([x0, y0, x1, y1])
                continue
            applied += 1
            if y0 < iy0:
                out.append([x0, y0, x1, iy0])
            if iy1 < y1:
                out.append([x0, iy1, x1, y1])
            if x0 < ix0:
                out.append([x0, iy0, ix0, iy1])
            if ix1 < x1:
                out.append([ix1, iy0, x1, iy1])
        masks = [r for r in out if r[2] > r[0] and r[3] > r[1]]
    return masks, applied


def clean(source: Path, masks: list[list[int]], out: Path, python: str,
          timeout: int = 1800) -> dict | None:
    """Run the external LaMa worker; return its status dict or None."""
    if not masks:
        return None
    payload = {"source": str(source), "masks": masks, "out": str(out)}
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(payload, fh)
        payload_path = fh.name
    try:
        proc = subprocess.run([python, str(WORKER), payload_path],
                              capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:  # noqa: BLE001
        print(f"cleanup failed to run: {exc}")
        return None
    finally:
        Path(payload_path).unlink(missing_ok=True)
    if proc.returncode != 0 or not out.is_file():
        print(f"cleanup worker exited {proc.returncode}: "
              f"{(proc.stderr or '').strip()[-400:]}")
        return None
    try:
        return json.loads((proc.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": True}
