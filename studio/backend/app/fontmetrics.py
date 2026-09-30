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
# Typical line advance of the reference designs, as a multiple of the font-size.
# Only used to disambiguate a wrapped block: the reference's line spacing is the
# one clue the box gives about how many lines a multi-line block has.
LINE_LEADING = 1.35


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


def char_at_x_fraction(text: str, frac: float, weight: int = DEFAULT_WEIGHT) -> int:
    """Index of the character whose advance interval contains `frac` of the line.

    Lets a measured pixel boundary inside a text box be turned into a split
    point in the string (e.g. white "Ant" then green "Hosting"): the characters
    before the returned index are the first run.
    """
    if frac <= 0:
        return 0
    total = text_width_em(text, weight)
    if total <= 0:
        return 0
    acc = 0.0
    for i, ch in enumerate(text):
        acc += text_width_em(ch, weight)
        if acc / total > frac:
            return i
    return len(text)


def ink_height_em(text: str, weight: int = DEFAULT_WEIGHT) -> float:
    """Height of the glyphs `text` actually draws, in em.

    The box a vision model reports is the *ink* box, so this is what a
    box-height estimate must divide by -- using the cap height alone is wrong
    for any string with a descender ("Hosting") or a tall lowercase letter.
    """
    font = _font(weight)
    upm = font["head"].unitsPerEm
    cmap = font.getBestCmap()
    glyf = font.get("glyf")
    if glyf is None:
        return cap_height_em(weight)
    top = bottom = None
    for ch in text:
        gname = cmap.get(ord(ch))
        if gname is None:
            continue
        glyph = glyf[gname]
        if glyph.numberOfContours == 0:
            continue
        top = glyph.yMax if top is None else max(top, glyph.yMax)
        bottom = glyph.yMin if bottom is None else min(bottom, glyph.yMin)
    if top is None or bottom is None:
        return cap_height_em(weight)
    return (top - bottom) / upm


def cap_height_em(weight: int = DEFAULT_WEIGHT) -> float:
    font = _font(weight)
    upm = font["head"].unitsPerEm
    os2 = font.get("OS/2")
    cap = getattr(os2, "sCapHeight", 0) if os2 else 0
    return (cap / upm) if cap else FALLBACK_CAP_EM


# ---------------------------------------------------------------------------
# Weight: measured, not assumed.
#
# A vision model returns a box, not a weight, and the first cut set every block
# at 400 -- so a bold display headline rendered as thin body type.  Weight is
# recoverable from the reference the same way size is: set the string in each
# vendored weight and compare its ink *coverage* (fraction of the ink box that
# is ink) against the reference's.  Coverage is string-independent because both
# sides are the same string, and it separates the weights cleanly (on the
# Montiva hero: reference 0.44, Inter 400 0.21, 500 0.22, 600 0.28).
# ---------------------------------------------------------------------------
def available_weights() -> list[int]:
    """The weights actually vendored in `pipeline/fonts/`, ascending."""
    out = []
    for w in (300, 400, 500, 600, 700, 800, 900):
        if (FONT_DIR / f"inter-latin-{w}-normal.woff2").is_file():
            out.append(w)
    return out or [DEFAULT_WEIGHT]


@lru_cache(maxsize=8)
def _ttf_bytes(weight: int) -> bytes:
    """The vendored woff2 for `weight` as plain TTF bytes (for PIL rasterising)."""
    import io as _io

    from fontTools.ttLib import TTFont

    path = FONT_DIR / f"inter-latin-{weight}-normal.woff2"
    if not path.is_file():
        path = FONT_DIR / f"inter-latin-{DEFAULT_WEIGHT}-normal.woff2"
    font = TTFont(str(path))
    font.flavor = None
    buf = _io.BytesIO()
    font.save(buf)
    return buf.getvalue()


@lru_cache(maxsize=64)
def pil_font(weight: int = DEFAULT_WEIGHT, size: int = 64):
    """A PIL font for the vendored Inter `weight` (cached per weight+size)."""
    import io as _io

    from PIL import ImageFont as _ImageFont

    return _ImageFont.truetype(_io.BytesIO(_ttf_bytes(weight)), size)


@lru_cache(maxsize=64)
def render_coverage(text: str, weight: int = DEFAULT_WEIGHT,
                    size: int = 64) -> float | None:
    """Ink coverage of `text` set in Inter `weight`, as a fraction of its box.

    `None` when the string draws nothing measurable (e.g. only spaces).
    """
    import numpy as _np
    from PIL import Image as _Image, ImageDraw as _ImageDraw

    if not text.strip():
        return None
    font = pil_font(weight, size)
    img = _Image.new("L", (size * (len(text) + 4), size * 3), 255)
    _ImageDraw.Draw(img).text((size, size), text, fill=0, font=font)
    a = _np.asarray(img).astype(_np.float32)
    ink = a < 128
    if int(ink.sum()) < 10:
        return None
    ys, xs = _np.nonzero(ink)
    h = int(ys.max() - ys.min() + 1)
    w = int(xs.max() - xs.min() + 1)
    return float(ink.sum()) / float(h * w)


def detect_weight(text: str, ref_coverage: float,
                  candidates: list[int] | None = None) -> int:
    """The vendored weight whose coverage best matches the reference's."""
    best, best_err = DEFAULT_WEIGHT, None
    for w in (candidates or available_weights()):
        c = render_coverage(text, w)
        if c is None:
            continue
        err = abs(c - ref_coverage)
        if best_err is None or err < best_err:
            best, best_err = w, err
    return best


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
    # No text (or no width): approximate from the box height.  The *ink* height,
    # not the cap height, is what the reported box spans.
    h_em = ink_height_em(text, weight) if text else cap_height_em(weight)
    return max(11.0, min(220.0, box_h / h_em))


def cap_top_offset(fs: float, weight: int = DEFAULT_WEIGHT, line_px: float | None = None) -> float:
    """Pixels from the top of a line box to the cap top.

    Lets a block be positioned so its *glyphs* align with the box the model
    reported, instead of the line box hanging above it.  `line_px` is the used
    line-height (defaults to the font-size, i.e. `line-height: 1`).
    """
    ascent, descent = _vmetrics_em(weight)
    line = fs if line_px is None else line_px
    glyph_h = (ascent + descent) * fs
    glyph_top_in_line = (line - glyph_h) / 2.0   # half-leading
    cap_top_in_glyph = (ascent - cap_height_em(weight)) * fs
    return glyph_top_in_line + cap_top_in_glyph


def wrap_lines(text: str, fs: float, box_w: float,
               weight: int = DEFAULT_WEIGHT) -> list[str]:
    """Greedy word-wrap of `text` at `fs` px inside `box_w` px."""
    words = text.split()
    if not words or box_w <= 0 or fs <= 0:
        return [text] if text else []
    space = text_width_em(" ", weight) * fs
    lines: list[str] = []
    cur = words[0]
    cur_w = text_width_em(words[0], weight) * fs
    for word in words[1:]:
        w = text_width_em(word, weight) * fs
        if cur_w + space + w <= box_w:
            cur = f"{cur} {word}"
            cur_w += space + w
        else:
            lines.append(cur)
            cur, cur_w = word, w
    lines.append(cur)
    return lines


def fit_wrapped(text: str, box_w: float, n_lines: int,
                weight: int = DEFAULT_WEIGHT) -> float | None:
    """Font size at which `text` wraps into exactly `n_lines` lines.

    The **largest** such size is returned, because that is the one whose widest
    wrapped line comes closest to filling `box_w` -- i.e. the size the reference
    was actually set at, given the box is the ink extent of the type.

    `None` when the requested line count is unreachable at any size (the text is
    too long or too short for the box), so the caller can fall back.
    """
    if n_lines <= 1 or box_w <= 1 or not text:
        return None

    def count(f: float) -> int:
        return len(wrap_lines(text, f, box_w, weight))

    lo, hi = 3.0, 400.0
    if count(lo) > n_lines or count(hi) < n_lines:
        return None
    # `count` grows monotonically with the font size; the largest size still
    # fitting in `n_lines` lines is the fixed point we want.
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if count(mid) <= n_lines:
            lo = mid
        else:
            hi = mid
    return lo


def fit_block_type(text: str, box_w: float, box_h: float, role: str,
                   weight: int = DEFAULT_WEIGHT,
                   n_lines: int | None = None) -> tuple[float, int]:
    """(font-size, line-count) for a block that may wrap onto several lines.

    `fit_font_size` solves the size from the box *width* assuming the whole
    string sits on one `nowrap` line.  The model is told to report a wrapped
    block as a single box, so for those the one-line width is far too long and
    the solve collapses to the minimum font-size.  Instead: find the size at
    which the wrapped text exactly fills the box width (a fixed point -- the
    widest wrapped line lands on the box edge).  For a single-line block this is
    algebraically the same as `fit_font_size`, so nothing else moves.

    `n_lines` is the line count *measured from the reference pixels* (see
    `measure_lines` in `generate`).  When supplied it is authoritative: the box
    width alone cannot tell a wrapped block from a single long line -- the
    Montiva hero box is 273x43 and its text fits on one 14 px line, yet the
    reference sets it on two ~22 px lines.  Given the true count, the size is
    solved directly (`fit_wrapped`) and the count is returned verbatim.
    """
    if n_lines and n_lines > 1 and text and box_w > 1:
        fs = fit_wrapped(text, box_w, n_lines, weight)
        if fs is not None:
            return max(8.0, fs), n_lines

    fs = fit_font_size(text, box_w, box_h, role, weight)
    if not text or box_w <= 1 or box_h <= 1:
        return fs, 1
    if len(wrap_lines(text, fs, box_w, weight)) <= 1:
        return fs, 1
    # Wrapped, but the line count was not measured from the reference.  The
    # width solve assumed a single line, so it is far too small -- and naive
    # fixed-point iteration on the width has several solutions (a 2-line set at
    # 9 px can fill the box as well as a 3-line set at 13 px).  The box height is
    # what picks between them: solve for the size whose wrapped height fills it
    # at the reference's normal leading.
    def height(f: float) -> float:
        return len(wrap_lines(text, f, box_w, weight)) * LINE_LEADING * f

    lo, hi = 4.0, max(4.0, box_h)
    if height(lo) >= box_h:
        fs = lo
    elif height(hi) <= box_h:
        fs = hi
    else:
        for _ in range(32):
            mid = (lo + hi) / 2.0
            if height(mid) < box_h:
                lo = mid
            else:
                hi = mid
        fs = lo
    return max(8.0, fs), len(wrap_lines(text, fs, box_w, weight))
