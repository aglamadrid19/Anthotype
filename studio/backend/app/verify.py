"""Fidelity self-check: screenshot the built page and score it.

Deliberately the same measurement the repo's `qa/verify.sh` uses -- headless
Chrome at 2x device scale, sRGB, downsample to 1024x768 with PIL Lanczos, then
mean absolute pixel difference against the reference -- so the number the studio
reports means the same thing as the numbers in the README.

This is advisory: a missing Chrome is reported as a warning, not a failure.
"""
from __future__ import annotations

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


def score(job_id: str, page: Path, ref_png: Path) -> tuple[float, float]:
    """Return (mean abs diff, pct of pixels off by >30/255)."""
    chrome = find_chrome()
    if not chrome:
        raise RuntimeError("Chrome not found (set CHROME=...)")

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
        render = _to_stage(raw)

    ref = np.asarray(Image.open(ref_png).convert("RGB")).astype(np.float32)
    diff = np.abs(ref - render)
    return float(diff.mean()), float(100.0 * (diff.mean(axis=2) > 30).mean())
