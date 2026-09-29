# Anthotype Studio — plan

A local web app on top of the pipeline: **upload a design PNG → backend runs the
existing pipeline → download a full Astro project + a self-contained
`index.html`.**

The pipeline stays the engine. The studio is an orchestrator around it and does
**not** modify `pipeline/`, `sites/` or `preview/` — the A/B/C regression suite
and the two invariants (potrace polarity, cumulative masks) are untouched.

## Decisions (locked)

| | |
|---|---|
| Text source | Auto-extract with a **vision LLM** — the local **AntSeed proxy** (`127.0.0.1:8377`), model `glm-5.3-flash` (with fallbacks) |
| Output | **Full Astro project zip** + self-contained `index.html` |
| Scope | **Local tool** on this Mac; no auth, no cloud storage |
| Stack | **FastAPI** backend + **React/Vite** frontend |
| Code location | `studio/` in this repo |

## Layout

```
studio/
  backend/
    app/
      main.py        FastAPI app: upload, status, preview, download
      jobs.py        job store (JSON on disk) + serialized 1-worker pool
      runner.py      pipeline orchestration (the stages below)
      extract.py     vision-LLM call -> copy + boxes + roles
      generate.py    boxes+colors -> content-<id>.json + <id>.page.css + design config
      workspace.py   per-job isolated pipeline copy
      imageutil.py   validate / normalize the upload
      config.py      env, keys, paths
    requirements.txt
    .env.example
  frontend/          React + Vite (upload, progress, preview, download)
  data/jobs/<id>/    uploads, workspace, artifacts, status.json   (gitignored)
```

## The 1024×768 decision (important)

`mkart.py` hardcodes `viewBox="0 0 1024 768"` for the emitted art, and the
shipped pages are a fixed 1024×768 stage scaled to the viewport. So the studio
**normalizes every upload to 1024×768** (aspect-fit onto a background-matched
canvas). This keeps the whole existing toolchain valid, keeps the art trace box
honest, and means OCR boxes come back in stage coordinates with no rescaling.

## Job lifecycle

`received → extracting → generating → tracing → composing → building →
verifying → packaging → done | failed`

Serialized (one heavy build at a time) by a 1-worker executor. Progress is
persisted to `data/jobs/<id>/status.json`; the frontend polls. Every stage is a
subprocess with a timeout and captured logs, so failures are reportable, not
fatal.

## Isolation

Each job gets its own workspace so name-keyed artifacts (`designs/*.json`,
`{v}-full.html`, Astro builds) cannot collide:

1. Copy a minimal pipeline skeleton (`lib/`, `qa/`, `site-template/`,
   `gen-page.mjs`, `to-astro.mjs`, `fonts/`), excluding `designs/`, `sites/`,
   `{a,b,c}.*`.
2. Symlink the repo `.venv`; symlink a scaffolded site's `node_modules`
   (fast path), with a per-job `npm install` fallback.
3. `newdesign.py <id> ref.png` scaffolds the rest.

## Pipeline calls per job (cwd = `<workspace>/pipeline`)

```
newdesign.py <id> ref.png        # scaffold config + content + css + site
mkart.py <id> --out <id>.svg     # trace  (the long pole)
gen-page.mjs <id>                # self-contained page
to-astro.mjs <id>
astro build                      # dist/index.html
```

## Extraction → generation

1. Send the normalized PNG to a vision model with a strict JSON schema prompt →
   blocks `{text, role: headline|subhead|tagline|cta|brand, bbox:[x0,y0,x1,y1]}`.
   The image carries an overlaid, labelled 64 px **coordinate grid**: on a plain
   mockup the model's boxes are biased by tens of pixels and move between
   identical calls, which then misplaces the whole text layer. The grid makes
   them accurate and repeatable. It is sent as WebP — a full-size PNG of the
   grid is ~1 MB and the local proxy silently drops images that large.
2. **Normalize roles by size.** The model is not stable about which line is the
   headline (it labels the largest title `headline` on one call and `brand` on
   the next); a `brand` block that is one of the largest lines is promoted.
3. **Refine locally** from the PNG (all deterministic):
   - snap each box onto the ink actually present, so a few pixels of box error
     do not become a visible font-size error (size is solved from box width);
   - split multi-colour runs (white "Ant" + green "Hosting") using the real
     Inter advance widths to find the boundary;
   - sample the ink colour of each run;
   - measure a button's real rectangle — flood-fill for a solid fill, otherwise
     treat it as an outline button (border ring, transparent interior).
4. Generate:
   - `content-<id>.json` — `stage` = 1024×768, `markup` with each block
     absolutely positioned; escaped text, one `<span>` per colour run.
   - `<id>.page.css` — per-block absolute position from the box, `font-size`
     solved from box width against real Inter metrics, sampled colour, Inter
     stack, same fit-to-viewport script.
   - `designs/<id>.json` — `box` = full frame, `text` = box rects grown by a
     safety margin. Over-covering is safe: it only preserves more glow.

The LLM's text boxes double as the `text`-exclusion rects `mkart.py` needs, so
they never have to be hand-tuned per design.

## Verification

Headless Chrome screenshot → Lanczos downsample to 1024×768 (reuse
`qa/downsample.py`) → mean abs diff vs the reference, plus the no-network check.
The score is reported in the UI.

## Packaging

Zip = full Astro project: `src/pages/index.astro`, `astro.config.mjs`
(`inlineStylesheets:'always'`), `package.json`, `package-lock.json`, a README,
**plus** the traced `<id>.svg`, `designs/<id>.json`, `content-<id>.json`,
`<id>.page.css`. `node_modules`/`dist` excluded. The self-contained
`index.html` is served for instant preview and included in the zip.

## Config

`studio/backend/.env` (gitignored): `VISION_PROVIDER`, `VISION_MODEL`,
`VISION_FALLBACK_MODELS`, `VISION_API_KEY`, `VISION_BASE_URL`. A
provider-agnostic OpenAI-compatible adapter is used, so any vision model can be
dropped in.

On this machine the provider is the local **AntSeed proxy**:

```sh
VISION_PROVIDER=openai
VISION_MODEL=glm-5.3-flash
VISION_FALLBACK_MODELS=deepseek-v4-flash-vision-exp,kimi-k3-fast
VISION_API_KEY=antseed-local
VISION_BASE_URL=http://127.0.0.1:8377/v1
```

## Verification / debugging

`studio/backend/doctor.py`:

- `env` — every dependency (repo venv, node/npm, potrace, Chrome, fonts, the
  pipeline files) plus the vision endpoint and a live probe of each configured
  model; non-zero exit on failure.
- `polarity` — synthetic light/dark checks for the ink, wrapping and extraction
  scope heuristics (no vision model, no pipeline).
- `light` — replays a frozen extraction against the light reference through the
  whole local pipeline and asserts the score and the page-copy scope filter.
- `regress` — runs the repo's own `qa/verify.sh` to prove the shipped pipeline
  is still intact (A/B/C PASS). This is the guard against a studio change
  disturbing the pipeline.
- `run <png>` — a full job in-process with per-stage timings.
- `job <id>` / `jobs` — inspect the on-disk job store, including full logs.

Every job keeps its working tree (`data/jobs/<id>/workspace/`) and logs
(`data/jobs/<id>/status.json`), so failures are reproducible by hand.

## Milestones

1. Backend skeleton + workspace isolation; drive the pipeline end to end on a
   fixed reference (prove isolation before adding the LLM).
2. Extraction + generation (content/CSS/design config from the LLM).
3. Packaging + quality self-check.
4. React UI.
5. Smoke-test the whole flow; confirm `pipeline/` untouched and
   `qa/verify.sh` still 2.71/2.76/2.99.

## Risks

- **Vision box accuracy is the weak link.** Mitigated by the coordinate grid,
  size-based role normalization, and local ink-snapping. Measured against the
  shipped references the studio now scores **a 2.72 / b 3.16 / c 3.34**, versus
  hand-tuned 2.71 / 2.76 / 2.99 — A matches, B and C are close. The residual
  gap is the model's box precision and its collapse of the reference's authored
  detail (multi-layer glow, per-element tracking) that a one-box-per-run
  extraction cannot express.
- **Python 3.14** venv — FastAPI wheels are thin; `studio/.venv` is separate and
  a `python@3.12` fallback is available.
- **`node_modules` symlink under Astro** — verified in milestone 1; fallback is a
  per-job `npm install`.
- **Long builds** — serialized worker, timeouts, live progress.
