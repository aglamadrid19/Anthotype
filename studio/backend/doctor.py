#!/usr/bin/env python3
"""Diagnose the studio and the pipeline.

When something looks wrong, start here.

    doctor env              check every dependency (venv, node, potrace, chrome,
                            fonts, the vision model / AntSeed proxy)
    doctor polarity         synthetic light/dark checks for the ink sampling and
                            page-copy scope, plus the generator's structure
                            logic: grouping, header/hero/footer naming, a clean
                            generated page, palette polarity (no model, no pipeline)
    doctor fixtures [name]  build every saved extraction end to end and assert its
                            STRUCTURE and its art-region pixel fidelity (a
                            per-fixture bound; no vision model):
                            light (hero-only), montiva (multi-section), antho
                            (photorealistic hero)
    doctor light [--keep]   the light fixture alone (kept for the README)
    doctor regress          prove the shipped pipeline is intact: run the repo's
                            own qa/verify.sh, report A/B/C PASS/FAIL, and check
                            that docs/STATE.json scores/targets still match
    doctor gate             run the whole safety net in order -- env -> polarity
                            -> fixtures -> regress -- and fail if any stage fails.
                            This is the one command to run before committing and
                            the one CI runs.  --quick runs polarity alone (fast,
                            no pipeline, no model).
    doctor run [png]        run one design end to end, in-process, printing every
                            stage and its timing (no HTTP, no queue)
    doctor critique <x>     review a generated page against its mockup with the
                            vision model: x is a job id (review the existing
                            build) or a design PNG (build it first).  Returns a
                            ranked list of composition/readability defects;
                            typeface differences are out of scope.  --page,
                            --height, --out report.json
    doctor job <id>         inspect a studio job: status, art fidelity, structure,
                            artifacts, logs
    doctor jobs             list recent jobs

Exit code is non-zero if any check fails, so it is CI-able.
"""
from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Re-exec under the studio venv if this interpreter lacks the studio deps, so
# `python3 studio/backend/doctor.py ...` just works (mirrors qa/_bootstrap.py).
try:
    import httpx  # noqa: F401
    import numpy  # noqa: F401
except ImportError:
    _HERE = Path(__file__).resolve().parent
    _VENV = _HERE.parent / ".venv" / "bin" / "python"
    if _VENV.is_file() and os.environ.get("_DOCTOR_BOOTSTRAPPED") != "1":
        env = dict(os.environ, _DOCTOR_BOOTSTRAPPED="1")
        os.execve(str(_VENV), [str(_VENV), str(Path(__file__).resolve()), *sys.argv[1:]], env)
    sys.stderr.write(
        "doctor: missing deps (httpx/numpy). Run with the studio venv:\n"
        "  studio/.venv/bin/python studio/backend/doctor.py ...\n"
        "or create it:  python3 -m venv studio/.venv && "
        "studio/.venv/bin/pip install -r studio/backend/requirements.txt\n")
    raise SystemExit(2)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from app import config  # noqa: E402
from app.config import PIPELINE_DIR, REPO_ROOT, STUDIO_DIR  # noqa: E402

OK, BAD, WARN = "ok  ", "FAIL", "warn"
_failures = 0


def _line(status: str, label: str, detail: str = "") -> None:
    global _failures
    if status == BAD:
        _failures += 1
    print(f"  [{status}] {label}" + (f"  {detail}" if detail else ""))


# --------------------------------------------------------------------------
# env
# --------------------------------------------------------------------------
def cmd_env(_args: list[str]) -> int:
    print("environment")
    _check_python()
    _check_node()
    _check_potrace()
    _check_chrome()
    _check_fonts()
    _check_pipeline()
    _check_vision()
    print()
    if _failures:
        print(f"{_failures} check(s) failed")
    else:
        print("all checks passed")
    return 1 if _failures else 0


def _check_python() -> None:
    venv = REPO_ROOT / ".venv" / "bin" / "python"
    if not venv.is_file():
        _line(BAD, "repo python venv", f"missing {venv} -- run ./bootstrap.sh")
        return
    try:
        out = subprocess.run(
            [str(venv), "-c", "import numpy,PIL,scipy,skimage;print('ok')"],
            capture_output=True, text=True, timeout=60)
    except Exception as exc:  # noqa: BLE001
        _line(BAD, "repo python venv", f"{type(exc).__name__}: {exc}")
        return
    if out.returncode == 0:
        _line(OK, "repo python venv", str(venv))
    else:
        _line(BAD, "repo python venv",
              "numpy/PIL/scipy/skimage not importable -- run ./bootstrap.sh")


def _check_node() -> None:
    from app.procs import find_node
    try:
        node = find_node()
    except RuntimeError as exc:
        _line(BAD, "node", str(exc))
        return
    ver = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    npm = Path(node).parent / "npm"
    _line(OK, "node", f"{node} ({ver})")
    if npm.exists():
        _line(OK, "npm", str(npm))
    else:
        _line(WARN, "npm", "not beside node; will fall back to PATH")


def _check_potrace() -> None:
    from app.procs import find_potrace
    pt = find_potrace()
    if not pt:
        _line(BAD, "potrace", "not found on PATH or in Homebrew's bin -- brew install potrace")
        return
    ver = subprocess.run([pt, "--version"], capture_output=True, text=True)
    _line(OK, "potrace", f"{pt} ({(ver.stdout or ver.stderr).strip().splitlines()[0]})")


def _check_chrome() -> None:
    from app.verify import find_chrome
    chrome = find_chrome()
    if chrome:
        _line(OK, "chrome", chrome)
    else:
        _line(WARN, "chrome", "not found -- fidelity scoring will be skipped")


def _check_fonts() -> None:
    fonts = sorted((PIPELINE_DIR / "fonts").glob("*.woff2")) if PIPELINE_DIR.is_dir() else []
    if not fonts:
        _line(BAD, "vendored fonts", f"none in {PIPELINE_DIR / 'fonts'}")
        return
    _line(OK, "vendored fonts", f"{len(fonts)} woff2 in pipeline/fonts/")
    try:
        from app import fontmetrics
        if fontmetrics.available():
            w = fontmetrics.text_width_em("AntHosting", 400)
            _line(OK, "font metrics", f"Inter parsed (AntHosting = {w:.3f} em)")
        else:
            _line(WARN, "font metrics", "no 400 weight; layout will fall back to box height")
    except Exception as exc:  # noqa: BLE001
        _line(BAD, "font metrics", f"{type(exc).__name__}: {exc}")


def _check_pipeline() -> None:
    needed = ["gen-page.mjs", "to-astro.mjs", "lib/designs.mjs",
              "qa/mkart.py", "qa/newdesign.py", "site-template/astro.config.mjs"]
    missing = [n for n in needed if not (PIPELINE_DIR / n).exists()]
    if missing:
        _line(BAD, "pipeline files", f"missing: {', '.join(missing)}")
    else:
        _line(OK, "pipeline files", str(PIPELINE_DIR))


def _check_vision() -> None:
    from app import extract  # noqa: F401
    v = config.vision.describe()
    if not v["configured"]:
        _line(WARN, "vision model", f"not configured ({v['model']}); set studio/backend/.env")
        return
    base = v["base_url"].rstrip("/")
    fb = v.get("fallbacks") or []
    _line(OK, "vision config",
          f"{v['provider']} {v['model']} (+{len(fb)} fallback)" if fb
          else f"{v['provider']} {v['model']} (no fallback)")
    # If it is the local AntSeed proxy, prove it is up *and* that a model on it
    # actually answers -- a reachable proxy says nothing about whether the peer
    # serving your model is up, which is exactly how a build fails at the
    # extraction stage.
    if "127.0.0.1" in base or "localhost" in base:
        try:
            import httpx
            r = httpx.get(f"{base}/models", timeout=5)
            n = len(r.json().get("data", [])) if r.status_code == 200 else 0
            if r.status_code == 200:
                _line(OK, "vision endpoint", f"reachable, {n} models")
            else:
                _line(BAD, "vision endpoint", f"HTTP {r.status_code}")
                return
        except Exception as exc:  # noqa: BLE001
            _line(BAD, "vision endpoint",
                  f"unreachable at {base} ({type(exc).__name__}) -- is the AntSeed proxy running?")
            return

        # Round-trip the text-only half of the real call for each configured
        # model, so a peer that does not serve it is caught here rather than
        # mid-build.
        for model in config.vision.models:
            try:
                live = _probe_model(base, config.vision.api_key, model)
                _line(OK if live else WARN, f"answers: {model}",
                      "live" if live else "no reply (the fallbacks will be tried)")
            except Exception as exc:  # noqa: BLE001
                _line(WARN, f"answers: {model}",
                      f"{type(exc).__name__}: {str(exc)[:90]}")


def _probe_model(base: str, key: str, model: str) -> bool:
    """True if `model` returns a chat completion from the proxy right now."""
    import httpx
    r = httpx.post(f"{base}/chat/completions",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": model, "max_tokens": 4, "temperature": 0,
                         "messages": [{"role": "user", "content": "say ok"}]},
                   timeout=45)
    return r.status_code < 400


# --------------------------------------------------------------------------
# polarity: the light/dark assumptions the studio used to hardcode
# --------------------------------------------------------------------------
def _synth_stage(bg: tuple[int, int, int], ink: tuple[int, int, int],
                 box: tuple[float, float, float, float],
                 split_at: int | None = None,
                 ink2: tuple[int, int, int] | None = None) -> "np.ndarray":
    """A stand-in 'word': vertical bars of `ink` inside `box`.

    `split_at` makes it a two-tone wordmark (first `split_at` bars `ink`, the
    rest `ink2`), which is how the shipped designs spell a brand.
    """
    from PIL import Image, ImageDraw
    import numpy as np
    x0, y0, x1, y1 = box
    img = Image.new("RGB", (config.STAGE_W, config.STAGE_H), bg)
    d = ImageDraw.Draw(img)
    # Thin bars: real type covers a minority of its box, and the ink mask is
    # calibrated for that (a dense block trips the adaptive percentile).
    # Bars: real type covers a minority of its box (the ink mask is calibrated
    # for that) but each tone still spans a decent slice of the line.
    n = 6
    bar = (x1 - x0) * 0.3 / n
    step = (x1 - x0 - bar) / (n - 1)
    for i in range(n):
        col = ink if split_at is None or i < split_at else (ink2 or ink)
        bx = x0 + i * step
        d.rectangle([bx, y0, bx + bar, y1], fill=col)
    return np.asarray(img.convert("RGB")).astype(np.float32)


def cmd_polarity(_args: list[str]) -> int:
    """Synthetic light/dark checks -- no vision model, no pipeline, fast.

    Guards exactly the assumptions the first light upload broke: which side of
    the background is the ink, that a two-tone wordmark splits on either ground,
    and that a wrapped block is not sized as one line.
    """
    import numpy as np
    from app import fontmetrics, generate

    print("polarity + wrapped type (synthetic; no vision model)\n")
    box = (300.0, 300.0, 700.0, 360.0)
    loose = (280.0, 290.0, 720.0, 370.0)      # what a loose model box looks like
    grounds = (("light ground", (248, 249, 247), (48, 53, 60)),
               ("dark ground", (10, 12, 14), (240, 244, 240)))
    for name, bg, ink in grounds:
        arr = _synth_stage(bg, ink, box)
        snapped = generate.snap_to_ink(arr, loose, bg)
        runs = generate.sample_runs(arr, snapped, "Word", bg)
        got = runs[0][1] if runs else (255, 255, 255)
        err = max(abs(a - b) for a, b in zip(got, ink))
        _line(OK if err <= 24 else BAD, f"ink sampling ({name})",
              f"sampled {got}, true {ink}")
        off = max(abs(a - b) for a, b in zip(snapped, box))
        _line(OK if off <= 2 else BAD, f"box snapping ({name})",
              f"snapped {tuple(round(v) for v in snapped)}, drawn "
              f"{tuple(int(v) for v in box)}")

    # Two-tone wordmark: must split into the two runs on either ground.  The
    # neutral tone has to suit the ground (a navy half is invisible on a near
    # black page, so a dark design's neutral half is light).
    tones = (("light ground", (248, 249, 247), (11, 19, 28), (27, 188, 99)),
             ("dark ground", (10, 12, 14), (253, 253, 253), (27, 203, 125)))
    for name, bg, neu, sat in tones:
        arr = _synth_stage(bg, neu, box, split_at=3, ink2=sat)
        snapped = generate.snap_to_ink(arr, loose, bg)
        runs = generate.sample_runs(arr, snapped, "anthotype", bg)
        ok = len(runs) == 2
        if ok:
            d0 = max(abs(a - b) for a, b in zip(runs[0][1], neu))
            d1 = max(abs(a - b) for a, b in zip(runs[1][1], sat))
            ok = d0 <= 24 and d1 <= 24
        _line(OK if ok else BAD, f"two-tone wordmark ({name})",
              " / ".join(f"{t}={c}" for t, c in runs) or "one run")

    # The extraction scope filter keeps page copy and drops illustration text.
    # `part=artwork` wins regardless of role; the size backstop applies only to
    # the ambiguous `other` role.  The backstop is deliberately lax now: for a
    # *website* dropping a real nav link is worse than emitting a stray caption.
    from app.extract import Block
    footer = Block("Open source · Community driven", "other", (49, 481, 318, 507))
    caption = Block("Plant Pigment", "other", (559, 344, 619, 356))
    word = Block("antseed", "brand", (88, 170, 182, 194))    # small but real copy
    nav = Block("Services", "other", (419, 105, 446, 114))   # a real nav link
    mock = Block("Get Started", "cta", (778, 466, 810, 480), part="artwork")
    checks = {"wide footer": generate.is_page_text(footer),
              "small wordmark": generate.is_page_text(word),
              "nav link": generate.is_page_text(nav),
              "tiny speck": not generate.is_page_text(
                  Block("x", "other", (10, 10, 12, 12))),
              "artwork CTA": not generate.is_page_text(mock)}
    ok = all(checks.values())
    _line(OK if ok else BAD, "page copy vs artwork",
          ", ".join(f"{k}={v}" for k, v in checks.items()))

    # The tracer's exclusion rects must cover EVERY text block, including the
    # text inside the artwork.  Artwork-internal text is not emitted as DOM, but
    # if it is left unblanked the trace bakes a ghost of it into the hero
    # backdrop, right where the real copy sits -- the ugliest defect the page can
    # have.  The pad is fixed, so a tiny caption is still enclosed (the rect
    # grows on both sides of it).
    rects = generate.text_rects([
        Block("Heading", "headline", (100, 100, 300, 140)),
        Block("Plant Pigment", "other", (559, 344, 619, 356), part="artwork"),
        Block("6", "other", (366, 470, 372, 476), part="artwork"),
    ])
    g = generate.TEXT_RECT_GROW
    ok = (len(rects) == 3
          and rects[2] == [366 - g, 470 - g, 372 + g, 476 + g]
          and rects[0] == [100 - g, 100 - g, 300 + g, 140 + g]
          and not generate.is_page_text(
              Block("6", "other", (366, 470, 372, 476), part="artwork")))
    _line(OK if ok else BAD, "exclusion rects cover artwork text",
          f"{len(rects)} rects, tiny {rects[2]}, head pad {g}")

    # A CTA's *plate* must be removed whole, not just its label: dropping the
    # label's bands leaves the button behind, ghosting under the DOM button (a
    # pale pill on the anthotype reference).  An artwork CTA is not chrome.
    btns = generate.button_rects([
        Block("Try Anthotype", "cta", (80, 448, 190, 468)),
        Block("Get Started", "cta", (778, 466, 810, 480), part="artwork"),
        Block("Heading", "headline", (100, 100, 300, 140)),
    ])
    ok = len(btns) == 1 and btns[0] == [80 - g, 448 - g, 190 + g, 468 + g]
    _line(OK if ok else BAD, "CTA plates are blanked whole", f"{btns}")

    # A trust-badge row is badges whatever role the model gave them: the same
    # reference came back `other` on one run and `tagline` on the next, and
    # stacking three badges as body copy is a visible defect.
    hp = generate.build_content(generate.group_sections([
        Block("Book Service →", "cta", (168, 244, 248, 256), section="hero"),
        Block("Local Utah Team", "tagline", (163, 278, 224, 287), section="hero"),
        Block("5-Star Service", "tagline", (238, 278, 291, 287), section="hero"),
        Block("Same Week Appointments", "tagline", (318, 278, 409, 287), section="hero"),
        Block("OUR SERVICES", "tagline", (148, 309, 206, 317), section="features"),
        Block("Computer Repair", "headline", (103, 369, 172, 379), section="features"),
    ]), "s")["markup"]
    ok = (hp.count('class="badge"') == 3
          and hp.count('class="lede"') == 0)
    _line(OK if ok else BAD, "trust badges are a row whatever the role",
          f"{hp.count('class=\"badge\"')} badges, {hp.count('class=\"lede\"')} lede")

    # A two-line button (label over a phone number) stays two lines.
    lab = generate._cta_label(Block("Call Now (801) 810-4242", "cta", (0, 0, 9, 9)))
    ok = "cta-label" in lab and "cta-sub" in lab and "810-4242" in lab
    _line(OK if ok else BAD, "two-line button label", lab[:60])

    # Structure inference: a flat page with an eyebrow-labelled sections list must
    # come back as named sections in reading order, with a header row split off
    # the top and a footer at the bottom.  This is what makes the output a
    # website rather than a pile of absolutely-positioned text.
    synthetic = [
        Block("Acme", "brand", (24, 20, 80, 32)),
        Block("Home", "other", (200, 20, 240, 30)),
        Block("Services", "other", (260, 20, 320, 30)),
        Block("Big headline", "headline", (24, 90, 600, 140)),
        Block("Sub line", "tagline", (24, 150, 400, 190)),
        Block("OUR SERVICES", "tagline", (24, 260, 140, 272)),
        Block("Computer Repair", "other", (24, 280, 160, 292)),
        Block("We fix computers.", "tagline", (24, 300, 180, 330)),
        Block("WHAT PEOPLE SAY", "tagline", (24, 420, 160, 432)),
        Block("Great service!", "tagline", (24, 440, 200, 470)),
        Block("Acme", "brand", (24, 700, 80, 712)),
        Block("© 2026 Acme", "other", (200, 702, 300, 712)),
    ]
    sections = generate.group_sections(synthetic)
    names = [s for s, _ in sections]
    _line(OK if "header" in names else BAD, "header split from the top row",
          f"{names}")
    _line(OK if "hero" in names else BAD, "hero identified", f"{names}")
    _line(OK if "footer" in names else BAD, "footer identified", f"{names}")
    _line(OK if len(sections) >= 4 else BAD, "sections split on eyebrows",
          f"{len(sections)} section(s): {names}")

    # Adjacent blocks the model tagged with the SAME section name are one section.
    # The model declares a section per block, so without the merge a 75-block
    # landing page ships one `<section>` per block.  A testimonial's author line
    # sits at the same y as the contact band beside it, so the reading order
    # *interleaves* the two names -- merging only adjacent runs fragments them.
    declared = [
        Block("LOCAL, RELIABLE", "tagline", (148, 133, 300, 145), section="hero"),
        Block("Local IT Help", "headline", (148, 145, 422, 188), section="hero"),
        Block("OUR SERVICES", "tagline", (149, 311, 260, 323), section="features"),
        Block("Computer Repair", "headline", (102, 372, 167, 381), section="features"),
        Block("Data Transfer", "headline", (246, 372, 302, 379), section="features"),
        Block("WHAT OUR CLIENTS SAY", "tagline", (90, 519, 260, 531), section="testimonials"),
        Block("Great service!", "tagline", (90, 531, 260, 560), section="testimonials"),
        Block("Sarah M.", "other", (326, 578, 382, 590), section="testimonials"),
        Block("PROUDLY SERVING", "tagline", (126, 578, 206, 602), section="contact"),
        Block("Get in touch", "tagline", (582, 593, 700, 608), section="contact"),
        Block("Book an Appointment", "cta", (834, 601, 954, 640), section="contact"),
    ]
    merged = [s for s, _ in generate.group_sections(declared)]
    ok = merged == ["hero", "features", "testimonials", "contact"]
    if ok:
        markup = generate.build_content(
            generate.group_sections(declared), "merge")["markup"]
        ok = markup.count('<section class="section sec-') == 3
    _line(OK if ok else BAD, "same-name blocks merge into one section", f"{merged}")

    # A hero's action/trust row is part of the hero, not a section of its own.
    # The row has no eyebrow and no headline, so it used to be named `features`
    # and shipped three trust badges as cards.
    hero_split = [
        Block("LOCAL, RELIABLE", "tagline", (148, 131, 276, 140), section="hero"),
        Block("Local IT Help", "headline", (146, 145, 424, 190), section="hero"),
        Block("Book Service →", "cta", (148, 235, 268, 264), section="hero"),
        Block("Call Now", "cta", (283, 233, 374, 271), section="hero"),
        Block("Local Utah Team", "other", (163, 279, 224, 287), section="hero"),
        Block("5-Star Service", "other", (237, 279, 292, 287), section="hero"),
        Block("OUR SERVICES", "tagline", (148, 309, 206, 317), section="features"),
        Block("Computer Repair", "headline", (103, 369, 172, 379), section="features"),
    ]
    names = [s for s, _ in generate.group_sections(hero_split)]
    _line(OK if names == ["hero", "features"] else BAD,
          "hero action row stays in the hero", f"{names}")

    # The traced art is the whole mockup, so the hero backdrop must be cropped to
    # the hero's own band -- otherwise the next section's cards show through.
    band = generate.hero_band(generate.group_sections(declared))
    ok = band is not None and band[0] == 0 and band[1] <= 311
    _line(OK if ok else BAD, "hero backdrop cropped to the hero band", f"{band}")

    # The hero's buttons are emitted where they sit, not appended: a fine-print
    # line drawn *under* the button must stay under it, not become a caption.
    hero_order = generate.build_content(generate.group_sections([
        Block("anthotype", "headline", (52, 240, 424, 300), section="hero"),
        Block("Try Anthotype", "cta", (80, 448, 190, 468), section="hero"),
        Block("Open source · Community driven", "tagline", (52, 492, 308, 504),
              section="hero"),
    ]), "h")["markup"]
    ok = hero_order.index("hero-actions") < hero_order.index("Open source")
    _line(OK if ok else BAD, "hero buttons keep their place", "actions before note")

    # Side-by-side buttons are emitted left to right, as drawn -- not in reading
    # order, which sorts by top edge and so swaps a solid button for an outline
    # one that sits a few pixels higher.
    btns_row = generate.build_content(generate.group_sections([
        Block("Call Now", "cta", (288, 233, 368, 264), section="hero"),
        Block("Book Service →", "cta", (148, 235, 268, 264), section="hero"),
        Block("Local IT Help", "headline", (146, 145, 424, 190), section="hero"),
    ]), "b")["markup"]
    ok = btns_row.index("Book Service") < btns_row.index("Call Now")
    _line(OK if ok else BAD, "hero buttons read left to right",
          "Book Service before Call Now" if ok else "swapped")

    # A heading with its own body under it heads a column, not the title row.
    contact = [
        Block("PROUDLY SERVING", "tagline", (136, 585, 198, 593), section="contact"),
        Block("Utah County", "headline", (134, 595, 366, 610), section="contact"),
        Block("We provide in-home IT.", "tagline", (134, 616, 424, 632), section="contact"),
        Block("Get in Touch", "headline", (610, 592, 652, 601), section="contact"),
        Block("Have a question?", "tagline", (610, 604, 766, 612), section="contact"),
        Block("Book an Appointment", "cta", (858, 617, 924, 625), section="contact"),
    ]
    body = generate.build_content(generate.group_sections(contact), "c")["markup"]
    ok = ("<h3>Get in Touch</h3>" in body and body.count("<h3>") == 2
          and body.count('class="col"') == 3)
    _line(OK if ok else BAD, "column headings stay in their column",
          f"h3 x{body.count('<h3>')}, cols x{body.count('class=\"col\"')}")

    # The generated page must be a real, flowing document: one h1, sections, no
    # dead links, nothing absolutely positioned.
    markup = generate.build_content(sections, "polarity")["markup"]
    issues = generate.structure_issues(sections, markup)
    _line(OK if not issues else BAD, "generated page structure",
          "; ".join(issues) or "clean")

    # A light ground must produce a light palette (and a dark one a dark palette).
    light_pal = generate.palette(synthetic, (248, 249, 247))
    dark_pal = generate.palette(synthetic, (10, 12, 14))
    _line(OK if light_pal["light"] and not dark_pal["light"] else BAD,
          "palette polarity",
          f"light bg -> light scheme={light_pal['light']}, "
          f"dark bg -> light scheme={dark_pal['light']}")

    # The sampled colours must stay legible on the ground they are painted on.
    # A design's headline can be a dark navy because it sat over a light hero
    # panel; using it as body ink on a dark page makes the whole page unreadable.
    navy = Block("Dark navy headline", "headline", (24, 90, 600, 140),
                 color=(20, 40, 90))
    ground = Block("Body copy", "tagline", (24, 150, 400, 190), color=(20, 40, 90))
    pal = generate.palette([navy, ground], (10, 12, 14))
    ratio = generate._contrast(pal["ink"], pal["bg"])
    _line(OK if ratio >= 4.5 else BAD, "palette contrast on a dark ground",
          f"ink {pal['ink']} on bg {pal['bg']} -> {ratio:.1f}:1")

    # A CTA's fill is the accent, so buttons and highlights agree.
    cta = Block("Buy", "cta", (24, 240, 120, 280), color=(255, 255, 255),
                fill=(20, 190, 120))
    pal = generate.palette([navy, ground, cta], (10, 12, 14))
    _line(OK if pal["accent"] == (20, 190, 120) else BAD, "accent follows the CTA fill",
          f"accent {pal['accent']}")

    # Extraction resilience: the retry escalates the image encoding, so a peer
    # that cannot decode WebP is not a dead end.
    from app.extract import _gridded_data_uri
    mimes = [_gridded_data_uri(config.PIPELINE_DIR / "qa" / "ref-a.png", attempt=i).split(";")[0]
             for i in range(3)]
    _line(OK if len(set(mimes)) == 3 else BAD, "vision retry encoding",
          " -> ".join(m.split(":")[-1] for m in mimes))

    # The studio's vision model + its fallbacks, as configured.
    v = config.vision.describe()
    n = len(v.get("fallbacks") or [])
    _line(OK if v["configured"] else WARN, "vision model",
          f"{v['model']}" + (f" (+{n} fallback)" if n else " (no fallback)"))

    # A card band must fill its last row.  A greedy `auto-fit` strung four cards
    # out as 3+1, leaving one stranded on its own line (a vision review flagged
    # it); `--cards` is set from `_balanced_cols` so every row but the last is
    # full.  The counts are the shapes a real page hits.
    cols = {k: generate._balanced_cols(k) for k in (2, 3, 4, 5, 6, 8, 9, 12)}
    cols_ok = (cols[2] == 2 and cols[3] == 3 and cols[4] == 4 and cols[5] == 3
               and cols[6] == 3 and cols[8] == 4 and cols[9] == 3 and cols[12] == 4)
    _line(OK if cols_ok else BAD, "card bands fill their last row",
          " ".join(f"{k}->{v_}" for k, v_ in cols.items()))

    # A phone number drawn *inside* a button plate is that button's second line,
    # not an orphan paragraph below the row.  `decorate` grows the CTA to its
    # plate, so the line is vertically inside the button, not merely under it.
    btn = Block("Call Now", "cta", (282, 227, 374, 270))
    phone = Block("(801) 810-4242", "other", (312, 251, 366, 259))
    subs = generate._cta_sublabels([btn, phone], [btn])
    _line(OK if subs.get(id(btn)) is phone else BAD, "phone folds into its button",
          f"{len(subs)} sublabel(s)")

    # A contact panel pairs each value with the caption under it -- even though
    # `decorate` has grown the value's box over the caption (the plate gotcha).
    # A long paragraph above them must not be mistaken for a value.
    para = Block("Have a question or need help? We're here for you.",
                 "tagline", (608, 604, 762, 612))
    tel = Block("(801) 810-4242", "other", (630, 616, 684, 624))
    cap = Block("Call or Text", "other", (630, 625, 662, 632))
    pairs, _ = generate._value_label_pairs([para, tel, cap])
    _line(OK if pairs == [(tel, cap)] else BAD, "contact panel pairs value + label",
          f"{[(v.text, l.text) for v, l in pairs]}")

    # A footer's nav links are `other`, not `cta`, and sit in a packed run; the
    # address and the legal links must not be pulled into the nav row.
    foot = [Block("Montiva Group", "brand", (114, 638, 198, 668)),
            Block("Home", "other", (404, 640, 442, 648)),
            Block("Services", "other", (442, 640, 488, 648)),
            Block("About", "other", (486, 640, 524, 648)),
            Block("Support", "other", (522, 640, 568, 648)),
            Block("Contact", "other", (566, 640, 612, 648)),
            Block("Pleasant Grove, UT", "other", (726, 640, 800, 648)),
            Block("Privacy Policy", "other", (852, 652, 900, 660))]
    nav_text = {b.text for b in foot if id(b) in generate._footer_nav_links(foot)}
    _line(OK if nav_text == {"Home", "Services", "About", "Support", "Contact"} else BAD,
          "footer nav links detected", f"{sorted(nav_text)}")

    print()
    if _failures:
        print(f"{_failures} check(s) failed")
    else:
        print("all checks passed")
    return 1 if _failures else 0


# --------------------------------------------------------------------------
# light: the frozen light-background fixture, end to end
# --------------------------------------------------------------------------
# A saved extraction replayed against a reference.  The vision model is never
# called, so these are deterministic and free; they guard the local *structure*
# and tracing paths in CI and on a fresh checkout.
#
# These are no longer scored on whole-page pixels: the studio now builds a real
# website whose copy is authored in the site's own type, so pixel parity with
# the reference's typeface is deliberately not the target.  Each fixture instead
# guards the NORTH STAR's two measures: the page's STRUCTURE (sections/hero/
# headings/links/flow, via `app.structure.inspect`) and the ARTWORK's pixel
# fidelity (the art-region mean, via `score_max`).
#
# `expect` is a list of substring requirements on the structure summary; a
# fixture may also pin counts with `page` / `artwork`.  `score_max` bounds the
# art-region mean with a little headroom -- it is stable because a fixture
# replays a saved extraction with no vision model.  The numbers are NOT
# comparable between fixtures (each masks its own region), so each is pinned
# separately; a tracer regression (half-resolution bands, baked-in text) raises
# one and fails the fixture.
FIXTURES: dict[str, dict] = {
    "light": dict(
        ref="light-ref.png", blocks="light-blocks.json",
        note="synthetic light ground: a hero-only page (structure + art)",
        expect=["hero"], page=8, artwork=0, score_max=3.0,
    ),
    "montiva": dict(
        ref="montiva-ref.png", blocks="montiva-blocks.json",
        note="real multi-section landing page (header/nav/hero/sections/footer)",
        expect=["header", "nav", "main", "section", "footer",
                "testimonials", "contact"], score_max=5.0,
    ),
    "antho": dict(
        ref="antho-ref.png", blocks="antho-blocks.json",
        note="real photorealistic hero: a hero-only page",
        expect=["header", "hero"], page=8, score_max=3.0,
    ),
}
LIGHT_FIXTURE = STUDIO_DIR / "fixtures"
# Kept for the README's `doctor light` entry point.
LIGHT_TARGET = None


def _fixture_ok(spec: dict, info: dict, page: list, art: list) -> list[str]:
    """Return the structure expectations this build failed (empty = pass)."""
    seen = " ".join(info.get("landmarks") or []) + " " + " ".join(info.get("sections") or [])
    seen += " " + " ".join(info.get("all_sections") or [])
    # A hero-only page has no `sec-*` class, so "hero" is checked via the DOM
    # marker the generator emits (`id="hero"`); `_run_fixture` passes that in.
    seen += " " + " ".join(spec.get("_dom", []))
    failed = [want for want in spec.get("expect", []) if want not in seen]
    if "page" in spec and len(page) != spec["page"]:
        failed.append(f"page blocks {len(page)} != {spec['page']}")
    if "artwork" in spec and len(art) != spec["artwork"]:
        failed.append(f"artwork blocks {len(art)} != {spec['artwork']}")
    return failed


def _run_fixture(name: str, keep: bool = False) -> int:
    """Build one saved extraction end to end (no model) and check its structure."""
    spec = FIXTURES[name]
    ref = LIGHT_FIXTURE / spec["ref"]
    blocks = LIGHT_FIXTURE / spec["blocks"]
    if not ref.is_file() or not blocks.is_file():
        print(f"missing fixture: {ref} / {blocks}")
        return 2

    print(f"fixture {name}: {ref.name} + {blocks.name} (no vision model)")
    print(f"  {spec['note']}\n")

    from app.jobs import JobStore
    from app.runner import PipelineRunner

    runner = PipelineRunner(None)
    store = JobStore(runner)
    runner.store = store

    os.environ["STUDIO_FAKE_BLOCKS"] = str(blocks)
    try:
        job = store.create(ref.read_bytes(), filename=ref.name)

        last, t0 = None, time.time()
        while time.time() - t0 < 1800:
            j = store.get(job.id)
            if j.stage != last:
                print(f"  [{j.progress*100:5.1f}%] {j.stage:11s} {j.message}")
                last = j.stage
            if j.status in ("done", "failed"):
                break
            time.sleep(0.5)
    finally:
        # Must outlive the worker: `create` only enqueues, and popping the var
        # before the job finished let the worker fall through to a *live* vision
        # call -- so a "fixture replay" was not reproducible at all.
        os.environ.pop("STUDIO_FAKE_BLOCKS", None)

    j = store.get(job.id)
    print()
    print(f"status : {j.status}")
    if j.status != "done":
        print("\nlog tail:")
        print("\n".join(j.logs[-30:]))
        if not keep:
            shutil.rmtree(j.dir, ignore_errors=True)
        return 1

    info = j.structure if isinstance(j.structure, dict) else {}
    issues = list(j.structure_issues or []) + list(info.get("issues") or [])
    page = [b for b in (j.blocks or []) if b.get("part") == "page"]
    art = [b for b in (j.blocks or []) if b.get("part") == "artwork"]

    # A hero-only page has no `sec-*` class to read, so also match `expect`
    # against the element ids the generator emits (hero/main/header/footer).
    try:
        html = (j.dir / "index.html").read_text(errors="replace")
        from app import structure as _structure
        dom = _structure.inspect(j.dir / "index.html")
        info = {**info, **dom}
        issues = list(j.structure_issues or []) + list(dom.get("issues") or [])
    except Exception:  # noqa: BLE001
        html, dom = "", {}
    spec["_dom"] = [m for m in ("hero", "main", "header", "footer")
                    if f'id="{m}"' in html]

    print(f"structure: {', '.join(info.get('sections') or []) or '(none)'}")
    print(f"landmarks: {', '.join(info.get('landmarks') or []) or '(none)'}")
    print(f"headings : {info.get('headings')}")
    print(f"art      : {'traced SVG present' if info.get('has_art') else 'MISSING'}")
    bound = spec.get("score_max")
    if j.score is None:
        print("fidelity : n/a")
    else:
        print(f"fidelity : art region mean {j.score:.2f}"
              + (f"  (max {bound:g})" if bound is not None else ""))
    print(f"blocks   : {len(page)} page, {len(art)} artwork left to the tracer")
    print(f"job dir  : {j.dir}")

    failed = _fixture_ok(spec, info, page, art) + issues
    if bound is not None:
        if j.score is None:
            failed.append("art fidelity not measured (no score)")
        elif j.score >= bound:
            failed.append(f"art region mean {j.score:.2f} >= max {bound:g}")
    ok = j.status == "done" and not failed

    if not keep:
        shutil.rmtree(j.dir, ignore_errors=True)
    print()
    if ok:
        print(f"fixture {name} PASS")
        return 0
    print(f"fixture {name} FAIL")
    for i in failed:
        print(f"  - {i}")
    print("\n".join(j.logs[-20:]))
    return 1


def cmd_fixtures(args: list[str]) -> int:
    """Run every saved fixture (or the named ones).  No vision model."""
    keep = "--keep" in args
    names = [a for a in args if not a.startswith("-")] or list(FIXTURES)
    bad = [n for n in names if n not in FIXTURES]
    if bad:
        print(f"unknown fixture(s): {', '.join(bad)}; have {', '.join(FIXTURES)}")
        return 2
    failed = 0
    for n in names:
        failed += _run_fixture(n, keep=keep)
        print("=" * 60)
    print(f"fixtures: {len(names) - failed}/{len(names)} passed")
    return 1 if failed else 0


def cmd_light(args: list[str]) -> int:
    """Build the light fixture end to end (no model) and score it.

    Kept as a stable entry point (the README documents it); `doctor fixtures`
    runs it alongside the two real-design regressions.
    """
    return _run_fixture("light", keep="--keep" in args)


# --------------------------------------------------------------------------
# regress: is the shipped pipeline still intact?
# --------------------------------------------------------------------------
def _state_consistency(measured: dict[str, float]) -> list[str]:
    """Compare docs/STATE.json against the design configs and this run.

    STATE.json is hand-maintained and had drifted (a stale score string, resolved
    leads still listed as priorities).  A fresh `qa/verify.sh` run is the
    authority -- so keep the machine-readable state honest mechanically: the
    scores must match what was just measured and the targets must match
    `designs/<v>.json` (which `verify.sh` enforces).
    """
    state_path = REPO_ROOT / "docs" / "STATE.json"
    try:
        state = json.loads(state_path.read_text())
    except Exception as exc:  # noqa: BLE001
        return [f"cannot read {state_path}: {type(exc).__name__}: {exc}"]
    scores = state.get("scores") or {}
    targets = state.get("targets") or {}
    bad: list[str] = []
    for v, m in sorted(measured.items()):
        if v not in scores:
            bad.append(f"STATE.json scores has no '{v}' (measured {m:.2f})")
        elif abs(float(scores[v]) - m) > 0.05:
            bad.append(f"STATE.json scores.{v} = {scores[v]} but this run measured {m:.2f}")
        cfg = PIPELINE_DIR / "designs" / f"{v}.json"
        want = json.loads(cfg.read_text()).get("target") if cfg.is_file() else None
        if want is not None:
            if v not in targets:
                bad.append(f"STATE.json targets has no '{v}' (design target {want})")
            elif abs(float(targets[v]) - float(want)) > 1e-9:
                bad.append(f"STATE.json targets.{v} = {targets[v]} but designs/{v}.json says {want}")
    return bad


def cmd_regress(args: list[str]) -> int:
    script = PIPELINE_DIR / "qa" / "verify.sh"
    if not script.is_file():
        print(f"no {script}")
        return 1
    print("pipeline regression: qa/verify.sh (scores each built site vs its reference)")
    print("expected: every design PASS under its target (designs/*.json)\n")
    # Stream AND capture: the output is parsed below for the docs check.
    proc = subprocess.Popen([str(script), *args], cwd=str(PIPELINE_DIR),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    lines = []
    for line in proc.stdout or []:
        sys.stdout.write(line)
        lines.append(line)
    rc = proc.wait()
    print()
    if rc != 0:
        print("regression FAIL")
        return rc
    print("regression PASS")

    measured: dict[str, float] = {}
    for line in lines:
        m = re.match(r"\s*(\S+)\s+mean\s+([\d.]+)", line)
        if m:
            measured[m.group(1)] = float(m.group(2))
    drift = _state_consistency(measured)
    if drift:
        print("\ndocs consistency FAIL -- docs/STATE.json is out of date:")
        for d in drift:
            print(f"  - {d}")
        print("  update docs/STATE.json (scores / targets).  The code and a fresh")
        print("  `qa/verify.sh` are authoritative; this check keeps them in sync.")
        return 1
    print(f"docs: STATE.json scores/targets match the designs and this run "
          f"({len(measured)} design(s))")
    return 0


# --------------------------------------------------------------------------
# gate: the whole safety net in order, as one command
# --------------------------------------------------------------------------
def cmd_gate(args: list[str]) -> int:
    """Run the project's whole safety net, in order, as one command.

    The north star has two measures -- the artwork's pixel fidelity (the A/B/C
    posters, via `regress`) and the website's structure (the studio fixtures,
    via `fixtures`) -- and both are guarded here, so a change is validated by
    one command instead of several.  The exit code is non-zero if any stage
    fails, so this is exactly what CI runs.

        doctor gate                 env -> polarity -> fixtures -> regress
        doctor gate --quick         polarity alone (fast, no pipeline, no model)
        doctor gate --no-env        skip the toolchain check
        doctor gate --no-fixtures   skip the end-to-end fixture builds
        doctor gate --no-regress    skip the A/B/C poster scoring
        doctor gate --keep          keep fixture job dirs for inspection

    `--quick` is the guard a fast CI job (or a pre-commit hook) can afford: it
    needs no potrace, no node, no Chrome and no vision model.
    """
    global _failures

    # `--quick` = the cheap, model-free guard: polarity alone.
    if "--quick" in args:
        args = [*args, "--no-env", "--no-fixtures", "--no-regress"]

    plan = []
    if "--no-env" not in args:
        plan.append(("env", cmd_env, []))
    if "--no-polarity" not in args:
        plan.append(("polarity", cmd_polarity, []))
    if "--no-fixtures" not in args:
        plan.append(("fixtures", cmd_fixtures, ["--keep"] if "--keep" in args else []))
    if "--no-regress" not in args:
        plan.append(("regress", cmd_regress, []))
    if not plan:
        print("nothing to do: every stage was disabled")
        return 2

    print(f"anthotype gate: {' -> '.join(name for name, _, _ in plan)}\n")
    results = []
    for name, fn, fargs in plan:
        print("=" * 68)
        print(f"stage: {name}")
        print("=" * 68)
        _failures = 0  # each stage owns its failure count
        results.append((name, fn(fargs)))
        print()

    failed = [name for name, rc in results if rc != 0]
    print("=" * 68)
    for name, rc in results:
        print(f"  [{OK if rc == 0 else BAD}] {name}")
    if failed:
        print(f"\ngate FAIL: {len(failed)}/{len(results)} stage(s) failed "
              f"({', '.join(failed)})")
        return 1
    print(f"\ngate PASS: {len(results)}/{len(results)} stages")
    return 0


# --------------------------------------------------------------------------
# run: one design end to end, in-process, with timings
# --------------------------------------------------------------------------
def cmd_run(args: list[str]) -> int:
    png = Path(args[0]) if args else Path("/tmp/studio-test-a.png")
    if not png.is_file():
        # Fall back to a shipped reference so this always has something to run.
        png = PIPELINE_DIR / "qa" / "ref-a.png"
    print(f"end-to-end run: {png}\n")

    from app.jobs import JobStore, STAGES
    from app.runner import PipelineRunner

    runner = PipelineRunner(None)
    store = JobStore(runner)
    runner.store = store

    raw = png.read_bytes()
    job = store.create(raw, filename=png.name)

    seen: dict[str, float] = {}
    last = None
    t0 = time.time()
    deadline = t0 + 2400
    while time.time() < deadline:
        j = store.get(job.id)
        if j.stage != last:
            now = time.time()
            if last is not None:
                seen[last] = now - seen.get(last, now)
            seen[j.stage] = now
            print(f"  [{j.progress*100:5.1f}%] {j.stage:11s} {j.message}")
            last = j.stage
        if j.status in ("done", "failed"):
            break
        time.sleep(0.5)

    j = store.get(job.id)
    total = time.time() - t0
    print()
    print(f"status : {j.status}")
    if j.score is not None:
        print(f"art fidelity: {j.score:.2f}  (pct>30 {j.pct_over_30:.2f}%)"
              + (f"  whole {j.whole_score:.2f}" if j.whole_score is not None else ""))
    info = j.structure if isinstance(j.structure, dict) else {}
    if info:
        print(f"structure: {', '.join(info.get('sections') or []) or '(none)'}")
    print(f"total  : {total:.0f}s")
    print(f"job dir: {j.dir}")
    if j.status != "done":
        print("\nlog tail:")
        print("\n".join(j.logs[-30:]))
        return 1
    for issue in (j.structure_issues or []) + list(info.get("issues") or []):
        print(f"structure: {issue}")
    print(f"artifacts: {json.dumps(j.artifacts, indent=2)}")
    return 0


# --------------------------------------------------------------------------
# critique: the vision review loop, made repeatable
# --------------------------------------------------------------------------
CRITIQUE_PROMPT = (
    "You are a senior web designer reviewing a GENERATED website against the "
    "flat design mockup it was built from.\n"
    "Image 1 is the original mockup. Image 2 is a screenshot of the generated "
    "website: a real responsive page whose artwork is traced to SVG as the hero "
    "backdrop and whose copy is authored DOM text in the site's own type scale.\n"
    "The target is a REAL website, not a pixel copy. The reference's typeface is "
    "deliberately NOT reproduced, so do NOT report typeface/font differences, "
    "sub-pixel spacing, or missing fine detail. The output is deliberately "
    "code-native: the artwork is traced to SVG and the copy is DOM text, so "
    "photos, icons, avatars and star images from the mockup are intentionally "
    "absent -- do NOT report them as missing. Judge COMPOSITION and "
    "READABILITY: hierarchy, grouping, balance, contrast, and anything that "
    "reads as a defect (ghosted/duplicated text, stray or orphaned elements, "
    "broken rows, unreadable copy, misplaced sections).\n"
    "Return ONLY a JSON object:\n"
    '{"verdict": "<one sentence>", "defects": [{"rank": 1, '
    '"severity": "high|medium|low", "where": "<region: header|hero|cards|'
    'contact|footer|...>", "what": "<one sentence>", "fix": "<one sentence>"}]}\n'
    "Rank by how much each defect hurts the page. Omit anything caused only by "
    "the different typeface. No markdown, no commentary."
)


def _vision_data_uri(png: Path, max_edge: int = 1600) -> str:
    """A plain (grid-free) data URI for a review image: WebP, JPEG fallback."""
    import io as _io
    from PIL import Image
    img = Image.open(png).convert("RGB")
    if max(img.size) > max_edge:
        scale = max_edge / max(img.size)
        img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                         Image.LANCZOS)
    buf = _io.BytesIO()
    try:
        img.save(buf, format="WEBP", quality=90, method=4)
        mime = "image/webp"
    except Exception:  # noqa: BLE001 - a build without WebP
        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        mime = "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def _vision_chat(images: list[Path], prompt: str,
                 max_edges: list[int] | None = None) -> str:
    """One multi-image chat call, trying the configured model then its fallbacks."""
    import httpx
    from app.config import vision
    if not vision.configured:
        raise RuntimeError("vision model not configured (set studio/backend/.env)")
    content: list[dict] = [{"type": "text", "text": prompt}]
    edges = max_edges or [1600] * len(images)
    for p, edge in zip(images, edges):
        content.append({"type": "image_url", "image_url": {"url": _vision_data_uri(p, edge)}})
    tried: list[str] = []
    for model in vision.models:
        try:
            resp = httpx.post(
                f"{vision.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {vision.api_key}"},
                json={"model": model, "temperature": 0, "max_tokens": 1500,
                      "messages": [{"role": "user", "content": content}]},
                timeout=300)
            if resp.status_code >= 400:
                tried.append(f"{model}: HTTP {resp.status_code}")
                continue
            return resp.json()["choices"][0]["message"]["content"] or ""
        except Exception as exc:  # noqa: BLE001
            tried.append(f"{model}: {type(exc).__name__}: {str(exc)[:80]}")
    raise RuntimeError("no vision model answered -- " + " | ".join(tried))


def _page_screenshot(chrome: str, page: Path, out: Path, height: int = 6000) -> None:
    """A 1x full-page screenshot of the built page.

    Chrome only captures the window, so the window is opened generously tall and
    the uniform background rows below the content are trimmed off.  A fixed
    2400px window cut a real landing page's contact and footer sections, and the
    review never saw them -- which is exactly how two real defects were missed.
    """
    raw = out.with_name(out.stem + "-raw.png")
    subprocess.run(
        [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--force-device-scale-factor=1", "--force-color-profile=srgb",
         "--no-first-run", "--no-default-browser-check", "--disable-http-cache",
         "--incognito", f"--window-size={config.STAGE_W},{height}",
         "--virtual-time-budget=8000", f"--screenshot={raw}",
         page.resolve().as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=180, check=True)
    if not raw.is_file() or raw.stat().st_size == 0:
        raise RuntimeError("Chrome produced no screenshot")
    import numpy as np
    from PIL import Image
    img = Image.open(raw).convert("RGB")
    arr = np.asarray(img)
    bg = np.median(arr[:4].reshape(-1, 3), axis=0)
    rows = np.abs(arr.astype(int) - bg).sum(axis=2).max(axis=1)
    nz = np.nonzero(rows > 12)[0]
    h = min(img.height, max(200, int(nz.max()) + 16)) if len(nz) else img.height
    img.crop((0, 0, img.width, h)).save(out)
    raw.unlink(missing_ok=True)


def _build_for_critique(png: Path):
    """Build a page from `png` in-process (no HTTP, no queue). Returns (job, store)."""
    from app.jobs import JobStore
    from app.runner import PipelineRunner
    runner = PipelineRunner(None)
    store = JobStore(runner)
    runner.store = store
    job = store.create(png.read_bytes(), filename=png.name)
    last = None
    t0 = time.time()
    while time.time() - t0 < 2400:
        j = store.get(job.id)
        if j.stage != last:
            print(f"  [{j.progress*100:5.1f}%] {j.stage:11s} {j.message}")
            last = j.stage
        if j.status in ("done", "failed"):
            break
        time.sleep(0.5)
    return store.get(job.id), store


def _parse_critique(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise RuntimeError(f"model did not return JSON: {raw[:300]!r}")
        return json.loads(m.group(0))


def cmd_critique(args: list[str]) -> int:
    """Review a generated page against its mockup with the vision model.

        doctor critique <job-id>                       review an existing build
        doctor critique <design.png>                   build it first, then review
        doctor critique <design.png> --page <built.html>
        doctor critique <job-id> --out report.json

    The mockup and a full-page screenshot of the built page go to the configured
    vision model, which returns a ranked list of composition/readability defects
    (typeface differences and missing raster assets are explicitly out of scope).
    The screenshot is captured tall and trimmed to the content, so a long page's
    lower sections are reviewed too.  This makes the review loop that found the
    ghosting and the composition defects repeatable, and its output comparable
    across builds.
    """
    from app.jobs import JobStore
    from app.verify import find_chrome

    pos = [a for a in args if not a.startswith("-")]
    if not pos:
        print("usage: doctor critique <job-id | design.png> [--page <built.html>] "
              "[--height N] [--out report.json]")
        return 2
    target = pos[0]
    page_arg = args[args.index("--page") + 1] if "--page" in args else None
    out_arg = args[args.index("--out") + 1] if "--out" in args else None
    # The window is opened this tall and the background below the content is
    # trimmed, so the default is a ceiling, not the page height.
    height = int(args[args.index("--height") + 1]) if "--height" in args else 6000

    mockup: Path | None = None
    page: Path | None = None

    if page_arg:
        mockup, page = Path(target), Path(page_arg)
    else:
        job = JobStore(lambda job: None).get(target)
        if job:
            mockup, page = job.dir / "ref.png", job.dir / "index.html"
        elif Path(target).is_file():
            print(f"building {Path(target).name} (no page given; running the pipeline)\n")
            job, _ = _build_for_critique(Path(target))
            print()
            if job.status != "done":
                print(f"build {job.status}; log tail:\n" + "\n".join(job.logs[-20:]))
                return 1
            mockup, page = job.dir / "ref.png", job.dir / "index.html"

    if mockup is None or page is None or not mockup.is_file() or not page.is_file():
        print(f"cannot find a mockup + built page for {target!r} "
              f"(mockup={mockup}, page={page})")
        return 2

    chrome = find_chrome()
    if not chrome:
        print("Chrome not found (set CHROME=...)")
        return 2

    shot = Path(tempfile.mkdtemp()) / "page.png"
    print(f"mockup : {mockup}")
    print(f"page   : {page}")
    try:
        _page_screenshot(chrome, page, shot, height=height)
    except Exception as exc:  # noqa: BLE001
        print(f"screenshot failed: {exc}")
        return 1
    from PIL import Image
    w, h = Image.open(shot).size
    print(f"full page captured at {w}x{h}")

    print("asking the vision model to review ...")
    try:
        # The page is taller than the mockup and carries the small print, so it
        # gets a larger long edge (still well under the payload limit).
        report = _parse_critique(
            _vision_chat([mockup, shot], CRITIQUE_PROMPT, max_edges=[1600, 2400]))
    except Exception as exc:  # noqa: BLE001
        print(f"critique failed: {exc}")
        return 1

    verdict = str(report.get("verdict", "")).strip()
    defects = report.get("defects") or []
    print()
    print(f"verdict: {verdict or '(none)'}\n")
    if not defects:
        print("no composition defects reported.")
    for d in defects:
        sev = str(d.get("severity", "?")).lower()
        print(f"  [{sev:6s}] {d.get('where', '?')} — {d.get('what', '')}")
        if d.get("fix"):
            print(f"           fix: {d['fix']}")
    if out_arg:
        Path(out_arg).write_text(json.dumps(report, indent=2))
        print(f"\nreport written to {out_arg}")
    return 0


# --------------------------------------------------------------------------
# job / jobs: inspect the studio's job store
# --------------------------------------------------------------------------
def cmd_job(args: list[str]) -> int:
    if not args:
        print("usage: doctor job <id>")
        return 2
    from app.jobs import JobStore
    store = JobStore(lambda job: None)  # load records only; never run anything
    j = store.get(args[0])
    if not j:
        print(f"no such job: {args[0]} (try: doctor jobs)")
        return 1
    print(json.dumps({k: v for k, v in j.to_dict().items() if k != "logs"}, indent=2))
    print("\nlogs:")
    print("\n".join(j.logs))
    return 0


def cmd_jobs(_args: list[str]) -> int:
    from app.jobs import JobStore
    store = JobStore(lambda job: None)
    jobs = store.list()
    if not jobs:
        print("no jobs yet")
        return 0
    for j in jobs:
        score = f"{j.score:.2f}" if j.score is not None else "  - "
        print(f"{j.id}  {time.strftime('%H:%M:%S', time.localtime(j.created))}  "
              f"{j.status:7s} {j.stage:11s} {score}  {j.src.get('filename') if j.src else ''}")
    return 0


COMMANDS = {
    "env": cmd_env,
    "polarity": cmd_polarity,
    "fixtures": cmd_fixtures,
    "light": cmd_light,
    "regress": cmd_regress,
    "gate": cmd_gate,
    "run": cmd_run,
    "critique": cmd_critique,
    "job": cmd_job,
    "jobs": cmd_jobs,
}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"unknown command {cmd!r}\n")
        print(__doc__)
        return 2
    return COMMANDS[cmd](sys.argv[2:])


if __name__ == "__main__":
    sys.exit(main())
