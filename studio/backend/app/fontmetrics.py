"""Real Inter metrics, read from the fonts the page actually inlines.

The generated layout must be *measurable*, not guessed.  A vision model returns
boxes, not font sizes, and converting a box to a font-size by height alone is
badly wrong (a text box is the line box, not the cap height).  Instead the text
is set `white-space: nowrap` and its font-size is solved from the box **width**
against the real advance widths of the vendored Inter, so the rendered line
lands exactly where the model saw it.

The same metrics give the ascent/descent needed to position a line vertically
under its glyph box.
"""
from __future__ import annotations

from functools import lru_cache

from fontTools.ttLib import TTFont

from .config import PIPELINE_DIR

FONT_DIR = PIPELINE_DIR / "fonts"
DEFAULT_WEIGHT = 400
FALLBACK_CAP_EM = 0.727


@lru_cache(maxsize=8)
def _font(weight: int) -> TTFont:
    path = FONT_DIR / f"inter-latin-{weight}-normal.woff2"
    if not path.is_file():
        path = FONT_DIR / f"inter-latin-{DEFAULT_WEIGHT}-normal.woff2"
    return TTFont(str(path))


def available() -> bool:
    return (FONT_DIR / f"inter-latin-{DEFAULT_WEIGHT}-normal.woff2").is_file()


def text_width_em(text: str, weight: int = DEFAULT_WEIGHT) -> float:
    """Advance width of `text` in em (1.0 = one font-size)."""
    font = _font(weight)
    upm = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    hmtx = font["hmtx"]
    space = cmap.get(0x20)
    total = 0
    for ch in text:
        gname = cmap.get(ord(ch)) or space
        if gname is None:
            continue
        total += hmtx[gname][0]
    return total / upm


def cap_height_em(weight: int = DEFAULT_WEIGHT) -> float:
    font = _font(weight)
    upm = font["head"].unitsPerEm
    os2 = font.get("OS/2")
    cap = getattr(os2, "sCapHeight", 0) if os2 else 0
    return (cap / upm) if cap else FALLBACK_CAP_EM


def _vmetrics_em(weight: int = DEFAULT_WEIGHT) -> tuple[float, float]:
    """(ascent, descent) in em, from hhea (what a line box uses)."""
    font = _font(weight)
    upm = font["head"].unitsPerEm
    hhea = font["hhea"]
    return hhea.ascent / upm, abs(hhea.descent) / upm


def fit_font_size(text: str, box_w: float, box_h: float, role: str,
                  weight: int = DEFAULT_WEIGHT) -> float:
    """Font-size (px) that makes `text` occupy `box_w` when set nowrap.

    Falls back to a height estimate when there is no text to measure.
    """
    if text and box_w > 1:
        w_em = text_width_em(text, weight)
        if w_em > 0:
            return max(8.0, min(400.0, box_w / w_em))
    # No text (or no width): approximate from the box height.
    return max(11.0, min(220.0, box_h / cap_height_em(weight)))


def cap_top_offset(fs: float, weight: int = DEFAULT_WEIGHT) -> float:
    """Pixels from the top of a `line-height: 1` line box to the cap top.

    Lets a block be positioned so its *glyphs* align with the box the model
    reported, instead of the line box hanging above it.
    """
    ascent, descent = _vmetrics_em(weight)
    line = fs                                    # line-height: 1
    glyph_h = (ascent + descent) * fs
    glyph_top_in_line = (line - glyph_h) / 2.0   # half-leading
    cap_top_in_glyph = (ascent - cap_height_em(weight)) * fs
    return glyph_top_in_line + cap_top_in_glyph
