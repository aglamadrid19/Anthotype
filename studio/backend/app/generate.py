"""Turn extracted text blocks into the three files the pipeline consumes.

  * `content-<id>.json`  -- the text layer (title, description, markup, stage)
  * `<id>.page.css`      -- per-block absolute layout derived from the boxes
  * `designs/<id>.json`  -- box = full frame, text = exclusion rects

The last one is the reuse that matters: the model's text boxes are exactly the
rectangles `mkart.py` must exclude so the trace does not bake a rasterised copy
of the words into the artwork.  Growing them slightly is safe -- it only
preserves a little more of the glow the type sits on.
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import numpy as np
from PIL import Image

from .config import STAGE_H, STAGE_W
from .extract import Block
from .fontmetrics import (cap_top_offset, char_at_x_fraction, fit_block_type,
                          fit_font_size, ink_height_em)

# Safety growth on the mkart text-exclusion rects (stage px).
TEXT_RECT_GROW = 6


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


def _max_channel_spread(colors: list[tuple[int, int, int]]) -> int:
    """Largest per-channel difference between any two of `colors`."""
    if len(colors) < 2:
        return 0
    return max(max(c[i] for c in colors) - min(c[i] for c in colors)
               for i in range(3))


def _role_rank(role: str) -> int:
    return {"brand": 0, "headline": 1, "subhead": 2, "tagline": 3,
            "cta": 4, "other": 5}.get(role, 5)


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


def measure_lines(arr: np.ndarray, bbox: tuple[float, float, float, float],
                  background: tuple[int, int, int]
                  ) -> tuple[int, float | None, list[tuple[int, int]]]:
    """Count the text lines inside `bbox` from the reference pixels.

    The model reports a wrapped block as ONE box, and neither the box's width nor
    its height says how many lines it holds -- so the layout used to guess, and
    on the Montiva hero it guessed one 14 px line where the reference sets two
    ~22 px ones.  The reference itself is unambiguous: each text line is a run of
    ink rows separated by a clear gap, so a horizontal ink projection counts
    them and measures the leading at the same time.

    Returns `(line_count, pitch_px, runs)`; `runs` are the `(row0, row1)` ink
    bands in stage coordinates (used to sample each line's own colour) and
    `pitch_px` is the median baseline-to-baseline distance.  Conservative --
    returns `(1, None, [])` unless the structure is clear, so a genuinely
    single-line block, or one whose ink is a single blob, is left to the width
    solve rather than mis-split.
    """
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(STAGE_W, x1), min(STAGE_H, y1)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return 1, None, []
    grey = arr[y0:y1, x0:x1].mean(axis=2)
    bg_mean = float(np.array(background, dtype=np.float32).mean())
    # Polarity-aware, like `snap_to_ink`: the ink may be either side of the
    # background, and a fixed threshold misses faint small print on a near-white
    # page entirely.
    d = np.abs(grey - bg_mean)
    base = float(d.max())
    if base < 6.0:
        return 1, None, []
    thr = max(10.0, 0.35 * base)
    ink = d > thr
    row_any = ink.sum(axis=1) >= 1
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i, on in enumerate(row_any):
        if on and start is None:
            start = i
        elif not on and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(row_any) - 1))
    # A real line is at least 2 px of ink; a lone anti-aliased edge row is not.
    runs = [(a, b) for a, b in runs if b - a + 1 >= 2]
    if len(runs) < 2:
        return 1, None, []
    # Wrapped lines are similar heights.  A second "line" that is a descender
    # sliver, a stray icon, or a neighbouring element is much shorter, and
    # treating it as a line would shatter a single-line block.
    heights = [b - a + 1 for a, b in runs]
    if max(heights) > 3.5 * min(heights):
        return 1, None, []
    gaps = [runs[i + 1][0] - runs[i][1] - 1 for i in range(len(runs) - 1)]
    if min(gaps) < 2:
        return 1, None, []
    centres = [(a + b) / 2.0 for a, b in runs]
    pitches = [centres[i + 1] - centres[i] for i in range(len(centres) - 1)]
    if min(pitches) <= 0:
        return 1, None, []
    abs_runs = [(y0 + a, y0 + b) for a, b in runs]
    return len(runs), float(np.median(pitches)), abs_runs


def sample_line_colors(arr: np.ndarray, runs: list[tuple[int, int]],
                       x0: float, x1: float,
                       background: tuple[int, int, int]
                       ) -> list[tuple[int, int, int]]:
    """Ink colour of each measured line band (for a multi-colour wrapped block).

    A wrapped display headline is often painted per line -- the Montiva hero is
    navy on line 1 and blue on line 2 -- and sampling the whole block collapses
    that to one colour, which reads as a large error on the most prominent
    element of the page.
    """
    return [sample_ink(arr, (x0, ry0, x1, ry1 + 1), background)
            for (ry0, ry1) in runs]


def ink_coverage(grey: np.ndarray, background: float,
                 thr: float = 6.0) -> float | None:
    """Fraction of the ink box of `grey` that is actually ink.

    The reference-side half of `fontmetrics.detect_weight`: the same statistic is
    measured on the reference glyphs and on the string rasterised in each
    vendored weight, and the closest weight wins.
    """
    d = np.abs(grey - background)
    base = float(d.max())
    if base < 6.0:
        return None
    ink = d > max(thr, 0.35 * base)
    n = int(ink.sum())
    if n < 10:
        return None
    ys, xs = np.nonzero(ink)
    h = int(ys.max() - ys.min() + 1)
    w = int(xs.max() - xs.min() + 1)
    if h < 2 or w < 2:
        return None
    return n / float(h * w)


def measure_weight(arr: np.ndarray, bbox: tuple[float, float, float, float],
                   text: str, background: tuple[int, int, int]) -> int:
    """Pick the Inter weight the reference sets `text` in (see `detect_weight`)."""
    from . import fontmetrics
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(STAGE_W, x1), min(STAGE_H, y1)
    if x1 - x0 < 4 or y1 - y0 < 4 or not text.strip():
        return fontmetrics.DEFAULT_WEIGHT
    grey = arr[y0:y1, x0:x1].mean(axis=2)
    bg_mean = float(np.array(background, dtype=np.float32).mean())
    cov = ink_coverage(grey, bg_mean)
    if cov is None:
        return fontmetrics.DEFAULT_WEIGHT
    return fontmetrics.detect_weight(text, cov)


def decorate(blocks: list[Block], ref_png: Path,
             background: tuple[int, int, int]) -> list[Block]:
    """Fill in each block's ink colour(s) (and a CTA's fill) from the reference."""
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
            # Keep the label box (font-size comes from it) and grow the block to
            # the real button so the DOM button and its exclusion rect match.
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
            # How many lines the reference actually sets this block on.  The
            # model reports a wrapped block as one box, and the box width alone
            # cannot distinguish it from a single long line (see `measure_lines`).
            n, pitch, line_runs = measure_lines(arr, b.bbox, background)
            b.meta["n_lines"] = n
            if pitch:
                b.meta["pitch"] = pitch
            if n > 1 and line_runs:
                b.meta["line_colors"] = sample_line_colors(
                    arr, line_runs, b.bbox[0], b.bbox[2], background)
            # How heavy the reference sets it.  A display headline is bold and a
            # body line is not, and the difference is the single largest source
            # of error once the text lands in the right place.
            b.meta["weight"] = measure_weight(arr, b.bbox, b.text, background)
    return blocks


def _element(block: Block, i: int) -> str:
    tag = {"headline": "h1", "subhead": "h2", "tagline": "p",
           "brand": "div", "cta": "a"}.get(block.role, "p")
    cls = f"blk blk-{i}"
    if block.runs and len(block.runs) > 1:
        # A multi-colour run: emit one span per colour so the wordmark prefix
        # can be neutral while the suffix is coloured.
        inner = "".join(
            f'<span style="color: {_hex(c)}">{html.escape(t)}</span>'
            for t, c in block.runs)
    else:
        inner = html.escape(block.text)
    if tag == "a":
        return f'<a class="{cls} cta" href="#">{inner}</a>'
    return f'<{tag} class="{cls}">{inner}</{tag}>'


def build_markup(blocks: list[Block]) -> str:
    ordered = sorted(enumerate(blocks), key=lambda kv: (_role_rank(kv[1].role), kv[0]))
    return "\n".join("      " + _element(b, i) for i, b in ordered)


def build_content(blocks: list[Block], name: str) -> dict:
    headline = next((b for b in blocks if b.role == "headline"), None)
    tagline = next((b for b in blocks if b.role == "tagline"), None)
    cta = next((b for b in blocks if b.role == "cta"), None)
    title = headline.text if headline else f"{name} — coming soon"
    return {
        "title": title,
        "description": tagline.text if tagline else "Built from a design reference.",
        "eyebrow": "Coming soon",
        "tagline": tagline.text if tagline else "",
        "cta": cta.text if cta else "",
        "stage": [STAGE_W, STAGE_H],
        "markup": build_markup(blocks),
    }


def build_page_css(blocks: list[Block], background: tuple[int, int, int]) -> str:
    bg = _hex(background)
    # Picked from the design, not hardcoded: a light mockup should get a light
    # scheme, so form controls and scrollbars match the page the artwork implies.
    scheme = "light" if sum(background) / 3.0 >= 128 else "dark"
    lines = [
        f":root {{ color-scheme: {scheme}; }}",
        "* { box-sizing: border-box; margin: 0; padding: 0; }",
        "html, body { width: 100%; height: 100%; }",
        f"body {{ background: {bg}; font-family: Inter, system-ui, sans-serif;",
        "  overflow: hidden; -webkit-font-smoothing: antialiased; }",
        f".stage {{ position: absolute; left: 50%; top: 50%; width: {STAGE_W}px;",
        f"  height: {STAGE_H}px; transform-origin: center center;",
        f"  background: {bg}; overflow: hidden; }}",
        ".content { position: absolute; inset: 0; z-index: 3; }",
        ".art { position: absolute; inset: 0; z-index: 2; }",
        f".art > svg {{ display: block; width: {STAGE_W}px; height: {STAGE_H}px; overflow: visible; }}",
        ".blk { position: absolute; white-space: nowrap; font-weight: 400; line-height: 1; }",
    ]
    for i, b in enumerate(blocks):
        x0, y0, x1, y1 = b.bbox
        if b.role == "cta":
            weight = 600
            label = b.meta.get("label_bbox") or b.bbox
            fs = fit_font_size(b.text, label[2] - label[0], label[3] - label[1],
                               b.role, weight)
            color = _hex(b.color or (255, 255, 255))
            left, top = x0, y0
            bw, bh = x1 - x0, y1 - y0
            if b.meta.get("outline"):
                # An outline button has no fill plate: a border ring plus the
                # label.  Painting an opaque fill here would be a large, wrong
                # patch of colour, so the interior stays transparent.
                border = _hex(b.meta.get("border") or b.color or (24, 196, 124))
                lines += [
                    f".blk-{i} {{ left: {left:.0f}px; top: {top:.0f}px; width: {bw:.0f}px;",
                    f"  height: {bh:.0f}px; display: inline-flex; align-items: center;",
                    f"  justify-content: center; border-radius: 15px; text-decoration: none;",
                    f"  border: 2px solid {border}; background: transparent;",
                    f"  color: {color}; font-size: {fs:.1f}px; font-weight: {weight}; }}",
                ]
            else:
                fill = _hex(b.fill or (24, 196, 124))
                lines += [
                    f".blk-{i} {{ left: {left:.0f}px; top: {top:.0f}px; width: {bw:.0f}px;",
                    f"  height: {bh:.0f}px; display: inline-flex; align-items: center;",
                    f"  justify-content: center; border-radius: 14px; text-decoration: none;",
                    f"  background: {fill}; color: {color}; font-size: {fs:.1f}px; font-weight: {weight}; }}",
                ]
        else:
            weight = b.meta.get("weight", 400)
            bw, bh = x1 - x0, y1 - y0
            fs, nlines = fit_block_type(b.text, bw, bh, b.role, weight,
                                        n_lines=b.meta.get("n_lines"))
            color = _hex(b.color or (255, 255, 255))
            if nlines > 1:
                # The model reports a wrapped block as ONE box, so the lines must
                # be laid out by wrapping inside it, with the leading spread to
                # fill the box height -- but never tighter than the glyphs.
                # Prefer the leading measured from the reference (`pitch`), which
                # is exact; fall back to spreading the box height over the lines.
                lh = b.meta.get("pitch") or max(bh / nlines, fs)
                top = max(0.0, y0 - cap_top_offset(fs, weight, lh))
                # A wrapped *display* line is often painted per line (the Montiva
                # hero is navy, then blue).  One colour for the whole block is a
                # large error on the page's most prominent element.  Only worth
                # doing for large type, though: on 8 px body copy the per-line
                # medians differ only by anti-aliasing, and a gradient there just
                # smears the colour.
                line_cols = b.meta.get("line_colors") or []
                paint = ""
                if (fs >= 18 and len(line_cols) >= 2
                        and _max_channel_spread(line_cols) > 24):
                    n = len(line_cols)
                    # Hard stops, not a smooth ramp: each measured line is a flat
                    # colour in the reference, so the transition belongs on the
                    # boundary between lines (a ramp would tint the top of line 1
                    # and the bottom of line 2).
                    stops = []
                    for k, c in enumerate(line_cols):
                        a, b = k * 100.0 / n, (k + 1) * 100.0 / n
                        stops.append(f"{_hex(c)} {a:.1f}%")
                        stops.append(f"{_hex(c)} {b:.1f}%")
                    color = "transparent"
                    paint = (f"background: linear-gradient(180deg, {', '.join(stops)}); "
                             f"-webkit-background-clip: text; background-clip: text;")
                lines.append(
                    f".blk-{i} {{ left: {x0:.0f}px; top: {top:.1f}px; width: {bw:.0f}px; "
                    f"white-space: normal; font-size: {fs:.1f}px; line-height: {lh:.1f}px; "
                    f"font-weight: {weight}; color: {color}; {paint}}}"
                )
            else:
                top = max(0.0, y0 - cap_top_offset(fs, weight))
                lines.append(
                    f".blk-{i} {{ left: {x0:.0f}px; top: {top:.1f}px; "
                    f"font-size: {fs:.1f}px; font-weight: {weight}; color: {color}; }}"
                )
    return "\n".join(lines) + "\n"


# A block the model called `other` must be at least this big to be page copy
# rather than a caption inside the artwork.  A backstop for the model's `part`
# judgement: a small step caption scored against a wrong box is worse than
# leaving it to the tracer.
#
# Only `other` is gated.  `headline`/`subhead`/`tagline` are the page's copy by
# definition, and a `brand` wordmark or a `cta` label is legitimately small (the
# reference's brand is 94 px, its button label 110 px).  `other` is the catch-all
# where a stray illustration caption lands, and those are far narrower than any
# real page line.
MIN_OTHER_W = 100
MIN_OTHER_H = 6


def is_page_text(b: Block) -> bool:
    """Is this block the page's own copy, rather than text inside the artwork?

    Text that belongs to an illustration (a device mockup, a product card) must
    not become a DOM element: its box is unreliable, so the element lands in the
    wrong place, and its exclusion rect punches a hole through the busiest part
    of the traced art.  Leaving it out lets the tracer reproduce it instead.

    The model's `part` is the primary signal.  The size backstop only applies to
    `other`, the catch-all role: a wordmark (`brand`) or a button label (`cta`)
    is legitimately small -- the brand here is a 94 px wordmark -- so gating on
    size would drop real copy.  `other` is where a stray illustration caption
    would land, and those are far narrower than any real page line.
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
    """mkart's exclusion rects: each text box grown, clamped to the stage."""
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


def write_all(pipeline: Path, name: str, blocks: list[Block],
              background: tuple[int, int, int]) -> dict:
    """Write content/page.css/design config into the job's pipeline copy."""
    blocks = page_blocks(blocks)
    content = build_content(blocks, name)
    (pipeline / f"content-{name}.json").write_text(
        json.dumps(content, indent=2, ensure_ascii=False) + "\n")

    (pipeline / f"{name}.page.css").write_text(build_page_css(blocks, background))

    cfg_path = pipeline / "designs" / f"{name}.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.is_file() else {"name": name}
    cfg["name"] = name
    cfg["box"] = [0, 0, STAGE_W, STAGE_H]        # full frame: exclude_text protects the type
    cfg["text"] = text_rects(blocks)
    cfg.setdefault("params", {})
    # Polarity-aware text exclusion.  `text_bg_lum` tells the tracer where the
    # page background sits, so it drops the bands that are *ink* (away from the
    # background) instead of assuming light type on a dark ground -- the rule
    # `text_lum_max` encodes, and which is correct for a dark design but turns a
    # text rect into a hard hole on a light one.  Only set it for a light
    # background: on a dark design the legacy rule is already right, and it is
    # what the regression suite is scored against.
    bg_lum = round(sum(background) / 3.0, 1)
    cfg["params"].update({
        "exclude_text": True, "text_lum_max": 200.0, "cumulative": True,
    })
    if bg_lum >= 128:
        cfg["params"]["text_bg_lum"] = bg_lum
        cfg["params"]["text_lum_margin"] = 45.0
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
    return content
