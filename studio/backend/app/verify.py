"""Self-check: how well the artwork was recovered, and what the page's structure is.

The pixel metric now measures the **artwork region**, not the whole stage.  The
page is a real website whose copy is authored in the site's own type, so grading
it on whole-page pixels would reward imitating the reference's typeface -- which
is exactly the target this project deliberately abandoned.

Two numbers and one structure report:
  * `art_score`  -- mean abs diff over the art region (the text rects masked out)
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


def assess(job_id: str, page: Path, ref_png: Path, *,
           pipeline: Path | None = None, art_svg: Path | None = None,
           layout: str = "poster",
           background: tuple[int, int, int] | None = None) -> dict:
    """Return {art_score, art_pct, whole_score, whole_pct, structure, issues}."""
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
    if box and (box[1] > 0 or box[3] < STAGE_H or box[0] > 0 or box[2] < STAGE_W):
        x0, y0, x1, y1 = box
        art = art[max(0, y0):min(STAGE_H, y1), max(0, x0):min(STAGE_W, x1)]
        if mask is not None:
            mask = mask[max(0, y0):min(STAGE_H, y1), max(0, x0):min(STAGE_W, x1)]
    per_px = art.mean(axis=2)
    if mask is not None and (~mask).any():
        per_px = per_px[~mask]
    out["art_score"] = float(per_px.mean())
    out["art_pct"] = float(100.0 * (per_px > 30).mean())

    try:
        from . import structure as _structure
        info = _structure.inspect(page)
        out["structure"] = info
        out["issues"] = info.get("issues") or []
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
