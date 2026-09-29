"""Per-job isolated workspace around the pipeline.

The pipeline keys every artifact by design name (`designs/<n>.json`,
`<n>-full.html`, `sites/variant-<n>/`) and hardwires a single repo tree, so two
jobs sharing one tree would collide.  Each job therefore gets its own copy of
the pipeline skeleton.

What is copied: the code and templates that make up the pipeline (`lib/`, `qa/`,
`site-template/`, `gen-page.mjs`, `to-astro.mjs`, `fonts/`).  What is NOT
copied: the shipped designs and their art (`designs/`, `sites/`, `{a,b,c}.*`) --
a job must never touch the regression suite.

Heavy, shareable things are symlinked instead of copied:
  * the repo's Python venv  -> `<ws>/.venv`
  * a scaffolded site's `node_modules` -> `<ws>/sites/variant-<id>/node_modules`
    (falling back to a real `npm install` if Astro cannot resolve through it).
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from .config import PIPELINE_DIR, REPO_ROOT, REPO_VENV_PY

# Pipeline entries a job needs.  Everything else in pipeline/ is either shipped
# design state or QA scratch.
COPY_DIRS = ["lib", "qa", "site-template", "fonts"]
COPY_FILES = ["gen-page.mjs", "to-astro.mjs"]

# Never copy these out of qa/ (stale scratch / other designs' references).
QA_SKIP_SUFFIXES = (".pyc",)
QA_SKIP_NAMES = {"__pycache__"}


@dataclass
class Workspace:
    root: Path
    job_id: str

    @property
    def pipeline(self) -> Path:
        return self.root / "pipeline"

    @property
    def site(self) -> Path:
        return self.root / "sites" / f"variant-{self.job_id}"

    @property
    def dist_page(self) -> Path:
        return self.site / "dist" / "index.html"

    @property
    def full_page(self) -> Path:
        return self.pipeline / f"{self.job_id}-full.html"

    @property
    def svg(self) -> Path:
        return self.pipeline / f"{self.job_id}.svg"


def _ignore(_dir: str, names: list[str]) -> set[str]:
    out = set()
    for n in names:
        if n in QA_SKIP_NAMES or n.endswith(QA_SKIP_SUFFIXES):
            out.add(n)
    return out


def _share_node_modules(ws: Workspace) -> bool:
    """Symlink a scaffolded site's node_modules into this job's site.

    Returns True when a shareable node_modules was found.  Astro resolves
    through the symlink because the site dir is inside the job workspace and the
    link target is an absolute path to a complete install.
    """
    site = ws.site
    if not site.is_dir():
        return False
    if (site / "node_modules").exists():
        return True
    for name in ("a", "b", "c"):
        candidate = REPO_ROOT / "sites" / f"variant-{name}" / "node_modules"
        if (candidate / "astro").is_dir():
            os.symlink(candidate, site / "node_modules", target_is_directory=True)
            return True
    return False


def create(job_id: str, jobs_dir: Path) -> Workspace:
    """Materialize an isolated pipeline workspace for `job_id`."""
    ws = Workspace(root=jobs_dir / job_id / "workspace", job_id=job_id)
    if ws.pipeline.is_dir():
        return ws

    ws.root.mkdir(parents=True, exist_ok=True)
    (ws.pipeline / "designs").mkdir(parents=True, exist_ok=True)
    (ws.root / "sites").mkdir(parents=True, exist_ok=True)

    for d in COPY_DIRS:
        src = PIPELINE_DIR / d
        if src.is_dir():
            shutil.copytree(src, ws.pipeline / d, ignore=_ignore)
    for f in COPY_FILES:
        src = PIPELINE_DIR / f
        if src.is_file():
            shutil.copy2(src, ws.pipeline / f)

    # The QA tools resolve the interpreter by probing candidate paths; a venv
    # symlinked at <ws>/.venv is the second candidate they try.
    if REPO_VENV_PY.is_file() and not (ws.root / ".venv").exists():
        os.symlink(REPO_VENV_PY.parent.parent, ws.root / ".venv",
                   target_is_directory=True)
    return ws


def share_node_modules(ws: Workspace) -> bool:
    """Called after `newdesign.py` has scaffolded the site."""
    return _share_node_modules(ws)
