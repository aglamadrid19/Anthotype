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

import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

from . import cleanup, enhance, generate, heroart, repair, workspace
from .config import (JOBS_DIR, STAGE_H, STAGE_W, TIMEOUT_BUILD, TIMEOUT_DEFAULT,
                     TIMEOUT_TRACE)
from .extract import ExtractError, extract
from .imageutil import UploadError, normalize
from .jobs import Job, JobStore
from .procs import StageError, find_node, node_env, run

# The scene rendition's WebP quality.  Measured at 2x: q82 softens the
# dashboard's small lettering; q90 is visually close to lossless and the 3172 px
# asset is ~206 KB (the whole point of the lossy path is payload -- the
# prototype's lossless file was 2 MB).
SCENE_QUALITY = 90

# node script names inside the workspace pipeline
GEN_PAGE = "gen-page.mjs"
TO_ASTRO = "to-astro.mjs"


def repair_enabled() -> bool:
    """The source-preserving repair runs with the enhancement by default."""
    return os.environ.get("STUDIO_ART_REPAIR", "").strip().lower() not in (
        "0", "off", "no", "false")


def _content_boxes(blocks: list | None, norm,
                   row_off: float) -> list[list[float]]:
    """The extraction's artwork blocks (stage coords) in the input's pixels."""
    out: list[list[float]] = []
    for b in blocks or []:
        if getattr(b, "part", "page") != "artwork":
            continue
        x0, y0, x1, y1 = b.bbox
        out.append([(x0 - norm.pad[0]) / norm.scale,
                    (y0 - norm.pad[1]) / norm.scale + row_off,
                    (x1 - norm.pad[0]) / norm.scale,
                    (y1 - norm.pad[1]) / norm.scale + row_off])
    return out


class NothingToAccept(RuntimeError):
    """The job has no pending enhancement candidate to accept."""


class ReviewRequired(RuntimeError):
    """The candidate's labels must be explicitly reviewed before it ships."""


class PipelineRunner:
    def __init__(self, store: JobStore) -> None:
        self.store = store
        # Acceptances rewrite the content and rebuild the page; two concurrent
        # requests would interleave those writes, so they are serialized.
        self._enhance_lock = threading.Lock()

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
        # The hero's flat-vs-photograph nature is measured HERE, before the page
        # is written: the scene prototype transforms the content (lifting the
        # benefit row, blanking its original row) and must not touch a
        # photographic hero.  `_hero_art` re-measures for the raster decision.
        self.store.advance(jid, "generating")
        ref = np.asarray(Image.open(norm.path).convert("RGB"))
        band = generate.hero_band(generate.group_sections(blocks))
        photo, _photo_score = heroart.is_photographic(ref, band)
        content = generate.write_all(ws.pipeline, jid, blocks, norm.background,
                                     scene_ok=not photo)
        if photo:
            self.store.log(jid, "hero: continuous-tone artwork -- the full-bleed "
                                "composition is used (no scene/illustration edits)")
        page = generate.page_blocks(blocks)
        self.store.update(jid, blocks=[
            {"text": b.text, "role": b.role, "part": getattr(b, "part", "page"),
             "section": getattr(b, "section", "other"),
             "bbox": [round(v) for v in b.bbox],
             "color": list(b.color) if b.color else None}
            for b in page
        ], artwork_rects=[list(b.bbox) for b in blocks
                          if getattr(b, "part", "page") == "artwork"],
            structure=content.get("_structure"),
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
        hero = self._hero_art(jid, ws, norm, job.dir, content, blocks)
        # An opt-in enhancement candidate (see `app/enhance.py`) is a preview:
        # it lands beside the page for the UI, but the shipped asset stays.
        # A diagnostic candidate (partial/failed repair) is shown the same way
        # but cannot be accepted.
        if self.store.get(jid).hero_enhance in ("pending", "diagnostic"):
            cand = ws.pipeline / f"{jid}-hero-enhance.webp"
            if cand.is_file():
                shutil.copy2(cand, job.dir / cand.name)
        # Where each recovered artwork element ended up: the labels of an
        # illustration must be *in* the asset, so this records their destination
        # rather than leaving their fate implicit in the pixels.
        self.store.update(jid, assets=self._asset_inventory(blocks, content))

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
        self._verify(jid, ws, norm.path, norm.background, blocks)

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
        if self.store.get(jid).hero_enhance in ("pending", "diagnostic"):
            artifacts["hero_enhance"] = f"{jid}/{jid}-hero-enhance.webp"
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
                  content: dict, blocks: list) -> dict:
        """Choose how the hero backdrop is represented, and export a raster if needed.

        A photograph cannot be traced to flat vector regions at a sane payload
        (measured: the tracer plateaus around 3.5 mean on a photo hero while every
        knob is flat), so a photographic hero ships a fixed-resolution WebP on the
        page.  And a *flat* hero whose upload is wider than the 1024 px stage ships
        the raster too, because the traced SVG is bounded by the stage and a
        full-bleed hero is magnified on any desktop wider than that (1.37x at
        1400 px, 1.88x at 1920 px) -- so the resolution the upload carries would
        otherwise be thrown away.  Flat artwork at the stage's own resolution
        keeps the traced SVG, which is exact, small and code-native.  The SVG
        master is produced either way -- it is deliverable one, shipped in the zip.

        A hero whose artwork is an *illustration* (the model recovered its own
        labels, see `generate.hero_figure`) is exported as that figure's own
        crop, not as a page-wide band: `object-fit: cover` on a full-bleed band
        crops exactly the sides the labels sit on.  The split is only taken for
        flat artwork -- a continuous-tone hero is a photograph, and a photograph
        is backdrop texture: it stays full-bleed even when labels were found in
        it.  The decision and the reason are logged.

        The raster is built from a native-resolution reference made from the
        ORIGINAL upload: the ingest fit throws away real resolution (a real
        upload was reduced to 61% of its linear detail).  For a *scene* the
        removed copy is reconstructed by the optional external cleanup (LaMa
        over upload-driven complete-element masks, original pixels kept outside
        them) when `studio/.cleanup-venv` or `STUDIO_CLEANUP_PYTHON` exists, and
        by the tracer's nearest fill otherwise -- the job records which.  The
        scene rendition is then Lanczos-upscaled for display sharpness (a
        rendering enhancement, not source detail: the resolution warning keeps
        reporting the source width) and encoded lossy at `SCENE_QUALITY`.
        """
        band = content.get("hero_band")
        ref = np.asarray(Image.open(norm.path).convert("RGB"))
        raster, score, _m, reason = heroart.wants_raster(ref, band, norm.scale)
        layout = content.get("hero_layout") if content.get("hero_layout") in (
            "full", "split", "scene") else "full"
        figure = content.get("hero_figure") if layout == "split" else None
        if layout in ("split", "scene"):
            # The illustration compositions are only right for FLAT artwork.  A
            # continuous-tone hero is a photograph: its "labels" are part of the
            # photograph, and the design is composed for a full-bleed backdrop.
            photo, _ = heroart.is_photographic(ref, band)
            if photo:
                layout, figure = "full", None
                reason += ("; illustration composition declined -- the artwork is "
                           "continuous-tone (a photograph) and stays the "
                           "page-wide backdrop")
                self.store.log(jid, f"hero illustration: {reason}")
        # Keep the in-memory content in step with the file below, so the asset
        # inventory and the caller see the final decision (not the provisional
        # split `write_all` offered before the pixels were measured).
        content["hero_layout"] = layout
        content["hero_figure"] = figure

        if not raster:
            self._set_content_hero(ws, jid, hero_layout=layout, hero_figure=figure)
            self.store.log(jid, f"hero backdrop: traced SVG -- {reason}")
            self.store.update(jid, hero_kind="svg", hero_distinct=score,
                              hero_reason=reason, hero_layout=layout)
            return {"kind": "svg", "layout": layout}

        try:
            cleaned_src, cleanup_kind = (None, "full")
            if layout in ("scene", "full"):
                cleaned_src, cleanup_kind = self._clean_artwork(
                    jid, ws, job_dir, norm, blocks, content)
            source_png = cleaned_src or (job_dir / "upload.bin")
            canvas = ws.pipeline / "qa" / f"ref-{jid}-hi.png"
            native = heroart.native_reference(
                source_png, canvas, STAGE_W, STAGE_H, norm.scale,
                (norm.pad[0], norm.pad[1]), norm.background)
            m = native["m"]
            if cleaned_src:
                # The cleaned canvas IS the prepared image: the copy is already
                # gone (LaMa-reconstructed), so the tracer is not asked to
                # inpaint anything on the raster path.  The SVG master still
                # runs the normal tracer path later.
                prepared = canvas
            else:
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
                prepared, band, m, ws.pipeline, f"{jid}-hero", figure=figure,
                quality=(SCENE_QUALITY if layout == "scene"
                         else heroart.WEBP_QUALITY),
                upscale=(2 if layout == "scene" else 1))
        except Exception as exc:  # noqa: BLE001 - fall back to the SVG master
            self._set_content_hero(ws, jid, hero_layout=layout, hero_figure=figure)
            self.store.log(jid, f"hero backdrop: raster export failed ({exc}); "
                                f"falling back to the traced SVG")
            self.store.update(jid, hero_kind="svg", hero_distinct=score,
                              hero_reason=f"raster export failed: {exc}",
                              hero_layout=layout)
            return {"kind": "svg", "layout": layout}

        if not written:
            self._set_content_hero(ws, jid, hero_layout=layout, hero_figure=figure)
            self.store.log(jid, "hero backdrop: raster wanted, but no image could be "
                                "written -- falling back to the traced SVG")
            self.store.update(jid, hero_kind="svg", hero_distinct=score,
                              hero_reason="raster wanted but not written",
                              hero_layout=layout)
            return {"kind": "svg", "layout": layout}

        meta = written["webp"]
        rendition = ("lanczos2"
                     if layout == "scene" and meta["w"] > meta["source_w"]
                     else "native")
        # Size honesty: is the asset enough for the pixels the page will paint?
        # The warning is about SOURCE resolution -- a Lanczos rendition is a
        # rendering enhancement and does not create detail, so `source_w` is
        # the number that counts.
        need, scale, note = heroart.resolution_gap(meta["source_w"], layout)
        info = {"kind": "photographic", "score": score, "native_scale": round(m, 3),
                "reason": reason, "layout": layout, "figure": figure,
                "cleanup": cleanup_kind, "rendition": rendition,
                "source_w": meta["source_w"], "needed": need,
                "w": meta["w"], "h": meta["h"], "bytes": meta["bytes"],
                "webp": meta["name"]}
        # The page reads layout/figure/image from `content-<id>.json` (see
        # `gen-page.mjs`).  The file is finalised here -- `write_all` could not
        # know the raster decision (it needs the upload's pixels), and the
        # content writer deliberately keeps `_structure`/`_issues` out of the
        # editable page definition.  This helper updates in place for the same
        # reason instead of re-serialising `content`.
        self._set_content_hero(ws, jid, hero_layout=layout, hero_figure=figure,
                               hero_image=info)

        self.store.update(jid, hero_needed=need, hero_scale=round(scale, 2))
        if note:
            self.store.log(jid, f"hero resolution: {note}")
            self.store.update(jid, warnings=(self.store.get(jid).warnings or []) + [note])

        for ext, meta_w in sorted(written.items()):
            self.store.log(jid, f"hero backdrop: raster export ({reason}; "
                                f"cleanup {cleanup_kind}, {rendition}) "
                                f"-> {meta_w['name']} {meta_w['w']}x{meta_w['h']} "
                                f"{meta_w['bytes'] // 1024} KB")
        self.store.update(jid, hero_kind="photographic", hero_distinct=score,
                          hero_reason=reason, hero_layout=layout,
                          hero_cleanup=cleanup_kind,
                          hero_bytes=written["webp"]["bytes"])
        # Opt-in Google enhancement: a *candidate*, never shipped by itself.
        # Both raster layouts share the path, and both require the LaMa-cleaned
        # upload: the tracer's fill is text-removed but not visually clean (it
        # leaves rectangular patches and component remnants), and sending that
        # to the model would ask it to re-render the artifacts.
        if layout in ("scene", "full"):
            if cleaned_src is not None:
                self._enhance_artwork(jid, ws, norm, content, cleaned_src, blocks)
            elif enhance.mode() is not None:
                self.store.log(jid, "hero enhance: skipped -- no LaMa-cleaned "
                                    "artwork (the tracer's fill is not a clean "
                                    "enhancement input)")
                self.store.update(jid, hero_enhance="skipped")
        return info

    def _enhance_artwork(self, jid: str, ws: workspace.Workspace, norm,
                         content: dict, cleaned_src: Path,
                         blocks: list | None = None) -> None:
        """Produce the opt-in enhanced candidate, pending acceptance.

        The input is the **LaMa-cleaned upload** (native resolution, page copy
        and component remnants removed) -- shared by the scene and the
        full-bleed raster layouts.  The band is in stage coordinates and the
        upload was fitted by `norm.scale`/`norm.pad`, so the crop rows are
        `(band - pad) / scale`; the candidate covers the upload at its own
        scale.  The raw model output then goes through the source-preserving
        repair (native content restored) before the band is derived.  Every
        failure keeps the shipped LaMa/Lanczos asset.
        """
        if not enhance.available():
            if enhance.mode() is not None:
                why = ("network forbidden" if enhance.network_forbidden()
                       else "GEMINI_API_KEY missing")
                self.store.log(jid, f"hero enhance: {why} -- skipped")
                self.store.update(jid, hero_enhance="skipped")
            return
        band = content.get("hero_band") or []
        if len(band) != 2:
            return
        # The whole step -- request, band crop, WebP encode, disk -- is optional:
        # ANY failure keeps the shipped LaMa/Lanczos asset and must never fail
        # the build (the candidate is a preview, not a deliverable).
        try:
            rows = ((band[0] - norm.pad[1]) / norm.scale,
                    (band[1] - norm.pad[1]) / norm.scale)
            # The band can extend past the upload's own pixels (into the canvas
            # letterbox); the input is extended with the design's background so
            # the candidate keeps the fallback export's geometry instead of
            # being clamped short.
            input_png, row_off = enhance.cover_band(
                cleaned_src, rows, norm.background,
                dest=ws.pipeline / f"{jid}-enhance-input.png")
            cand = enhance.candidate(input_png)
            if cand:
                raw_png = cand["png"]
                meta = dict(cand["meta"])
                # Source-preserving repair: restore the artwork's protected
                # content (labels/values/icons -- including content the
                # extraction boxes missed) from the native input.  It ALWAYS
                # runs when enabled, even with no extraction boxes, because the
                # pixel detector finds content the model did not box.  Only a
                # COMPLETE repair is normally acceptable: a partial or failed
                # repair keeps the native fallback shipping and leaves the
                # candidate as a diagnostic preview that cannot be accepted.
                repair_state = "off"
                if repair_enabled():
                    boxes = _content_boxes(blocks, norm, row_off)
                    try:
                        rep = repair.repair_candidate(
                            input_png, raw_png, boxes=boxes,
                            out_dir=raw_png.parent)
                    except Exception as exc:  # noqa: BLE001
                        rep = (None, f"{type(exc).__name__}: {exc}")
                    if isinstance(rep, dict):
                        raw_png = rep["png"]
                        meta["repair"] = rep["meta"]
                        audit = rep["meta"]["audit"]
                        n_det = int(audit.get("detected") or 0)
                        n_rep = int(audit.get("repaired") or 0)
                        n_skip = len(audit.get("skipped") or [])
                        # complete = every detected region accounted for, at
                        # least one region, nothing skipped (detected =
                        # repaired + skipped is enforced by the repair module)
                        complete = n_det > 0 and n_skip == 0 and n_rep == n_det
                        repair_state = ("repaired" if complete
                                        else "partial" if n_rep else "failed")
                        self.store.log(
                            jid, f"hero enhance: source-preserving repair "
                                 f"({n_rep} region(s), {n_skip} skipped, 0 diff "
                                 f"outside, max residual "
                                 f"{audit['max_residual']:.1f})")
                    else:
                        reason = rep[1] if isinstance(rep, tuple) else "unknown"
                        meta["repair"] = {"status": "failed", "reason": reason}
                        repair_state = "failed"
                else:
                    meta["repair"] = {"status": "off"}
                meta["repair_state"] = repair_state
                rows = (rows[0] + row_off, rows[1] + row_off)
                img = enhance.band(raw_png, norm.src_w, rows,
                                   heroart.EXPORT_TARGET_WIDTH)
                out = ws.pipeline / f"{jid}-hero-enhance.webp"
                img.save(out, "WEBP", quality=SCENE_QUALITY, method=6)
                meta["band"] = list(img.size)
                meta["input"] = {"cleaned": cleaned_src.name,
                                 "upload": [norm.src_w, norm.src_h]}
                if input_png != cleaned_src:
                    meta["input"]["padded"] = {
                        "file": input_png.name, "row_offset": row_off,
                        "size": list(Image.open(input_png).size)}
                meta["webp"] = {"name": out.name, "w": img.width, "h": img.height,
                                "bytes": out.stat().st_size}
                when = "cache" if meta.get("cached") else f"{meta.get('seconds')}s"
                self.store.log(jid, f"hero enhance: candidate ready ({meta['model']}, "
                                    f"generated {meta['generated']}, band "
                                    f"{img.width}x{img.height}, "
                                    f"{out.stat().st_size // 1024} KB, {when})")
                if repair_state == "repaired":
                    self.store.update(jid, hero_enhance="pending",
                                      hero_enhance_meta=meta)
                    self.store.log(jid, "hero enhance: NOT shipped -- preview it and "
                                        "accept to swap it in (LaMa/Lanczos stays "
                                        "the fallback)")
                else:
                    self.store.update(jid, hero_enhance="diagnostic",
                                      hero_enhance_meta=meta)
                    why = ("the repair could not verify every content region"
                           if repair_state == "partial" else
                           "the repair failed" if repair_state == "failed" else
                           "the source-preserving repair is disabled")
                    note = (f"hero enhancement is diagnostic only ({why}) -- it "
                            f"cannot be accepted; the cleaned-native fallback ships")
                    self.store.log(jid, note)
                    self.store.update(jid, warnings=(self.store.get(jid).warnings or [])
                                      + [note])
                return
            self.store.log(jid, "hero enhance: no candidate -- keeping the "
                                "LaMa/Lanczos artwork")
        except Exception as exc:  # noqa: BLE001 - optional step, never fail the job
            self.store.log(jid, f"hero enhance: {type(exc).__name__}: {exc} -- "
                                f"keeping the LaMa/Lanczos artwork")
        self.store.update(jid, hero_enhance="skipped")

    @staticmethod
    def _snapshot_files(src_dir: Path, names: tuple[str, ...], dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        for n in names:
            p = src_dir / n
            if p.is_file():
                shutil.copy2(p, dest / n)

    @staticmethod
    def _restore_files(dest_dir: Path, backup: Path, names: tuple[str, ...]) -> None:
        for n in names:
            s, p = backup / n, dest_dir / n
            if s.is_file():
                shutil.copy2(s, p)
            elif p.is_file():
                p.unlink()

    @staticmethod
    def _snapshot_paths(paths: list[Path],
                        dest: Path) -> list[tuple[Path, Path | None]]:
        """Copy each existing file into `dest`; remember which did not exist."""
        dest.mkdir(parents=True, exist_ok=True)
        saved: list[tuple[Path, Path | None]] = []
        for i, p in enumerate(paths):
            if p.is_file():
                b = dest / f"{i}-{p.name}"
                shutil.copy2(p, b)
                saved.append((p, b))
            else:
                saved.append((p, None))
        return saved

    @staticmethod
    def _restore_paths(saved: list[tuple[Path, Path | None]]) -> None:
        for p, b in saved:
            if b is not None:
                shutil.copy2(b, p)
            elif p.is_file():
                p.unlink()

    def accept_enhance(self, jid: str, *, reviewed: bool = False) -> dict:
        """Ship the pending enhancement candidate and rebuild the page.

        Serialized and failure-safe.  The content and every field the rebuild
        may touch are snapshotted first; any failure rolls them back and leaves
        the base LaMa/Lanczos artwork shipping exactly as it was (the job is
        never left "accepted" without a packaged page).  The candidate's labels
        must be explicitly reviewed (`reviewed=True`, from the UI's confirmation)
        and the review is recorded against the candidate's own hash, so an
        acceptance never claims an audit that did not happen.
        """
        with self._enhance_lock:
            job = self.store.get(jid)
            if job is None:
                raise NothingToAccept(f"no job {jid}")
            if job.status != "done":
                raise NothingToAccept(
                    f"the job is not finished (status={job.status!r}) -- wait "
                    f"for its build to finish before accepting")
            if job.hero_enhance == "diagnostic":
                raise NothingToAccept(
                    "the enhancement candidate is diagnostic only (the "
                    "source-preserving repair was incomplete or failed) -- it "
                    "cannot be accepted; the cleaned-native fallback ships")
            if job.hero_enhance != "pending":
                raise NothingToAccept(
                    f"nothing to accept (hero_enhance={job.hero_enhance!r})")
            if not reviewed:
                raise ReviewRequired(
                    "the candidate's labels must be reviewed before it ships")
            ws = workspace.create(jid, JOBS_DIR)
            cand = ws.pipeline / f"{jid}-hero-enhance.webp"
            if not cand.is_file():
                raise NothingToAccept("no enhancement candidate for this job")
            shipped = ws.pipeline / f"{jid}-hero-enhanced.webp"
            cfg_path = ws.pipeline / f"content-{jid}.json"

            # Snapshot everything the acceptance may touch.  Packaging is the
            # last stage, so the shipped page/zip only change after every build
            # stage has passed -- and a packaging failure is rolled back too.
            content_before = cfg_path.read_bytes()
            shipped_before = shipped.read_bytes() if shipped.is_file() else None
            fields = ("status", "stage", "progress", "message", "hero_enhance",
                      "hero_enhance_audit", "hero_fidelity", "hero_label_max",
                      "hero_label_p95", "score", "art_p95", "pct_over_30",
                      "whole_score", "whole_pct", "blank_seam", "structure",
                      "warnings", "artifacts")
            job_before = {k: getattr(job, k) for k in fields}
            backup = Path(tempfile.mkdtemp(prefix="enhance-rollback-"))
            job_files = ("index.html", "dist.zip", f"{jid}.svg",
                         f"{jid}-hero.webp", f"{jid}-hero-enhance.webp",
                         shipped.name)
            self._snapshot_files(job.dir, job_files, backup)
            # The generated workspace pages too: a failed acceptance must not
            # leave a half-rebuilt page (or an Astro source) that no longer
            # matches the restored content.  The dist tree covers the built
            # index.html and anything else the build emitted.
            pages_before = self._snapshot_paths(
                [ws.full_page, ws.site / "src" / "pages" / "index.astro"],
                backup / "pages")
            dist = ws.site / "dist"
            dist_before = backup / "dist"
            if dist.is_dir():
                shutil.copytree(dist, dist_before)
            audit = {"reviewed": True, "method": "visual", "at": time.time(),
                     "candidate_sha256": hashlib.sha256(cand.read_bytes()).hexdigest()}
            try:
                shutil.copy2(cand, shipped)
                img = Image.open(shipped)
                data = json.loads(content_before)
                info = dict(data.get("hero_image") or {})
                meta = job.hero_enhance_meta or {}
                enhance_info = {k: meta.get(k) for k in
                                ("provider", "mode", "model", "size", "generated",
                                 "input_sha256", "image_tokens")}
                if meta.get("repair"):
                    enhance_info["repair"] = meta["repair"]
                info.update({
                    "webp": shipped.name, "w": img.width, "h": img.height,
                    "bytes": shipped.stat().st_size, "rendition": "enhance",
                    "enhance": enhance_info,
                })
                data["hero_image"] = info
                cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

                before = job.hero_fidelity
                self.store.advance(jid, "composing", "Accepting the enhanced artwork")
                self._stage(jid, "compose", [self._node(), GEN_PAGE, jid],
                            ws.pipeline, TIMEOUT_DEFAULT)
                self._stage(jid, "to-astro", [self._node(), TO_ASTRO, jid],
                            ws.pipeline, TIMEOUT_DEFAULT)
                self.store.advance(jid, "building")
                self._npm_build(jid, ws)
                if not ws.dist_page.is_file():
                    raise RuntimeError("rebuild produced no page")
                self.store.advance(jid, "verifying")
                bg = (job.src or {}).get("background")
                self._verify(jid, ws, job.dir / "ref.png",
                             tuple(bg) if bg else None, None)
                after = self.store.get(jid).hero_fidelity

                self.store.advance(jid, "packaging")
                zip_path = self._package(jid, ws)

                # Everything succeeded: NOW the job becomes accepted.
                arts = dict(job_before["artifacts"] or {})
                arts.update({"zip": f"{jid}/dist.zip", "preview": f"{jid}/index.html",
                             "page_bytes": ws.dist_page.stat().st_size,
                             "zip_bytes": zip_path.stat().st_size,
                             "hero": f"{jid}/{info['webp']}"})
                warnings = list(self.store.get(jid).warnings or [])
                if before is not None and after is not None and after > before + 0.5:
                    # The pixel metric measures drift from the reference.  A
                    # generative re-render is sharper but not pixel-identical, so
                    # a higher number is expected and is NOT a quality loss; say
                    # so, and tie it to the recorded review.
                    note = (f"the enhanced rendition's hero score ({after:.2f}) is "
                            f"higher than the base rendition's ({before:.2f}): the "
                            f"metric measures pixel drift from the reference, and a "
                            f"generative re-render is sharper but not "
                            f"pixel-identical -- the rise is drift, not a quality "
                            f"loss. The candidate's labels were reviewed before "
                            f"acceptance (hero_enhance_audit, sha256 "
                            f"{audit['candidate_sha256'][:12]}).")
                    self.store.log(jid, f"hero enhance: {note}")
                    warnings.append(note)
                self.store.update(jid, hero_enhance="accepted",
                                  hero_enhance_audit=audit,
                                  warnings=warnings, artifacts=arts,
                                  status="done", stage="done", progress=1.0,
                                  message="Done")
                self.store.log(jid, f"hero enhance: accepted {info['webp']} -- page rebuilt")
                return self.store.get(jid).to_dict()
            except Exception as exc:
                cfg_path.write_bytes(content_before)
                if shipped_before is None:
                    shipped.unlink(missing_ok=True)
                else:
                    shipped.write_bytes(shipped_before)
                self._restore_files(job.dir, backup, job_files)
                self._restore_paths(pages_before)
                if dist_before.is_dir():
                    shutil.rmtree(dist, ignore_errors=True)
                    shutil.copytree(dist_before, dist)
                self.store.update(jid, **job_before)
                self.store.log(jid, f"hero enhance: acceptance failed "
                                    f"({type(exc).__name__}: {exc}); the base "
                                    f"artwork is unchanged")
                self.store.update(
                    jid,
                    warnings=(self.store.get(jid).warnings or [])
                    + ["hero enhancement acceptance failed; the base artwork is "
                       "unchanged -- retry, or keep it and reject the candidate"],
                    status="done", stage="done", progress=1.0, message="Done")
                raise
            finally:
                shutil.rmtree(backup, ignore_errors=True)

    def _clean_artwork(self, jid: str, ws: workspace.Workspace, job_dir: Path,
                       norm, blocks: list, content: dict) -> tuple[Path | None, str]:
        """Try the optional external cleanup for a raster hero; (cleaned_png, kind).

        The masks are upload-driven and the **component types are detected from
        the page's own structure**: the CTA plates (`button_rects`), the hero
        eyebrow, and the row drawn inside the band whose copy a later DOM
        section replaces (`_benefit_blank_rects`, whose candidates come from
        short lines sharing a row -- the scene's lifted benefit row, or a
        full-layout page's features row).  A "blank minus text" difference does
        not work: on a dark design the config appends every text rect to
        `blank`, so the difference left only the row -- the buttons and the
        eyebrow then kept a 3 px copy mask, and their plate outline, shadow and
        dot stayed in the backdrop as ghosts.  Copy rects (`text` minus the
        component rects) get only a small pad; component rects are grown to the
        element they belong to, capped so illustration content is never
        swallowed.  On success the cleaned upload is the source for the hero
        canvas; on any failure the caller keeps the tracer's fill, and the job
        says which happened.
        """
        python = cleanup.find_python()
        if not python:
            note = ("artwork cleanup: LaMa is not available (set "
                    "STUDIO_CLEANUP_PYTHON or create studio/.cleanup-venv); the "
                    "hero keeps the tracer's fill and its known artifacts")
            self.store.log(jid, note)
            self.store.update(jid, warnings=(self.store.get(jid).warnings or []) + [note])
            return None, "fallback"
        cfg = json.loads((ws.pipeline / "designs" / f"{jid}.json").read_text())
        src = np.asarray(Image.open(job_dir / "upload.bin").convert("RGB"))
        scale = norm.scale
        pad_l, pad_t = norm.pad[0], norm.pad[1]

        def to_source(r: tuple[float, float, float, float]) -> list[float]:
            x0, y0, x1, y1 = r
            return [(x0 - pad_l) / scale, (y0 - pad_t) / scale,
                    (x1 - pad_l) / scale, (y1 - pad_t) / scale]

        sections = generate.group_sections(blocks)
        page = generate.page_blocks(blocks)
        hero = [b for n, g in sections if n == "hero" for b in g]
        band = content.get("hero_band") or [0, STAGE_H]
        grow = generate.TEXT_RECT_GROW

        def grown(b) -> list[int]:
            """The same rect `text_rects` builds for a block (grow on every side)."""
            x0, y0, x1, y1 = b.bbox
            return [max(0, int(round(x0)) - grow), max(0, int(round(y0)) - grow),
                    min(STAGE_W, int(round(x1)) + grow),
                    min(STAGE_H, int(round(y1)) + grow)]

        def in_band(r) -> bool:
            """Only the scene's own slice is cleaned: the mockup's header sits
            above the band (the page renders its own), so its rects -- and the
            header CTA `button_rects` picks up -- are not part of the scene."""
            return r[1] >= band[0] - 2 and r[1] < band[1] and r[3] > band[0]

        # An eyebrow is a short line above the headline; the all-caps test is
        # the repo's definition, but the model case is not stable, so a short
        # hero line entirely above the headline counts too -- its container
        # (the pill) is what must be removed whole.
        headline = next((b for b in hero if b.role == "headline"), None)

        def _eyebrowish(b) -> bool:
            if generate._is_eyebrow(b):
                return True
            return (headline is not None and b is not headline
                    and b.role in ("tagline", "other")
                    and len(b.text) <= 40
                    and b.bbox[3] <= headline.bbox[1] + 2)

        # Components are named explicitly: CTA plates and the hero eyebrow.  The
        # eyebrow needs its *grown* rect so the pill's outline intersects the
        # seed (the decorated block box is tighter and leaves the flood inside
        # the text).  The benefit row's blank already reaches its icons (a 40 px
        # left pad), so it gets a pad-only mask -- growing it would let the
        # floor glow it sits on pull the mask far beyond the row.
        grow_rects = [r for r in (generate.button_rects(page)
                                  + [grown(b) for b in hero if _eyebrowish(b)])
                      if in_band(r)]
        grow_set = {tuple(r) for r in grow_rects}
        # The row drawn inside the band whose copy a later DOM section replaces
        # (the scene's lifted benefit row, or a full-layout page's features row):
        # its icons/plates are not in the text rects, so the whole row is
        # masked.  Detection is the existing one -- short lines sharing a row --
        # never a hard-coded cutoff.
        pad_rects = ([r for r in generate._benefit_blank_rects(
                          sections, content, any_layout=True) if in_band(r)]
                     + [r for r in (cfg.get("text") or [])
                        if in_band(r) and tuple(r) not in grow_set])
        masks = cleanup.copy_masks(src, [to_source(r) for r in pad_rects])
        masks += cleanup.component_masks(src, [to_source(r) for r in grow_rects])
        # Labels are protected content: a mask must never remove one.  The
        # masks are built to avoid illustration content (growth is capped and
        # connected to the element), but this is the hard guarantee -- any
        # overlap is subtracted before the cleaner runs, and the subtraction is
        # recorded because it means a control was only partly removed.
        label_rects = [to_source([b.bbox[0], b.bbox[1], b.bbox[2], b.bbox[3]])
                       for b in blocks if getattr(b, "part", "page") == "artwork"]
        masks, cut = cleanup.subtract_rects(masks, label_rects)
        if cut:
            note = (f"artwork cleanup: {cut} mask overlap(s) with artwork labels "
                    f"were subtracted -- labels are never removed")
            self.store.log(jid, note)
            self.store.update(jid, warnings=(self.store.get(jid).warnings or []) + [note])
        cleaned = ws.pipeline / f"{jid}-cleaned.png"
        status = cleanup.clean(job_dir / "upload.bin", masks, cleaned, python,
                               timeout=TIMEOUT_TRACE)
        if not status:
            note = ("artwork cleanup: the external LaMa worker failed; the hero "
                    "keeps the tracer's fill")
            self.store.log(jid, note)
            self.store.update(jid, warnings=(self.store.get(jid).warnings or []) + [note])
            return None, "fallback"
        # Record the removal in the design config (stage coords): the raster
        # score excludes the pixels the page replaces, and the cleanup's masks
        # are the same kind of fact as the tracer's `text`/`blank` -- without
        # this, the deliberate removal of a plate/row reads as a fidelity
        # regression.  The seam check keeps using text+blank only (the tracer
        # never filled these).
        stage_masks = [[int(round(x0 * scale + pad_l)),
                        int(round(y0 * scale + pad_t)),
                        int(round(x1 * scale + pad_l)),
                        int(round(y1 * scale + pad_t))]
                       for x0, y0, x1, y1 in masks]
        cfg["cleanup_removed"] = stage_masks
        (ws.pipeline / "designs" / f"{jid}.json").write_text(
            json.dumps(cfg, indent=2) + "\n")
        self.store.log(jid, f"hero cleanup: LaMa over {len(masks)} mask(s) on the "
                            f"original upload ({status.get('device', '?')}); "
                            f"pixels outside the masks are the original")
        return cleaned, "lama"

    @staticmethod
    def _set_content_hero(ws: workspace.Workspace, jid: str, **fields) -> None:
        """Persist the final hero decisions into `content-<id>.json`."""
        cfg_path = ws.pipeline / f"content-{jid}.json"
        data = json.loads(cfg_path.read_text())
        data.update(fields)
        cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

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

    @staticmethod
    def _hero_figure(ws: workspace.Workspace, jid: str) -> list[int] | None:
        """The illustration's own region from the generated content, if any."""
        try:
            data = json.loads((ws.pipeline / f"content-{jid}.json").read_text())
        except Exception:  # noqa: BLE001
            return None
        fig = data.get("hero_figure")
        return fig if isinstance(fig, list) and len(fig) == 4 else None

    @staticmethod
    def _asset_inventory(blocks, content: dict) -> list[dict]:
        """Where every recovered artwork element ended up.

        The model's `part: artwork` blocks are an illustration's own content
        (region names, captions, table labels).  None becomes DOM; each must be
        *retained in the artwork asset*, so this records which asset shows it --
        a missing label is then visible in the job record and not only in the
        pixels.  The destinations are honest about what the page displays: a
        `scene` hero ships the whole band (`hero-scene`); a `split` hero ships
        only the figure region (`hero-illustration`), so artwork outside it lives
        in the SVG master alone (`artwork-master`), even when it falls inside the
        band, because the band is no longer shown.  A proper asset pipeline for
        logos and lower-section images is future work; this covers everything the
        extraction actually recovers.
        """
        band = content.get("hero_band") or []
        figure = content.get("hero_figure") if content.get("hero_layout") == "split" else []
        figure = figure or []
        layout = content.get("hero_layout")
        out: list[dict] = []
        for b in blocks:
            if getattr(b, "part", "page") != "artwork":
                continue
            cy = (b.bbox[1] + b.bbox[3]) / 2.0
            in_figure = (len(figure) == 4 and figure[0] <= b.bbox[0]
                         and b.bbox[2] <= figure[2] and figure[1] <= cy <= figure[3])
            in_band = len(band) == 2 and band[0] <= cy <= band[1]
            if layout == "scene":
                dest = "hero-scene" if in_band else "artwork-master"
            elif len(figure) == 4:
                dest = "hero-illustration" if in_figure else "artwork-master"
            elif in_band:
                dest = "hero-artwork"
            else:
                dest = "artwork-master"
            out.append({"text": b.text, "bbox": [round(v) for v in b.bbox],
                        "destination": dest})
        return out

    # A preserved illustration label should differ from the reference only by
    # compression and resampling.  A label the asset *lost* leaves its fill
    # behind, which is far above these -- and a thin, sparse label can erase
    # into a low rectangle *mean* while its p95 is unmistakable, so either
    # number can raise the warning.
    _LABEL_DAMAGE_MAX = 28.0
    _LABEL_DAMAGE_P95_MAX = 64.0

    def _hero_image_path(self, ws: workspace.Workspace, jid: str) -> Path:
        """The raster the page actually ships, when it ships one.

        Normally `<jid>-hero.webp`; after an accepted enhancement the content
        names the accepted file instead, and scoring must follow the shipped
        asset rather than the base name.
        """
        try:
            info = json.loads(
                (ws.pipeline / f"content-{jid}.json").read_text()).get("hero_image") or {}
            name = info.get("webp")
            if name and (ws.pipeline / name).is_file():
                return ws.pipeline / name
        except Exception:  # noqa: BLE001
            pass
        return ws.pipeline / f"{jid}-hero.webp"

    def _verify(self, jid: str, ws: workspace.Workspace, ref_png: Path,
                background: tuple[int, int, int] | None = None,
                blocks: list | None = None) -> None:
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
            rects = [list(b.bbox) for b in (blocks or [])
                     if getattr(b, "part", "page") == "artwork"]
            if not rects:
                # An acceptance re-check has no block objects; the rects were
                # kept on the job for exactly this.
                rects = self.store.get(jid).artwork_rects or []
            result = verify.assess(
                jid, ws.dist_page, ref_png, pipeline=ws.pipeline,
                art_svg=ws.pipeline / f"{jid}.svg",
                layout=cfg.get("layout", "page"),
                background=background,
                hero_image=self._hero_image_path(ws, jid),
                hero_band=self._hero_band(ws, jid),
                hero_figure=self._hero_figure(ws, jid),
                artwork_rects=rects,
                cleanup_rects=cfg.get("cleanup_removed") or None)
        except Exception as exc:  # noqa: BLE001 - never fail a job over scoring
            self.store.log(jid, f"score skipped: {exc}")
            self.store.update(jid, warnings=(self.store.get(jid).warnings or [])
                              + [f"self-check unavailable: {exc}"])
            return
        self.store.update(jid, score=result.get("art_score"),
                          art_p95=result.get("art_p95"),
                          pct_over_30=result.get("art_pct"),
                          whole_score=result.get("whole_score"),
                          whole_pct=result.get("whole_pct"),
                          blank_seam=result.get("blank_seam"),
                          hero_fidelity=result.get("hero_score"),
                          hero_label_max=result.get("hero_label_max"),
                          hero_label_p95=result.get("hero_label_p95"))
        seam = result.get("blank_seam")
        p95 = result.get("art_p95")
        self.store.log(
            jid, f"fidelity: art region mean {result['art_score']:.2f} "
                 + (f"(p95 {p95:.2f} on the artwork), " if p95 is not None else "")
                 + f"(pct>30 {result['art_pct']:.2f}%, "
                   f"from the {result.get('art_source', 'page')}), "
                   f"whole page mean {result['whole_score']:.2f}"
                 + (f", blank seam {seam:.0f}/255" if seam is not None else ""))
        if result.get("hero_source") == "raster":
            labels = ""
            if result.get("hero_label_max") is not None:
                labels = f", worst artwork label {result['hero_label_max']:.0f}"
                if result.get("hero_label_p95") is not None:
                    labels += f" (p95 {result['hero_label_p95']:.0f})"
            self.store.log(jid, f"hero backdrop: shipped raster matches the reference "
                                f"at {result['hero_score']:.2f} mean"
                                + (f" / {result['hero_p95']:.2f} p95"
                                   if result.get("hero_p95") is not None else "")
                                + labels
                                + f" (the traced master is {result['art_score']:.2f})")
        label_max = result.get("hero_label_max")
        label_p95 = result.get("hero_label_p95")
        damaged = ((label_max is not None and label_max > self._LABEL_DAMAGE_MAX)
                   or (label_p95 is not None
                       and label_p95 > self._LABEL_DAMAGE_P95_MAX))
        if damaged:
            warning = (f"hero artwork: an illustration label is off from the "
                       f"reference (worst {label_max:.0f}/255 mean")
            if label_p95 is not None:
                warning += f", {label_p95:.0f}/255 p95"
            warning += ") -- the shipped asset may have lost or smeared it"
            self.store.log(jid, f"hero artwork: {warning}")
            self.store.update(jid, warnings=(self.store.get(jid).warnings or [])
                              + [warning])
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
        # The traced art master lands beside the page too.  `artifacts["svg"]`
        # advertises it and the API serves job-dir files by name, but the tracer
        # writes it into the workspace -- so the advertised path used to 404.
        svg = ws.pipeline / f"{jid}.svg"
        if svg.is_file():
            shutil.copy2(svg, out / svg.name)
        # The hero raster, when the page ships one: the page inlines it, but the
        # picture is deliverable two in its own right (a resolution-fixed image
        # that renders properly on the web), so it also lands beside the page and
        # at the root of the zip as a standalone asset.  The shipped name comes
        # from the content (it may be the accepted enhancement), and any pending
        # candidate is included as provenance.
        hero_names: list[str] = []
        try:
            info = json.loads((ws.pipeline / f"content-{jid}.json").read_text())
            name = (info.get("hero_image") or {}).get("webp")
            if name:
                hero_names.append(name)
        except Exception:  # noqa: BLE001
            pass
        for extra in (f"{jid}-hero.webp", f"{jid}-hero-enhance.webp"):
            if extra not in hero_names:
                hero_names.append(extra)
        hero_files = [p for p in (ws.pipeline / n for n in hero_names) if p.is_file()]
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
    how = ("reconstructed by the external **LaMa** cleanup"
           if info.get("cleanup") == "lama"
           else "removed by the tracer's fill (the optional LaMa cleanup "
                "environment was not present)")
    if info.get("layout") == "scene":
        if info.get("rendition") == "enhance":
            enh = info.get("enhance") or {}
            gen = enh.get("generated") or ["?", "?"]
            rend = (f"**generated by {enh.get('model', 'an image model')}** at "
                    f"{enh.get('size', 'high')} resolution ({gen[0]}×{gen[1]} px), "
                    f"reviewed and accepted")
        elif info.get("rendition") == "lanczos2":
            rend = "Lanczos ×2 for display sharpness"
        else:
            rend = "native scale"
        return (
            "The hero IS the artwork: a **scene export** ({} × {} px WebP, {} KB,\n"
            "inlined as a data URI) shown at its own aspect with the page's own copy\n"
            "over it — nothing is cropped, boxed or dimmed. The mockup's copy was {};\n"
            "the rendition is {}. The upload's own width is {} px, so a wider 2×\n"
            "display is magnified ({:.2f}×) — a higher-resolution artwork upload would\n"
            "sharpen it. `pipeline/{}.svg` is the traced art master."
        ).format(info.get("w"), info.get("h"), kb, how, rend,
                 info.get("source_w", info.get("w")),
                 (info.get("needed", 0) or 0) / max(1, info.get("source_w", 1)),
                 jid)
    if info.get("layout") == "split":
        return (
            "The hero's artwork is an **illustration export** ({} × {} px WebP, {}\n"
            "KB, inlined as a data URI). It carries the mockup's own labels, so the\n"
            "page shows it whole in its own responsive region beside the copy —\n"
            "nothing is cropped or dimmed. `pipeline/{}.svg` is the traced art master,\n"
            "kept as a separate deliverable."
        ).format(info.get("w"), info.get("h"), kb, jid)
    return (
        "The hero backdrop is a **photographic export** ({} × {} px WebP, {} KB,\n"
        "inlined as a data URI).  Flat vector regions cannot represent photographic\n"
        "tone at a web payload, so the page ships the image; the mockup's own copy\n"
        "and interface elements were {}; `pipeline/{}.svg` is the traced art\n"
        "master, kept as a separate deliverable."
    ).format(info.get("w"), info.get("h"), kb, how, jid)
