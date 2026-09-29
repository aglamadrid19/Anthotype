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
from .fontmetrics import cap_top_offset, fit_font_size

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
    # Sanity: the button must contain the label and be a plausible size.
    if bw < (x1 - x0) or bh < (y1 - y0) or bw > 4 * (x1 - x0) + 80:
        return bbox
    return (wx0 + fx0, wy0 + fy0, wx0 + fx1, wy0 + fy1)


def estimate_font_size(block: Block, weight: int = 400) -> float:
    """Font-size solved from the block's box width against real Inter metrics."""
    x0, y0, x1, y1 = block.bbox
    return fit_font_size(block.text, x1 - x0, y1 - y0, block.role, weight)


def _hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def _role_rank(role: str) -> int:
    return {"brand": 0, "headline": 1, "subhead": 2, "tagline": 3,
            "cta": 4, "other": 5}.get(role, 5)


def decorate(blocks: list[Block], ref_png: Path,
             background: tuple[int, int, int]) -> list[Block]:
    """Fill in each block's ink colour (and a CTA's fill) from the reference."""
    arr = _as_array(ref_png)
    for b in blocks:
        if b.role == "cta":
            x0, y0, x1, y1 = b.bbox
            pad = 80
            win = (max(0, x0 - pad), max(0, y0 - pad),
                   min(STAGE_W, x1 + pad), min(STAGE_H, y1 + pad))
            # The label box is mostly label, so the fill must be sampled from a
            # wider window where the button dominates.
            b.fill = sample_fill(arr, win, background)
            b.color = sample_contrast(arr, b.bbox, b.fill)
            # Keep the label box (font-size comes from it) and grow the block to
            # the real button so the DOM button and its exclusion rect match.
            b.meta["label_bbox"] = b.bbox
            b.bbox = refine_button_bbox(arr, b.bbox, b.fill)
        else:
            b.color = sample_ink(arr, b.bbox, background)
    return blocks


def _element(block: Block, i: int) -> str:
    tag = {"headline": "h1", "subhead": "h2", "tagline": "p",
           "brand": "div", "cta": "a"}.get(block.role, "p")
    cls = f"blk blk-{i}"
    text = html.escape(block.text)
    if tag == "a":
        return f'<a class="{cls} cta" href="#">{text}</a>'
    return f'<{tag} class="{cls}">{text}</{tag}>'


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
    lines = [
        ":root { color-scheme: dark; }",
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
            fs = fit_font_size(b.text, (b.meta.get("label_bbox") or b.bbox)[2]
                               - (b.meta.get("label_bbox") or b.bbox)[0],
                               y1 - y0, b.role, weight)
            color = _hex(b.color or (255, 255, 255))
            fill = _hex(b.fill or (24, 196, 124))
            left, top = x0, y0
            bw, bh = x1 - x0, y1 - y0
            lines += [
                f".blk-{i} {{ left: {left:.0f}px; top: {top:.0f}px; width: {bw:.0f}px;",
                f"  height: {bh:.0f}px; display: inline-flex; align-items: center;",
                f"  justify-content: center; border-radius: 14px; text-decoration: none;",
                f"  background: {fill}; color: {color}; font-size: {fs:.1f}px; font-weight: {weight}; }}",
            ]
        else:
            weight = 400
            fs = estimate_font_size(b, weight)
            color = _hex(b.color or (255, 255, 255))
            top = max(0.0, y0 - cap_top_offset(fs, weight))
            lines.append(
                f".blk-{i} {{ left: {x0:.0f}px; top: {top:.1f}px; "
                f"font-size: {fs:.1f}px; font-weight: {weight}; color: {color}; }}"
            )
    return "\n".join(lines) + "\n"


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
    cfg["params"].update({
        "exclude_text": True, "text_lum_max": 200.0, "cumulative": True,
    })
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n")
    return content
