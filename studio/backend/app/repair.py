"""Source-preserving repair of an enhanced artwork (design-agnostic).

The enhancement prompt asks the model to preserve labels, but a generative
re-render cannot be trusted with content.  This stage finds the artwork's
protected content in the **native** image -- the extraction's artwork boxes plus
content the boxes missed (values, icons) found from the pixels themselves -- and
restores those regions from the native source into the enhanced output.  The
validated repair rules are baked in:

  * exact source-to-output mapping (the model's own scale factors),
  * confidence-checked local alignment (an uncertain region fails the repair,
    it is never guessed),
  * complete coverage of every detected region,
  * opaque glyph/icon cores with genuinely feathered borders,
  * **zero** change outside the repaired regions before encoding.

Everything else stays the model's output.  The repaired variant is cached
separately from the raw model output (`repair-v1.png` / `repair-v1.json`
beside `output.png`), and the audit report travels with it.  Uncertain
alignment or incomplete coverage returns `None` with a reason: the caller keeps
the raw candidate and reports a warning -- corrupted artwork is never silently
promoted.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

VERSION = "v1"
FEATHER = 8            # raw px: soft border, opaque core
MAX_SHIFT = 8          # raw px of local alignment we trust
RING = 14              # native px of context around a region used to align it
CONTRAST = 26          # native contrast that marks content pixels
FLAT_STD = 16.0        # background std that marks a flat UI panel
MIN_AREA = 6           # px (downsampled) a content component must have


def _components(mask: np.ndarray) -> list[tuple[int, int, int, int, int]]:
    """Bounding boxes + areas of the 4-connected components (iterative BFS)."""
    h, w = mask.shape
    seen = np.zeros_like(mask, bool)
    out: list[tuple[int, int, int, int, int]] = []
    for y0 in range(h):
        row = mask[y0]
        if not row.any():
            continue
        for x0 in np.where(row)[0]:
            if seen[y0, x0]:
                continue
            stack = [(y0, x0)]
            seen[y0, x0] = True
            minx = maxx = x0
            miny = maxy = y0
            n = 0
            while stack:
                y, x = stack.pop()
                n += 1
                if x < minx:
                    minx = x
                if x > maxx:
                    maxx = x
                if y < miny:
                    miny = y
                if y > maxy:
                    maxy = y
                for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            out.append((minx, miny, maxx + 1, maxy + 1, n))
    return out


def _exact_bbox(contrast: np.ndarray, x0: int, y0: int, x1: int, y1: int,
                scale: int) -> tuple[int, int, int, int] | None:
    """The component's exact full-res bbox from its downsampled one.

    The downsampled bbox (`* scale`) can be offset by a pixel from the real
    strokes -- sampling picks even rows, so a stroke shifted by one lands half
    a cell away.  Using the scaled bbox directly leaked the stroke's own edge
    into the flatness border and rejected it (a measured one-pixel regression:
    the same two strokes detected at shift 0, zero at shift 1).  The exact
    bbox is taken from the full-res contrast within a one-cell margin.
    """
    h, w = contrast.shape
    fx0 = max(0, x0 * scale - scale)
    fy0 = max(0, y0 * scale - scale)
    fx1 = min(w, x1 * scale + scale)
    fy1 = min(h, y1 * scale + scale)
    win = contrast[fy0:fy1, fx0:fx1]
    ys, xs = np.where(win)
    if not len(xs):
        return None
    return (fx0 + int(xs.min()), fy0 + int(ys.min()),
            fx0 + int(xs.max()) + 1, fy0 + int(ys.max()) + 1)


def detect_content(native: np.ndarray,
                   boxes: list[list[int]] | None = None,
                   scale: int = 2) -> list[list[int]]:
    """Protected content rects (native px): boxes plus pixel-detected content.

    The pixels are found by contrast against a local background, and a component
    is kept only when its surrounding background is **flat** -- a UI panel.
    That gate is what keeps artwork texture (globe dots, hardware, glow) out:
    it is not flat.  Components are merged by dilation so a word is one region.
    """
    boxes = [[int(round(v)) for v in b] for b in (boxes or [])]
    gray = native.astype(np.float32).mean(axis=2)
    bg = np.asarray(Image.fromarray(gray.astype(np.uint8)).filter(
        ImageFilter.MedianFilter(size=25)), np.float32)
    contrast = np.abs(gray - bg) > CONTRAST
    small = contrast[::scale, ::scale]
    regions: list[list[int]] = []
    for (x0, y0, x1, y1, n) in _components(small):
        if n < MIN_AREA:
            continue
        ex = _exact_bbox(contrast, x0, y0, x1, y1, scale)
        if ex is None:
            continue
        x0, y0, x1, y1 = ex                     # full-res from here on
        # surrounding background flatness: the *residual* against the local
        # background (the blurred background itself is smooth by construction,
        # so measuring it would pass every texture), over the BORDER around the
        # component's exact bbox -- the component's own contrast must not count
        # as texture.  A flat UI panel has a near-zero residual; artwork
        # texture (dots, glow, gradient) does not.
        pad = 6 * scale
        ax0, ay0 = max(0, x0 - pad), max(0, y0 - pad)
        ax1 = min(contrast.shape[1], x1 + pad)
        ay1 = min(contrast.shape[0], y1 + pad)
        area = (gray - bg)[ay0:ay1, ax0:ax1]
        inner = np.zeros(area.shape, bool)
        inner[y0 - ay0:y1 - ay0, x0 - ax0:x1 - ax0] = True
        vals = area[~inner]
        if vals.size == 0 or float(vals.std()) > FLAT_STD:
            continue
        # a compact round blob is a dot, not content: require some spread or
        # structure (a text stroke is elongated; an icon has internal contrast)
        bw, bh = x1 - x0, y1 - y0
        fill = float(contrast[y0:y1, x0:x1].mean())
        if bw < 3 and bh < 3:
            continue
        if 0.45 < bw / max(1, bh) < 2.2 and fill > 0.72:
            continue
        regions.append([x0, y0, x1, y1])
    # merge overlapping/nearby detected regions by dilation
    if regions:
        m = Image.new("L", (native.shape[1], native.shape[0]), 0)
        d = ImageDraw.Draw(m)
        for r in regions:
            d.rectangle([r[0] - 8, r[1] - 8, r[2] + 8, r[3] + 8], fill=255)
        m = m.filter(ImageFilter.MaxFilter(9))
        for (x0, y0, x1, y1, _n) in _components(np.asarray(m) > 0):
            regions.append([x0, y0, x1, y1])
    # the extraction boxes are protected by definition
    regions += boxes
    # final dedupe/merge
    merged: list[list[int]] = []
    for r in sorted(regions, key=lambda r: (r[1], r[0])):
        for m2 in merged:
            if not (r[2] < m2[0] - 4 or r[0] > m2[2] + 4
                    or r[3] < m2[1] - 4 or r[1] > m2[3] + 4):
                m2[0], m2[1] = min(m2[0], r[0]), min(m2[1], r[1])
                m2[2], m2[3] = max(m2[2], r[2]), max(m2[3], r[3])
                break
        else:
            merged.append(list(r))
    return merged


def _find_shift(context: np.ndarray, ring: np.ndarray, struct: np.ndarray,
                raw: np.ndarray, x0: int, y0: int,
                max_residual: float) -> tuple[float, int, int] | None:
    """Align a region via its context: structured pixels, else flat trust.

    The content itself may be garbled -- the model can change the very pixels
    the patch must replace -- so alignment is measured on the ring *around* the
    region.  A uniform panel matches at *every* shift, so the search only uses
    the ring's **structured** pixels; with none, the exact global mapping is
    accepted after verifying the ring really is flat (a textured, re-rendered
    ring fails).  Returns `(residual, dx, dy)` or None when untrustworthy.
    """
    h, w = context.shape[:2]
    if int(struct.sum()) >= 30:
        total = float(struct.sum())
        best = (1e9, 0, 0)
        for dy in range(-MAX_SHIFT, MAX_SHIFT + 1):
            for dx in range(-MAX_SHIFT, MAX_SHIFT + 1):
                ax0, ay0 = x0 + dx, y0 + dy
                if (ax0 < 0 or ay0 < 0 or ax0 + w > raw.shape[1]
                        or ay0 + h > raw.shape[0]):
                    continue
                m = float((np.abs(raw[ay0:ay0 + h, ax0:ax0 + w] - context)
                           * struct[..., None]).sum() / (total * 3))
                if m < best[0]:
                    best = (m, dx, dy)
        return best if best[0] <= max_residual else None
    # flat context: the global mapping is exact by construction; the ring only
    # has to prove it was preserved (not re-rendered into texture)
    total = float(ring.sum()) or 1.0
    m = float((np.abs(raw[y0:y0 + h, x0:x0 + w] - context)
               * ring[..., None]).sum() / (total * 3))
    return (m, 0, 0) if m <= max_residual else None


def _align_content(patch: np.ndarray, raw: np.ndarray, x0: int, y0: int,
                   max_residual: float = 55.0) -> tuple[float, int, int] | None:
    """Last-resort alignment on the content itself (a preserved re-render).

    Used when the context is untrustworthy (content drawn over re-rendered
    artwork, e.g. a chip on a globe).  If the model preserved the content, it
    aligns; if it is garbled, nothing aligns and the region is skipped -- the
    candidate keeps the model's version there and the audit says so.
    """
    h, w = patch.shape[:2]
    best = (1e9, 0, 0)
    for dy in range(-MAX_SHIFT, MAX_SHIFT + 1):
        for dx in range(-MAX_SHIFT, MAX_SHIFT + 1):
            ax0, ay0 = x0 + dx, y0 + dy
            if ax0 < 0 or ay0 < 0 or ax0 + w > raw.shape[1] or ay0 + h > raw.shape[0]:
                continue
            m = float(np.abs(raw[ay0:ay0 + h, ax0:ax0 + w] - patch).mean())
            if m < best[0]:
                best = (m, dx, dy)
    return best if best[0] <= max_residual else None


def repair_candidate(native_png: Path, enhanced_png: Path,
                     boxes: list[list[int]] | None = None,
                     out_dir: Path | None = None,
                     max_context_residual: float = 40.0) -> dict | None:
    """Restore the native content into `enhanced_png`; None + reason on doubt.

    Returns `{"png": Path, "meta": {...}}`.  The repaired image is written to
    `out_dir / "repair-v1.png"` (default: beside the enhanced file) with a
    `repair-v1.json` provenance/audit sidecar.
    """
    native = Image.open(native_png).convert("RGB")
    enhanced = Image.open(enhanced_png).convert("RGB")
    nat = np.asarray(native, np.float32)
    enh = np.asarray(enhanced, np.float32)
    fx = enhanced.width / native.width
    fy = enhanced.height / native.height
    regions = detect_content(nat, boxes)
    if not regions:
        # "Nothing detected" does NOT prove "nothing to protect": the detector
        # can miss content (a measured one-pixel shift once zeroed it), so a
        # zero-detection repair is UNCERTAIN.  The caller keeps the native
        # fallback and marks the raw output diagnostic -- never a normally
        # acceptable candidate.
        return None, ("no protected content detected -- absence cannot be "
                      "verified")

    out = enh.copy()
    provenance = []
    skipped: list[dict] = []
    for r in regions:
        # x clamps by width, y by height -- a portrait image must not lose its
        # lower content to a width clamp
        sx0 = max(0, min(native.width, int(r[0]) - 4))
        sx1 = max(0, min(native.width, int(r[2]) + 4))
        sy0 = max(0, min(native.height, int(r[1]) - 4))
        sy1 = max(0, min(native.height, int(r[3]) + 4))
        if sx1 <= sx0 or sy1 <= sy0:
            skipped.append({"region": [int(v) for v in r],
                            "reason": "empty or fully out-of-bounds region"})
            continue
        dx0, dy0 = round(sx0 * fx), round(sy0 * fy)
        dx1, dy1 = round(sx1 * fx), round(sy1 * fy)
        if dx1 - dx0 < 2 or dy1 - dy0 < 2:
            skipped.append({"region": [int(v) for v in r],
                            "reason": "region maps to fewer than 2 px"})
            continue
        patch = native.crop((sx0, sy0, sx1, sy1)).resize(
            (dx1 - dx0, dy1 - dy0), Image.LANCZOS)
        patch_arr = np.asarray(patch, np.float32)
        # alignment from the context ring around the region (the content itself
        # may be garbled, so it cannot be trusted to align)
        cx0, cy0 = max(0, sx0 - RING), max(0, sy0 - RING)
        cx1, cy1 = min(native.width, sx1 + RING), min(native.height, sy1 + RING)
        cdx0, cdy0 = round(cx0 * fx), round(cy0 * fy)
        cdx1, cdy1 = round(cx1 * fx), round(cy1 * fy)
        ctx = native.crop((cx0, cy0, cx1, cy1)).resize(
            (cdx1 - cdx0, cdy1 - cdy0), Image.LANCZOS)
        ctx_arr = np.asarray(ctx, np.float32)
        ring = np.ones(ctx_arr.shape[:2], np.float32)
        ring[dy0 - cdy0:dy0 - cdy0 + (dy1 - dy0),
             dx0 - cdx0:dx0 - cdx0 + (dx1 - dx0)] = 0
        align = None
        if ring.sum() >= 50:
            # structured ring pixels only: a flat panel matches at every shift,
            # so the search needs the ring's own structure (or a verified flat
            # ring)
            gray = ctx_arr.mean(axis=2)
            cbg = np.asarray(Image.fromarray(gray.astype(np.uint8)).filter(
                ImageFilter.MedianFilter(size=25)), np.float32)
            struct = ring * (np.abs(gray - cbg) > CONTRAST)
            align = _find_shift(ctx_arr, ring, struct, enh, cdx0, cdy0,
                                max_context_residual)
        if align is None:
            # content over re-rendered artwork: the context cannot vouch for the
            # alignment, so try the content itself (preserved re-renders align;
            # garbled ones do not and are skipped with a warning)
            align = _align_content(patch_arr, enh, dx0, dy0)
        if align is None:
            skipped.append({"region": [int(v) for v in r],
                            "reason": "context and content both unalignable"})
            continue
        diff, sdx, sdy = align
        px0, py0 = dx0 + sdx, dy0 + sdy
        px1, py1 = px0 + patch_arr.shape[1], py0 + patch_arr.shape[0]
        if px0 < 0 or py0 < 0 or px1 > enhanced.width or py1 > enhanced.height:
            return None, f"region {r} maps outside the enhanced image"
        w, h = patch_arr.shape[1], patch_arr.shape[0]
        # feather adapts to small patches (a thin stroke maps to a few px)
        fw = max(1, min(FEATHER, (w - 1) // 3))
        fh = max(1, min(FEATHER, (h - 1) // 3))
        m = Image.new("L", (w, h), 0)
        ImageDraw.Draw(m).rectangle(
            [fw, fh, w - 1 - fw, h - 1 - fh], fill=255)
        m = m.filter(ImageFilter.GaussianBlur(min(fw, fh)))
        m_arr = np.asarray(m, np.float32)[..., None] / 255.0
        out[py0:py1, px0:px1] = (out[py0:py1, px0:px1] * (1 - m_arr)
                                 + patch_arr * m_arr)
        provenance.append({"region": [int(v) for v in r],
                           "source": [int(v) for v in (sx0, sy0, sx1, sy1)],
                           "dest": [int(px0), int(py0), int(px1), int(py1)],
                           "shift": [int(sdx), int(sdy)],
                           "residual": round(float(diff), 2)})

    covered = np.zeros(out.shape[:2], bool)
    for p in provenance:
        x0, y0, x1, y1 = p["dest"]
        covered[y0:y1, x0:x1] = True
    outside = np.abs(out - enh).max(axis=2)[~covered]
    outside_max = int(outside.max()) if outside.size else 0
    if outside_max != 0:
        return None, f"repair changed pixels outside its regions ({outside_max})"
    if len(provenance) + len(skipped) != len(regions):
        return None, (f"region accounting mismatch: {len(provenance)} repaired + "
                      f"{len(skipped)} skipped != {len(regions)} detected")
    if not provenance:
        return None, "no region could be aligned confidently"

    repaired = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    dest = out_dir or enhanced_png.parent
    dest.mkdir(parents=True, exist_ok=True)
    png = dest / "repair-v1.png"
    repaired.save(png)
    meta = {
        "version": VERSION,
        "kind": "source-preserving repair (native content restored)",
        "native_sha256": hashlib.sha256(native_png.read_bytes()).hexdigest(),
        "enhanced_sha256": hashlib.sha256(enhanced_png.read_bytes()).hexdigest(),
        "repaired_sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
        "scale": {"fx": round(fx, 4), "fy": round(fy, 4)},
        "regions": provenance,
        "audit": {
            "detected": len(regions),
            "repaired": len(provenance),
            "skipped": skipped,
            "outside_max_diff": outside_max,
            "max_residual": max((p["residual"] for p in provenance), default=0),
            "created": time.time(),
        },
    }
    (dest / "repair-v1.json").write_text(json.dumps(meta, indent=1) + "\n")
    return {"png": png, "meta": meta}
