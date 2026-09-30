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


def palette(blocks: list[Block], background: tuple[int, int, int]) -> dict:
    """A small design system (bg/ink/muted/accent/surface) from the reference.

    The reference's *colours* are the design, so they are sampled; its *type* is
    not reproduced.  The result is enough for a coherent page -- body ground,
    text, a muted tone and one accent -- without imitating the mockup.
    """
    bg = tuple(int(v) for v in background)
    light = sum(bg) / 3.0 >= 128
    colors = [tuple(b.color) for b in blocks if b.color]
    fills = [tuple(b.fill) for b in blocks if b.fill]
    accents = [c for c in colors + fills if _sat(c) >= 40]
    accent = max(accents, key=_sat) if accents else ((14, 150, 100) if light else (25, 210, 130))
    headline = next((b for b in blocks if b.role == "headline" and b.color), None)
    if headline:
        ink = tuple(headline.color)
    elif colors:
        ink = max(colors, key=lambda c: abs(sum(c) / 3.0 - sum(bg) / 3.0))
    else:
        ink = (17, 24, 32) if light else (244, 255, 249)
    toward = (0, 0, 0) if light else (255, 255, 255)
    return {
        "light": light,
        "bg": bg,
        "ink": ink,
        "muted": _mix(ink, bg, 0.42),
        "accent": accent,
        "accent_ink": (6, 20, 14) if sum(accent) / 3.0 > 140 else (255, 255, 255),
        "surface": _mix(bg, toward, 0.05 if light else 0.07),
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

SECTION_TITLE = {
    "hero": "", "features": "What we offer", "testimonials": "What people say",
    "pricing": "Pricing", "contact": "Get in touch", "other": "",
}


def _reading_order(blocks: list[Block]) -> list[Block]:
    """Sort by vertical position then horizontal -- how a person reads a page."""
    return sorted(blocks, key=lambda b: (round(b.bbox[1]), round(b.bbox[0])))


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
            if i == 0 and (roles & {"headline", "subhead", "cta"}):
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
    return out


def group_sections(blocks: list[Block]) -> list[tuple[str, list[Block]]]:
    """Ordered `[(section, [blocks])]` for the page's own copy.

    Prefers the model's `section`.  A block the model left unspecified is
    attached to the nearest declared section by vertical position; when the
    model declared nothing at all, the blocks are clustered by vertical gap and
    named by position (see `_infer_sections`).

    A section name may repeat (a landing page often has several feature bands),
    so this returns an ordered *list* of groups, never a name-keyed dict.
    """
    page = [b for b in blocks if is_page_text(b)]
    if not page:
        return []
    declared = [b for b in page if b.section in KNOWN_SECTIONS]
    if not declared:
        return _infer_sections(page)

    pending: list[tuple[str, list[Block]]] = []
    for b in _reading_order(page):
        if b.section in KNOWN_SECTIONS:
            pending.append((b.section, [b]))
            continue
        # Attach an unspecified block to the nearest declared block *above* it,
        # else below -- by vertical position, so reading order survives.
        cy = (b.bbox[1] + b.bbox[3]) / 2.0
        above = [p for p in pending if (p[1][0].bbox[1] + p[1][0].bbox[3]) / 2.0 <= cy]
        target = above[-1] if above else (pending[0] if pending else None)
        if target is None:
            pending.append(("other", [b]))
        else:
            target[1].append(b)

    # Merge adjacent blocks that share a name into ONE section.  The model
    # declares a section per block ("features" on the eyebrow, on the heading and
    # on each card), so emitting one group per block would ship 25 `<section>`s
    # where the page has 4.  A new group starts only when the name changes;
    # the rank sort then fixes the *order* of the names (a hero the model
    # labelled after the nav still renders first).
    groups: list[tuple[str, list[Block]]] = []
    for name, blk in pending:
        if groups and groups[-1][0] == name:
            groups[-1][1].extend(blk)
        else:
            groups.append((name, list(blk)))
    rank = {s: i for i, s in enumerate(SECTION_ORDER)}
    groups.sort(key=lambda sg: rank.get(sg[0], 99))
    return groups


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


def _cta_html(b: Block, href: str, cls: str = "cta") -> str:
    color = _hex(b.color or (255, 255, 255))
    if b.meta.get("outline"):
        border = _hex(b.meta.get("border") or b.color or (24, 196, 124))
        style = f' style="color: {color}; border-color: {border}"'
        return f'<a class="{cls} outline" href="{_attr(href)}"{style}>{_inline(b)}</a>'
    fill = _hex(b.fill or (24, 196, 124))
    style = f' style="background: {fill}; color: {color}"'
    return f'<a class="{cls}" href="{_attr(href)}"{style}>{_inline(b)}</a>'


def _card_html(col: list[Block], heading_used: list[bool],
               cta_href: str = "#top") -> str:
    """One card: a title line plus any body lines that share its column.

    The card title is an `h3` -- the page's only `h1` lives in the hero and the
    section eyebrow is its `h2`-level label.
    """
    title_done = False
    parts: list[str] = []
    for b in col:
        if b.role == "cta":
            parts.append(_cta_html(b, cta_href, "cta small"))
        elif not title_done:
            parts.append(f"<h3>{_inline(b)}</h3>")
            title_done = True
        else:
            parts.append(f"<p>{_inline(b)}</p>")
    return '<div class="card">\n        ' + "\n        ".join(parts) + "\n      </div>"


def _section_body(name: str, blocks: list[Block], heading_used: list[bool],
                  cta_href: str) -> str:
    """The inner markup of one non-hero section.

    A section's *eyebrow* (a short all-caps kicker) becomes its visible title;
    the reference's own repeated section headline is not re-emitted as an `h1`
    (there is exactly one `h1` on the page, in the hero), so it is demoted to a
    lead paragraph when it duplicates the eyebrow's meaning.
    """
    eyebrow = next((b for b in blocks if _is_eyebrow(b)), None)
    out: list[str] = []
    if eyebrow is not None:
        out.append(f'<p class="eyebrow">{_inline(eyebrow)}</p>')
        if _title_equivalent(SECTION_TITLE.get(name, ""), eyebrow.text):
            out.append(f'<h2 class="section-title">{html.escape(SECTION_TITLE[name])}</h2>')

    rest = [b for b in blocks if b is not eyebrow]

    if name in GRID_SECTIONS:
        heads = [b for b in rest if b.role in {"headline", "subhead"}]
        body = [b for b in rest if b not in heads]
        for h in heads:
            out.append(f'<p class="lead">{_inline(h)}</p>')
        if body:
            cards = [_card_html(c, heading_used, cta_href) for c in _columns(body)]
            out.append('<div class="cards">\n      ' + "\n      ".join(cards) + "\n    </div>")
        return "\n    ".join(out)

    for b in rest:
        if b.role == "cta":
            out.append(_cta_html(b, cta_href))
        elif b.role in {"headline", "subhead"}:
            out.append(f'<p class="lead">{_inline(b)}</p>')
        else:
            out.append(f'<p class="lead">{_inline(b)}</p>')
    return "\n    ".join(out)


def _title_equivalent(a: str, b: str) -> bool:
    """Are two section labels the same idea?  ("Features" vs "OUR SERVICES")"""
    aw = {w for w in re.findall(r"[a-z]+", a.lower()) if len(w) > 3}
    bw = {w for w in re.findall(r"[a-z]+", b.lower()) if len(w) > 3}
    return bool(aw & bw) or not aw


def _hero_html(blocks: list[Block], cta_href: str) -> str:
    out = []
    for b in blocks:
        if b.role == "headline":
            out.append(f'<h1>{_inline(b)}</h1>')
        elif b.role == "subhead":
            out.append(f'<p class="subhead">{_inline(b)}</p>')
        elif b.role == "cta":
            out.append(_cta_html(b, cta_href))
        elif b.role == "brand":
            out.append(f'<span class="brand">{_inline(b)}</span>')
        elif _is_eyebrow(b):
            out.append(f'<p class="eyebrow">{_inline(b)}</p>')
        else:
            out.append(f'<p class="lede">{_inline(b)}</p>')
    return "\n      ".join(out)


def _header_html(brand: Block | None, links: list[Block], cta_href: str) -> str:
    left = (f'<a class="brand" href="#top">{_inline(brand)}</a>' if brand
            else '<a class="brand" href="#top">Home</a>')
    nav = "".join(
        _cta_html(b, cta_href, "cta small") if b.role == "cta"
        else f'<a href="{_attr(cta_href)}">{_inline(b)}</a>'
        for b in links)
    return (f'<div class="wrap">\n      {left}\n'
            f'      <nav class="site-nav" aria-label="Primary">{nav}</nav>\n    </div>')


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
    heading_used = [False]
    parts: list[str] = []
    used: dict[str, int] = {}
    anchors: list[tuple[str, str]] = []   # (section name, id), in page order

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
        parts.append('<section class="hero" id="hero">\n      '
                     '<div class="hero-art" aria-hidden="true"><!--ART--></div>\n'
                     '      <div class="wrap hero-copy">\n      '
                     + _hero_html(hero, cta_href) + "\n      </div>\n    </section>")
        anchors.append(("hero", "hero"))

    middle = []
    for name, blocks in sections:
        if name in ("header", "nav", "hero", "footer"):
            continue
        sid = _stable_id(name, used)
        anchors.append((name, sid))
        body = _section_body(name, blocks, heading_used, cta_href)
        if not body:
            continue
        middle.append(f'<section class="section sec-{name}" id="{sid}">\n'
                      f'    <div class="wrap">\n    {body}\n    </div>\n  </section>')
    if middle:
        parts.append('<main id="main">\n  ' + "\n  ".join(middle) + "\n  </main>")

    footer = [b for name, g in sections if name == "footer" for b in g]
    if footer:
        items = []
        for b in footer:
            if b.role == "cta":
                items.append(_cta_html(b, cta_href, "cta small"))
            elif _is_navish(b):
                items.append(f'<a href="#top">{_inline(b)}</a>')
            else:
                items.append(f"<p>{_inline(b)}</p>")
        parts.append('<footer class="site-footer" id="footer">\n    '
                     '<div class="wrap">\n      ' + "\n      ".join(items)
                     + "\n    </div>\n  </footer>")
    return "\n  ".join(parts)


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
  --border: {_hex(p['border'])};
  --maxw: 1120px;
}}
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scroll-behavior: smooth; }}
body {{
  background: var(--bg); color: var(--ink);
  font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.55; -webkit-font-smoothing: antialiased;
}}
h1, h2, h3 {{ line-height: 1.1; letter-spacing: -0.02em; }}
a {{ color: inherit; }}
.wrap {{ width: 100%; max-width: var(--maxw); margin: 0 auto; padding: 0 24px; }}
.muted, .lead {{ color: var(--muted); }}

.site-header {{
  position: sticky; top: 0; z-index: 20;
  background: var(--bg); border-bottom: 1px solid var(--border);
}}
.site-header .wrap {{
  display: flex; align-items: center; justify-content: space-between;
  gap: 24px; min-height: 68px; flex-wrap: wrap;
}}
.brand {{ font-weight: 600; font-size: 18px; text-decoration: none; }}
.site-nav {{ display: flex; gap: 22px; flex-wrap: wrap; }}
.site-nav a {{ color: var(--muted); text-decoration: none; font-size: 15px; }}
.site-nav a:hover {{ color: var(--ink); }}

.hero {{ position: relative; overflow: hidden; border-bottom: 1px solid var(--border); }}
.hero-art {{ position: absolute; inset: 0; z-index: 0; opacity: 1; }}
.hero-art svg {{ width: 100%; height: 100%; display: block; }}
.hero-copy {{
  position: relative; z-index: 1; display: grid; gap: 18px; justify-items: start;
  padding-top: 104px; padding-bottom: 104px; max-width: 760px;
}}
.hero h1 {{ font-size: clamp(38px, 6.5vw, 74px); font-weight: 600; }}
.hero .subhead {{ font-size: clamp(19px, 2.6vw, 28px); font-weight: 600; }}
.hero .lede {{ font-size: clamp(16px, 1.7vw, 20px); color: var(--muted); max-width: 62ch; }}
.hero .brand {{ font-size: 20px; font-weight: 600; }}

.section {{ padding: 84px 0; border-bottom: 1px solid var(--border); }}
.section > .wrap {{ display: grid; gap: 26px; }}
.section-title {{ font-size: clamp(25px, 3.6vw, 38px); font-weight: 600; }}
.eyebrow {{
  text-transform: uppercase; letter-spacing: 0.14em;
  font-size: 13px; font-weight: 600; color: var(--accent);
}}
.lead {{ font-size: clamp(16px, 1.6vw, 19px); max-width: 68ch; }}

.cards {{
  display: grid; gap: 20px;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
}}
.card {{
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 16px; padding: 24px; display: grid; gap: 10px; align-content: start;
}}
.card h3 {{ font-size: 18px; font-weight: 600; }}
.card .lead, .card p {{ color: var(--muted); font-size: 15px; line-height: 1.5; }}

.cta {{
  display: inline-flex; align-items: center; justify-content: center; gap: 10px;
  padding: 14px 28px; border-radius: 12px; text-decoration: none;
  background: var(--accent); color: var(--accent-ink);
  font-weight: 600; font-size: 16px; width: fit-content; border: 2px solid transparent;
}}
.cta:hover {{ filter: brightness(1.06); }}
.cta.outline {{ background: transparent; border: 2px solid var(--accent); }}
.cta.small {{ padding: 10px 18px; font-size: 15px; }}

.site-footer {{ padding: 48px 0; }}
.site-footer .wrap {{
  display: flex; flex-wrap: wrap; gap: 18px 28px;
  align-items: center; justify-content: space-between; color: var(--muted);
}}
.site-footer a {{ color: var(--muted); text-decoration: none; }}
.site-footer a:hover {{ color: var(--ink); }}

@media (max-width: 620px) {{
  .hero-copy {{ padding-top: 72px; padding-bottom: 72px; }}
  .section {{ padding: 60px 0; }}
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

    # The exclusion rects are ALL page blocks (the ones emitted as DOM), so the
    # traced artwork never bakes in a rasterised copy of the page's own copy.
    # Artwork-internal text is deliberately left to the tracer.
    page = [b for b in blocks if is_page_text(b)]
    cfg_path = pipeline / "designs" / f"{name}.json"
    cfg = json.loads(cfg_path.read_text()) if cfg_path.is_file() else {"name": name}
    cfg["name"] = name
    cfg["layout"] = "page"                       # a real website, not a poster
    cfg["box"] = [0, 0, STAGE_W, STAGE_H]        # full frame: exclude_text protects the type
    cfg["text"] = text_rects(page)
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
    # Structure is returned, not written into content-*.json: the file stays a
    # clean, editable page definition.
    content["_structure"] = describe(sections, content["markup"])
    content["_issues"] = structure_issues(sections, content["markup"])
    return content
