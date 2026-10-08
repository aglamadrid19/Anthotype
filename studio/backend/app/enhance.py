"""Opt-in Google enhancement of the cleaned scene (preview before accepting).

Off by default.  When `STUDIO_ART_ENHANCE` selects a mode and `GEMINI_API_KEY`
is present, a scene job additionally produces an enhanced *candidate* backdrop
from the LaMa-cleaned artwork -- it is **not** shipped until the user accepts it
(`runner.accept_enhance`, exposed by the studio API).  LaMa/Lanczos remains the
fallback: when this module is off, unconfigured or fails, the job is exactly as
before.

  STUDIO_ART_ENHANCE=google-flash  -> gemini-3.1-flash-image, 4K (default)
  STUDIO_ART_ENHANCE=google-pro    -> gemini-3-pro-image, 4K
  STUDIO_ART_ENHANCE=auto          -> google-flash

Results are cached by `sha256(cleaned PNG) + model + size`, so retries, replays
and acceptance never pay twice.  The accepted asset's provenance keeps the
ORIGINAL upload width (`source_w`) for the resolution warning and records the
model-generated dimensions separately (`generated`) -- a 4K rendition is not
source detail.
"""
from __future__ import annotations

import base64
import hashlib
import json
import math
import os
import time
from pathlib import Path

import httpx
from PIL import Image

from .config import DATA_DIR, STUDIO_DIR

API = "https://generativelanguage.googleapis.com/v1beta/models"
MODELS = {"google-flash": "gemini-3.1-flash-image",
          "google-pro": "gemini-3-pro-image"}
SIZE = "4K"
CACHE = DATA_DIR / "enhance-cache"
PROMPT = (
    "Upscale and enhance this image, preserving it exactly. Keep the composition, "
    "perspective, colours, lighting, gradients and every element where it is. "
    "Every existing text label (including the small dashboard labels, table rows "
    "and the caption at the bottom right) must remain identical and legible. "
    "Do not add any new text, UI controls, buttons, headers or page copy. "
    "Do not remove anything."
)


def _key() -> str:
    env = os.environ.get("GEMINI_API_KEY", "").strip()
    if env:
        return env
    try:
        for line in (STUDIO_DIR / "backend" / ".env").read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def mode() -> str | None:
    """The requested enhancement mode, or None when it is off/unconfigured."""
    requested = os.environ.get("STUDIO_ART_ENHANCE", "").strip().lower()
    if not requested or requested in ("0", "off", "none"):
        return None
    if requested == "auto":
        requested = "google-flash"
    return requested if requested in MODELS else None


def network_forbidden() -> bool:
    """A hard kill switch: no paid provider call, whatever else is set.

    `doctor gate` / `doctor fixtures` set `STUDIO_ART_ENHANCE_NETWORK=forbidden`
    for their duration, so a developer who has the enhancement configured in
    their environment still gets spend-free, deterministic fixture builds.
    """
    return os.environ.get("STUDIO_ART_ENHANCE_NETWORK", "").strip().lower() in (
        "0", "off", "no", "false", "forbidden")


def available() -> bool:
    return (mode() is not None and bool(_key())
            and not network_forbidden())


def cache_key(cleaned_png: Path, model: str) -> str:
    h = hashlib.sha256(cleaned_png.read_bytes()).hexdigest()
    return f"{h[:24]}-{model.split('/')[-1]}-{SIZE.lower()}"


def candidate(cleaned_png: Path, *, timeout: int = 600) -> dict | None:
    """The enhanced candidate for `cleaned_png`, from cache or Google.

    Returns `{"png": path, "meta": {...}}` or None on any failure -- the caller
    keeps the LaMa/Lanczos asset and reports that the enhancement was skipped.
    """
    m = mode()
    if not m or not cleaned_png.is_file() or network_forbidden():
        return None
    model = MODELS[m]
    key = cache_key(cleaned_png, model)
    cache_dir = CACHE / key
    meta_path = cache_dir / "meta.json"
    png_path = cache_dir / "output.png"
    if meta_path.is_file() and png_path.is_file():
        meta = json.loads(meta_path.read_text())
        meta["cached"] = True
        return {"png": png_path, "meta": meta}

    key_str = _key()
    if not key_str:
        return None
    body = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inlineData": {"mimeType": "image/png",
                                "data": base64.b64encode(cleaned_png.read_bytes()).decode()}},
                {"text": PROMPT},
            ],
        }],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"],
                             "imageConfig": {"imageSize": SIZE}},
    }
    t0 = time.time()
    try:
        resp = httpx.post(f"{API}/{model}:generateContent",
                          headers={"x-goog-api-key": key_str,
                                   "Content-Type": "application/json"},
                          json=body, timeout=timeout)
    except httpx.HTTPError as exc:
        print(f"enhance: request failed: {exc}")
        return None
    dt = time.time() - t0
    if resp.status_code != 200:
        print(f"enhance: HTTP {resp.status_code}: {resp.text[:300]}")
        return None
    data = resp.json()
    raw = None
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                raw = base64.b64decode(inline["data"])
    if not raw:
        print("enhance: response carried no image")
        return None
    cache_dir.mkdir(parents=True, exist_ok=True)
    png_path.write_bytes(raw)
    img = Image.open(png_path)
    usage = data.get("usageMetadata") or {}
    image_tokens = sum(d.get("tokenCount", 0)
                       for d in (usage.get("candidatesTokensDetails") or [])
                       if d.get("modality") == "IMAGE")
    meta = {
        "provider": "google",
        "mode": m,
        "model": model,
        "size": SIZE,
        "input_sha256": hashlib.sha256(cleaned_png.read_bytes()).hexdigest(),
        "generated": list(img.size),
        "seconds": round(dt, 1),
        "image_tokens": image_tokens,
        "usage": usage,
        "created": time.time(),
        "cached": False,
    }
    meta_path.write_text(json.dumps(meta, indent=1))
    return {"png": png_path, "meta": meta}


def cover_band(src_png: Path, rows: tuple[float, float],
               background: tuple[int, int, int] | None = None,
               dest: Path | None = None) -> tuple[Path, float]:
    """The enhancement input extended so the band's rows are inside it.

    The hero band is trimmed to the hero box's aspect, so it can extend past
    the upload's own pixels (into the canvas letterbox -- the same pixels the
    fallback export shows there).  Sending the bare upload clamps the crop and
    returns a candidate *shorter* than the fallback's geometry (measured:
    3840x1929 against 3840x2193).  The extension is the design's own background
    colour, not invented content.  Returns `(path, row_offset)`: the band's
    rows in the returned image are `rows + row_offset`.
    """
    img = Image.open(src_png).convert("RGB")
    y0, y1 = rows
    top = max(0, int(math.ceil(-y0))) if y0 < 0 else 0
    bottom = max(0, int(math.ceil(y1)) - img.height)
    if top == 0 and bottom == 0:
        return src_png, 0.0
    bg = tuple(int(v) for v in (background if background is not None
                                else img.getpixel((0, 0))))
    out = Image.new("RGB", (img.width, img.height + top + bottom), bg)
    out.paste(img, (0, top))
    p = dest or src_png.with_name(f"{src_png.stem}-padded.png")
    out.save(p, "PNG")
    return p, float(top)


def band(candidate_png: Path, upload_w: int, band_rows: tuple[int, int],
         width: int) -> Image.Image:
    """The scene band of the candidate, downscaled to `width`.

    The candidate covers the whole upload at its own scale; `band_rows` are the
    scene's rows in the *upload's* coordinates (the caller knows them), and the
    band is left at `width` -- never upscaled past that, and never counted as
    source detail.
    """
    img = Image.open(candidate_png).convert("RGB")
    factor = img.width / max(1, upload_w)
    y0, y1 = (max(0, int(round(r * factor))) for r in band_rows)
    crop = img.crop((0, y0, img.width, min(img.height, y1)))
    w = min(width, crop.width)
    h = max(1, round(w * crop.height / max(1, crop.width)))
    return crop.resize((w, h), Image.LANCZOS)
