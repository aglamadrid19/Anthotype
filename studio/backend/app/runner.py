"""The orchestrator: run the pipeline for one uploaded design.

The stages mirror `qa/newdesign.py`'s documented loop, with the two additions
the studio needs (a vision-LLM extraction step, and a fidelity self-check):

    extract  -> vision LLM gives the copy + boxes
    generate -> content-<id>.json, <id>.page.css, designs/<id>.json
    trace    -> python qa/mkart.py <id> --out <id>.svg
    compose  -> node gen-page.mjs <id>
    build    -> node to-astro.mjs <id> && astro build
    verify   -> screenshot, downsample, mean-abs-diff vs the reference
    package  -> zip the Astro project + the self-contained page

Every stage is a subprocess with a timeout; a failure is recorded on the job
rather than raised out of the worker.
"""
from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from . import generate, workspace
from .config import JOBS_DIR, TIMEOUT_BUILD, TIMEOUT_DEFAULT, TIMEOUT_TRACE
from .extract import ExtractError, extract
from .imageutil import UploadError, normalize
from .jobs import Job, JobStore
from .procs import StageError, find_node, node_env, run

# node script names inside the workspace pipeline
GEN_PAGE = "gen-page.mjs"
TO_ASTRO = "to-astro.mjs"


class PipelineRunner:
    def __init__(self, store: JobStore) -> None:
        self.store = store

    # -- helpers -----------------------------------------------------------
    def _py(self, ws: workspace.Workspace) -> str:
        """The venv python, falling back to the repo's (symlinked as .venv)."""
        cand = ws.root / ".venv" / "bin" / "python"
        return str(cand) if cand.exists() else "python3"

    def _node(self) -> str:
        return find_node()

    def _npm(self) -> str:
        node = find_node()
        npm = Path(node).parent / "npm"
        return str(npm) if npm.exists() else "npm"

    # -- the job -----------------------------------------------------------
    def __call__(self, job: Job) -> None:
        jid = job.id
        ws = workspace.create(jid, JOBS_DIR)
        self.store.log(jid, f"workspace: {ws.root}")

        # ---- 1. normalize the upload ------------------------------------
        self.store.advance(jid, "received", "Normalizing the upload")
        raw = (job.dir / "upload.bin").read_bytes()
        # Kept in the job dir (not in the workspace): `newdesign.py` copies it
        # into the pipeline itself, and pre-placing it would make that a no-op
        # copy onto itself.
        norm = normalize(raw, job.dir / "ref.png")
        self.store.update(jid, src={
            "filename": (job.src or {}).get("filename"),
            "bytes": len(raw),
            "width": norm.src_w, "height": norm.src_h,
            "scale": round(norm.scale, 4),
            "background": list(norm.background),
        })
        self.store.log(jid, f"reference normalized: {norm.src_w}x{norm.src_h} -> "
                            f"{norm.path.name}, bg={norm.background}")

        # ---- 2. scaffold the design -------------------------------------
        self.store.advance(jid, "generating", "Scaffolding the design")
        self._stage(jid, "scaffold", [
            self._py(ws), "qa/newdesign.py", jid, str(norm.path),
            "--box", "0", "0", "1024", "768", "--no-site",
        ], ws.pipeline, TIMEOUT_DEFAULT)
        # The template's npm script uses a fixed port; the studio never runs
        # `npm run dev`, so the placeholder is harmless.  Bring the site in from
        # the template and share a node_modules so the build is fast.
        self._scaffold_site(jid, ws)

        # ---- 3. extract the text layer ----------------------------------
        self.store.advance(jid, "extracting")
        blocks = self._extract(jid, norm.path, norm.background)

        # ---- 4. generate content + layout + exclusion rects -------------
        self.store.advance(jid, "generating")
        generate.write_all(ws.pipeline, jid, blocks, norm.background)
        self.store.update(jid, blocks=[
            {"text": b.text, "role": b.role,
             "bbox": [round(v) for v in b.bbox],
             "color": list(b.color) if b.color else None}
            for b in blocks
        ])
        self.store.log(jid, f"generated text layer: {len(blocks)} block(s)")

        # ---- 5. trace the artwork ---------------------------------------
        self.store.advance(jid, "tracing")
        log = self._stage(jid, "trace", [
            self._py(ws), "qa/mkart.py", jid, "--out", f"{jid}.svg",
        ], ws.pipeline, TIMEOUT_TRACE)
        self.store.log(jid, log.strip().splitlines()[-1] if log.strip() else "traced")

        # ---- 6. compose the self-contained page -------------------------
        self.store.advance(jid, "composing")
        self._stage(jid, "compose", [self._node(), GEN_PAGE, jid],
                    ws.pipeline, TIMEOUT_DEFAULT)
        self._stage(jid, "to-astro", [self._node(), TO_ASTRO, jid],
                    ws.pipeline, TIMEOUT_DEFAULT)

        # ---- 7. build the Astro site ------------------------------------
        self.store.advance(jid, "building")
        self._npm_build(jid, ws)
        if not ws.dist_page.is_file():
            raise RuntimeError(f"build produced no {ws.dist_page}")

        # ---- 8. verify ---------------------------------------------------
        self.store.advance(jid, "verifying")
        self._verify(jid, ws, norm.path)

        # ---- 9. package --------------------------------------------------
        self.store.advance(jid, "packaging")
        zip_path = self._package(jid, ws)
        self.store.update(jid, artifacts={
            "zip": f"{jid}/dist.zip",
            "preview": f"{jid}/index.html",
            "svg": f"{jid}/{jid}.svg",
            "page_bytes": ws.dist_page.stat().st_size,
            "zip_bytes": zip_path.stat().st_size,
        })
        self.store.log(jid, f"packaged {zip_path.name} ({zip_path.stat().st_size // 1024} KB)")

    # -- stage wrappers ----------------------------------------------------
    def _stage(self, jid: str, name: str, cmd: list[str], cwd: Path, timeout: int) -> str:
        self.store.log(jid, f"$ {' '.join(str(c) for c in cmd)}")
        try:
            log = run(name, [str(c) for c in cmd], cwd, timeout=timeout, env=node_env())
        except StageError as exc:
            self.store.log(jid, str(exc))
            raise
        for line in log.strip().splitlines()[-6:]:
            self.store.log(jid, "  " + line)
        return log

    def _scaffold_site(self, jid: str, ws: workspace.Workspace) -> None:
        """newdesign.py --no-site skipped the Astro project; bring it in here so
        we can share node_modules before the build."""
        site = ws.site
        site.mkdir(parents=True, exist_ok=True)
        tmpl = ws.pipeline / "site-template"
        shutil.copy(tmpl / "astro.config.mjs", site / "astro.config.mjs")
        pkg = (tmpl / "package.json.tmpl").read_text()
        (site / "package.json").write_text(
            pkg.replace("__NAME__", jid).replace("__PORT__", "0"))
        (site / "src" / "pages").mkdir(parents=True, exist_ok=True)
        if workspace.share_node_modules(ws):
            self.store.log(jid, "reusing an existing node_modules (symlinked)")
        else:
            self.store.log(jid, "no shareable node_modules; will install")

    def _npm_build(self, jid: str, ws: workspace.Workspace) -> None:
        npm = self._npm()
        if not (ws.site / "node_modules" / "astro").exists():
            self._stage(jid, "npm-install", [npm, "install", "--no-audit", "--no-fund"],
                        ws.site, TIMEOUT_BUILD)
        self._stage(jid, "astro-build", [npm, "run", "build"], ws.site, TIMEOUT_BUILD)

    def _extract(self, jid: str, ref_png: Path, background: tuple[int, int, int]):
        try:
            blocks = extract(ref_png)
        except ExtractError as exc:
            raise RuntimeError(str(exc)) from exc
        return generate.decorate(blocks, ref_png, background)

    # -- verification ------------------------------------------------------
    def _verify(self, jid: str, ws: workspace.Workspace, ref_png: Path) -> None:
        """Screenshot the built page and score it against the reference.

        Optional: a missing Chrome or a screenshot failure is a warning, not a
        build failure -- the site itself is still valid and downloadable.
        """
        try:
            from . import verify
            score, pct = verify.score(jid, ws.dist_page, ref_png)
        except Exception as exc:  # noqa: BLE001 - never fail a job over scoring
            self.store.log(jid, f"score skipped: {exc}")
            self.store.update(jid, warnings=(self.store.get(jid).warnings or [])
                              + [f"self-check unavailable: {exc}"])
            return
        self.store.update(jid, score=score, pct_over_30=pct)
        self.store.log(jid, f"fidelity: mean {score:.2f}, pct>30 {pct:.2f}%")

    # -- packaging ---------------------------------------------------------
    def _package(self, jid: str, ws: workspace.Workspace) -> Path:
        out = JOBS_DIR / jid
        shutil.copy2(ws.dist_page, out / "index.html")
        zip_path = out / "dist.zip"
        site = ws.site
        readme = _README.format(name=jid)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            # the built, self-contained page
            z.write(ws.dist_page, "index.html")
            # the editable source
            for rel in ("astro.config.mjs", "package.json", "package-lock.json"):
                p = site / rel
                if p.is_file():
                    z.write(p, rel)
            page = site / "src" / "pages" / "index.astro"
            if page.is_file():
                z.write(page, "src/pages/index.astro")
            # pipeline provenance, so the page can be regenerated/re-tuned
            for rel in (f"{jid}.svg", f"{jid}.page.css", f"content-{jid}.json",
                        f"designs/{jid}.json"):
                p = ws.pipeline / rel
                if p.is_file():
                    z.write(p, f"pipeline/{Path(rel).name}")
            z.writestr("README.md", readme)
        return zip_path


_README = """# {name} — code-native site

Generated by **Anthotype Studio** from a design reference.  The output contains
no raster images: the artwork is traced SVG geometry, the text is real DOM, and
the page is a single self-contained `index.html`.

## Use it as-is

Open `index.html` in a browser (no server, no network).  It is one file.

## Develop it

```sh
npm install
npm run dev      # then open the printed localhost URL
npm run build    # -> dist/index.html
```

## What's here

| path | what |
|---|---|
| `index.html` | the built, self-contained page |
| `src/pages/index.astro` | the page source |
| `pipeline/<name>.svg` | the traced artwork (real vector geometry) |
| `pipeline/<name>.page.css` | the layout/type layer |
| `pipeline/content-<name>.json` | the text layer |
| `pipeline/designs/<name>.json` | tracing config (box, text rects, params) |

The artwork is decorative (`aria-hidden`); the headline, tagline and CTA are
real text and carry all the meaning.

## Regenerate the art

The tracer needs [potrace](https://potrace.sourceforge.net/) (`brew install potrace`):

```sh
python qa/mkart.py <name> --out <name>.svg
```
"""
