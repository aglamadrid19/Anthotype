"""Self-check: how well the artwork was recovered, and what the page's structure is.

The pixel metric now measures the **artwork region**, not the whole stage.  The
page is a real website whose copy is authored in the site's own type, so grading
it on whole-page pixels would reward imitating the reference's typeface -- which
is exactly the target this project deliberately abandoned.

Two numbers and one structure report:
  * `art_score`  -- mean abs diff over the art region (the text rects masked out)
  * `art_p95`    -- the 95th percentile of the same diff, over the pixels the eye
                    reads as artwork (see `artwork_mask`).  The mean is dominated
                    by whatever is flat and large -- on a dark design it can read
                    1.4 while the artwork is wrong by five times that -- so this
                    is the number that tracks posterisation.
  * `whole_score`-- mean abs diff over the whole stage, kept for reference only
  * `structure`  -- the DOM structure (sections, headings, links, flow layout)

Everything here is advisory: a missing Chrome is a warning, not a build failure.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from .config import STAGE_H, STAGE_W

_SRGB = "/System/Library/ColorSync/Profiles/sRGB Profile.icc"


def find_chrome() -> str | None:
    env = os.environ.get("CHROME")
    if env and Path(env).is_file():
        return env
    for cand in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                 "/Applications/Chromium.app/Contents/MacOS/Chromium"):
        if Path(cand).is_file():
            return cand
    for name in ("google-chrome", "chromium", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _screenshot(chrome: str, page: Path, out: Path, height: int | None = None) -> None:
    win_h = height or STAGE_H
    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=2", "--force-color-profile=srgb",
        "--no-first-run", "--no-default-browser-check", "--disable-http-cache",
        "--incognito", f"--window-size={STAGE_W},{win_h}", "--virtual-time-budget=8000",
        f"--screenshot={out}", page.resolve().as_uri(),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=120, check=True)
    if not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError("Chrome produced no screenshot")


def _to_stage(png: Path, height: int | None = None) -> np.ndarray:
    h = height or STAGE_H
    img = Image.open(png).convert("RGB")
    if img.size != (STAGE_W, h):
        img = img.resize((STAGE_W, h), Image.LANCZOS)
    return np.asarray(img).astype(np.float32)


def _art_mask(pipeline: Path, name: str) -> np.ndarray | None:
    """A 1024x768 boolean mask of the page copy's exclusion rects, or None.

    The artwork is scored *outside* these rects: inside them the reference is
    the original typeface, which the generated page deliberately replaces.
    """
    cfg = pipeline / "designs" / f"{name}.json"
    if not cfg.is_file():
        return None
    try:
        rects = json.loads(cfg.read_text()).get("text") or []
    except Exception:  # noqa: BLE001
        return None
    if not rects:
        return None
    mask = np.zeros((STAGE_H, STAGE_W), bool)
    for x0, y0, x1, y1 in rects:
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(STAGE_W, int(x1)), min(STAGE_H, int(y1))
        mask[y0:y1, x0:x1] = True
    return mask


def _merge_rects(mask: np.ndarray | None,
                 rects: list | None) -> np.ndarray | None:
    """`mask` plus extra stage-space removal rects (e.g. the cleanup's masks).

    The raster hero score excludes the pixels the page replaces.  The tracer's
    `text`/`blank` cover its own removals; the optional LaMa cleanup removes a
    few more complete elements (a CTA's grown plate, the band row whose copy a
    later DOM section replaces), and those are the same kind of deliberate
    removal -- excluding them keeps the score measuring the backdrop, not the
    removal.  `blank_seams` deliberately does NOT use this: the tracer never
    filled those pixels, so a step there is not a fill defect.
    """
    if not rects:
        return mask
    mask = mask.copy() if mask is not None else np.zeros((STAGE_H, STAGE_W), bool)
    for x0, y0, x1, y1 in rects:
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(STAGE_W, int(x1)), min(STAGE_H, int(y1))
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = True
    return mask


def _clear_rects(mask: np.ndarray | None,
                 rects: list[list[int]] | None) -> np.ndarray | None:
    """Clear every `rects` area from `mask`: artwork labels are never excluded.

    A partially masked label would otherwise hide the very pixels damage shows
    up in -- an erased glyph under the exclusion reads as a clean label (a
    synthetic erased run went 114/228 -> 0/0).  The label rects are cleared from
    the combined exclusions and scored in full, so damage cannot hide behind a
    mask edge.
    """
    if mask is None or not rects:
        return mask
    mask = mask.copy()
    for x0, y0, x1, y1 in rects:
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(STAGE_W, int(x1)), min(STAGE_H, int(y1))
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = False
    return mask


def _removed_mask(pipeline: Path, name: str) -> np.ndarray | None:
    """Every rectangle the tracer *removed* pixels from: `text` plus `blank`.

    Distinct from `_art_mask` on purpose.  The art score masks out `text` because
    the page replaces that copy with live DOM; `blank` (a CTA's whole plate) is
    chrome the tracer also has to fill, and it is where the visible pasted-on
    shapes come from.  A seam check that only looked at `text` would miss every
    button plate on the page.
    """
    cfg = pipeline / "designs" / f"{name}.json"
    if not cfg.is_file():
        return None
    try:
        data = json.loads(cfg.read_text())
        rects = list(data.get("text") or []) + list(data.get("blank") or [])
    except Exception:  # noqa: BLE001
        return None
    if not rects:
        return None
    mask = np.zeros((STAGE_H, STAGE_W), bool)
    for x0, y0, x1, y1 in rects:
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(STAGE_W, int(x1)), min(STAGE_H, int(y1))
        mask[y0:y1, x0:x1] = True
    return mask if mask.any() else None


def _art_box(pipeline: Path, name: str) -> tuple[int, int, int, int] | None:
    """The tracer's box from `designs/<name>.json`, clamped to the stage.

    The traced SVG only covers the box, so the art metric must be measured over
    that same region: scoring un-traced area against the reference would count
    empty space as error.  (The studio currently traces the full frame, so this is
    a no-op there; it keeps the metric correct if a design ever crops its box.)
    """
    cfg = pipeline / "designs" / f"{name}.json"
    if not cfg.is_file():
        return None
    try:
        box = json.loads(cfg.read_text()).get("box") or []
        if len(box) != 4:
            return None
        x0, y0, x1, y1 = (int(v) for v in box)
    except Exception:  # noqa: BLE001
        return None
    return (max(0, x0), max(0, y0), min(STAGE_W, x1), min(STAGE_H, y1))


def _render_stage(chrome: str, page: Path, height: int | None = None) -> np.ndarray:
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "shot.png"
        _screenshot(chrome, page, raw, height=height)
        # Match the repo's scorer: sRGB conversion (macOS) before downsampling.
        if Path("/usr/bin/sips").is_file() and Path(_SRGB).is_file():
            converted = Path(td) / "shot.srgb.png"
            subprocess.run(["/usr/bin/sips", "--matchTo", _SRGB, str(raw),
                            "--out", str(converted)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False)
            if converted.is_file():
                raw = converted
        return _to_stage(raw, height=height)


def _art_page(svg: str, bg: tuple[int, int, int]) -> str:
    """A throwaway page that renders the traced artwork at the reference stage.

    The stage is sized to the SVG's *own* viewBox, at 1024 px wide.  Pinning it
    to 1024x768 would stretch any SVG whose viewBox is not exactly 768 tall --
    the traced art would then be measured against a squashed copy of itself.
    """
    r, g, b = (max(0, min(255, int(v))) for v in bg)
    h = _svg_height(svg)
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"html,body{{margin:0;padding:0;background:rgb({r},{g},{b})}}"
        f"svg{{display:block;width:1024px;height:{h}px}}</style></head>"
        f"<body>{svg}</body></html>")


_SVG_VB = re.compile(r'viewBox="\s*([-\d.]+)\s+([-\d.]+)\s+([\d.]+)\s+([\d.]+)\s*"')


def _svg_height(svg: str) -> int:
    """The SVG's viewBox height, so a cropped art renders at natural scale."""
    m = _SVG_VB.search(svg)
    if not m:
        return STAGE_H
    try:
        return max(1, int(round(float(m.group(4)))))
    except ValueError:
        return STAGE_H


def _render_art(chrome: str, svg: str, bg: tuple[int, int, int]) -> np.ndarray:
    """The traced artwork alone, rendered at 1024x768.

    A *page* layout reflows: its screenshot is the top of a responsive document,
    not a poster, so comparing it to the reference measures layout, not tracing.
    Rendering the SVG by itself gives the tracer's own fidelity -- which is what
    the art metric is for -- independent of how the page happens to flow.

    A cropped SVG (viewBox shorter than 768) is rendered at its natural height at
    the top of a full-stage array, so the result always lines up with the
    reference in stage coordinates (which is what `_art_box` crops to).
    """
    h = _svg_height(svg)
    with tempfile.TemporaryDirectory() as td:
        html = Path(td) / "art.html"
        html.write_text(_art_page(svg, bg))
        shot = _render_stage(chrome, html, height=h)
    if h == STAGE_H:
        return shot
    full = np.zeros((STAGE_H, STAGE_W, 3), np.float32)
    full[:, :, 0], full[:, :, 1], full[:, :, 2] = bg
    full[:min(h, STAGE_H)] = shot[:min(h, STAGE_H)]
    return full


# How far into a blanked rect the seam is measured (pixels).
_SEAM_RING = 3


def blank_seams(render: np.ndarray, mask: np.ndarray | None) -> float | None:
    """How hard a step the blanked rectangles leave, relative to the art's own detail.

    The art score masks the text rects *out* (`per_px[~mask]`), so it is measured
    only on the pixels that were already working -- and is structurally blind to
    the damage inside the blanks.  That is how a trace the design review called
    "unusable" still scored 4.21: masked 4.21 against 60.94 unmasked, a 14x gap.

    A blanked rect is filled from its surroundings, so if the fill does not match
    the local gradient it leaves a *step* at the rectangle's edge -- the hard
    organic-edged plate a review reads as a "worm-like smudge".  A smooth fill has
    no step.  So measure the step directly: for every pixel just inside a blank,
    the tonal distance to the nearest pixel just outside it, in 0-255 intensity
    units.  An absolute measure, not a ratio, so it stays meaningful on a design
    that is nearly flat (where a ratio to "typical detail" divides by ~0).

    ~0 is invisible; past ~12 the boundary is a visible pasted-on edge.
    Returns None when there is nothing masked to measure.
    """
    if mask is None or not mask.any():
        return None
    # Nearest non-blank pixel for each blank pixel, by repeated dilation of the
    # known indices.  Written in numpy rather than scipy because this module is
    # the fidelity scorer and the studio venv pins only numpy/PIL (scipy lives in
    # the *pipeline* venv, which is a different environment).  A few passes is all
    # it needs: we only ever ask about the ring touching real artwork.
    h, w = mask.shape
    idx = np.full(h * w, -1, np.int64)
    # Flat indices of the pixels that are NOT blanked -- these are what index into
    # `render.reshape(-1, 3)`.  (Ranks would be wrong: they are not positions.)
    idx[~mask.ravel()] = np.flatnonzero(~mask.ravel())
    idx = idx.reshape(h, w)
    for _ in range(_SEAM_RING):
        filled = idx >= 0
        if (mask & ~filled).sum() == 0:
            break
        prop = idx.copy()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            src = np.roll(np.roll(idx, dy, axis=0), dx, axis=1)
            # A rolled-in edge would wrap around; never adopt a wrapped neighbour.
            if dy == 1: src[0, :] = -1
            if dy == -1: src[-1, :] = -1
            if dx == 1: src[:, 0] = -1
            if dx == -1: src[:, -1] = -1
            prop = np.where((~filled) & (src >= 0), src, prop)
        idx = np.where(filled, idx, prop)
    ring_in = mask & (idx >= 0)
    if not ring_in.any():
        return None
    outside = render.reshape(-1, 3)[idx.ravel()].reshape(h, w, 3)
    step = np.abs(render - outside).mean(axis=2)[ring_in]
    return float(step.mean())


# How far from the design's own dominant tone a pixel must sit before the eye
# reads it as artwork rather than background (0-255 intensity units).  Used to
# restrict the p95 below to the artwork: see `artwork_mask`.
_EYE_FLOOR = 14.0
# Fewer than this many artwork pixels and the percentile is noise, not a measure.
_EYE_MIN_PX = 200


def artwork_mask(ref: np.ndarray, keep: np.ndarray | None = None) -> np.ndarray:
    """The pixels the eye reads as artwork: not the design's own flat ground.

    The art-region *mean* is dominated by whatever is flat and large, so on a dark
    design with a bright illustration it can read 1.4 while the artwork itself is
    wrong by five times that -- and a reviewer sees exactly the artwork, not the
    ground.  The p95 over these pixels is the number that tracks posterisation.

    Polarity-agnostic: the design's dominant tone is the *median*, and artwork is
    whatever departs from it in either direction, so a light page (dark ink on a
    light ground) selects the ink rather than nothing.
    """
    lum = ref.mean(axis=2)
    ground = float(np.median(lum))
    eye = np.abs(lum - ground) > _EYE_FLOOR
    if keep is not None:
        eye = eye & keep
    return eye


def _stage_crop(ref: np.ndarray, region: list[int] | None) -> tuple[int, int, int, int]:
    """Clamp a stage-space region to the reference image.

    `region` is either a full-bleed band `[y0, y1]` (full width) or a rectangle
    `[x0, y0, x1, y1]` -- an illustration's figure, which the shipped asset was
    cropped to.  Returns `(x0, y0, x1, y1)`.
    """
    if region and len(region) == 4:
        x0, y0, x1, y1 = (int(round(v)) for v in region)
    elif region and len(region) == 2:
        x0, x1 = 0, ref.shape[1]
        y0, y1 = (int(round(v)) for v in region)
    else:
        return 0, 0, ref.shape[1], ref.shape[0]
    x0 = max(0, min(ref.shape[1] - 1, x0))
    x1 = max(x0 + 1, min(ref.shape[1], x1))
    y0 = max(0, min(ref.shape[0] - 1, y0))
    y1 = max(y0 + 1, min(ref.shape[0], y1))
    return x0, y0, x1, y1


def _asset_diff(ref: np.ndarray, region: list[int] | None,
                raster: Path) -> tuple[np.ndarray, tuple[int, int]]:
    """Per-pixel abs diff between the reference crop and the shipped asset."""
    x0, y0, x1, y1 = _stage_crop(ref, region)
    target = ref[y0:y1, x0:x1]
    img = Image.open(raster).convert("RGB")
    if img.size != (target.shape[1], target.shape[0]):
        img = img.resize((target.shape[1], target.shape[0]), Image.LANCZOS)
    return np.abs(np.asarray(img, np.float32) - target).mean(axis=2), (x0, y0)


def hero_fidelity(ref: np.ndarray, region: list[int], raster: Path,
                  mask: np.ndarray | None = None) -> tuple[float, float | None] | None:
    """How faithfully the SHIPPED hero art matches the reference.

    `art_score` measures the traced SVG, which for a photographic design is a
    secondary artifact the page no longer shows.  This measures the thing the
    page actually ships -- the raster export -- against the reference, over the
    same region the page shows: `region` is the band for a full-bleed backdrop,
    or the illustration's own `[x0, y0, x1, y1]` for a split figure (scoring a
    deliberate figure crop against the whole band would report the crop itself
    as an error).  Chrome-free: the asset is a file.

    `mask` (the tracer's removed rects) is excluded for the same reason the art
    score excludes it: the export deliberately inpaints the mockup's own copy
    out, so scoring those pixels would penalise exactly the removal that makes
    the backdrop usable.  An illustration's own labels are NOT in that mask --
    they are content the asset must retain, and they are scored.

    Returns `(mean, p95)`; the p95 is over the artwork pixels (see
    `artwork_mask`) and is None when there are too few to measure.
    """
    if region is None or len(region) not in (2, 4):
        return None
    per_px, _ = _asset_diff(ref, region, raster)
    keep = np.ones(per_px.shape, bool)
    if mask is not None:
        x0, y0, x1, y1 = _stage_crop(ref, region)
        m = mask[y0:y1, x0:x1]
        if (~m).any():
            keep = ~m
    x0, y0, x1, y1 = _stage_crop(ref, region)
    eye = artwork_mask(ref[y0:y1, x0:x1], keep)
    p95 = (round(float(np.percentile(per_px[eye], 95)), 2)
           if int(eye.sum()) >= _EYE_MIN_PX else None)
    return float(per_px[keep].mean()), p95


def label_fidelity(ref: np.ndarray, region: list[int], raster: Path,
                   rects: list[list[int]] | None,
                   mask: np.ndarray | None = None
                   ) -> tuple[float, float] | None:
    """The worst artwork label's difference: `(mean, p95)`.

    `rects` are stage-space boxes of the model's `part: artwork` blocks -- the
    labels an illustration carries.  A label the asset retained scores like the
    rest of the artwork; a label the asset lost or inpainted away leaves its
    fill behind and scores far higher.

    The **p95** matters as much as the mean: a label is mostly background, so
    erasing all its (thin) glyphs can leave the rectangle mean low -- a 60x12
    caption whose strokes cover a quarter of the box reads ~45/255 even when
    fully erased.  The percentile over the rect's own pixels sees the erased
    strokes regardless of how much background surrounds them, which is why the
    runner warns on either number.  `mask` (the tracer's removed rects) is
    excluded for the same reason it is in `hero_fidelity`: where a label
    overlaps copy the page deliberately replaces, the inpaint is the design,
    not damage.  Returns None when no rect lands inside the shipped region.
    """
    if not rects:
        return None
    per_px, (ox, oy) = _asset_diff(ref, region, raster)
    keep = None
    if mask is not None:
        x0, y0, x1, y1 = _stage_crop(ref, region)
        keep = ~mask[y0:y1, x0:x1]
    means: list[float] = []
    p95s: list[float] = []
    for r in rects:
        x0, y0, x1, y1 = (int(round(v)) for v in r)
        lx0, ly0 = max(0, x0 - ox), max(0, y0 - oy)
        lx1 = min(per_px.shape[1], x1 - ox)
        ly1 = min(per_px.shape[0], y1 - oy)
        if lx1 <= lx0 or ly1 <= ly0:
            continue
        patch = per_px[ly0:ly1, lx0:lx1]
        if keep is not None:
            pk = keep[ly0:ly1, lx0:lx1]
            if pk.any():
                patch = patch[pk]
            # A mask that covers the label entirely must NOT erase it from the
            # check: skipping would silently turn a damaged label into no label
            # at all.  The mask's job is to skip replaced copy *inside* a label,
            # never the label; with no unmasked pixels the full rectangle is
            # scored instead.
        means.append(float(patch.mean()))
        p95s.append(float(np.percentile(patch, 95)))
    if not means:
        return None
    return max(means), max(p95s)


def assess(job_id: str, page: Path, ref_png: Path, *,
           pipeline: Path | None = None, art_svg: Path | None = None,
           layout: str = "poster",
           background: tuple[int, int, int] | None = None,
           hero_image: Path | None = None,
           hero_band: list[int] | None = None,
           hero_figure: list[int] | None = None,
           artwork_rects: list[list[int]] | None = None,
           cleanup_rects: list[list[int]] | None = None) -> dict:
    """Return {art_score, art_p95, art_pct, whole_score, whole_pct, structure, issues}."""
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("Chrome not found (set CHROME=...)")

    ref = np.asarray(Image.open(ref_png).convert("RGB")).astype(np.float32)
    render = _render_stage(chrome, page)
    diff = np.abs(ref - render)

    out: dict = {
        "whole_score": float(diff.mean()),
        "whole_pct": float(100.0 * (diff.mean(axis=2) > 30).mean()),
    }

    mask = _art_mask(pipeline, job_id) if pipeline else None
    box = _art_box(pipeline, job_id) if pipeline else None
    # Score the traced SVG itself for a reflowing page; the page screenshot for
    # a fixed poster (where it *is* the artwork's frame).
    if layout == "page" and art_svg and Path(art_svg).is_file():
        bg = background or tuple(int(v) for v in ref[0, 0])
        rendered = _render_art(chrome, Path(art_svg).read_text(), bg)
        art = np.abs(ref - rendered)
        out["art_source"] = "svg"
    else:
        art = diff
        out["art_source"] = "page"
    # The traced box may be a sub-region of the stage (the studio crops it to the
    # hero band, which is all the page shows).  Compare like for like: scoring the
    # un-traced area below the band against the reference would count empty space
    # as error and report a box crop as a regression when it is an improvement.
    ref_c = ref
    if box and (box[1] > 0 or box[3] < STAGE_H or box[0] > 0 or box[2] < STAGE_W):
        x0, y0, x1, y1 = box
        art = art[max(0, y0):min(STAGE_H, y1), max(0, x0):min(STAGE_W, x1)]
        ref_c = ref[max(0, y0):min(STAGE_H, y1), max(0, x0):min(STAGE_W, x1)]
        if mask is not None:
            mask = mask[max(0, y0):min(STAGE_H, y1), max(0, x0):min(STAGE_W, x1)]
    per_px = art.mean(axis=2)
    # Measured on the RENDER, not the diff: this asks whether the trace itself has
    # a step at a blank's edge, which is what the eye sees as a pasted-on plate.
    # Measured on the diff it would just re-report that the reference has text
    # there -- true of every design, good fill or not.
    #
    # It is also the check that covers the very pixels `art_score` throws away, so
    # a trace cannot look good there by having blanked the region it got wrong.
    seam_src = rendered if out.get("art_source") == "svg" else render
    seam = blank_seams(np.asarray(seam_src, dtype=np.float32),
                       _removed_mask(pipeline, job_id) if pipeline else None)
    if seam is not None:
        out["blank_seam"] = round(seam, 1)
    keep = (np.ones(per_px.shape, bool) if mask is None or not (~mask).any()
            else ~mask)
    vals = per_px[keep]
    out["art_score"] = float(vals.mean())
    out["art_pct"] = float(100.0 * (vals > 30).mean())
    # The mean above is dominated by whatever is flat and large.  The p95 over the
    # pixels the eye actually reads as artwork is the number that tracks
    # posterisation -- the glow, the render, the gradient.  See `artwork_mask`.
    eye = artwork_mask(ref_c, keep)
    if int(eye.sum()) >= _EYE_MIN_PX:
        out["art_p95"] = round(float(np.percentile(per_px[eye], 95)), 2)

    # What the page actually ships for the hero, when that is a raster rather
    # than the traced SVG.  Reported alongside `art_score` (the tracer's own
    # number on the master) so neither hides the other.  The region is the
    # illustration's figure when the page shows one (the asset was cropped to
    # it), else the hero band; see `hero_fidelity`.
    region = hero_figure if (hero_figure and len(hero_figure) == 4) else hero_band
    if hero_image is not None and region and Path(hero_image).is_file():
        removed = _removed_mask(pipeline, job_id) if pipeline else None
        # Artwork labels are protected content: the exclusions must never cover
        # them.  Clear the label rects from the combined exclusions (tracer's
        # removals + the cleanup's) and score them in full -- a partially masked
        # label would otherwise hide exactly where damage shows.
        removed_hero = _clear_rects(_merge_rects(removed, cleanup_rects),
                                    artwork_rects)
        got = hero_fidelity(ref, region, Path(hero_image), removed_hero)
        if got is not None:
            val, p95 = got
            out["hero_score"] = round(val, 2)
            if p95 is not None:
                out["hero_p95"] = p95
            out["hero_source"] = "raster"
            out["hero_region"] = list(region)
        lab = label_fidelity(ref, region, Path(hero_image), artwork_rects,
                             removed_hero)
        if lab is not None:
            out["hero_label_max"] = round(lab[0], 1)
            out["hero_label_p95"] = round(lab[1], 1)

    # Surfaced as an advisory, not folded into the score: the two measures answer
    # different questions, and a high seam is a *readability* problem (a pasted-on
    # plate behind the copy) rather than a pixel-parity one.
    if seam is not None and seam > 12.0:
        out.setdefault("issues", []).append(
            f"blanked rectangles leave a hard seam ({seam:.0f}/255) — the hero "
            f"backdrop has pasted-on shapes where text was removed")

    try:
        from . import structure as _structure
        info = _structure.inspect(page)
        out["structure"] = info
        # Append, don't replace: the seam advisory above is one of `issues`, and
        # overwriting the list here silently dropped it (a job could carry a
        # pasted-on plate *and* report a clean structure).
        out["issues"] = list(out.get("issues") or []) + list(info.get("issues") or [])
    except Exception:  # noqa: BLE001 - structure is advisory
        pass
    return out


def score(job_id: str, page: Path, ref_png: Path) -> tuple[float, float]:
    """Backwards-compatible whole-stage score (mean, pct>30)."""
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("Chrome not found (set CHROME=...)")
    render = _render_stage(chrome, page)
    ref = np.asarray(Image.open(ref_png).convert("RGB")).astype(np.float32)
    diff = np.abs(ref - render)
    return float(diff.mean()), float(100.0 * (diff.mean(axis=2) > 30).mean())
