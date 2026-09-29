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
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .config import vision

ROLES = {"headline", "subhead", "tagline", "cta", "brand", "other"}

SYSTEM_PROMPT = (
    "You are a meticulous UI reverse-engineer. You are shown a flat design "
    "mockup of a web page. Extract every piece of visible TEXT, exactly as "
    "written, and report it as JSON.\n\n"
    "For each text block give:\n"
    '  "text": the exact string (no commentary),\n'
    '  "role": one of headline | subhead | tagline | cta | brand | other,\n'
    '  "bbox": [x0, y0, x1, y1] in pixels of the image you are shown.\n\n'
    "Rules:\n"
    "- bbox must tightly enclose the visible glyphs, not the surrounding space.\n"
    "- role headline = the largest/most prominent title; subhead = a secondary "
    "line directly under it; tagline = body/supporting sentence; cta = the "
    "label inside a button; brand = a logo wordmark.\n"
    "- Do NOT transcribe decorative artwork, icons or shapes as text.\n"
    "- If a block wraps across several lines, report it as ONE block whose bbox "
    "spans all its lines.\n"
    "- Output ONLY a JSON object of the form "
    '{"blocks": [{"text": "...", "role": "...", "bbox": [0,0,0,0]}]}. '
    "No markdown, no commentary."
)


@dataclass
class Block:
    text: str
    role: str
    bbox: tuple[float, float, float, float]
    color: tuple[int, int, int] | None = None      # ink colour (sampled locally)
    fill: tuple[int, int, int] | None = None       # CTA button fill (sampled locally)
    meta: dict = field(default_factory=dict)


class ExtractError(RuntimeError):
    pass


def _data_uri(png: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(png.read_bytes()).decode()


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
        out.append(Block(text=text_val, role=role if role in ROLES else "other",
                         bbox=(x0, y0, x1, y1)))
    return out


def _openai(png: Path) -> str:
    payload = {
        "model": vision.model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": "Extract the text blocks."},
                {"type": "image_url", "image_url": {"url": _data_uri(png)}},
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


def _anthropic(png: Path) -> str:
    payload = {
        "model": vision.model,
        "max_tokens": 2048,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": _data_uri(png).split(",", 1)[1]}},
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

    raw = _anthropic(png) if provider == "anthropic" else _openai(png)
    blocks = _parse_blocks(raw)
    if not blocks:
        raise ExtractError("the model found no text blocks in this design")
    return blocks
