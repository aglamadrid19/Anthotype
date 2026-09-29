#!/usr/bin/env python3
"""Diagnose the studio and the pipeline.

When something looks wrong, start here.

    doctor env              check every dependency (venv, node, potrace, chrome,
                            fonts, the vision model / AntSeed proxy)
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
from app.config import PIPELINE_DIR, REPO_ROOT  # noqa: E402

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
    _line(OK, "vision config", f"{v['provider']} {v['model']} @ {base}")
    # If it is the local AntSeed proxy, prove it is up.
    if "127.0.0.1" in base or "localhost" in base:
        try:
            import httpx
            r = httpx.get(f"{base}/models", timeout=5)
            n = len(r.json().get("data", [])) if r.status_code == 200 else 0
            if r.status_code == 200:
                _line(OK, "vision endpoint", f"reachable, {n} models")
            else:
                _line(BAD, "vision endpoint", f"HTTP {r.status_code}")
        except Exception as exc:  # noqa: BLE001
            _line(BAD, "vision endpoint",
                  f"unreachable at {base} ({type(exc).__name__}) -- is the AntSeed proxy running?")


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
