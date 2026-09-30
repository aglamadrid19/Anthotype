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


def _screenshot(chrome: str, page: Path, out: Path) -> None:
    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=2", "--force-color-profile=srgb",
        "--no-first-run", "--no-default-browser-check", "--disable-http-cache",
        "--incognito", "--window-size=1024,768", "--virtual-time-budget=8000",
        f"--screenshot={out}", page.resolve().as_uri(),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   timeout=120, check=True)
    if not out.is_file() or out.stat().st_size == 0:
        raise RuntimeError("Chrome produced no screenshot")


def _to_stage(png: Path) -> np.ndarray:
    img = Image.open(png).convert("RGB")
    if img.size != (STAGE_W, STAGE_H):
        img = img.resize((STAGE_W, STAGE_H), Image.LANCZOS)
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


def _render_stage(chrome: str, page: Path) -> np.ndarray:
    with tempfile.TemporaryDirectory() as td:
        raw = Path(td) / "shot.png"
        _screenshot(chrome, page, raw)
        # Match the repo's scorer: sRGB conversion (macOS) before downsampling.
        if Path("/usr/bin/sips").is_file() and Path(_SRGB).is_file():
            converted = Path(td) / "shot.srgb.png"
            subprocess.run(["/usr/bin/sips", "--matchTo", _SRGB, str(raw),
                            "--out", str(converted)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           check=False)
            if converted.is_file():
                raw = converted
        return _to_stage(raw)


def _art_page(svg: str, bg: tuple[int, int, int]) -> str:
    """A throwaway page that renders the traced artwork at the reference stage."""
    r, g, b = (max(0, min(255, int(v))) for v in bg)
    return (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        f"html,body{{margin:0;padding:0;background:rgb({r},{g},{b})}}"
        "svg{display:block;width:1024px;height:768px}</style></head>"
        f"<body>{svg}</body></html>")


def _render_art(chrome: str, svg: str, bg: tuple[int, int, int]) -> np.ndarray:
    """The traced artwork alone, rendered at 1024x768.

    A *page* layout reflows: its screenshot is the top of a responsive document,
    not a poster, so comparing it to the reference measures layout, not tracing.
    Rendering the SVG by itself gives the tracer's own fidelity -- which is what
    the art metric is for -- independent of how the page happens to flow.
    """
    with tempfile.TemporaryDirectory() as td:
        html = Path(td) / "art.html"
        html.write_text(_art_page(svg, bg))
        return _render_stage(chrome, html)


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
    # Score the traced SVG itself for a reflowing page; the page screenshot for
    # a fixed poster (where it *is* the artwork's frame).
    if layout == "page" and art_svg and Path(art_svg).is_file():
        bg = background or tuple(int(v) for v in ref[0, 0])
        art = np.abs(ref - _render_art(chrome, Path(art_svg).read_text(), bg))
        out["art_source"] = "svg"
    else:
        art = diff
        out["art_source"] = "page"
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
