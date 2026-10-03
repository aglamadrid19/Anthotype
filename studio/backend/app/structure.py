"""Inspect the built page's structure: is it actually a website?

The pixel score cannot see any of this.  A page can match the reference closely
and still be a poster -- absolutely-positioned text, no sections, a dead CTA.
This module reads the built HTML and reports what the page *is*:

  * the semantic landmarks it has (header / nav / main / section / footer)
  * heading structure (exactly one h1, headings in order)
  * link targets (no `href="#"`)
  * flow layout (no absolutely-positioned content)
  * per-section copy

It is deliberately dependency-free (the DOM is small and generated, so a regex
scan is honest) and returns issues rather than raising.
"""
from __future__ import annotations

import re
from pathlib import Path

_WRAP = re.compile(r"</(header|nav|main|section|footer)>", re.I)
_SECTION = re.compile(r"<section\b[^>]*\bclass=\"[^\"]*\bsec-([a-z]+)\b", re.I)
_SECTION_ANY = re.compile(r"<section\b[^>]*\bid=\"([^\"]+)\"", re.I)
_H1 = re.compile(r"<h1\b", re.I)
_H2 = re.compile(r"<h2\b", re.I)
_H3 = re.compile(r"<h3\b", re.I)
_HREF = re.compile(r"<a\b[^>]*\bhref=\"([^\"]*)\"", re.I)
_ABS = re.compile(r"position\s*:\s*absolute", re.I)
_TAG = re.compile(r"<[^>]+>")
_ART_SVG = re.compile(r"<svg\b", re.I)
# A photographic hero ships a fixed-resolution raster rather than traced geometry
# (see `app/heroart.py`), so the backdrop counts as artwork either way -- the
# question this answers is "does the page have a hero backdrop?".
_ART_IMG = re.compile(r"<img\b[^>]*\bclass=\"hero-img\"", re.I)
# `<style>`/`<script>` are not the DOM structure -- the decorative hero backdrop
# is legitimately absolutely positioned, but the *content* must be in flow.
_STYLE = re.compile(r"<(style|script)\b[^>]*>.*?</\1>", re.I | re.S)


def _markup(html: str) -> str:
    return _STYLE.sub("", html)


def _strip(html: str) -> str:
    return _TAG.sub(" ", html)


def inspect(page: Path) -> dict:
    """Structural summary + a list of problems for the built page."""
    html = page.read_text(errors="replace")
    body = _markup(html)
    landmarks = sorted({m.lower() for m in _WRAP.findall(body)},
                       key=lambda t: ["header", "nav", "main", "section", "footer"].index(t)
                       if t in ("header", "nav", "main", "section", "footer") else 9)
    sections = _SECTION.findall(body)
    # A generated hero is a `<section id="hero">` without a `sec-*` class; include
    # every section id so a hero-only page still reports its structure.
    all_sections = sections or _SECTION_ANY.findall(body)

    hrefs = _HREF.findall(body)
    dead = [h for h in hrefs if h.strip() in ("", "#")]
    ids = set(re.findall(r"\bid=\"([^\"]+)\"", body))
    unresolved = [h for h in hrefs if h.startswith("#") and len(h) > 1 and h[1:] not in ids]

    n_h1, n_h2, n_h3 = len(_H1.findall(body)), len(_H2.findall(body)), len(_H3.findall(body))

    info: dict = {
        "landmarks": landmarks,
        "sections": sections,
        "all_sections": all_sections,
        "headings": {"h1": n_h1, "h2": n_h2, "h3": n_h3},
        "links": len(hrefs),
        "dead_links": dead,
        "unresolved_anchors": unresolved,
        "flow_layout": not bool(_ABS.search(body)),
        "has_art": bool(_ART_SVG.search(body) or _ART_IMG.search(body)),
        "has_svg": bool(_ART_SVG.search(body)),
        "bytes": page.stat().st_size,
    }

    issues: list[str] = []
    if not all_sections and "main" not in landmarks:
        issues.append("no <section> elements: the page is not structured")
    if "main" not in landmarks and sections:
        issues.append("no <main> landmark")
    if n_h1 == 0:
        issues.append("no <h1>")
    elif n_h1 > 1:
        issues.append(f"{n_h1} <h1> elements (should be exactly one)")
    if dead:
        issues.append(f"{len(dead)} dead link(s) pointing at '#'")
    if unresolved:
        issues.append(f"{len(unresolved)} anchor link(s) with no target: "
                      + ", ".join(sorted(set(unresolved))[:4]))
    if not info["flow_layout"]:
        issues.append("absolutely-positioned content: not a flow layout")
    if not info["has_art"]:
        issues.append("no traced artwork in the page")
    info["issues"] = issues
    return info


def summarize(page: Path | None, css: Path | None = None) -> dict:
    """A light summary for the job record (inspect without the CSS file)."""
    if page is None or not page.is_file():
        return {}
    return inspect(page)
