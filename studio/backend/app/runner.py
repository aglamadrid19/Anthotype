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

import numpy as np
from PIL import Image

from . import generate, heroart, workspace
from .config import (JOBS_DIR, STAGE_H, STAGE_W, TIMEOUT_BUILD, TIMEOUT_DEFAULT,
                     TIMEOUT_TRACE)
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

        # ---- 4. generate the page structure + stylesheet ----------------
        self.store.advance(jid, "generating")
        content = generate.write_all(ws.pipeline, jid, blocks, norm.background)
        page = generate.page_blocks(blocks)
        self.store.update(jid, blocks=[
            {"text": b.text, "role": b.role, "part": getattr(b, "part", "page"),
             "section": getattr(b, "section", "other"),
             "bbox": [round(v) for v in b.bbox],
             "color": list(b.color) if b.color else None}
            for b in page
        ], structure=content.get("_structure"),
            structure_issues=content.get("_issues"))
        skipped = len(blocks) - len(page)
        note = f", {skipped} artwork block(s) left to the tracer" if skipped else ""
        sections = content.get("sections") or []
        self.store.log(jid, f"generated page: {len(page)} block(s) across "
                            f"{len(sections)} section(s) "
                            f"[{', '.join(sections) or 'none'}]{note}")
        for issue in content.get("_issues") or []:
            self.store.log(jid, f"  structure: {issue}")

        # ---- 4b. the hero backdrop: traced SVG or photographic raster ----
        hero = self._hero_art(jid, ws, norm, job.dir, content)

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
        self._verify(jid, ws, norm.path, norm.background)

        # ---- 9. structure self-check ------------------------------------
        # The pixel number no longer grades the page (it grades the *art* and
        # the palette).  What makes the output a website is its structure, so a
        # structural problem is surfaced as a warning rather than hidden behind
        # a good-looking score.
        structure = self._structure(jid, ws)
        if structure:
            self.store.update(jid, structure=structure)

        # ---- 9. package --------------------------------------------------
        self.store.advance(jid, "packaging")
        zip_path = self._package(jid, ws)
        artifacts = {
            "zip": f"{jid}/dist.zip",
            "preview": f"{jid}/index.html",
            "svg": f"{jid}/{jid}.svg",
            "page_bytes": ws.dist_page.stat().st_size,
            "zip_bytes": zip_path.stat().st_size,
        }
        if hero.get("kind") == "photographic" and hero.get("webp"):
            artifacts["hero"] = f"{jid}/{hero['webp']}"
        self.store.update(jid, artifacts=artifacts)
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

    def _hero_art(self, jid: str, ws: workspace.Workspace, norm, job_dir: Path,
                  content: dict) -> dict:
        """Choose how the hero backdrop is represented, and export a raster if needed.

        A photograph cannot be traced to flat vector regions at a sane payload
        (measured: the tracer plateaus around 3.5 mean on a photo hero while every
        knob is flat), so a photographic hero ships a fixed-resolution WebP on the
        page.  Flat artwork keeps the traced SVG, which is exact, small and
        code-native.  The SVG master is produced either way -- it is deliverable
        one, shipped in the zip.

        The decision is measured on the hero band (see `heroart`).  The raster is
        built by the tracer itself, from a native-resolution reference made from
        the ORIGINAL upload: the ingest fit throws away real resolution (a real
        upload was reduced to 61% of its linear detail), and -- more importantly --
        the tracer is the thing that knows how to inpaint the reference's own
        glyphs out, which a raw crop would leave ghosting behind the DOM copy.
        """
        band = content.get("hero_band")
        ref = np.asarray(Image.open(norm.path).convert("RGB"))
        photo, score = heroart.is_photographic(ref, band)
        if not photo:
            self.store.log(jid, f"hero backdrop: flat artwork (colour score {score} "
                                f"< {heroart.PHOTO_DISTINCT}) -> traced SVG")
            self.store.update(jid, hero_kind="svg", hero_distinct=score)
            return {"kind": "svg"}

        try:
            native = heroart.native_reference(
                job_dir / "upload.bin", ws.pipeline / "qa" / f"ref-{jid}-hi.png",
                STAGE_W, STAGE_H, norm.scale, (norm.pad[0], norm.pad[1]),
                norm.background)
            m = native["m"]
            base = json.loads((ws.pipeline / "designs" / f"{jid}.json").read_text())
            hi_name = f"{jid}-hi"
            (ws.pipeline / "designs" / f"{hi_name}.json").write_text(
                json.dumps(heroart.scaled_config(
                    base, m, f"qa/ref-{jid}-hi.png", hi_name, native["size"]),
                    indent=2) + "\n")
            prepared = ws.pipeline / f"{jid}-prepared.png"
            self._stage(jid, "prepare-hero", [
                self._py(ws), "qa/mkart.py", hi_name, "--up", "1",
                "--prepared-out", str(prepared),
            ], ws.pipeline, TIMEOUT_TRACE)
            written = heroart.export_from_prepared(
                prepared, band, m, ws.pipeline, f"{jid}-hero")
        except Exception as exc:  # noqa: BLE001 - fall back to the SVG master
            self.store.log(jid, f"hero backdrop: raster export failed ({exc}); "
                                f"falling back to the traced SVG")
            self.store.update(jid, hero_kind="svg", hero_distinct=score)
            return {"kind": "svg"}

        if not written:
            self.store.log(jid, "hero backdrop: photographic, but no raster could be "
                                "written -- falling back to the traced SVG")
            self.store.update(jid, hero_kind="svg", hero_distinct=score)
            return {"kind": "svg"}

        meta = written["webp"]
        info = {"kind": "photographic", "score": score, "native_scale": round(m, 3),
                "w": meta["w"], "h": meta["h"], "bytes": meta["bytes"],
                "webp": meta["name"]}
        # The page reads this from `content-<id>.json` (see `gen-page.mjs`).
        # Injected into the file rather than re-serialising the dict: `write_all`
        # deliberately keeps `_structure`/`_issues` out of the file, and a
        # re-write would leak them into the editable page definition.
        cfg_path = ws.pipeline / f"content-{jid}.json"
        data = json.loads(cfg_path.read_text())
        data["hero_image"] = info
        cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

        for ext, meta in sorted(written.items()):
            self.store.log(jid, f"hero backdrop: photographic (colour score {score}) "
                                f"-> {meta['name']} {meta['w']}x{meta['h']} "
                                f"{meta['bytes'] // 1024} KB")
        self.store.update(jid, hero_kind="photographic", hero_distinct=score,
                          hero_bytes=written["webp"]["bytes"])
        return info

    def _extract(self, jid: str, ref_png: Path, background: tuple[int, int, int]):
        try:
            blocks = extract(ref_png)
        except ExtractError as exc:
            raise RuntimeError(str(exc)) from exc
        # Keep the model's raw boxes before any local refinement (the CTA box in
        # particular is rewritten), so a bad extraction can be re-laid-out
        # without another model call.
        (JOBS_DIR / jid / "raw-blocks.json").write_text(json.dumps(
            {"blocks": [{"text": b.text, "role": b.role,
                         "part": getattr(b, "part", "page"),
                         "bbox": [float(v) for v in b.bbox]} for b in blocks]},
            indent=2) + "\n")
        return generate.decorate(blocks, ref_png, background)

    # -- verification ------------------------------------------------------
    @staticmethod
    def _hero_band(ws: workspace.Workspace, jid: str) -> list[int] | None:
        """The hero band from the generated content, to score the shipped art."""
        try:
            data = json.loads((ws.pipeline / f"content-{jid}.json").read_text())
        except Exception:  # noqa: BLE001
            return None
        band = data.get("hero_band")
        return band if isinstance(band, list) and len(band) == 2 else None

    def _verify(self, jid: str, ws: workspace.Workspace, ref_png: Path,
                background: tuple[int, int, int] | None = None) -> None:
        """Score the built page against the reference and check its structure.

        The pixel score now measures how faithfully the *artwork* and palette
        were recovered -- not how exactly the type was imitated.  A missing
        Chrome or a screenshot failure is a warning, not a build failure: the
        site itself is still valid and downloadable.
        """
        try:
            from . import verify
            cfg = {}
            try:
                cfg = json.loads(
                    (ws.pipeline / "designs" / f"{jid}.json").read_text())
            except Exception:  # noqa: BLE001
                pass
            result = verify.assess(
                jid, ws.dist_page, ref_png, pipeline=ws.pipeline,
                art_svg=ws.pipeline / f"{jid}.svg",
                layout=cfg.get("layout", "page"),
                background=background,
                hero_image=ws.pipeline / f"{jid}-hero.webp",
                hero_band=self._hero_band(ws, jid))
        except Exception as exc:  # noqa: BLE001 - never fail a job over scoring
            self.store.log(jid, f"score skipped: {exc}")
            self.store.update(jid, warnings=(self.store.get(jid).warnings or [])
                              + [f"self-check unavailable: {exc}"])
            return
        self.store.update(jid, score=result.get("art_score"),
                          pct_over_30=result.get("art_pct"),
                          whole_score=result.get("whole_score"),
                          whole_pct=result.get("whole_pct"),
                          blank_seam=result.get("blank_seam"),
                          hero_fidelity=result.get("hero_score"))
        seam = result.get("blank_seam")
        self.store.log(
            jid, f"fidelity: art region mean {result['art_score']:.2f} "
                 f"(pct>30 {result['art_pct']:.2f}%, "
                 f"from the {result.get('art_source', 'page')}), "
                 f"whole page mean {result['whole_score']:.2f}"
                 + (f", blank seam {seam:.0f}/255" if seam is not None else ""))
        if result.get("hero_source") == "raster":
            self.store.log(jid, f"hero backdrop: shipped raster matches the reference "
                                f"at {result['hero_score']:.2f} mean "
                                f"(the traced master is {result['art_score']:.2f})")
        for issue in result.get("issues") or []:
            self.store.log(jid, f"  structure: {issue}")
            self.store.update(jid, warnings=(self.store.get(jid).warnings or [])
                              + [f"structure: {issue}"])
        self.store.update(jid, structure=result.get("structure"))

    def _structure(self, jid: str, ws: workspace.Workspace) -> dict | None:
        try:
            from . import structure
            return structure.summarize(ws.dist_page, ws.pipeline / f"{jid}.page.css")
        except Exception as exc:  # noqa: BLE001
            self.store.log(jid, f"structure check skipped: {exc}")
            return None

    # -- packaging ---------------------------------------------------------
    def _package(self, jid: str, ws: workspace.Workspace) -> Path:
        out = JOBS_DIR / jid
        shutil.copy2(ws.dist_page, out / "index.html")
        zip_path = out / "dist.zip"
        site = ws.site
        # The hero raster, when the page ships one: the page inlines it, but the
        # picture is deliverable two in its own right (a resolution-fixed image
        # that renders properly on the web), so it also lands beside the page and
        # at the root of the zip as a standalone asset.
        hero_files = [p for p in (ws.pipeline / f"{jid}-hero.webp",) if p.is_file()]
        for p in hero_files:
            shutil.copy2(p, out / p.name)
        readme = _README.format(name=jid, hero=_hero_readme(ws, jid))

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            # the built, self-contained page
            z.write(ws.dist_page, "index.html")
            for p in hero_files:
                z.write(p, p.name)
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


_README = """# {name} — site

Generated by **Anthotype Studio** from a design reference.  The text is real DOM
and the page is a single self-contained `index.html` — open it in a browser with
no server and no network.

{hero}

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
| `pipeline/<name>.svg` | the traced artwork — the vector art master |
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

## Both representations

The artwork is produced two ways, and they answer different questions:

- **the traced SVG** (`pipeline/<name>.svg`) is the vector master. It is exact
  and re-colourable for flat artwork, and it is what the page shows in that case.
- **the exported image** (`<name>-hero.webp`, when present) is what a photographic
  page actually ships. The page inlines it as a data URI; the copy at the root of
  this zip is the same picture as a standalone, resolution-fixed asset you can
  drop into any other design or CMS.

The image is built from your original upload at its own resolution, with the
reference's text inpainted out, so nothing from the mockup's type is baked in.
"""


def _hero_readme(ws: workspace.Workspace, jid: str) -> str:
    """What the hero backdrop is, for the download's README.

    The two representations are genuinely different products, and a reader of the
    zip should not have to guess which one they have.
    """
    info: dict = {}
    cfg = ws.pipeline / f"content-{jid}.json"
    if cfg.is_file():
        try:
            info = json.loads(cfg.read_text()).get("hero_image") or {}
        except Exception:  # noqa: BLE001
            info = {}
    if not info:
        return ("The hero backdrop is traced **SVG geometry** — real vector paths,\n"
                "no raster image anywhere in the page.")
    kb = info.get("bytes", 0) // 1024
    return (
        "The hero backdrop is a **photographic export** ({} × {} px WebP, {} KB,\n"
        "inlined as a data URI).  Flat vector regions cannot represent photographic\n"
        "tone at a web payload, so the page ships the image; `pipeline/{}.svg` is the\n"
        "traced art master, kept as a separate deliverable."
    ).format(info.get("w"), info.get("h"), kb, jid)
