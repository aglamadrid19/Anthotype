"""The hero backdrop: a traced SVG, or a photographic raster export.

Two deliverables come out of a build, and they want different things:

  * the **website** -- judged on how good it looks.  A photograph cannot be
    represented as flat vector regions at a sane payload (measured: the tracer
    plateaus at ~3.5 mean on a photo hero while every knob is flat), so a
    photographic hero is exported at a fixed resolution to WebP instead.
  * the **SVG art master** -- always produced, always shipped in the project
    zip, artwork only (never text or fonts).  For a photographic design the
    page no longer uses it, so it is a secondary artifact and is not tuned.

The choice is made by *measurement*, not by guessing, and it is deliberately
biased toward the raster: misclassifying flat art as photographic costs bytes
and the code-native property but looks the same, whereas misclassifying a photo
as flat produces the smeared, posterised backdrop this module exists to fix.

Two independent things decide it, and either one is enough:

  * **the artwork is continuous-tone** -- a photograph cannot be flat regions.
  * **the upload carries more resolution than the stage** -- the stage is 1024
    wide and the hero is full-bleed, so on any desktop wider than that the traced
    art is magnified (1.37x at 1400 px, 1.88x at 1920 px) and reads soft.  The
    raster is built from the upload, so when the upload is meaningfully wider
    there is real detail to gain by shipping it.  See `MIN_NATIVE_GAIN`.

Two things the raster must get right, and both are easy to get wrong:

  * **The reference's own text must be gone.**  Handing the raw reference to the
    page bakes a copy of the mockup's nav bar, headline and buttons into the
    backdrop, where they sit behind the real DOM copy as ghosts of themselves.
    The glyphs are inpainted out by the tracer (`mkart.py`), so the export is
    taken from the tracer's *prepared* image -- see `export_from_prepared`.
  * **It must come from the original upload, not the normalised reference.**
    `normalize()` aspect-fits every upload onto the 1024x768 stage, discarding
    real resolution (a real upload went 1672x941 -> 1024x576, 61% of its linear
    detail).  So the tracer is fed a native-resolution reference built from the
    upload, and the export inherits that detail.

Everything here is numpy/PIL only -- the studio venv pins no scipy (that lives
in the pipeline venv, a different environment), so the inpainting itself is done
by `mkart.py`, which already runs there.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

# --- detection -------------------------------------------------------------
# How much colour survives downsampling the hero to a small fixed grid, with each
# channel quantised to 5 bits.  Compression noise is high-frequency and
# area-averaging (BOX) removes it, so this is robust across the source formats the
# references actually arrive in (some are JPEG-derived and noisy at 1:1).  The
# grid is FIXED rather than aspect-derived so the score does not drift with the
# hero band's shape -- an aspect-derived width changed a real upload's score by
# 60% for the same artwork.
#
# Measured over every unique reference in the repo: flat art 29-91, photographs
# 245 and 358.  The gap is 2.7x, wide enough that the exact cut is not delicate.
DETECT_GRID = (64, 32)      # width, height of the sample grid
DETECT_SHIFT = 3            # 5 bits per channel
# Biased toward rasterising (see module docstring): a flat design just below the
# cut becomes a WebP that looks identical, which is a cheap mistake; the other
# direction is the expensive one.  Sits between 91 (the most photographic flat
# art measured) and 245 (the least photographic photograph), with ~60% margin.
PHOTO_DISTINCT = 150

# How much more linear resolution than the 1024 px stage the upload must carry
# before the raster is worth shipping for its own sake.
#
# The traced SVG is bounded by the stage; the hero is full-bleed, so at 1400 px
# it is magnified 1.37x and at 1920 px 1.88x, and soft.  A raster built from the
# upload (`native_reference`) has the upload's own detail, so it is ~1:1 at
# 1400 px and downscaled -- crisp -- above that.  This arm exists because the
# colour score is *not* the right question for a dark, glow-heavy design: a real
# upload scored 113 (under the cut) while its artwork-region p95 was 17.3, and a
# raster of the same hero scored 4.7.  There was 1.55x the linear detail sitting
# in the upload, unused.
#
# 1.2 rather than 1.0 so a small rounding gain does not flip a design: at 1024
# px wide the factor is exactly 1.0 and the traced SVG stays.
MIN_NATIVE_GAIN = 1.2

# --- export ----------------------------------------------------------------
# The hero box is `min-height: clamp(460px, 70vh, 680px)` and full-bleed, so a
# 1920 px desktop at 2x wants ~3840 device pixels across.  The export target is
# that width: the prepared image is never upscaled (the source is the real
# ceiling), but a source that has the pixels keeps them instead of being
# downsampled to a cap.  When the source is *below* the target the job records
# the shortfall rather than hiding it -- see `resolution_gap`.  (The target was
# 2880 until the artwork-quality experiment; a 1920 px Retina display is the
# common wide case.)
EXPORT_TARGET_WIDTH = 3840
# The CSS width the hero artwork is actually shown at, for the resolution check.
# Full-bleed takes the viewport; 1920 px is the widest desktop the generated
# pages are budgeted for.  A split illustration is capped by the page CSS at
# `generate.HERO_FIGURE_MAX_CSS` (560 px) -- `doctor polarity` fails if the two
# numbers drift, because this budget must be the *worst case*, not the desktop
# column width.
HERO_CSS_FULL = 1920
HERO_CSS_SPLIT = 560
# The native reference is the stage scaled by a single factor `m`, chosen so the
# upload is shown at its own resolution (`1 / stage_scale`) and capped here: the
# inpainting is a median filter over the whole canvas, so an unbounded `m` buys
# resolution the source does not have at a real cost in time and memory.  4
# covers a 4096 px upload at 1:1; the canvas is then up to 4096x3072 (~12.6 MP)
# and the median-filter inpaint is correspondingly slower.
MAX_NATIVE_SCALE = 4
# WebP only, inlined into the page as a data URI (see `gen-page.mjs`).  Inlining
# both WebP and AVIF would carry both payloads to every visitor for no gain, and
# a `file://` page cannot reference a sibling asset at all; WebP is the right
# single choice.  Moving to external assets with a `<picture>` fallback is the
# natural upgrade when the page is served over HTTP.
WEBP_QUALITY = 82


def hero_slice(arr: np.ndarray, band: list[int] | None) -> np.ndarray:
    """The hero band of a stage-sized array, clamped to it."""
    if not band or len(band) != 2:
        return arr
    y0, y1 = (int(round(v)) for v in band)
    y0 = max(0, min(arr.shape[0] - 1, y0))
    y1 = max(y0 + 1, min(arr.shape[0], y1))
    return arr[y0:y1]


def distinct_colours(patch: np.ndarray) -> int:
    """Distinct 5-bit colours after BOX-downsampling to `DETECT_GRID`."""
    img = Image.fromarray(np.asarray(patch, np.uint8))
    small = np.asarray(img.resize(DETECT_GRID, Image.BOX)).astype(np.int32)
    q = small >> DETECT_SHIFT
    key = (q[..., 0] << 10) | (q[..., 1] << 5) | q[..., 2]
    return int(len(np.unique(key)))


def is_photographic(arr: np.ndarray, band: list[int] | None) -> tuple[bool, int]:
    """Is the hero's backdrop continuous-tone (a photograph)?

    Returns `(verdict, score)` so the caller can log the number that decided it.
    """
    score = distinct_colours(hero_slice(arr, band))
    return score >= PHOTO_DISTINCT, score


def native_factor(stage_scale: float, max_scale: float = MAX_NATIVE_SCALE) -> float:
    """The stage -> native factor `m` (see `native_reference`).

    Split out because the *decision* to rasterise needs `m` before any file is
    written: it is exactly `1 / stage_scale` (the factor that shows the upload at
    its own resolution), capped.
    """
    scale = stage_scale if stage_scale and stage_scale > 0 else 1.0
    return max(1.0, min(1.0 / scale, float(max_scale)))


def needed_width(layout: str) -> int:
    """Device pixels the hero artwork wants at 2x for the layout it ships in."""
    css = HERO_CSS_SPLIT if layout == "split" else HERO_CSS_FULL
    return 2 * css


def resolution_gap(asset_w: int, layout: str) -> tuple[int, float, str | None]:
    """How far the shipped hero asset is from 2x of its rendered size.

    Returns `(needed_px, scale, note)`: `scale > 1` means the asset is magnified
    in device pixels on a Retina display, and `note` is a one-line, honest
    account of it.  The asset is never upscaled beyond the upload's own detail
    (there is nothing to invent), so a shortfall from the *source* is reported
    instead of padded away.
    """
    need = needed_width(layout)
    scale = need / max(1, int(asset_w))
    if scale <= 1.05:
        return need, 1.0, None
    where = ("split illustration" if layout == "split"
             else "full-bleed scene" if layout == "scene"
             else "full-bleed hero")
    return need, scale, (
        f"hero artwork is {asset_w} px wide; a {where} at "
        f"{HERO_CSS_FULL if layout != 'split' else HERO_CSS_SPLIT} CSS px needs "
        f"~{need} px for 2x displays, so it is magnified {scale:.2f}x on Retina "
        f"-- a higher-resolution upload would sharpen it")


def wants_raster(arr: np.ndarray, band: list[int] | None,
                 stage_scale: float) -> tuple[bool, int, float, str]:
    """Should the page ship a raster export of the hero rather than the traced SVG?

    Two independent reasons, either sufficient:

      * the artwork is continuous-tone (`is_photographic`), or
      * the upload carries more resolution than the stage kept
        (`native_factor >= MIN_NATIVE_GAIN`), so a full-bleed hero is magnified
        on any desktop wider than the stage.

    Returns `(verdict, colour_score, m, reason)` so the caller can log which arm
    fired -- a decision this consequential must not be silent.
    """
    photo, score = is_photographic(arr, band)
    m = native_factor(stage_scale)
    gain = m >= MIN_NATIVE_GAIN
    if photo:
        reason = f"photographic (colour score {score} >= {PHOTO_DISTINCT})"
    elif gain:
        reason = (f"flat, but the upload is {m:.2f}x the stage's resolution "
                  f"(colour score {score} < {PHOTO_DISTINCT})")
    else:
        reason = (f"flat artwork at stage resolution (colour score {score} < "
                  f"{PHOTO_DISTINCT}, upload {m:.2f}x the stage)")
    return (photo or gain), score, m, reason


def native_reference(source_png: Path, dest: Path, stage_w: int, stage_h: int,
                     stage_scale: float, stage_offset: tuple[int, int],
                     background: tuple[int, int, int],
                     max_scale: float = MAX_NATIVE_SCALE) -> dict:
    """Write a stage reference built from the original upload at its own scale.

    `normalize()` fits the upload onto the 1024x768 stage with `stage_scale` and
    `stage_offset`, so `stage = source * stage_scale + stage_offset`.  This canvas
    is the stage scaled by a single factor `m`, with the upload pasted at
    `stage_offset * m` and at native size whenever it fits -- so the mapping from
    the stage is exactly `native = stage * m`, and the tracer's existing config
    (box, text rects, blank rects) carries straight over, multiplied by `m`.

    `m` is the largest factor that still shows the upload at its own resolution
    (`1 / stage_scale`), capped at `max_scale`: the inpainting is a median filter
    over the whole canvas, so an unbounded `m` buys resolution the source does not
    have at a real cost in time and memory.

    Returns `{"m", "scale", "size", "offset"}` so the caller can scale the config
    and map back to the stage.
    """
    img = Image.open(source_png).convert("RGB")
    sw, sh = img.size
    m = native_factor(stage_scale, max_scale)
    cw, ch = max(1, round(stage_w * m)), max(1, round(stage_h * m))
    hi = min(cw / sw, ch / sh, 1.0)                 # native, never upscaled
    fw, fh = max(1, round(sw * hi)), max(1, round(sh * hi))
    if (fw, fh) != (sw, sh):
        img = img.resize((fw, fh), Image.LANCZOS)
    ox = max(0, min(cw - fw, int(round(stage_offset[0] * m))))
    oy = max(0, min(ch - fh, int(round(stage_offset[1] * m))))
    canvas = Image.new("RGB", (cw, ch), tuple(int(v) for v in background))
    canvas.paste(img, (ox, oy))
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, "PNG", optimize=True)
    return {"m": m, "scale": hi, "size": (cw, ch), "offset": (ox, oy)}


def scaled_config(base: dict, m: float, ref_rel: str, name: str,
                  size: tuple[int, int]) -> dict:
    """The tracer's config for the native reference: geometry scaled by `m`.

    The box and every exclusion rect are multiplied by `m`; the params (bands,
    despeckle, chroma, the text-inpaint polarity) are copied verbatim, so the
    prepared image is produced by exactly the code path the SVG master uses.
    """
    def scaled(rects: list) -> list:
        return [[round(float(v) * m) for v in r] for r in (rects or [])]

    cfg = dict(base)
    cfg["name"] = name
    cfg["ref"] = ref_rel
    cfg["box"] = [0, 0, size[0], size[1]]
    cfg["text"] = scaled(base.get("text"))
    cfg["blank"] = scaled(base.get("blank"))
    cfg["params"] = dict(base.get("params") or {})
    return cfg


def export_from_prepared(prepared_png: Path, band: list[int] | None, m: float,
                         out_dir: Path, stem: str,
                         export_width: int = EXPORT_TARGET_WIDTH,
                         figure: list[int] | None = None,
                         lossless: bool = False,
                         quality: int = WEBP_QUALITY,
                         upscale: int = 1) -> dict:
    """Crop the hero's pixels out of the prepared (text-removed) reference.

    `band` is in stage coordinates and the prepared image is the stage scaled by
    `m`, so the full-bleed crop is `band * m` across the full width.  When
    `figure` is given -- the illustration's own `[x0, y0, x1, y1]`, stage
    coordinates -- that rectangle is the crop instead.  `lossless` writes a
    lossless WebP (the artwork-quality experiment's isolation mode); the shipped
    page uses the studio quality.  `upscale` is the *rendering* enhancement: a
    Lanczos grow (capped at `export_width`) for display sharpness, which does
    not create source detail -- the manifest's `source_w` is the pre-upscale
    width and is what the resolution warning must use.

    Nothing is ever upscaled past `export_width`, and the width is never grown
    past the prepared image's own size except by `upscale`.  Returns a manifest
    `{"webp": {"name", "w", "h", "source_w", "bytes"}}`, or `{}`.
    """
    img = Image.open(prepared_png).convert("RGB")
    if figure and len(figure) == 4:
        fx0, fy0, fx1, fy1 = (float(v) for v in figure)
        x0 = max(0, int(round(fx0 * m)))
        y0 = max(0, int(round(fy0 * m)))
        x1 = min(img.width, int(round(fx1 * m)))
        y1 = min(img.height, int(round(fy1 * m)))
        if x1 > x0 and y1 > y0:
            img = img.crop((x0, y0, x1, y1))
    elif band and len(band) == 2:
        y0 = max(0, min(img.height - 1, int(round(band[0] * m))))
        y1 = max(y0 + 1, min(img.height, int(round(band[1] * m))))
        img = img.crop((0, y0, img.width, y1))
    w = min(export_width, img.width)
    source_w = w
    h = max(1, round(w * img.height / max(1, img.width)))
    if (w, h) != img.size:
        img = img.resize((w, h), Image.LANCZOS)
    if upscale > 1 and img.width < export_width:
        factor = min(float(upscale), export_width / max(1, img.width))
        if factor > 1.01:
            img = img.resize((max(1, round(img.width * factor)),
                              max(1, round(img.height * factor))), Image.LANCZOS)

    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{stem}.webp"
    if lossless:
        img.save(p, format="WEBP", lossless=True, method=6)
    else:
        img.save(p, quality=quality, method=6)
    if not p.is_file() or not p.stat().st_size:
        return {}
    return {"webp": {"name": p.name, "w": img.width, "h": img.height,
                     "source_w": source_w, "bytes": p.stat().st_size}}
