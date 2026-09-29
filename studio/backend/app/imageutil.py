"""Validate and normalize an uploaded design PNG.

The whole downstream toolchain is hardwired to a 1024x768 stage (`mkart.py`
emits `viewBox="0 0 1024 768"` and the shipped pages are a fixed 1024x768
stage), so every upload is normalized to exactly that: aspect-fit onto a
background-matched canvas.  Doing it here means OCR boxes come back in stage
coordinates and need no rescaling later.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFile

from .config import STAGE_H, STAGE_W

ImageFile.LOAD_TRUNCATED_IMAGES = False

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_SOURCE_PIXELS = 40_000_000
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP", "BMP", "TIFF"}


class UploadError(ValueError):
    """Raised when an upload is not a usable design image."""


@dataclass
class Normalized:
    path: Path          # the written 1024x768 PNG
    src_w: int          # original pixel dimensions (for reporting)
    src_h: int
    scale: float        # how much the source was scaled to fit
    pad: tuple[int, int, int, int]  # left, top, right, bottom padding in stage px
    background: tuple[int, int, int]


def _dominant_border_color(img: Image.Image) -> tuple[int, int, int]:
    """Background colour of the design: the median of the border pixels.

    A flat design's background touches the frame, so the border median is a
    robust estimate; the corner median alone is fragile if a mark bleeds off an
    edge.
    """
    w, h = img.size
    px = img.load()
    samples: list[tuple[int, int, int]] = []
    step = max(1, min(w, h) // 64)
    for x in range(0, w, step):
        samples.append(px[x, 0][:3])
        samples.append(px[x, h - 1][:3])
    for y in range(0, h, step):
        samples.append(px[0, y][:3])
        samples.append(px[w - 1, y][:3])
    if not samples:
        return (0, 0, 0)
    channels = list(zip(*samples))
    return tuple(int(sorted(c)[len(c) // 2]) for c in channels)  # type: ignore[return-value]


def normalize(raw: bytes, dest: Path) -> Normalized:
    """Decode, validate and write a 1024x768 PNG to `dest`."""
    if not raw:
        raise UploadError("empty upload")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise UploadError(f"upload too large (>{MAX_UPLOAD_BYTES // (1024 * 1024)} MB)")

    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception as exc:  # noqa: BLE001 - surface any decode failure to the user
        raise UploadError(f"not a readable image: {exc}") from exc

    if img.format not in ALLOWED_FORMATS:
        raise UploadError(
            f"unsupported format {img.format!r}; use one of {sorted(ALLOWED_FORMATS)}"
        )
    src_w, src_h = img.size
    if src_w < 8 or src_h < 8:
        raise UploadError("image is too small (minimum 8x8)")
    if src_w * src_h > MAX_SOURCE_PIXELS:
        raise UploadError("image is too large (maximum 40 megapixels)")

    img = img.convert("RGB")
    bg = _dominant_border_color(img)

    # Aspect-fit into the fixed stage; never upscale beyond 1x so we do not
    # invent detail the source does not have.
    scale = min(STAGE_W / src_w, STAGE_H / src_h, 1.0)
    fit_w, fit_h = max(1, round(src_w * scale)), max(1, round(src_h * scale))
    if (fit_w, fit_h) != (src_w, src_h):
        img = img.resize((fit_w, fit_h), Image.LANCZOS)

    canvas = Image.new("RGB", (STAGE_W, STAGE_H), bg)
    ox, oy = (STAGE_W - fit_w) // 2, (STAGE_H - fit_h) // 2
    canvas.paste(img, (ox, oy))

    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, "PNG", optimize=True)

    pad = (ox, oy, STAGE_W - fit_w - ox, STAGE_H - fit_h - oy)
    return Normalized(path=dest, src_w=src_w, src_h=src_h, scale=scale,
                      pad=pad, background=bg)
