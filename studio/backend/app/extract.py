"""Extract the text layer from a design PNG with a vision LLM.

The design reference is a flat raster concept: the pipeline recovers its
*geometry* by tracing, but the words are a separate layer that must be authored.
This module asks a vision model for the words, their roles and their bounding
boxes, in stage coordinates.

Three consumers depend on the result:
  * the copy itself (headline / tagline / CTA),
  * the per-block layout CSS (`generate.py`), and
  * the `text` exclusion rects `mkart.py` needs, so the trace does not bake a
    rasterised copy of the words into the artwork.

Providers:
  * `openai`    -- any OpenAI-compatible /chat/completions endpoint (default)
  * `anthropic` -- the Anthropic /v1/messages API
  * `stub`      -- no network; returns no text blocks.  Used to exercise the
                   whole pipeline offline (art-only page) and in tests.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .config import vision

ROLES = {"headline", "subhead", "tagline", "cta", "brand", "other"}
PARTS = {"page", "artwork"}

SYSTEM_PROMPT = (
    "You are a meticulous UI reverse-engineer. You are shown a flat design "
    "mockup of a web page. Extract every piece of visible TEXT, exactly as "
    "written, and report it as JSON.\n\n"
    "For each text block give:\n"
    '  "text": the exact string (no commentary),\n'
    '  "role": one of headline | subhead | tagline | cta | brand | other,\n'
    '  "part": one of page | artwork,\n'
    '  "bbox": [x0, y0, x1, y1] in pixels of the image you are shown.\n\n'
    "Rules:\n"
    "- bbox must tightly enclose the visible glyphs, not the surrounding space.\n"
    "- role headline = the largest/most prominent title; subhead = a secondary "
    "line directly under it; tagline = body/supporting sentence; cta = the "
    "label inside a button; brand = a logo wordmark.\n"
    "- part page = the page's own copy (title, navigation, body, button labels, "
    "footer). part artwork = text that is part of an illustration, a device "
    "mockup, a screenshot or a product card in the design.\n"
    "- Do NOT transcribe decorative artwork, icons or shapes as text.\n"
    "- If a block wraps across several lines, report it as ONE block whose bbox "
    "spans all its lines.\n"
    "- Output ONLY a JSON object of the form "
    '{"blocks": [{"text": "...", "role": "...", "part": "...", '
    '"bbox": [0,0,0,0]}]}. '
    "No markdown, no commentary."
)

# A labelled coordinate grid is overlaid on the image before it is sent.  Boxes
# read off a plain mockup are badly biased -- on the shipped references the
# model put the headline tens of pixels below its true position, and moved it
# again between identical calls -- which then misplaces the whole DOM text
# layer.  With grid lines every 64 px the same model returns boxes within a few
# pixels of the real ink, repeatably.
GRID_STEP = 64
GRID_NOTE = (
    f"\n- The image is overlaid with magenta grid lines every {GRID_STEP} px, "
    "each labelled with its pixel coordinate. Use those labels to report bbox "
    "in image pixels. The grid is a measurement aid: never transcribe the "
    "labels or treat the lines as artwork."
)


@dataclass
class Block:
    text: str
    role: str
    bbox: tuple[float, float, float, float]
    part: str = "page"                             # page copy | artwork
    color: tuple[int, int, int] | None = None      # ink colour (sampled locally)
    fill: tuple[int, int, int] | None = None       # CTA button fill (sampled locally)
    runs: list[tuple[str, tuple[int, int, int]]] = field(default_factory=list)
    meta: dict = field(default_factory=dict)


class ExtractError(RuntimeError):
    pass


def _gridded_data_uri(png: Path, step: int = GRID_STEP) -> str:
    """Data URI with a labelled coordinate grid overlaid, as WebP.

    See GRID_NOTE: the grid is what makes the model's bboxes accurate.

    The encoding matters.  A full-size PNG of the grid is ~1 MB, and the local
    proxy silently drops images at that size (the model then correctly reports
    that no image arrived).  WebP is visually lossless at this scale and roughly
    an eighth of the size, which the proxy delivers every time.
    """
    from PIL import Image, ImageDraw

    img = Image.open(png).convert("RGB").copy()
    d = ImageDraw.Draw(img)
    for x in range(0, img.width, step):
        d.line([(x, 0), (x, img.height)], fill=(255, 0, 255), width=1)
        d.text((x + 2, 2), str(x), fill=(255, 255, 0))
    for y in range(0, img.height, step):
        d.line([(0, y), (img.width, y)], fill=(255, 0, 255), width=1)
        d.text((2, y + 2), str(y), fill=(255, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="WEBP", quality=88, method=4)
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def _parse_blocks(raw: str) -> list[Block]:
    """Parse the model's reply into Blocks, tolerating fences and prose."""
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ExtractError(f"model did not return JSON: {raw[:300]!r}")
        data = json.loads(m.group(0))

    items = data.get("blocks") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ExtractError(f"unexpected JSON shape: {raw[:300]!r}")

    out: list[Block] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        text_val = str(it.get("text", "")).strip()
        bbox = it.get("bbox")
        if not text_val or not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
            continue
        try:
            x0, y0, x1, y1 = (float(v) for v in bbox)
        except (TypeError, ValueError):
            continue
        if x1 < x0:
            x0, x1 = x1, x0
        if y1 < y0:
            y0, y1 = y1, y0
        role = str(it.get("role", "other")).strip().lower()
        part = str(it.get("part", "page")).strip().lower()
        out.append(Block(text=text_val, role=role if role in ROLES else "other",
                         bbox=(x0, y0, x1, y1),
                         part=part if part in PARTS else "page"))
    return out


def _chat_once(model: str, png: Path) -> str:
    """One OpenAI-compatible vision call.  Raises ExtractError on any failure."""
    payload = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + GRID_NOTE},
            {"role": "user", "content": [
                {"type": "text", "text": "Extract the text blocks."},
                {"type": "image_url", "image_url": {"url": _gridded_data_uri(png)}},
            ]},
        ],
    }
    resp = httpx.post(
        f"{vision.base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {vision.api_key}"},
        json=payload, timeout=300,
    )
    if resp.status_code >= 400:
        raise ExtractError(f"vision API {resp.status_code}: {resp.text[:400]}")
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError) as exc:
        raise ExtractError(f"unexpected response shape: {str(data)[:300]}") from exc


def _openai(png: Path) -> str:
    """Call the configured model, falling back to the next candidate on failure.

    On a peer-to-peer marketplace a request can fail for reasons that have
    nothing to do with the request -- the chosen peer does not serve the model,
    is offline, or is out of credit.  Retrying the same model can land on the
    same bad peer, so the fallbacks are *different* models that are known to
    handle this task; the first reply that parses wins.
    """
    tried: list[str] = []
    for model in vision.models:
        try:
            return _chat_once(model, png)
        except (ExtractError, httpx.HTTPError) as exc:
            tried.append(f"{model}: {exc}")
            continue
    raise ExtractError("no vision model answered -- " + " | ".join(tried))


def _anthropic(png: Path) -> str:
    payload = {
        "model": vision.model,
        "max_tokens": 2048,
        "system": SYSTEM_PROMPT + GRID_NOTE,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/webp",
                                         "data": _gridded_data_uri(png).split(",", 1)[1]}},
            {"type": "text", "text": "Extract the text blocks."},
        ]}],
    }
    resp = httpx.post(
        f"{vision.base_url.rstrip('/')}/v1/messages",
        headers={"x-api-key": vision.api_key, "anthropic-version": "2023-06-01"},
        json=payload, timeout=120,
    )
    if resp.status_code >= 400:
        raise ExtractError(f"vision API {resp.status_code}: {resp.text[:400]}")
    parts = resp.json().get("content", [])
    return "".join(p.get("text", "") for p in parts if p.get("type") == "text")


def normalize_roles(blocks: list[Block]) -> list[Block]:
    """Make the roles consistent with the blocks' relative size.

    The model is not stable about which line is the headline: on the same image
    it labels the largest title "headline" on one call and "brand" on the next.
    A brand wordmark is always *small*, so any block the model called `brand`
    that is actually one of the largest lines is promoted to `headline`.  Roles
    drive both the element (`h1` vs `div`) and the type scale, so this matters
    more than the label alone suggests.
    """
    sized = [b for b in blocks if b.text]
    if not sized:
        return blocks
    heights = sorted((b.bbox[3] - b.bbox[1]) for b in sized)
    tallest = heights[-1]
    if tallest <= 0:
        return blocks
    for b in blocks:
        h = b.bbox[3] - b.bbox[1]
        if b.role == "brand" and h >= 0.7 * tallest:
            b.role = "headline"
    return blocks


def extract(png: Path) -> list[Block]:
    """Return the text blocks for `png` (stage coordinates)."""
    # Development seam: a JSON file of blocks to use instead of calling a model.
    # Lets the full text path (layout + exclusion rects + scoring) be exercised
    # with no API key.  Never set in normal use.
    fake = os.environ.get("STUDIO_FAKE_BLOCKS")
    if fake and Path(fake).is_file():
        data = json.loads(Path(fake).read_text())
        items = data.get("blocks", data) if isinstance(data, dict) else data
        return [Block(text=str(b["text"]), role=str(b.get("role", "other")),
                      bbox=tuple(float(v) for v in b["bbox"])) for b in items]

    provider = vision.provider.lower()

    if provider == "stub":
        return []
    if not vision.configured:
        raise ExtractError(
            "vision model is not configured: set VISION_PROVIDER, VISION_MODEL "
            "and VISION_API_KEY in studio/backend/.env (or use VISION_PROVIDER=stub)"
        )

    # The proxy occasionally drops the image and the model then (correctly)
    # refuses to invent boxes.  That is a transport failure, not a design with
    # no text, so retry before giving up.
    last: Exception | None = None
    for attempt in range(3):
        raw = _anthropic(png) if provider == "anthropic" else _openai(png)
        try:
            blocks = _parse_blocks(raw)
        except ExtractError as exc:
            last = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
            continue
        if blocks:
            return normalize_roles(blocks)
        last = ExtractError("the model found no text blocks in this design")
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    raise last or ExtractError("the model found no text blocks in this design")
