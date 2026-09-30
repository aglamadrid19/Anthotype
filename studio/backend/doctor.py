#!/usr/bin/env python3
"""Diagnose the studio and the pipeline.

When something looks wrong, start here.

    doctor env              check every dependency (venv, node, potrace, chrome,
                            fonts, the vision model / AntSeed proxy)
    doctor polarity         synthetic light/dark checks for the ink, wrapping and
                            scope heuristics (no vision model, no pipeline)
    doctor fixtures [name]  build every saved extraction end to end and score it
                            (no vision model): the light fixture plus the two
                            real designs that regressed
    doctor light [--keep]   the light fixture alone (kept for the README)
    doctor regress          prove the shipped pipeline is intact: run the repo's
                            own qa/verify.sh and report A/B/C PASS/FAIL
    doctor run [png]        run one design end to end, in-process, printing every
                            stage and its timing (no HTTP, no queue)
    doctor job <id>         inspect a studio job: status, score, artifacts, logs
    doctor jobs             list recent jobs

Exit code is non-zero if any check fails, so it is CI-able.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
    import shutil
    pt = shutil.which("potrace")
    if not pt:
        _line(BAD, "potrace", "not on PATH -- brew install potrace")
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

    # Wrapped block: many lines, and not clamped to the old 8 px floor.
    tagline = ("A tool inspired by the anthotype process — sunlight, plant "
               "pigment, and time — to transform an image into a real website.")
    fs, n = fontmetrics.fit_block_type(tagline, 331, 53, "tagline")
    _line(OK if n > 1 and fs >= 9 else BAD, "wrapped block sizing",
          f"{fs:.1f}px over {n} line(s)")
    one = fontmetrics.fit_block_type("Coming soon", 270, 42, "subhead")
    _line(OK if one[1] == 1 else BAD, "single-line block sizing",
          f"{one[0]:.1f}px over {one[1]} line(s)")

    # The extraction scope filter keeps page copy and drops illustration text.
    # `part=artwork` wins regardless of role; the size backstop applies only to
    # the ambiguous `other` role.
    from app.extract import Block
    footer = Block("Open source · Community driven", "other", (49, 481, 318, 507))
    caption = Block("Plant Pigment", "other", (559, 344, 619, 356))
    word = Block("antseed", "brand", (88, 170, 182, 194))    # small but real copy
    mock = Block("Get Started", "cta", (778, 466, 810, 480), part="artwork")
    checks = {"wide footer": generate.is_page_text(footer),
              "small wordmark": generate.is_page_text(word),
              "small caption": not generate.is_page_text(caption),
              "artwork CTA": not generate.is_page_text(mock)}
    ok = all(checks.values())
    _line(OK if ok else BAD, "page copy vs artwork",
          ", ".join(f"{k}={v}" for k, v in checks.items()))

    # Reference-driven line measurement: a wrapped block is two ink bands in the
    # reference, and the count must be read from the pixels -- the box alone
    # cannot tell a wrapped block from a single long line (the Montiva hero).
    from PIL import Image, ImageDraw, ImageFont
    stage = Image.new("RGB", (config.STAGE_W, config.STAGE_H), (248, 249, 247))
    d = ImageDraw.Draw(stage)
    d.text((100, 100), "First line of the headline", fill=(20, 24, 40),
           font=fontmetrics.pil_font(600, 30))
    d.text((100, 142), "Second line of the headline", fill=(20, 90, 220),
           font=fontmetrics.pil_font(600, 30))
    arr = np.asarray(stage).astype(np.float32)
    n_lines, pitch, runs = generate.measure_lines(arr, (95, 92, 420, 182), (248, 249, 247))
    _line(OK if n_lines == 2 and pitch and 30 <= pitch <= 48 else BAD,
          "line count from the reference",
          f"{n_lines} line(s), pitch {pitch and round(pitch, 1)}")
    if n_lines == 2:
        cols = generate.sample_line_colors(arr, runs, 95, 420, (248, 249, 247))
        spread = generate._max_channel_spread(cols)
        _line(OK if spread > 60 else BAD, "per-line colour (two-tone headline)",
              " / ".join(str(c) for c in cols))

    # Weight is measured, not assumed: a bold line covers more of its box than a
    # regular one, and the studio must pick the heavier vendored face for it.
    reg = Image.new("RGB", (900, 120), (248, 249, 247))
    ImageDraw.Draw(reg).text((20, 20), "Complete IT Services", fill=(10, 12, 20),
                             font=fontmetrics.pil_font(400, 48))
    bold = Image.new("RGB", (900, 120), (248, 249, 247))
    ImageDraw.Draw(bold).text((20, 20), "Complete IT Services", fill=(10, 12, 20),
                              font=fontmetrics.pil_font(600, 48))
    w_reg = generate.measure_weight(np.asarray(reg).astype(np.float32),
                                    (15, 15, 500, 80), "Complete IT Services",
                                    (248, 249, 247))
    w_bold = generate.measure_weight(np.asarray(bold).astype(np.float32),
                                     (15, 15, 500, 80), "Complete IT Services",
                                     (248, 249, 247))
    _line(OK if w_bold > w_reg else BAD, "weight from the reference",
          f"regular->{w_reg}, bold->{w_bold}")

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
# called, so these are deterministic and free; they guard the local layout,
# tracing and scoring paths in CI and on a fresh checkout.
#
# `light` is the synthetic first light design; `montiva` and `antho` are real
# uploads that failed badly (12.04 / 6.39) before the reference-driven line
# measurement and the ink inpainting landed, so they are the regression suite
# for exactly those two fixes.
FIXTURES: dict[str, dict] = {
    "light": dict(
        ref="light-ref.png", blocks="light-blocks.json", target=6.6,
        note="synthetic light ground; font substitution, not layout",
        page=8, artwork=0,
    ),
    "montiva": dict(
        ref="montiva-ref.png", blocks="montiva-blocks.json", target=9.2,
        note="real multi-section landing page (was 12.04; reference face is not Inter)",
    ),
    "antho": dict(
        ref="antho-ref.png", blocks="antho-blocks.json", target=7.0,
        note="real photorealistic hero (was 6.39; logo face is not Inter)",
    ),
}
LIGHT_FIXTURE = STUDIO_DIR / "fixtures"
LIGHT_TARGET = FIXTURES["light"]["target"]


def _run_fixture(name: str, keep: bool = False) -> int:
    """Build one saved extraction end to end (no model) and score it."""
    spec = FIXTURES[name]
    ref = LIGHT_FIXTURE / spec["ref"]
    blocks = LIGHT_FIXTURE / spec["blocks"]
    if not ref.is_file() or not blocks.is_file():
        print(f"missing fixture: {ref} / {blocks}")
        return 2

    print(f"fixture {name}: {ref.name} + {blocks.name} (no vision model)")
    print(f"  {spec['note']}; target <= {spec['target']}\n")

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
    if j.score is None:
        print("\nlog tail:")
        print("\n".join(j.logs[-30:]))
        if not keep:
            shutil.rmtree(j.dir, ignore_errors=True)
        return 1

    page = [b for b in (j.blocks or []) if b.get("part") == "page"]
    art = [b for b in (j.blocks or []) if b.get("part") == "artwork"]
    ok = j.score <= spec["target"] and not art
    # The light fixture pins an exact scope-filter result; the real fixtures only
    # assert that the copy survived (their block sets are large and model-derived).
    if "page" in spec:
        ok = ok and len(page) == spec["page"] and len(art) == spec["artwork"]
    else:
        ok = ok and any(b.get("role") == "headline" for b in page)

    print(f"score  : {j.score:.2f}  (target <= {spec['target']})")
    print(f"blocks : {len(page)} page, {len(art)} artwork left to the tracer")
    print(f"job dir: {j.dir}")
    if not keep:
        shutil.rmtree(j.dir, ignore_errors=True)
    print()
    if ok:
        print(f"fixture {name} PASS")
        return 0
    print(f"fixture {name} FAIL (score too high, or scope filter regressed)")
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
def cmd_regress(args: list[str]) -> int:
    script = PIPELINE_DIR / "qa" / "verify.sh"
    if not script.is_file():
        print(f"no {script}")
        return 1
    print("pipeline regression: qa/verify.sh (scores each built site vs its reference)")
    print("expected: a 2.71 / b 2.76 / c 2.99, all PASS\n")
    rc = subprocess.run([str(script), *args], cwd=str(PIPELINE_DIR)).returncode
    print()
    print("regression PASS" if rc == 0 else "regression FAIL")
    return rc


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
        print(f"score  : {j.score:.2f}  (pct>30 {j.pct_over_30:.2f}%)")
    print(f"total  : {total:.0f}s")
    print(f"job dir: {j.dir}")
    if j.status != "done":
        print("\nlog tail:")
        print("\n".join(j.logs[-30:]))
        return 1
    print(f"artifacts: {json.dumps(j.artifacts, indent=2)}")
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
    "run": cmd_run,
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
