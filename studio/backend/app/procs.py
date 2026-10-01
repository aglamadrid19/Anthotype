"""Subprocess helpers: run a stage with a timeout and captured output."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StageError(RuntimeError):
    stage: str
    cmd: list[str]
    returncode: int | None
    log: str

    def __str__(self) -> str:  # pragma: no cover - display only
        tail = "\n".join(self.log.strip().splitlines()[-12:])
        return f"stage {self.stage!r} failed (rc={self.returncode}):\n{tail}"


def find_node() -> str:
    """Resolve node without hardcoding an nvm path (mirrors _env.py)."""
    node = os.environ.get("NODE") or shutil.which("node")
    if node:
        return node
    import glob
    for cand in sorted(glob.glob(os.path.expanduser("~/.nvm/versions/node/*/bin/node")),
                       reverse=True):
        if os.path.isfile(cand):
            return cand
    for cand in ("/opt/homebrew/bin/node", "/usr/local/bin/node"):
        if os.path.isfile(cand):
            return cand
    raise RuntimeError("no node found on PATH (install node, or set NODE=...)")


# Directories that a GUI-launched or minimal-PATH server commonly misses.  A
# backend started by launchd, an IDE, or a shell without Homebrew on PATH cannot
# see `potrace`, and the trace stage then dies with `FileNotFoundError: 'potrace'`
# *after* extraction and generation have already succeeded -- a confusing failure.
_FALLBACK_BINS = ("/opt/homebrew/bin", "/usr/local/bin")


def find_potrace() -> str | None:
    """Locate the potrace binary, or None if it is genuinely absent.

    Same fallback logic as `find_node`: a GUI-launched or minimal-PATH shell
    cannot see Homebrew's bin, yet `mkart.py` shells out to `potrace` through
    `node_env()`, which does prepend those dirs.  `doctor env` must therefore use
    this too, or it reports a failure the pipeline would not actually hit.
    """
    found = os.environ.get("POTRACE") or shutil.which("potrace")
    if found:
        return found
    for d in _FALLBACK_BINS:
        cand = Path(d) / "potrace"
        if cand.is_file():
            return str(cand)
    return None


def node_env() -> dict[str, str]:
    """Env for a pipeline subprocess: node on PATH, plus the usual tool dirs.

    `mkart.py` shells out to `potrace`, so the subprocess PATH must contain the
    Homebrew/local bin dirs even when the *server's* PATH does not.  Prepending
    them unconditionally is safe: real entries win (they are prepended in order and
    deduped), and a missing dir is simply ignored.
    """
    env = dict(os.environ)
    parts = [os.path.dirname(find_node()), *_FALLBACK_BINS]
    pt = find_potrace()
    if pt:
        d = os.path.dirname(pt)
        if d not in parts:
            parts.insert(0, d)
    for extra in (env.get("PATH", "") or "").split(os.pathsep):
        if extra and extra not in parts:
            parts.append(extra)
    env["PATH"] = os.pathsep.join(parts)
    return env


def run(stage: str, cmd: list[str], cwd: Path, *, timeout: int,
        env: dict[str, str] | None = None) -> str:
    """Run `cmd`, returning combined stdout/stderr.

    Raises StageError on a non-zero exit or timeout, carrying the captured log
    so the job can report exactly what went wrong.
    """
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd), env=env, timeout=timeout,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except subprocess.TimeoutExpired as exc:
        log = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        raise StageError(stage, cmd, None, f"timed out after {timeout}s\n{log}") from exc
    log = proc.stdout or ""
    if proc.returncode != 0:
        raise StageError(stage, cmd, proc.returncode, log)
    return log
