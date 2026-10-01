"""Turn extracted text blocks into the three files the pipeline consumes.

  * `content-<id>.json`  -- the page (title, description, semantic markup, stage)
  * `<id>.page.css`      -- the site's stylesheet (flow layout, role-based scale)
  * `designs/<id>.json`  -- box = full frame, text = exclusion rects

The output is a **real website**: semantic sections (`header`/`nav`/`main` with
one `section` per region/`footer`) in normal document flow, responsive, with a
role-based type scale.  It is deliberately *not* a pixel-placed poster -- the
reference's glyphs are not reproduced, they are replaced by authored copy in the
site's own type.

The one place the reference pixels still matter is `mkart.py`'s exclusion rects:
the model's text boxes are exactly the rectangles the tracer must exclude so the
traced artwork does not bake in a rasterised copy of the words.  Growing them
slightly is safe -- it only preserves a little more of the glow the type sits on.
"""
from __future__ import annotations

import html
import json
import re
import threading
from pathlib import Path

import numpy as np
from PIL import Image

from .config import STAGE_H, STAGE_W
from .extract import Block
from .fontmetrics import char_at_x_fraction

# Safety growth on the mkart text-exclusion rects (stage px).
TEXT_RECT_GROW = 6

# How far apart two blocks can be (as a multiple of the taller block) and still
# be considered part of the same visual group when the model gives no usable
# section.  Used only as a backstop -- see `group_sections`.
GROUP_GAP = 2.5


def _as_array(png: Path) -> np.ndarray:
    return np.asarray(Image.open(png).convert("RGB")).astype(np.float32)


def sample_ink(arr: np.ndarray, bbox: tuple[float, float, float, float],
               background: tuple[int, int, int]) -> tuple[int, int, int]:
    """Ink colour inside `bbox`: the pixels that differ most from the background.

    Polarity-agnostic -- works for light type on dark and dark type on light.
    """
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(STAGE_W, x1), min(STAGE_H, y1)
    if x1 <= x0 or y1 <= y0:
        return (255, 255, 255)
    patch = arr[y0:y1, x0:x1].reshape(-1, 3)
    bg = np.array(background, dtype=np.float32)
    dist = np.linalg.norm(patch - bg, axis=1)
    if dist.size == 0 or float(dist.max()) < 1e-3:
        return tuple(int(v) for v in np.median(patch, axis=0))
    ink = patch[dist >= np.percentile(dist, 70)]
    return tuple(int(v) for v in np.median(ink, axis=0))


def sample_runs(arr: np.ndarray, bbox: tuple[float, float, float, float], text: str,
                background: tuple[int, int, int], weight: int = 400
                ) -> list[tuple[str, tuple[int, int, int]]]:
    """Split a block into colour runs, e.g. white "Ant" + green "Hosting".

    A vision model reports one box per text run, but a run may be painted in two
    colours (a neutral wordmark prefix and a coloured suffix).  A single median
    sample collapses those to one colour, which reads as a visible error.  The
    ink is clustered into a neutral and a saturated group; when both are
    substantial the x boundary between them is mapped back to a character index
    with the real Inter advance widths, giving [(run_text, colour), ...].
    """
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(STAGE_W, x1), min(STAGE_H, y1)
    sub = arr[y0:y1, x0:x1]
    if sub.size == 0 or not text:
        return [(text, sample_ink(arr, bbox, background))]

    dist = np.linalg.norm(sub - np.array(background, dtype=np.float32), axis=2)
    ink = dist > max(28.0, float(np.percentile(dist, 60)))
    if int(ink.sum()) < 20:
        return [(text, sample_ink(arr, bbox, background))]

    px = sub[ink]
    dsel = dist[ink]
    # The ink that actually draws the glyphs is the ink furthest from the
    # background.  Distance, not brightness: selecting by brightness assumes
    # light type on a dark ground (the shipped references) and on a light design
    # it keeps only the anti-aliased fringe beside the background, washing every
    # block out to near-white.
    #
    # Taken *per tone*, so a two-tone wordmark keeps both runs: the dark half and
    # the saturated half sit at different distances, and a single distance cut
    # drops the weaker one entirely.
    sat_px = px.max(axis=1) - px.min(axis=1)
    is_neutral = sat_px < 26

    def _core(mask: np.ndarray) -> np.ndarray:
        g, gd = px[mask], dsel[mask]
        if g.size == 0:
            return g
        return g[gd >= np.percentile(gd, 65)]

    neutral, coloured = _core(is_neutral), _core(~is_neutral)
    both = max(1, len(neutral) + len(coloured))
    # Both groups must be real, not a few stray antialiased pixels.  Measured by
    # pixel count AND by horizontal extent: a coloured suffix must occupy a
    # meaningful slice of the line, not just a highlight on one glyph.
    w = max(1, sub.shape[1])
    if len(neutral) < 0.10 * both or len(coloured) < 0.10 * both:
        # One tone: the glyph interior of the strongest ink.
        pick = px[dsel >= np.percentile(dsel, 65)] if dsel.size else px
        return [(text, tuple(int(v) for v in np.median(pick, axis=0)))]

    # The coloured run starts where a *column* is dominated by saturated ink,
    # not where a single stray saturated pixel happens to appear: one noisy
    # pixel inside the neutral half used to move the split by a whole glyph.
    mask_sat = ink & ((sub.max(axis=2) - sub.min(axis=2)) >= 26)
    mask_neu = ink & ~mask_sat
    col_ink = ink.sum(axis=0)
    col_sat = mask_sat.sum(axis=0)
    dom = (col_ink > 0) & (col_sat >= np.maximum(2, 0.5 * col_ink))
    sat_cols = np.nonzero(dom)[0]
    neu_cols = np.nonzero(mask_neu.sum(axis=0) > 0)[0]
    if len(sat_cols) == 0 or len(neu_cols) == 0:
        pick = neutral if len(neutral) >= len(coloured) else coloured
        return [(text, tuple(int(v) for v in np.median(pick, axis=0)))]
    if len(sat_cols) < 0.12 * w or len(neu_cols) < 0.12 * w:
        pick = neutral if len(neutral) >= len(coloured) else coloured
        return [(text, tuple(int(v) for v in np.median(pick, axis=0)))]
    frac = float(sat_cols.min()) / w
    idx = char_at_x_fraction(text, frac, weight)
    idx = max(1, min(len(text) - 1, idx))
    # A real two-tone run splits at a word boundary ("Ant" + "Hosting"): the
    # coloured part is at least a quarter of the string's width.  A split that
    # fragments a glyph -- a saturated highlight on one letter -- is noise, and
    # emitting it as a run paints that letter a different colour (the Montiva
    # hero paragraph came back as a grey "Compu" + a slate rest).  When the split
    # is not structural, fall back to one colour for the block.
    if idx < 3 or idx > len(text) - 3:
        pick = px[dsel >= np.percentile(dsel, 65)] if dsel.size else px
        return [(text, tuple(int(v) for v in np.median(pick, axis=0)))]
    return [(text[:idx], tuple(int(v) for v in np.median(neutral, axis=0))),
            (text[idx:], tuple(int(v) for v in np.median(coloured, axis=0)))]


def sample_fill(arr: np.ndarray, bbox: tuple[float, float, float, float],
                background: tuple[int, int, int]) -> tuple[int, int, int]:
    """Button fill: the dominant colour inside the box that is not background.

    A CTA box contains mostly button and a minority of label, so among the
    non-background pixels the median is the fill (the label is the extreme, not
    the majority).  This is robust to a loose box, unlike a border-ring sample,
    because the ring can fall outside the button.
    """
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(STAGE_W, x1), min(STAGE_H, y1)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return (24, 196, 124)
    patch = arr[y0:y1, x0:x1].reshape(-1, 3)
    bg = np.array(background, dtype=np.float32)
    dist = np.linalg.norm(patch - bg, axis=1)
    sel = patch[dist > max(24.0, float(np.percentile(dist, 40)))]
    if sel.size == 0:
        return (24, 196, 124)
    return tuple(int(v) for v in np.median(sel, axis=0))


def sample_plate_fill(arr: np.ndarray, bbox: tuple[float, float, float, float],
                      background: tuple[int, int, int], grow: int = 6
                      ) -> tuple[int, int, int]:
    """Fill of the plate the CTA label sits on, sampled just outside the label.

    The model reports the *label*, so the pixels immediately around it are the
    button plate.  Unlike `sample_fill` this cannot be contaminated by
    surrounding artwork (a CTA dropped on top of a photo) or by a label box that
    is off-centre on its button -- the plate is by definition the saturated
    colour adjacent to the label.
    """
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    wx0, wy0 = max(0, x0 - grow), max(0, y0 - grow)
    wx1, wy1 = min(STAGE_W, x1 + grow), min(STAGE_H, y1 + grow)
    if wx1 - wx0 < 3 or wy1 - wy0 < 3:
        return (24, 196, 124)
    patch = arr[wy0:wy1, wx0:wx1].reshape(-1, 3)
    bg = np.array(background, dtype=np.float32)
    dist = np.linalg.norm(patch - bg, axis=1)
    sel = patch[dist > max(24.0, float(np.percentile(dist, 40)))]
    if sel.size == 0:
        return (24, 196, 124)
    sat = sel.max(axis=1) - sel.min(axis=1)
    strong = sel[sat >= max(30.0, float(np.percentile(sat, 75)))]
    pick = strong if len(strong) >= max(8, 0.1 * len(sel)) else sel
    return tuple(int(v) for v in np.median(pick, axis=0))


def sample_contrast(arr: np.ndarray, bbox: tuple[float, float, float, float],
                    against: tuple[int, int, int]) -> tuple[int, int, int]:
    """Colour inside `bbox` that is furthest from `against`.

    For a CTA the label is the minority colour that contrasts with the button
    fill, so `sample_ink` (which measures distance from the *background*) would
    return the fill itself.  Measuring distance from the fill instead recovers
    the label.
    """
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(STAGE_W, x1), min(STAGE_H, y1)
    if x1 <= x0 or y1 <= y0:
        return (255, 255, 255)
    patch = arr[y0:y1, x0:x1].reshape(-1, 3)
    ref = np.array(against, dtype=np.float32)
    dist = np.linalg.norm(patch - ref, axis=1)
    if dist.size == 0 or float(dist.max()) < 12.0:
        return (255, 255, 255)
    sel = patch[dist >= np.percentile(dist, 85)]
    return tuple(int(v) for v in np.median(sel, axis=0))


def _region_bbox(mask: np.ndarray, seeds: np.ndarray,
                 max_iter: int = 400) -> tuple[int, int, int, int] | None:
    """Bounding box of the connected region of `mask` reachable from `seeds`.

    Iterative 4-connected dilation restricted to `mask` (no scipy).  Used to
    grow a CTA's label box out to the real button, which is a solid region the
    model does not report.
    """
    region = seeds & mask
    if not region.any():
        return None
    for _ in range(max_iter):
        grown = region.copy()
        grown[1:, :] |= region[:-1, :]
        grown[:-1, :] |= region[1:, :]
        grown[:, 1:] |= region[:, :-1]
        grown[:, :-1] |= region[:, 1:]
        grown &= mask
        if np.array_equal(grown, region):
            break
        region = grown
    ys, xs = np.nonzero(region)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def refine_button_bbox(arr: np.ndarray, bbox: tuple[float, float, float, float],
                       fill: tuple[int, int, int], pad: int = 90) -> tuple[float, float, float, float]:
    """Grow a CTA label box out to the full button.

    A vision model reports the *label*, not the button, so a DOM button built
    from that box is too small and its text-exclusion rect misses the button
    art.  The button is a solid fill region containing the label, so measuring
    it is easy and exact.
    """
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    wx0, wy0 = max(0, x0 - pad), max(0, y0 - pad)
    wx1, wy1 = min(STAGE_W, x1 + pad), min(STAGE_H, y1 + pad)
    win = arr[wy0:wy1, wx0:wx1]
    if win.size == 0:
        return bbox
    dist = np.linalg.norm(win - np.array(fill, dtype=np.float32), axis=2)
    mask = dist < 90.0
    seeds = np.zeros(mask.shape, bool)
    seeds[max(0, y0 - wy0):y1 - wy0, max(0, x0 - wx0):x1 - wx0] = True
    found = _region_bbox(mask, seeds)
    if not found:
        return bbox
    fx0, fy0, fx1, fy1 = found
    bw, bh = fx1 - fx0, fy1 - fy0
    # The button must be plausible and overlap the label.  It need not *contain*
    # the label box: the model's box is a few pixels loose, and on a small pill
    # it can be wider than the button itself.
    #
    # But it must be at least as tall as the label: a real button has the label
    # inside it, so a flooded region *shorter* than the label is the surrounding
    # artwork, not the button.  Without this, "Call Now" on the Montiva hero
    # matched a blue patch of the photograph (35x6 against a 32x9 label) and the
    # CTA rendered as a small blue smear.
    if bw < 1.02 * (x1 - x0) or bh < 1.02 * (y1 - y0):
        return bbox
    if bw > 4 * (x1 - x0) + 80 or bh > 4 * (y1 - y0) + 80:
        return bbox
    return (wx0 + fx0, wy0 + fy0, wx0 + fx1, wy0 + fy1)


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _sat(rgb: tuple[int, int, int]) -> int:
    return max(rgb) - min(rgb)


def measure_button_bbox(arr: np.ndarray, label: tuple[float, float, float, float],
                        background: tuple[int, int, int],
                        padx: int | None = None,
                        pady: int | None = None) -> tuple[int, int, int, int] | None:
    """Full button rectangle for an *outline* (bordered) button.

    A solid-fill button is found by flood-filling its fill colour
    (`refine_button_bbox`), but an outline button has no fill to flood -- only a
    border.  Its border and label are the only non-background pixels around the
    label box, so the bounding box of that ink is the button.

    The search window is scaled from the label rather than fixed: on a busy
    background a fixed +-90/+30 window swallows the surrounding artwork and
    returns a box tens of times too large (a 44x12 label once produced a 224x72
    button over a laptop mockup).
    """
    x0, y0, x1, y1 = (int(round(v)) for v in label)
    lh = max(1, y1 - y0)
    if padx is None:
        padx = max(24, int(1.2 * lh) + 12)
    if pady is None:
        pady = max(12, int(0.8 * lh) + 8)
    wx0, wy0 = max(0, x0 - padx), max(0, y0 - pady)
    wx1, wy1 = min(STAGE_W, x1 + padx), min(STAGE_H, y1 + pady)
    win = arr[wy0:wy1, wx0:wx1]
    if win.size == 0:
        return None
    dist = np.linalg.norm(win - np.array(background, dtype=np.float32), axis=2)
    mask = dist > 22.0
    if not mask.any():
        return None
    ys, xs = np.nonzero(mask)
    bx0, by0 = wx0 + int(xs.min()), wy0 + int(ys.min())
    bx1, by1 = wx0 + int(xs.max()) + 1, wy0 + int(ys.max()) + 1
    # The button must contain the label and be a plausible size.
    if bx1 - bx0 < x1 - x0 or by1 - by0 < y1 - y0:
        return None
    if (bx1 - bx0) > 4 * (x1 - x0) + 80 or (by1 - by0) > 4 * (y1 - y0) + 80:
        return None
    return (bx0, by0, bx1, by1)


def snap_to_ink(arr: np.ndarray, bbox: tuple[float, float, float, float],
                background: tuple[int, int, int], pad: int = 10,
                thr: float = 40.0) -> tuple[float, float, float, float]:
    """Tighten a model box onto the glyphs actually present in the reference.

    Even with the coordinate grid the model's boxes are a few pixels loose or
    shifted.  The type is the only ink inside its own box, so measuring it
    locally removes that residual error -- and because font-size is solved from
    the box width, a few pixels of width error becomes a visible size error.

    Polarity-aware: the ink may be either side of the background, so the side is
    measured rather than assumed (see the note below).
    """
    x0, y0, x1, y1 = bbox
    wx0, wy0 = max(0, int(x0) - pad), max(0, int(y0) - pad)
    wx1, wy1 = min(STAGE_W, int(x1) + pad), min(STAGE_H, int(y1) + pad)
    if wx1 - wx0 < 3 or wy1 - wy0 < 3:
        return bbox
    sub = arr[wy0:wy1, wx0:wx1]
    grey = sub.mean(axis=2)
    bg_mean = float(np.array(background, dtype=np.float32).mean())
    # Keep only the ink connected to the reported box, so a neighbouring line
    # cannot drag the fit.
    seed = np.zeros(grey.shape, bool)
    seed[max(0, int(y0) - wy0):int(y1) - wy0,
         max(0, int(x0) - wx0):int(x1) - wx0] = True
    # A fixed threshold assumes high contrast (bright type on a dark ground).
    # Faint type -- light grey small print on a near-white page -- sits within
    # `thr` of the background and would be missed entirely, collapsing the box.
    # Never be stricter than the block's own strongest ink.
    d = np.abs(grey - bg_mean)
    base = float(d.max())
    thr_eff = min(thr, max(14.0, 0.4 * base)) if base > 0 else thr
    # Polarity is a property of the design, not a constant.  The references are
    # light type on a dark ground, but an upload can be dark type on a light
    # ground; a hardcoded `>` silently returns the model box unchanged whenever
    # the background is near white (the threshold exceeds 255).  Choose the side
    # of the background that actually carries the ink inside the reported box.
    seed_grey = grey[seed] if seed.any() else grey
    dark = float((seed_grey < bg_mean - thr_eff).mean())
    light = float((seed_grey > bg_mean + thr_eff).mean())
    ink = grey > (bg_mean + thr_eff) if light > dark else grey < (bg_mean - thr_eff)
    if not ink.any():
        return bbox
    region = seed & ink
    if not region.any():
        return bbox
    for _ in range(500):
        grown = region.copy()
        grown[1:, :] |= region[:-1, :]
        grown[:-1, :] |= region[1:, :]
        grown[:, 1:] |= region[:, :-1]
        grown[:, :-1] |= region[:, 1:]
        grown &= ink
        if np.array_equal(grown, region):
            break
        region = grown
    ys, xs = np.nonzero(region)
    sx0, sy0 = wx0 + int(xs.min()), wy0 + int(ys.min())
    sx1, sy1 = wx0 + int(xs.max()) + 1, wy0 + int(ys.max()) + 1
    # Refuse a fit that clearly left the box (it caught a different element).
    # The lower bound is deliberately loose: thin, anti-aliased small print has
    # only a few solidly-dark rows, and a tight snap there under-measures the
    # box so badly that a wrapped block gets the wrong size and an exclusion
    # rect misses the type.
    if sx1 - sx0 < 0.6 * (x1 - x0) or sy1 - sy0 < 0.6 * (y1 - y0):
        return bbox
    if sx1 - sx0 > 2.0 * (x1 - x0) + 20 or sy1 - sy0 > 2.0 * (y1 - y0) + 20:
        return bbox
    return (float(sx0), float(sy0), float(sx1), float(sy1))


def decorate(blocks: list[Block], ref_png: Path,
             background: tuple[int, int, int]) -> list[Block]:
    """Fill in each block's real colour(s) (and a CTA's fill) from the reference.

    The reference is no longer reproduced glyph-for-glyph, but its *palette* is
    still the design: sampling the ink colour per block keeps the generated page
    in the reference's colours without imitating its type.
    """
    arr = _as_array(ref_png)
    for b in blocks:
        if b.role == "cta":
            x0, y0, x1, y1 = b.bbox
            pad = 80
            win = (max(0, x0 - pad), max(0, y0 - pad),
                   min(STAGE_W, x1 + pad), min(STAGE_H, y1 + pad))
            # The label box is mostly label, so the fill must be sampled from a
            # wider window where the button dominates.  But on top of artwork
            # that window is contaminated, so prefer the saturated plate that
            # sits immediately around the label when there is one.
            wide = sample_fill(arr, win, background)
            plate = sample_plate_fill(arr, b.bbox, background)
            b.fill = plate if _sat(plate) > _sat(wide) + 40 else wide
            # Keep the label box (used to size the exclusion rect) and grow the
            # block to the real button so the traced art does not bake it in.
            b.meta["label_bbox"] = b.bbox
            solid = refine_button_bbox(arr, b.bbox, b.fill)
            if solid != tuple(b.bbox):
                # A solid fill region was found: the label is the minority colour
                # inside it, so measure contrast against the fill.
                b.color = sample_contrast(arr, b.bbox, b.fill)
                b.bbox = solid
            else:
                # No solid fill to flood: the button is an outline.  Its border
                # and label are the only ink, so measure the button from that,
                # and take the label colour from the label box itself.
                found = measure_button_bbox(arr, b.bbox, background)
                if found:
                    b.bbox = found
                    b.meta["outline"] = True
                b.color = sample_ink(arr, b.meta["label_bbox"], background)
                b.meta["border"] = b.color
        else:
            b.bbox = snap_to_ink(arr, b.bbox, background)
            b.runs = sample_runs(arr, b.bbox, b.text, background)
            b.color = b.runs[0][1] if len(b.runs) == 1 else None
    return blocks


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def _lum(c: tuple[int, int, int]) -> float:
    r, g, b = c
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """A rough WCAG contrast ratio between two colours."""
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 5.0) / (lo + 5.0)


def palette(blocks: list[Block], background: tuple[int, int, int]) -> dict:
    """A small design system (bg/ink/muted/accent/surface) from the reference.

    The reference's *colours* are the design, so they are sampled; its *type* is
    not reproduced.  The result is enough for a coherent page -- body ground,
    text, a muted tone and one accent -- without imitating the mockup.

    Sampling is not enough on its own: a design's most prominent headline can be
    a dark navy on a dark ground (it sat over a light hero panel), and using it
    as body ink makes the whole page unreadable.  So the sampled colours are
    only accepted when they actually contrast with the ground.
    """
    bg = tuple(int(v) for v in background)
    light = _lum(bg) >= 128
    neutral = (17, 24, 32) if light else (244, 255, 249)
    colors = [tuple(b.color) for b in blocks if b.color]
    fills = [tuple(b.fill) for b in blocks if b.fill]

    # Body ink: the most common block colour that is legible on the ground.
    legible = [c for c in colors if _contrast(c, bg) >= 4.5]
    ink = neutral
    if legible:
        counts: dict[tuple[int, int, int], int] = {}
        for c in legible:
            counts[c] = counts.get(c, 0) + 1
        ink = max(counts, key=lambda c: (counts[c], _contrast(c, bg)))

    # Accent: prefer the colour the calls to action are painted with, so the
    # buttons and the highlights agree.
    cta_fills = [tuple(b.fill) for b in blocks if b.role == "cta" and b.fill]
    sat = [c for c in colors + fills if _sat(c) >= 40 and _contrast(c, bg) >= 2.0]
    pool = cta_fills or sat
    accent = max(pool, key=_sat) if pool else ((14, 150, 100) if light else (25, 210, 130))

    toward = (0, 0, 0) if light else (255, 255, 255)
    muted = _mix(ink, bg, 0.38)
    if _contrast(muted, bg) < 3.0:                     # keep it readable
        muted = _mix(ink, bg, 0.2)
    card = _mix(bg, (255, 255, 255), 0.72 if light else 0.10)
    tint = _mix(bg, toward, 0.04)
    shadow = ("0 1px 2px rgba(15,23,42,.05), 0 12px 28px -16px rgba(15,23,42,.28)"
              if light else
              "0 1px 2px rgba(0,0,0,.5), 0 16px 36px -18px rgba(0,0,0,.85)")
    return {
        "light": light,
        "bg": bg,
        "ink": ink,
        "muted": muted,
        "accent": accent,
        "accent_ink": (6, 20, 14) if _lum(accent) > 140 else (255, 255, 255),
        "surface": _mix(bg, toward, 0.05 if light else 0.07),
        "card": card,
        "tint": tint,
        "shadow": shadow,
        "border": _mix(bg, ink, 0.16),
    }


# Sections, in the order they are laid out down the page.
SECTION_ORDER = ["header", "hero", "nav", "features", "testimonials",
                 "pricing", "contact", "footer", "other"]
KNOWN_SECTIONS = [s for s in SECTION_ORDER if s != "other"]
GRID_SECTIONS = {"features", "testimonials", "pricing"}
# How far apart two blocks can be (as a multiple of the taller block) and still
# belong to the same visual group when the model gave no usable section.
GROUP_GAP = 2.0


def _reading_order(blocks: list[Block]) -> list[Block]:
    """Sort by vertical position then horizontal -- how a person reads a page."""
    return sorted(blocks, key=lambda b: (round(b.bbox[1]), round(b.bbox[0])))


def _row_order(blocks: list[Block]) -> list[Block]:
    """Left to right within a row, rows top to bottom.

    For a row of buttons `_reading_order` is wrong: it sorts by top edge first,
    and two buttons drawn side by side are rarely aligned to the pixel, so the
    right-hand one wins and the pair comes out swapped.
    """
    rows: list[list[Block]] = []
    for b in sorted(blocks, key=lambda b: b.bbox[1]):
        for row in rows:
            if any(_overlaps(b, o) for o in row):
                row.append(b)
                break
        else:
            rows.append([b])
    return [b for row in rows for b in sorted(row, key=lambda b: b.bbox[0])]


def _is_eyebrow(b: Block) -> bool:
    """A short all-caps line: an eyebrow/kicker that marks a new section."""
    t = b.text.strip()
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 3 or len(t) > 52:
        return False
    return sum(1 for c in letters if c.isupper()) / len(letters) > 0.8


def _cluster_by_gap(blocks: list[Block]) -> list[list[Block]]:
    """Split a reading-ordered run into visual groups.

    A new group starts at a clear vertical gap, at an eyebrow/kicker line (the
    all-caps label a landing page puts above each section title), or at a brand
    line in the bottom quarter of the page (the footer bar starts there).  Real
    landing pages separate sections mostly with those labels, not with large
    whitespace, so gap alone collapses the whole page into one group.
    """
    if not blocks:
        return []
    page_bottom = max(b.bbox[3] for b in blocks)
    groups = [[blocks[0]]]
    for prev, b in zip(blocks, blocks[1:]):
        hp = prev.bbox[3] - prev.bbox[1]
        hb = b.bbox[3] - b.bbox[1]
        # Measure the gap against the *smaller* of the two rows.  Using the
        # taller one is too permissive: a short nav row above a big hero
        # headline would swallow the headline into the nav.
        h = max(min(hp, hb), 1.0)
        new = b.bbox[1] - prev.bbox[3] > GROUP_GAP * h
        if (not new and b.role == "brand" and prev.role != "brand"
                and b.bbox[1] > 0.8 * page_bottom):
            new = True
        if not new and _is_eyebrow(b) and not _is_eyebrow(prev) and len(groups[-1]) >= 2:
            new = True
        if new:
            groups.append([b])
        else:
            groups[-1].append(b)
    return groups


def _columns(blocks: list[Block]) -> list[list[Block]]:
    """Group a card grid into columns by horizontal overlap.

    A card grid reads in rows (`title1 title2 ... titleN` then the descriptions),
    so consecutive blocks are not the same card.  Blocks that share an x-range are
    the same column, which is what reconstructs one card per column.
    """
    cols: list[list[Block]] = []
    for b in sorted(blocks, key=lambda b: (b.bbox[0], b.bbox[1])):
        placed = False
        for col in cols:
            x0 = min(x.bbox[0] for x in col)
            x1 = max(x.bbox[2] for x in col)
            overlap = min(x1, b.bbox[2]) - max(x0, b.bbox[0])
            if overlap > 0.15 * max(1.0, min(x1 - x0, b.bbox[2] - b.bbox[0])):
                col.append(b)
                placed = True
                break
        if not placed:
            cols.append([b])
    cols.sort(key=lambda c: min(x.bbox[0] for x in c))
    for c in cols:
        c.sort(key=lambda b: b.bbox[1])
    return cols


def _infer_sections(blocks: list[Block]) -> list[tuple[str, list[Block]]]:
    """Name sections by position and eyebrow keywords when the model declared none.

    Landing pages separate sections with an all-caps eyebrow label above each
    title ("OUR SERVICES", "WHAT OUR CLIENTS SAY"), so the label is the strongest
    signal for what a group *is*.  Falls back to position: the first group with a
    headline is the hero, the last group is the footer, anything between is a
    feature section.
    """
    groups = _cluster_by_gap(_reading_order(blocks))
    if not groups:
        return []
    page_bottom = max(b.bbox[3] for b in blocks)
    out: list[tuple[str, list[Block]]] = []
    seen_hero = False
    # The top row is a header when it is mostly links/wordmark, not a title.
    # Splitting a fused top row: if the first group mixes a link row and a
    # headline, the row above the first headline is the header.
    if groups:
        g0 = groups[0]
        if len(g0) >= 2 and "headline" not in {g0[0].role}:
            split = None
            for i, b in enumerate(g0):
                if b.role in {"headline", "subhead"} and i >= 2:
                    split = i
                    break
            if split is not None and sum(1 for b in g0[:split] if _is_navish(b)) >= 1:
                groups[0] = g0[split:]
                groups.insert(0, g0[:split])
            elif "headline" not in {b.role for b in g0}:
                groups.pop(0)
                out.append(("header", g0))
    for i, g in enumerate(groups):
        roles = {b.role for b in g}
        eyebrow = next((b.text.lower() for b in g if _is_eyebrow(b)), "")
        name = ""
        for key, sect in (("testimonial", "testimonials"), ("review", "testimonials"),
                          ("client", "testimonials"), ("say", "testimonials"),
                          ("pricing", "pricing"), ("plan", "pricing"),
                          ("contact", "contact"), ("get in touch", "contact"),
                          ("reach", "contact"), ("serving", "contact"),
                          ("question", "contact"),
                          ("service", "features"), ("feature", "features"),
                          ("offer", "features"), ("choose", "features")):
            if key in eyebrow:
                name = sect
                break
        if not name:
            first_is_brand = g[0].role == "brand"
            # A headless group directly after the hero is the hero's own action
            # and trust row -- the buttons, the phone number, the badges.  It has
            # no eyebrow and no headline, so without this it becomes a stray
            # `features` section holding three badges in cards.
            tail_of_hero = (bool(out) and out[-1][0] == "hero"
                            and "headline" not in roles and not eyebrow
                            and (any(b.role == "cta" for b in g)
                                 or all(b.role in {"other", "cta"} for b in g)))
            if tail_of_hero:
                name = "hero"
            elif i == 0 and (roles & {"headline", "subhead", "cta"}):
                name = "hero"
            elif first_is_brand and g[0].bbox[1] > 0.75 * page_bottom:
                name = "footer"
            elif "headline" in roles and not seen_hero:
                name = "hero"
            else:
                name = "features"
        if name == "hero":
            seen_hero = True
        out.append((name, g))
    # Anything after the footer bar (a legal row, a tagline) is part of the
    # footer -- it must not become another feature section.
    for i in range(len(out) - 1, 0, -1):
        if out[i - 1][0] == "footer":
            out[i - 1][1].extend(out[i][1])
            del out[i]
    # A hero split across clusters (its copy, then its action/trust row) is one
    # section; the same for any name that repeats back to back.
    merged: list[tuple[str, list[Block]]] = []
    for name, group in out:
        if merged and merged[-1][0] == name:
            merged[-1][1].extend(group)
        else:
            merged.append((name, list(group)))
    return merged


def group_sections(blocks: list[Block]) -> list[tuple[str, list[Block]]]:
    """Ordered `[(section, [blocks])]` for the page's own copy.

    Prefers the model's `section`.  A block the model left unspecified is
    attached to the nearest declared section by vertical position; when the
    model declared nothing at all, the blocks are clustered by vertical gap and
    named by position (see `_infer_sections`).

    Two things make the model's names usable:

    * **A name is one section.**  The model tags *every* block, and at a given y
      the reading order can interleave two sections (a testimonial's author line
      beside the contact band), so merging only adjacent runs fragments one
      section into several.  Within a visual group every block of a name joins
      that name's section.
    * **A genuine band boundary still splits.**  A landing page can have two
      feature bands ("OUR SERVICES" and "WHY CHOOSE US"), both tagged `features`.
      Those are separate groups because the vertical-gap clustering separates
      them first; adjacent groups of the same name then merge back, so a section
      broken by a spurious gap is not split in two.
    """
    page = [b for b in blocks if is_page_text(b)]
    if not page:
        return []
    declared = [b for b in page if b.section in KNOWN_SECTIONS]
    if not declared:
        return _lift_bottom_nav(page, _infer_sections(page))

    order = _reading_order(page)
    declared_y = [(b, (b.bbox[1] + b.bbox[3]) / 2.0)
                  for b in order if b.section in KNOWN_SECTIONS]

    def name_of(b: Block) -> str:
        if b.section in KNOWN_SECTIONS:
            return b.section
        # An unspecified block joins the nearest declared block above it, else
        # the first declared one -- by vertical position.
        cy = (b.bbox[1] + b.bbox[3]) / 2.0
        above = [d for d, dy in declared_y if dy <= cy]
        return above[-1].section if above else declared_y[0][0].section

    # Every block of a name becomes that name's section: the model tags each
    # block, and at a given y two sections can interleave, so merging only
    # adjacent runs fragments one section into several.  A landing page with two
    # feature bands keeps them *inside* one section, rendered as two bands by
    # `_section_body` -- that is a composition question, not a structure one.
    by_name: dict[str, list[Block]] = {}
    for b in order:
        by_name.setdefault(name_of(b), []).append(b)

    groups = list(by_name.items())
    groups.sort(key=lambda sg: min(b.bbox[1] for b in sg[1]))
    return _lift_bottom_nav(page, groups)


def _lift_bottom_nav(page: list[Block],
                     groups: list[tuple[str, list[Block]]]
                     ) -> list[tuple[str, list[Block]]]:
    """Move a nav-link row at the page bottom into the footer.

    A landing page's footer often repeats the header nav ("Home", "Services", ...)
    and the model tags those links with whatever section it last saw -- frequently
    `contact`, because they sit right below the contact band.  Left there they
    render as a stray link row at the end of the contact section.  The footer links
    sit in the bottom band of the page beside the footer bar, so they belong to the
    footer: lift the run into it.
    """
    if not page or not groups:
        return groups
    names = {n for n, _ in groups}
    if "footer" not in names:
        return groups
    page_bottom = max(b.bbox[3] for b in page)
    page_top = min(b.bbox[1] for b in page)
    span = max(1.0, page_bottom - page_top)
    nav_ids = _nav_cta_ids(page)
    if not nav_ids:
        return groups

    footer_blocks = next(g for n, g in groups if n == "footer")
    # Where the footer bar starts: its topmost block.
    foot_top = min(b.bbox[1] for b in footer_blocks)
    lifted: list[Block] = []
    out: list[tuple[str, list[Block]]] = []
    for name, grp in groups:
        if name == "footer":
            continue
        keep = []
        for b in grp:
            # A nav link in the bottom 12% of the page and at/below the footer's
            # own top edge is a footer link, not part of this section.
            if (id(b) in nav_ids
                    and b.bbox[1] >= foot_top - 0.04 * span
                    and b.bbox[1] >= page_top + 0.8 * span):
                lifted.append(b)
            else:
                keep.append(b)
        if keep:
            out.append((name, keep))
    if not lifted:
        return groups
    # Re-emit in page order, footer last.
    out.sort(key=lambda sg: min(b.bbox[1] for b in sg[1]))
    footer_blocks = sorted(footer_blocks + lifted, key=lambda b: (round(b.bbox[1]), round(b.bbox[0])))
    out.append(("footer", footer_blocks))
    return out


def _inline(b: Block) -> str:
    """The block's inner HTML: escape the text, or emit one span per colour run."""
    if b.runs and len(b.runs) > 1:
        return "".join(
            f'<span style="color: {_hex(c)}">{html.escape(t)}</span>'
            for t, c in b.runs)
    return html.escape(b.text)


def _attr(value: str) -> str:
    return html.escape(value, quote=True)


def _is_navish(b: Block) -> bool:
    """A short `other` block in a nav/footer row is a link, not a paragraph."""
    return b.role == "other" and len(b.text) <= 32 and len(b.text.split()) <= 4


def _cta_label(b: Block, sub: Block | None = None) -> str:
    """A button's label, with a phone number that shares the plate on its own line.

    The reference's outline button is two lines -- "Call Now" over the number --
    and the model reports it as one string.  On one line the button is far wider
    than the design's.
    """
    t = b.text.strip()
    m = re.search(r"^(.*?)\s*(\(?\d[\d\-\s().]{6,}\d\)?)$", t)
    if m and m.group(1).strip() and m.group(2).strip() != t:
        return (f'<span class="cta-label">{html.escape(m.group(1).strip())}</span>'
                f'<span class="cta-sub">{html.escape(m.group(2).strip())}</span>')
    if sub is not None and sub.text.strip():
        return (f'<span class="cta-label">{html.escape(t)}</span>'
                f'<span class="cta-sub">{html.escape(sub.text.strip())}</span>')
    return _inline(b)


def _cta_sublabels(blocks: list[Block], ctas: list[Block]) -> dict[int, Block]:
    """A phone line drawn under a CTA belongs to the button it sits under.

    The model often reports the button's second line as its own block, so
    rendered as DOM it becomes an orphaned plain-text line under the button row
    (a vision review flagged exactly this on a real upload).  When a phone number
    is the only block directly below a button and shares its column, fold it into
    that button's label instead of emitting it as hero copy.
    """
    sub: dict[int, Block] = {}
    for b in blocks:
        if b in ctas or not _is_phone(b):
            continue
        host = None
        for c in ctas:
            cx0, cy0, cx1, cy1 = c.bbox
            overlap = min(cx1, b.bbox[2]) - max(cx0, b.bbox[0])
            width = max(1.0, min(cx1 - cx0, b.bbox[2] - b.bbox[0]))
            # `decorate` grows a CTA to its full plate, so a two-line button
            # *contains* its phone line rather than sitting above it: the box is
            # near the button's bottom edge, not below it.  Accept anywhere from
            # just inside the plate to a little under it.
            near = cy0 - 8 <= b.bbox[1] <= cy1 + 14
            if overlap >= 0.4 * width and near:
                if host is None or c.bbox[3] > host.bbox[3]:
                    host = c
        if host is not None:
            sub[id(host)] = b
    return sub


def _nav_cta_ids(blocks: list[Block]) -> set[int]:
    """Ids of `cta` blocks that are really nav links, not buttons.

    The vision model tags *every* link `cta`, so a nav row ("Home", "Services",
    "About") is indistinguishable from a button by role alone.  Two signals
    separate them, and both are needed:

    * **shape** -- a nav link is short (<= 2 words, <= 18 chars, no arrow).  An
      isolated short link is a button ("Call Now"); a longer phrase with an arrow
      is a button ("View All Services ->").
    * **row** -- the links come in runs of three or more short items sharing a
      row, where the one real button ("Book Service") sits at the row's end with
      a *solid fill*.  A solid-filled short CTA is a button even in that row.

    So: short AND in a link row AND (no solid button fill) => a nav link.
    """
    def short(b: Block) -> bool:
        t = b.text.strip()
        return (len(t) <= 18 and len(t.split()) <= 2
                and not any(ch in t for ch in "→»>"))

    def solid_button(b: Block) -> bool:
        # A real button carries a solid fill the tracer sampled; a nav link on a
        # busy row comes back as an outline with a contaminated fill.  The model
        # sets `outline` for the latter.
        return b.fill is not None and not b.meta.get("outline")

    ctas = [b for b in blocks if b.role == "cta"]
    ids: set[int] = set()
    for b in ctas:
        if not short(b):
            continue
        row = [o for o in ctas if o is not b and _overlaps(b, o)]
        if sum(1 for o in row if short(o)) >= 2 and not solid_button(b):
            ids.add(id(b))
    return ids


# Ids of `cta` blocks that are really nav links (not buttons), for the current
# build.  Set by `build_markup` from `_nav_cta_ids`; read by `_cta_html`.  This is
# a build-scoped context rather than a parameter because every section renderer
# (`_card_html`, `_band_html`, `_hero_html`, header, footer) would otherwise have
# to thread the same set through.  Thread-local so the value cannot leak between
# jobs if the worker pool is ever made concurrent.
_NAV_CTX = threading.local()


def _nav_links() -> set[int]:
    return getattr(_NAV_CTX, "ids", set())


def _cta_html(b: Block, href: str, cls: str = "cta", sub: Block | None = None) -> str:
    # A short link that belongs to a nav row is drawn as a plain link, not a
    # button: the model tags nav links `cta`, so rendering them as buttons turns
    # each nav/footer row into a stack of boxes.
    if id(b) in _nav_links():
        return f'<a class="navlink" href="{_attr(href)}">{_inline(b)}</a>'
    color = _hex(b.color or (255, 255, 255))
    label = _cta_label(b, sub)
    if b.meta.get("outline"):
        border = _hex(b.meta.get("border") or b.color or (24, 196, 124))
        style = f' style="color: {color}; border-color: {border}"'
        return f'<a class="{cls} outline" href="{_attr(href)}"{style}>{label}</a>'
    fill = _hex(b.fill or (24, 196, 124))
    style = f' style="background: {fill}; color: {color}"'
    return f'<a class="{cls}" href="{_attr(href)}"{style}>{label}</a>'


def _is_stars(b: Block) -> bool:
    """A star-rating line: only stars and spaces."""
    t = b.text.strip()
    return bool(t) and all(c in "★☆*·. 0123456789/()" for c in t) and any(c in "★☆*" for c in t)


def _card_html(col: list[Block], cta_href: str = "#top",
               kind: str = "", plain: bool = False) -> str:
    """One card: a title line plus any body lines that share its column.

    A testimonial is not a title+body card -- its body is the quote and its
    footer is the attribution -- so it gets a `blockquote` shape instead.
    """
    if kind == "testimonials":
        body = [b for b in col if b.role != "cta"]
        stars = [b for b in body if _is_stars(b)]
        body = [b for b in body if b not in stars]
        quote = max(body, key=lambda b: len(b.text), default=None)
        rest = [b for b in body if b is not quote]
        parts = []
        if stars:
            parts.append(f'<p class="stars" aria-label="5 out of 5">{_inline(stars[0])}</p>')
        if quote is not None:
            parts.append(f"<blockquote>{_inline(quote)}</blockquote>")
        byline = " · ".join(_inline(b) for b in rest)
        if byline:
            parts.append(f'<p class="byline">{byline}</p>')
        for b in col:
            if b.role == "cta":
                parts.append(_cta_html(b, cta_href, "cta small"))
        return ('<figure class="card quote">\n        '
                + "\n        ".join(parts) + "\n      </figure>")
    title_done = False
    parts = []
    for b in col:
        if b.role == "cta":
            parts.append(_cta_html(b, cta_href, "cta small"))
        elif not title_done:
            parts.append(f"<h3>{_inline(b)}</h3>")
            title_done = True
        else:
            parts.append(f"<p>{_inline(b)}</p>")
    cls = "card plain" if plain else "card"
    return f'<div class="{cls}">\n        ' + "\n        ".join(parts) + "\n      </div>"


def _overlaps(a: Block, b: Block) -> bool:
    """Do two blocks share a text row (their y-ranges overlap by half a line)?"""
    top, bottom = max(a.bbox[1], b.bbox[1]), min(a.bbox[3], b.bbox[3])
    if bottom <= top:
        return False
    return (bottom - top) > 0.5 * min(a.bbox[3] - a.bbox[1], b.bbox[3] - b.bbox[1])


def _x_overlaps(a: Block, b: Block) -> bool:
    return min(a.bbox[2], b.bbox[2]) - max(a.bbox[0], b.bbox[0]) > 0


def _has_below(b: Block, others: list[Block], gap: float = 44.0) -> bool:
    """Is there copy in `b`'s own column just under it?

    Then `b` heads a column rather than acting as a section-level link.
    """
    for o in others:
        if o is b or not _x_overlaps(o, b):
            continue
        if -2.0 <= o.bbox[1] - b.bbox[3] < gap:
            return True
    return False


def _action(b: Block, href: str) -> str:
    """A link that sits beside a section title ("View all services ->")."""
    if b.role == "cta":
        return _cta_html(b, href, "cta small")
    return f'<a class="section-action" href="{_attr(href)}">{_inline(b)}</a>'


def _section_body(name: str, blocks: list[Block], cta_href: str) -> str:
    """The inner markup of one non-hero section.

    A section can hold more than one *band*: the model names both "OUR SERVICES"
    and "WHY CHOOSE US" `features`, and they are one section with two title+grid
    bands.  Each band is rendered on its own -- an eyebrow, a title row with any
    action link, then its cards -- so the page reads as a designed page rather
    than a wall of paragraphs.
    """
    bands = _cluster_by_gap(_reading_order(blocks))
    out = [b for b in (_band_html(name, band, cta_href) for band in bands) if b]
    return "\n    ".join(out)


def _balanced_cols(n: int) -> int:
    """A column count that fills the last row instead of leaving it ragged.

    A greedy `auto-fit` leaves a four-card band as 3+1, so the fourth card sits
    alone on a second row -- a defect a vision review flagged on a real upload.
    Prefer a count whose last row is as full as possible, and among those the one
    with the fewest rows (2-4 columns; a small band stays on one row).
    """
    if n <= 1:
        return 1
    best, best_key = n, None
    for k in range(2, min(4, n) + 1):
        rows = -(-n // k)
        fill = n - k * (rows - 1)      # cards on the last (partial) row
        key = (rows, -fill, -k)
        if best_key is None or key < best_key:
            best, best_key = k, key
    return best


def _band_html(name: str, band: list[Block], cta_href: str) -> str:
    """One title+grid band inside a section."""
    eyebrow = next((b for b in band if _is_eyebrow(b)), None)
    rest = [b for b in band if b is not eyebrow]

    # The band's title is its topmost headline -- but only when it sits clearly
    # above the rest.  In a bare card grid the top row *is* card titles, and
    # promoting one of them to the section heading would drop it from its card.
    headings = [b for b in rest if b.role in {"headline", "subhead"}]
    lead = None
    if headings:
        first, others = headings[0], headings[1:]
        if not others or first.bbox[3] <= min(h.bbox[1] for h in others):
            lead = first
    # A section action ("View all services ->") sits at the title's row and has
    # nothing under it.  A *column heading* at the same row (a contact panel's
    # "Get in Touch") has its own body below it, so it must stay in its column --
    # hoisting it to the title row crams the panel into the section header.
    head_row = [b for b in rest
                if b is not lead and lead is not None and _overlaps(b, lead)
                and (b.role == "cta" or _is_navish(b))
                and not _has_below(b, rest)]
    cards_src = [b for b in rest if b is not lead and b not in head_row]

    parts: list[str] = []
    if eyebrow is not None:
        parts.append(f'<p class="eyebrow">{_inline(eyebrow)}</p>')
    if lead is not None or head_row:
        title = (f'<h2 class="section-title">{_inline(lead)}</h2>'
                 if lead is not None else "")
        actions = "".join(_action(b, cta_href) for b in head_row)
        parts.append(f'<div class="section-head">{title}{actions}</div>')

    if cards_src:
        cols = _columns(cards_src)
        if name in GRID_SECTIONS:
            # A band of one-liners is not a card grid: boxes around two words
            # each read as heavy chrome, so those items get a rule instead.  An
            # item with a description of its own keeps the card.
            compact = (len(cols) >= 3
                       and all(len(c) == 1 and len(c[0].text) <= 40 for c in cols))
            cards = [_card_html(c, cta_href, name, plain=compact) for c in cols]
            parts.append(f'<div class="cards{" compact" if compact else ""}" '
                         f'style="--cards:{_balanced_cols(len(cols))}">\n      '
                         + "\n      ".join(cards) + "\n    </div>")
        else:
            # A non-grid band (contact details, a two-column blurb) keeps its
            # columns but not the card chrome.
            cells = []
            for col in cols:
                # A run of nav links (a footer's link row the model grouped into
                # this band) is one horizontal nav row, not a stack of items.
                rows: list[str] = []
                run: list[Block] = []

                def _flush() -> None:
                    if run:
                        rows.append('<nav class="navlink-row">'
                                    + "".join(_cta_html(x, cta_href) for x in run)
                                    + "</nav>")
                        run.clear()

                for i, b in enumerate(col):
                    if b.role == "cta" and id(b) in _nav_links():
                        run.append(b)
                        continue
                    _flush()
                    rows.append(_cta_html(b, cta_href, "cta small") if b.role == "cta"
                                else (f"<h3>{_inline(b)}</h3>"
                                      if i == 0 and b.role in {"headline", "subhead", "brand"}
                                      else f"<p>{_inline(b)}</p>"))
                _flush()
                body = "\n        ".join(rows)
                cells.append(f'<div class="col">\n        {body}\n      </div>')
            parts.append('<div class="cols">\n      '
                         + "\n      ".join(cells) + "\n    </div>")
    return "\n    ".join(parts)


def _drop_artwork_labels(blocks: list[Block]) -> list[Block]:
    """Remove a hero illustration's own captions from the hero's DOM copy.

    A hero is often a copy column beside an illustration (a device mockup, a
    diagram).  The illustration carries its own small labels -- step numbers,
    "Generate", "Time", a logo on the device screen.  The vision model tags them
    all `part: page` on some uploads, so they are emitted as DOM paragraphs and
    land in the copy column as stray single words between the headline and the
    lede ("Generate", "Time", "Refine and grow meaning" on the anthotype upload).

    A hero's copy reads as a single column: the headline, then the subhead under
    it.  A *short* `other`/`brand` line is a label rather than copy when either

      (a) its vertical band overlaps the headline or the subhead (with a
          line-height of slack -- a caption drawn beside the headline is often a
          few px off its row), or
      (b) it sits fully clear of the running copy's right edge (an illustration
          legend drawn along the bottom of the artwork).

    The real copy never interleaves a stray word with its own headline, so the
    overlap test is safe.  A `brand` block is deliberately NOT an anchor: on an
    upload whose hero is a device mockup the logo drawn on the screen comes back
    `role: brand`, and using it as the column edge would swallow the illustration.
    """
    if not blocks:
        return blocks
    copy = [b for b in blocks if b.role in {"headline", "subhead"}]
    if not copy:
        return blocks
    # The copy column's right edge, from the running copy only (the lede or the
    # tagline; a device-screen logo is `brand`, not copy).
    run = [b for b in blocks if b.role in {"lede", "tagline"}] or copy
    col_right = max(b.bbox[2] for b in run)
    hero_top = min(c.bbox[1] for c in copy)

    def is_label(b: Block) -> bool:
        if b.role not in {"other", "brand"}:
            return False
        if len(b.text) > 60:
            return False
        x0, y0, x1, y1 = b.bbox
        # (a) drawn beside the headline / subhead: a caption overlapping a copy
        #     row (with a line-height of slack -- a caption is often a few px off).
        by = (y0 + y1) / 2.0
        for c in copy:
            slack = 0.6 * max(8.0, c.bbox[3] - c.bbox[1])
            if c.bbox[1] - slack <= by <= c.bbox[3] + slack:
                return True
        # (b) an illustration legend: a short line sitting fully clear of the copy
        #     column's right edge, inside the hero's own vertical band.
        return x0 >= col_right - 4 and y0 >= hero_top - 40

    kept = [b for b in blocks if not is_label(b)]
    # Never empty the hero: if the rule would remove everything but one line,
    # it has misfired (there was no real copy column to anchor against).
    return kept if len(kept) >= 2 else blocks


def _hero_html(blocks: list[Block], cta_href: str,
               sublabels: dict[int, Block] | None = None) -> str:
    """The hero's copy: eyebrow, headline, subhead, actions, a trust row.

    Grouping the calls to action and the short trust badges into their own rows
    is what makes the hero read as a hero rather than a stack of paragraphs.
    """
    # Buttons sharing a row are emitted left to right, as they are drawn.  The
    # reading order sorts by top edge first, and a solid button and an outline one
    # beside it rarely share a top edge (a pixel or two apart is enough), so it
    # would swap them.
    blocks = _drop_artwork_labels(blocks)
    subs = sublabels or {}
    # A phone line that is a button's second line is not hero copy: drop it here
    # so it cannot render as an orphaned paragraph under the button row.
    sub_ids = {id(p) for p in subs.values()}
    blocks = [b for b in blocks if id(b) not in sub_ids]
    cta_blocks = _row_order([b for b in blocks if b.role == "cta"])
    # Short lines that share a row are trust badges, not copy.  The model's role
    # for them is not stable (the same reference came back `other` on one run and
    # `tagline` on the next), so detect them by shape, not by role.
    short = [b for b in blocks
             if b.role in {"other", "tagline"} and len(b.text) <= 40]
    badges = _row_order([b for b in short
                         if sum(1 for o in short if o is not b and _overlaps(b, o)) >= 1])

    # The rows are emitted where they actually sit.  Appending the buttons at the
    # end puts them *below* a fine-print line that the reference drew under them
    # ("Open source · Community driven · Powered by Antseed"), which then reads as
    # a caption for the buttons.
    out: list[str] = []
    actions_done = badges_done = False
    for b in _reading_order(blocks):
        if b.role == "cta":
            if not actions_done:
                row = "".join(_cta_html(c, cta_href, sub=subs.get(id(c)))
                              for c in cta_blocks)
                out.append(f'<div class="hero-actions">{row}</div>')
                actions_done = True
            continue
        if b in badges:
            if not badges_done:
                row = "".join(f'<span class="badge">{_inline(x)}</span>' for x in badges)
                out.append(f'<ul class="hero-badges">{row}</ul>')
                badges_done = True
            continue
        if b.role == "headline":
            out.append(f'<h1>{_inline(b)}</h1>')
        elif b.role == "subhead":
            out.append(f'<p class="subhead">{_inline(b)}</p>')
        elif b.role == "brand":
            out.append(f'<span class="brand">{_inline(b)}</span>')
        elif _is_eyebrow(b):
            out.append(f'<p class="eyebrow">{_inline(b)}</p>')
        else:
            out.append(f'<p class="lede">{_inline(b)}</p>')
    if cta_blocks and not actions_done:
        row = "".join(_cta_html(b, cta_href, sub=subs.get(id(b))) for b in cta_blocks)
        out.append(f'<div class="hero-actions">{row}</div>')
    if badges and not badges_done:
        row = "".join(f'<span class="badge">{_inline(b)}</span>' for b in badges)
        out.append(f'<ul class="hero-badges">{row}</ul>')
    return "\n      ".join(out)


def _is_phone(b: Block) -> bool:
    """A phone number, not a nav link -- it belongs beside the header button."""
    t = b.text.strip()
    digits = sum(c.isdigit() for c in t)
    return len(t) >= 7 and digits >= 6 and all(c in "0123456789+-() ." for c in t)


def _tel(text: str) -> str:
    return "tel:" + "".join(c for c in text if c.isdigit() or c == "+")


def _header_html(brand: Block | None, links: list[Block], cta_href: str) -> str:
    """Brand, the nav, and the header actions -- three separate groups.

    Grouping them (rather than one flex row of everything) is what lets the
    stylesheet put the brand left, the nav centred and the phone + button right,
    which is how the references are drawn.
    """
    brand_html = (f'<a class="brand" href="#top">{_inline(brand)}</a>' if brand
                  else '<a class="brand" href="#top">Home</a>')
    # A header `cta` in a nav row renders as a plain link (`_cta_html` consults
    # the nav-link set); the real button and the phone render as actions.
    nav = [b for b in links
           if not _is_phone(b) and (b.role != "cta" or id(b) in _nav_links())]
    actions = sorted((b for b in links
                      if _is_phone(b) or (b.role == "cta" and id(b) not in _nav_links())),
                     key=_is_phone)          # the phone sits before the button
    nav_html = "".join(
        f'<a href="{_attr(cta_href)}">{_inline(b)}</a>' for b in nav)
    act_html = "".join(
        f'<a class="phone" href="{_attr(_tel(b.text))}">{_inline(b)}</a>'
        if _is_phone(b) else _cta_html(b, cta_href, "cta small")
        for b in actions)

    out = [f'<div class="wrap">\n      {brand_html}']
    if nav_html:
        out.append(f'      <nav class="site-nav" aria-label="Primary">{nav_html}</nav>')
    if act_html:
        out.append(f'      <div class="header-actions">{act_html}</div>')
    out.append("    </div>")
    return "\n".join(out)


def _stable_id(name: str, used: dict[str, int]) -> str:
    """A unique in-page id for a section (`features`, `features-2`, ...)."""
    used[name] = used.get(name, 0) + 1
    return name if used[name] == 1 else f"{name}-{used[name]}"


def build_markup(sections: list[tuple[str, list[Block]]],
                 cta_href: str) -> str:
    """The page's body markup: a header, a hero, the sections, a footer.

    Section names may repeat, so every section gets a unique id and each CTA
    links to a real anchor on the page (never `#`).
    """
    parts: list[str] = []
    used: dict[str, int] = {}
    # Classify the CTAs once for the whole build: a short `cta` in a row with two
    # or more other short `cta`s is a nav link, not a button (see `_nav_cta_ids`).
    # `_cta_html` reads this to render nav rows as links instead of button stacks.
    _NAV_CTX.ids = _nav_cta_ids([b for _, g in sections for b in g])

    header = [(n, g) for n, g in sections if n in ("header", "nav")]
    header_blocks = [b for _, g in header for b in g]
    if header_blocks:
        brand = next((b for b in header_blocks if b.role == "brand"), None)
        links = [b for b in header_blocks
                 if b is not brand and (_is_navish(b) or b.role == "cta")]
        parts.append('<header class="site-header" id="top">\n    '
                     + _header_html(brand, links, cta_href) + "\n  </header>")

    hero_groups = [(n, g) for n, g in sections if n == "hero"]
    hero = [b for _, g in hero_groups for b in g]
    if hero:
        hero_ctas = _row_order([b for b in hero if b.role == "cta"])
        parts.append('<section class="hero" id="hero">\n      '
                     '<div class="hero-art" aria-hidden="true"><!--ART--></div>\n'
                     '      <div class="wrap hero-copy">\n      '
                     + _hero_html(hero, cta_href, _cta_sublabels(hero, hero_ctas))
                     + "\n      </div>\n    </section>")
    middle = []
    for name, blocks in sections:
        if name in ("header", "nav", "hero", "footer"):
            continue
        sid = _stable_id(name, used)
        body = _section_body(name, blocks, cta_href)
        if not body:
            continue
        middle.append(f'<section class="section sec-{name}" id="{sid}">\n'
                      f'    <div class="wrap">\n    {body}\n    </div>\n  </section>')
    if middle:
        parts.append('<main id="main">\n  ' + "\n  ".join(middle) + "\n  </main>")

    footer = [b for name, g in sections if name == "footer" for b in g]
    if footer:
        parts.append('<footer class="site-footer" id="footer">\n    '
                     '<div class="wrap">\n      '
                     + _footer_html(footer, cta_href) + "\n    </div>\n  </footer>")
    return "\n  ".join(parts)


def _footer_html(blocks: list[Block], cta_href: str) -> str:
    """The footer bar: brand, a nav row, and the legal/meta lines.

    A reference footer is a *bar* -- brand on the left, the repeated nav links,
    then the address and the legal line.  Emitting every block as an equal sibling
    turns it into a wall of links with no hierarchy, so the parts are grouped: the
    brand, one nav row, and the rest as small print.
    """
    blocks = sorted(blocks, key=lambda b: (round(b.bbox[1]), round(b.bbox[0])))
    brand = next((b for b in blocks if b.role == "brand"), None)
    links = [b for b in blocks if id(b) in _nav_links()]
    cta = next((b for b in blocks if b.role == "cta" and id(b) not in _nav_links()), None)
    rest = [b for b in blocks if b is not brand and b not in links and b is not cta]

    out: list[str] = []
    if brand is not None:
        out.append(f'<div class="footer-brand">'
                   f'<a class="brand" href="#top">{_inline(brand)}</a></div>')
    if links:
        nav = "".join(f'<a href="{_attr(cta_href)}">{_inline(b)}</a>' for b in links)
        out.append(f'<nav class="footer-nav" aria-label="Footer">{nav}</nav>')
    if rest or cta:
        bits = []
        if cta is not None:
            bits.append(_cta_html(cta, cta_href, "cta small"))
        for b in rest:
            cls = "footer-link" if _is_navish(b) else "footer-note"
            if cls == "footer-link":
                bits.append(f'<a class="{cls}" href="#top">{_inline(b)}</a>')
            else:
                bits.append(f'<p class="{cls}">{_inline(b)}</p>')
        out.append('<div class="footer-meta">' + "\n        ".join(bits) + "</div>")
    return "\n      ".join(out)


def cta_target(sections: list[tuple[str, list[Block]]],
               markup: str) -> str:
    """The CTA's destination: a real anchor that exists on the generated page.

    The reference only specifies the button's *appearance*, so there is no real
    URL to recover.  Linking to the most relevant section that was actually
    emitted is always valid -- unlike the poster's dead `href="#"`.
    """
    ids = set(re.findall(r'\bid="([^"]+)"', markup))
    names = [s for s, _ in sections]
    for want in ("contact", "features", "testimonials", "pricing"):
        if want in names and want in ids:
            return f"#{want}"
    if "hero" in ids:
        return "#hero"
    if "main" in ids:
        return "#main"
    return "#top"


def hero_band(sections: list[tuple[str, list[Block]]]) -> list[int] | None:
    """The mockup's vertical slice that the hero backdrop should show.

    The traced artwork is the *whole* mockup.  Spliced into the hero unchanged it
    shows the section below the hero too -- the next section's cards, icons and
    eyebrow bleed into the backdrop and read as clutter behind the copy.  The
    backdrop is the hero's own band: from the top of the mockup (a hero near the
    top is a full-bleed banner, so the art above the copy is part of it) down to
    where the next section starts.
    """
    hero = [b for n, g in sections if n == "hero" for b in g]
    if not hero:
        return None
    top = min(b.bbox[1] for b in hero)
    bottom = max(b.bbox[3] for b in hero)
    below = [b.bbox[1] for n, g in sections
             if n not in ("header", "nav", "hero", "footer") for b in g]
    y1 = min(below) if below else min(STAGE_H, bottom + max(60.0, bottom - top))
    y0 = 0 if top < STAGE_H * 0.5 else max(0.0, top - (bottom - top))
    y1 = min(STAGE_H, max(y0 + 40.0, y1))
    return [int(round(y0)), int(round(y1))]


def build_content(sections: list[tuple[str, list[Block]]], name: str) -> dict:
    blocks = [b for _, group in sections for b in group]
    headline = next((b for b in blocks if b.role == "headline"), None)
    tagline = next((b for b in blocks if b.role == "tagline"), None)
    cta = next((b for b in blocks if b.role == "cta"), None)
    title = headline.text if headline else f"{name} — coming soon"
    # Two passes: build the sections first so the CTA can link to a real anchor
    # that the markup actually created, then build the markup with that target.
    sections = [(s, _reading_order(g)) for s, g in sections]
    probe = build_markup(sections, "#top")
    href = cta_target(sections, probe)
    return {
        "title": title,
        "description": tagline.text if tagline else "Built from a design reference.",
        "cta": cta.text if cta else "",
        "cta_href": href,
        "stage": [STAGE_W, STAGE_H],
        "hero_band": hero_band(sections),
        "sections": [s for s, _ in sections],
        "markup": build_markup(sections, href),
    }


def build_page_css(palette_: dict) -> str:
    """The generated site's stylesheet: normal flow, responsive, role-based scale."""
    p = palette_
    scheme = "light" if p["light"] else "dark"
    return f"""/* Generated by Anthotype Studio.  A real website: flow layout, responsive,
   role-based type scale.  No absolute positioning, no fixed stage. */
:root {{
  color-scheme: {scheme};
  --bg: {_hex(p['bg'])};
  --ink: {_hex(p['ink'])};
  --muted: {_hex(p['muted'])};
  --accent: {_hex(p['accent'])};
  --accent-ink: {_hex(p['accent_ink'])};
  --surface: {_hex(p['surface'])};
  --card: {_hex(p['card'])};
  --tint: {_hex(p['tint'])};
  --shadow: {p['shadow']};
  --border: {_hex(p['border'])};
  --maxw: 1140px;
  --pad: clamp(20px, 5vw, 32px);
  --section-y: clamp(64px, 9vw, 112px);
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scroll-behavior: smooth; }}
body {{
  background: var(--bg); color: var(--ink);
  font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.6; -webkit-font-smoothing: antialiased; text-rendering: optimizeLegibility;
}}
h1, h2, h3 {{ line-height: 1.12; letter-spacing: -0.022em; text-wrap: balance; }}
p {{ text-wrap: pretty; }}
a {{ color: inherit; }}
.wrap {{ width: 100%; max-width: var(--maxw); margin: 0 auto; padding: 0 var(--pad); }}
.muted, .lead {{ color: var(--muted); }}
:focus-visible {{ outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 4px; }}

/* ---- header ------------------------------------------------------------- */
.site-header {{
  position: sticky; top: 0; z-index: 20;
  background: color-mix(in srgb, var(--bg) 88%, transparent);
  backdrop-filter: saturate(1.4) blur(10px);
  border-bottom: 1px solid var(--border);
}}
/* Brand left, nav centred, actions right -- the arrangement a real site uses. */
.site-header .wrap {{
  display: grid; grid-template-columns: auto 1fr auto;
  align-items: center; gap: clamp(16px, 3vw, 40px);
  min-height: 72px;
}}
.brand {{
  font-weight: 600; font-size: 18px; letter-spacing: -0.02em;
  text-decoration: none; white-space: nowrap;
}}
.site-nav {{ display: flex; align-items: center; justify-content: center; gap: clamp(14px, 2.2vw, 30px); flex-wrap: wrap; }}
.site-nav a {{
  color: var(--muted); text-decoration: none; font-size: 15px;
  padding: 6px 0; border-bottom: 2px solid transparent;
  transition: color .15s ease, border-color .15s ease;
}}
.site-nav a:hover {{ color: var(--ink); border-bottom-color: var(--accent); }}
/* A `cta` the model tagged on a nav row renders as a plain link, not a button. */
.navlink {{
  color: var(--muted); text-decoration: none; font-size: 15px;
  transition: color .15s ease;
}}
.navlink:hover {{ color: var(--ink); }}
.navlink-row {{
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px 20px;
}}
.site-footer .navlink {{ font-size: 14.5px; }}
.header-actions {{
  display: flex; align-items: center; gap: clamp(10px, 1.6vw, 18px);
  justify-self: end;
}}
.header-actions .phone {{
  color: var(--ink); text-decoration: none; font-size: 15px; font-weight: 500;
  white-space: nowrap;
}}
@media (max-width: 820px) {{
  .site-header .wrap {{ grid-template-columns: auto auto; justify-content: space-between; }}
  .site-nav {{ grid-column: 1 / -1; justify-content: flex-start; order: 3; }}
}}

/* ---- hero --------------------------------------------------------------- */
.hero {{ position: relative; overflow: hidden; border-bottom: 1px solid var(--border); }}
.hero-art {{ position: absolute; inset: 0; z-index: 0; }}
.hero-art svg {{ width: 100%; height: 100%; display: block; }}
/* A scrim over the artwork so the copy keeps contrast whatever the art does.
   It holds the page ground across the copy column, then releases the art
   abruptly on the right.  Two earlier versions were wrong in opposite ways: the
   first faded too slowly (~86% ground out to two-thirds of the width), washing
   the traced art to near-white and reading as an empty panel; a later, very
   soft version let the lede sit over the photograph and a review called the
   body copy unreadable.  This keeps the copy legible *and* leaves the art a
   real image on the right. */
.hero-art::after {{
  content: ""; position: absolute; inset: 0;
  background: linear-gradient(96deg,
    color-mix(in srgb, var(--bg) 95%, transparent) 0%,
    color-mix(in srgb, var(--bg) 88%, transparent) 36%,
    color-mix(in srgb, var(--bg) 82%, transparent) 52%,
    color-mix(in srgb, var(--bg) 14%, transparent) 72%, transparent 88%);
}}
.hero-copy {{
  position: relative; z-index: 1; display: grid; gap: clamp(14px, 2vw, 22px);
  justify-items: start; align-content: center;
  padding-top: clamp(80px, 12vw, 140px); padding-bottom: clamp(80px, 12vw, 140px);
  min-height: clamp(460px, 70vh, 680px);
}}
/* The copy stays in the scrim's strong end: the column is capped, but the block
   itself keeps the page's own gutter so the hero reads left-aligned. */
.hero-copy > * {{ max-width: min(100%, 520px); }}
.hero h1 {{ font-size: clamp(36px, 5.6vw, 60px); font-weight: 600; }}
.hero .subhead {{ font-size: clamp(18px, 2.4vw, 27px); font-weight: 600; }}
.hero .lede {{ font-size: clamp(16px, 1.7vw, 20px); color: var(--muted); }}
.hero .eyebrow {{ margin-bottom: 2px; }}
.hero .brand {{ font-size: 20px; font-weight: 600; }}
.hero-actions {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 6px; }}
.hero-badges {{
  list-style: none; display: flex; flex-wrap: wrap; gap: 10px 20px;
  margin-top: 18px; color: var(--muted); font-size: 14px;
}}
.hero-badges .badge {{ display: inline-flex; align-items: center; gap: 8px; }}
.hero-badges .badge::before {{
  content: ""; width: 7px; height: 7px; border-radius: 50%;
  background: var(--accent); flex: none;
}}

/* ---- sections ----------------------------------------------------------- */
.section {{ padding: var(--section-y) 0; border-bottom: 1px solid var(--border); }}
.section:nth-of-type(even) {{ background: var(--tint); }}
.section > .wrap {{ display: grid; gap: clamp(26px, 4vw, 44px); }}
.section-head {{
  display: flex; align-items: end; justify-content: space-between;
  gap: 20px; flex-wrap: wrap;
}}
.section-title {{ font-size: clamp(26px, 3.8vw, 42px); font-weight: 600; max-width: 22ch; }}
.section-action {{
  color: var(--accent); text-decoration: none; font-weight: 500; font-size: 15px;
  white-space: nowrap; padding-bottom: 4px;
}}
.section-action:hover {{ text-decoration: underline; text-underline-offset: 4px; }}
.eyebrow {{
  text-transform: uppercase; letter-spacing: 0.16em;
  font-size: 12.5px; font-weight: 600; color: var(--accent);
}}
.lead {{ font-size: clamp(16px, 1.6vw, 19px); max-width: 68ch; }}

/* ---- cards -------------------------------------------------------------- */
.cards {{
  display: grid; gap: clamp(14px, 1.6vw, 18px);
  /* `--cards` is set per band to a count that fills the last row; a greedy
     `auto-fit` leaves a 4-card band as 3+1, with the last card stranded.  The
     media queries below take over on narrow screens. */
  grid-template-columns: repeat(var(--cards, 3), minmax(0, 1fr));
}}
@media (max-width: 900px) {{ .cards {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} }}
@media (max-width: 560px) {{ .cards {{ grid-template-columns: 1fr; }} }}
.card {{
  background: var(--card); border: 1px solid var(--border);
  border-radius: 14px; padding: clamp(18px, 1.8vw, 22px);
  display: grid; gap: 8px; align-content: start;
  box-shadow: var(--shadow);
  transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease;
}}
.card:hover {{
  transform: translateY(-3px); border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
  box-shadow: 0 16px 36px -18px color-mix(in srgb, var(--accent) 55%, transparent);
}}
.card h3 {{ font-size: 16.5px; font-weight: 600; }}
.card .lead, .card p {{ color: var(--muted); font-size: 14.5px; line-height: 1.5; }}
/* A band of one-liners (a "why choose us" row) is not a card grid: a marker
   and a rule reads cleaner than six boxes around two words each. */
.cards.compact {{ gap: clamp(18px, 2.4vw, 34px); }}
.card.plain {{
  background: none; border: 0; box-shadow: none; padding: 0;
  border-top: 2px solid var(--accent); padding-top: 14px; border-radius: 0;
}}
.card.plain:hover {{ transform: none; box-shadow: none; border-color: var(--accent); }}
.card.quote {{ display: flex; flex-direction: column; gap: 16px; }}
.card.quote blockquote {{
  font-size: clamp(15px, 1.5vw, 17px); line-height: 1.6; color: var(--ink);
  text-wrap: pretty;
}}
.card.quote blockquote::before {{ content: "\\201C"; color: var(--accent); }}
.card.quote blockquote::after {{ content: "\\201D"; color: var(--accent); }}
.card.quote .stars {{ color: var(--accent); letter-spacing: 2px; font-size: 14px; }}
.card.quote .byline {{
  margin-top: auto; color: var(--muted); font-size: 14px; font-weight: 500;
}}

/* ---- plain columns (contact details, blurbs) ---------------------------- */
.cols {{
  display: grid; gap: clamp(24px, 4vw, 56px);
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 280px), 1fr));
}}
.col {{ display: grid; gap: 10px; align-content: start; }}
.col h3 {{ font-size: clamp(20px, 2.4vw, 26px); font-weight: 600; }}
.col p {{ color: var(--muted); font-size: 15.5px; max-width: 52ch; }}

/* ---- buttons ------------------------------------------------------------ */
.cta {{
  display: inline-flex; align-items: center; justify-content: center; gap: 10px;
  padding: 14px 28px; border-radius: 12px; text-decoration: none;
  background: var(--accent); color: var(--accent-ink);
  font-weight: 600; font-size: 16px; width: fit-content;
  border: 2px solid transparent; transition: filter .15s ease, transform .15s ease;
}}
.cta:hover {{ filter: brightness(1.07); transform: translateY(-1px); }}
.cta.outline {{ background: transparent; border: 2px solid var(--accent); }}
.cta.small {{ padding: 9px 18px; font-size: 15px; }}
/* A button whose plate carries two lines (a label over a phone number): the
   plate is a flex row, so the two lines need the axis turned. */
.cta:has(.cta-sub) {{ flex-direction: column; align-items: flex-start; gap: 0; }}
.cta-label, .cta-sub {{ display: block; line-height: 1.25; }}
.cta-sub {{ font-size: .82em; font-weight: 500; opacity: .85; }}

/* ---- footer ------------------------------------------------------------- */
.site-footer {{ padding: clamp(40px, 6vw, 64px) 0; }}
.site-footer .wrap {{
  display: flex; flex-wrap: wrap; gap: 18px 36px;
  align-items: center; justify-content: space-between; color: var(--muted);
  font-size: 14.5px;
}}
.footer-brand {{ display: flex; align-items: center; }}
.site-footer .brand {{ font-size: 16px; color: var(--ink); }}
.footer-nav {{
  display: flex; flex-wrap: wrap; align-items: center; gap: 10px 22px;
}}
.footer-nav a {{ color: var(--muted); text-decoration: none; transition: color .15s ease; }}
.footer-nav a:hover {{ color: var(--ink); }}
.footer-meta {{
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px 20px;
  justify-content: flex-end;
}}
.footer-meta .footer-note {{ color: var(--muted); }}
.footer-meta .footer-link {{ color: var(--muted); text-decoration: none; }}
.footer-meta .footer-link:hover {{ color: var(--ink); }}
.site-footer a:hover {{ color: var(--ink); }}

@media (max-width: 620px) {{
  .hero-copy {{ min-height: 0; }}
  .section-head {{ align-items: start; }}
}}

@media (prefers-reduced-motion: reduce) {{
  *, *::before, *::after {{ transition: none !important; animation: none !important; }}
  html {{ scroll-behavior: auto; }}
}}
"""


# A block the model called `other` must be at least this big to be page copy
# rather than a caption inside the artwork.  The model's `part` is the primary
# signal; this is only a backstop for a stray fragment.
#
# It is deliberately small.  For a *website* the cost of the two errors is not
# symmetric: emitting a stray illustration caption is a cosmetic extra line,
# while dropping a real navigation link ("Home", "Services") or a card title
# breaks the page.  So the floor only rejects genuinely tiny specks.
MIN_OTHER_W = 18
MIN_OTHER_H = 5


def is_page_text(b: Block) -> bool:
    """Is this block the page's own copy, rather than text inside the artwork?

    Text that belongs to an illustration (a device mockup, a product card) must
    not become a DOM element: its box is unreliable, so the element lands in the
    wrong place, and its exclusion rect punches a hole through the busiest part
    of the traced art.  Leaving it out lets the tracer reproduce it instead.

    The model's `part` is the primary signal; the size backstop only applies to
    the catch-all `other` role, and only rejects genuinely tiny fragments.
    """
    if getattr(b, "part", "page") == "artwork":
        return False
    if b.role != "other":
        return True
    x0, y0, x1, y1 = b.bbox
    return (x1 - x0) >= MIN_OTHER_W and (y1 - y0) >= MIN_OTHER_H


def page_blocks(blocks: list[Block]) -> list[Block]:
    return [b for b in blocks if is_page_text(b)]


def text_rects(blocks: list[Block]) -> list[list[int]]:
    """mkart's exclusion rects: each text box grown, clamped to the stage.

    The caller passes **every** text block -- the page copy that becomes DOM and
    the text inside the artwork.  A text block is not art: leaving one unblanked
    bakes a ghost of it into the hero backdrop, where the real copy sits.  A
    small box (a `6px` label) is still enclosed by the pad, since the rect grows
    on both sides of it.
    """
    out: list[list[int]] = []
    for b in blocks:
        x0, y0, x1, y1 = b.bbox
        out.append([
            max(0, int(round(x0)) - TEXT_RECT_GROW),
            max(0, int(round(y0)) - TEXT_RECT_GROW),
            min(STAGE_W, int(round(x1)) + TEXT_RECT_GROW),
            min(STAGE_H, int(round(y1)) + TEXT_RECT_GROW),
        ])
    return out


def button_rects(blocks: list[Block]) -> list[list[int]]:
    """Rects the tracer must remove *whole*: the reference's own CTA buttons.

    A button is a solid plate, so dropping only its label's bands leaves the
    plate behind -- a ghost of the button under the DOM one (a pale pill on the
    anthotype reference).  The button is chrome, never artwork.
    """
    out: list[list[int]] = []
    for b in blocks:
        if b.role != "cta" or not is_page_text(b):
            continue
        x0, y0, x1, y1 = b.bbox
        out.append([
            max(0, int(round(x0)) - TEXT_RECT_GROW),
            max(0, int(round(y0)) - TEXT_RECT_GROW),
            min(STAGE_W, int(round(x1)) + TEXT_RECT_GROW),
            min(STAGE_H, int(round(y1)) + TEXT_RECT_GROW),
        ])
    return out


def describe(sections: list[tuple[str, list[Block]]], markup: str) -> list[dict]:
    """A machine-readable summary of the generated structure (for the API/UI)."""
    out = []
    for name, blocks in sections:
        out.append({
            "name": name,
            "blocks": len(blocks),
            "text": [b.text for b in blocks][:8],
        })
    return out


def structure_issues(sections: list[tuple[str, list[Block]]], markup: str) -> list[str]:
    """Self-check: report structural problems rather than shipping a bad page."""
    issues: list[str] = []
    names = [s for s, _ in sections]
    if not sections:
        return ["no page copy was recovered from this design"]
    if "hero" not in names and "header" not in names:
        issues.append("no hero/header section was found")
    if markup.count("<h1") == 0:
        issues.append("no <h1> was generated")
    if markup.count("<h1") > 1:
        issues.append(f"{markup.count('<h1')} <h1> elements (should be one)")
    if 'href="#"' in markup:
        issues.append("a link points at '#' (dead)")
    if 'position: absolute' in markup or "position:absolute" in markup:
        issues.append("absolutely-positioned content (not flow layout)")
    return issues


def write_all(pipeline: Path, name: str, blocks: list[Block],
              background: tuple[int, int, int]) -> dict:
    """Write content/page.css/design config into the job's pipeline copy."""
    sections = group_sections(blocks)
    content = build_content(sections, name)
    (pipeline / f"content-{name}.json").write_text(
        json.dumps(content, indent=2, ensure_ascii=False) + "\n")

    (pipeline / f"{name}.page.css").write_text(build_page_css(palette(blocks, background)))

    # The exclusion rects are EVERY text block the model found -- the page copy
    # that becomes DOM *and* the text inside the artwork (labels on a device
    # mockup, a logo on a wall).  The artwork is a decorative backdrop: any text
    # baked into it doubles with the real DOM copy sitting over it, which is the
    # single ugliest defect the page can have.  A text block is not art, so it is
    # blanked either way; the tracer repaints it from the surrounding pixels.
    cfg_path = pipeline / "designs" / f"{name}.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.is_file() else {"name": name}
    cfg["name"] = name
    cfg["layout"] = "page"                       # a real website, not a poster
    # The trace box is the FULL frame.  Cropping it to the hero band looks like an
    # obvious win (only the hero is displayed) but measures WORSE: the tracer's
    # luminance band edges are percentiles of the *box's own* histogram
    # (`mkart.build`: lo,hi = percentile(lum) over the box), so a hero-only box
    # re-bins the image against the hero's tonal range and loses fidelity.
    # Measured on a real multi-section upload, masked hero art: 4.14 with the full
    # box vs 5.37 with the hero box, same 96 bands.  The box stays full;
    # `hero_band` crops what is *shown*, not what is traced.
    cfg["box"] = [0, 0, STAGE_W, STAGE_H]
    text_r = text_rects(blocks)
    cfg["text"] = text_r
    cfg["blank"] = button_rects(blocks)
    cfg.setdefault("params", {})
    bg_lum = round(sum(background) / 3.0, 1)
    cfg["params"].update({
        "exclude_text": True, "text_lum_max": 200.0, "cumulative": True,
        # `bands` is the tracer's parity/payload lever.  The studio scaffold
        # (newdesign.py) defaults to 48, but measuring the *masked art region* on
        # a real upload puts the optimum near 96: 48->96 improves it (4.244 ->
        # 4.144), and beyond 96 it degrades again -- it is a knee, not "more is
        # better".  Pin it here so the studio does not inherit the scaffold value.
        "bands": 96, "up": 2,
    })
    # Text exclusion polarity.
    #
    # LIGHT design: `text_bg_lum` (the page ground) makes mkart INPAINT the glyph
    # ink -- it finds ink by *local contrast*, so it works whatever the type
    # colour, and it fills the pixels from the surroundings so gradients survive.
    #
    # DARK design: the legacy rule drops a band only when the band's median colour
    # inside the rect exceeds `text_lum_max` (200).  That assumes near-white type.
    # When the type is COLOURED or dim -- green on near-black, the AntHosting
    # upload -- the glyph *fringe* sits around lum 100, no band clears 200, and the
    # headline is traced into the artwork as a ghost behind the real DOM copy.
    # (The art metric masks the rects, so it cannot see this; the page shows it
    # because the hero scales the art up with `preserveAspectRatio="slice"`.)
    # The robust cure is the same inpainting: put the text rects through
    # `blank_rects` and enable the local-contrast inpaint path with the design's
    # own ground luminance.  Measured on the AntHosting upload: the traced ghost
    # disappears completely and the page reads clean.
    if bg_lum >= 128:
        cfg["params"]["text_bg_lum"] = bg_lum
        cfg["params"]["text_lum_margin"] = 45.0
    else:
        cfg["params"]["text_bg_lum"] = bg_lum
        cfg["params"]["text_lum_margin"] = 45.0
        cfg["blank"] = cfg["blank"] + text_r     # inpaint the text, don't trace it
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
    # Structure is returned, not written into content-*.json: the file stays a
    # clean, editable page definition.
    content["_structure"] = describe(sections, content["markup"])
    content["_issues"] = structure_issues(sections, content["markup"])
    return content
