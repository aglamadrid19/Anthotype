# Anthotype Studio — plan

A local web app on top of the pipeline: **upload a design PNG → backend runs the
existing pipeline → download a full Astro project + a self-contained
`index.html`.**

The pipeline stays the engine. The studio is an orchestrator around it and does
**not** modify `pipeline/`, `sites/` or `preview/` — the A/B/C regression suite
and the two invariants (potrace polarity, cumulative masks) are untouched.

## The output: a website, not a poster

The studio builds a **real, responsive website**: a header, a hero, one
`<section>` per inferred page region, and a footer, in normal document flow, with
a role-based type scale and real links. The traced artwork is the hero's
decorative backdrop.

It deliberately does **not** pixel-match the mockup. The previous approach placed
each text block absolutely from a measured box and tuned it against a whole-page
pixel metric; its residual was ultimately **font substitution** (the reference's
typeface is not the vendored Inter), which is unwinnable. That layer was retired.

The page is judged on two separate things:

| layer | judged on |
|---|---|
| artwork | pixel fidelity over the **art region** (page-copy rects masked) |
| website | **structure** — landmarks, sections, one `h1`, resolving links, flow layout |

## Decisions (locked)

| | |
|---|---|
| Structure source | A **vision LLM** recovers the page's sections, roles and copy |
| Text source | The same call (the copy comes with the structure) |
| Output | **Full Astro project zip** + self-contained `index.html` |
| Page shape | Responsive, semantic, normal flow; art as hero backdrop |
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
      extract.py     vision-LLM call -> sections + roles + copy + boxes
      generate.py    structure+copy -> semantic markup, the stylesheet, the
                     design config (trace box + exclusion rects)
      structure.py   read the built DOM: landmarks, sections, headings, links
      verify.py      art-region fidelity + the structure report
      workspace.py   per-job isolated pipeline copy
      imageutil.py   validate / normalize the upload
      config.py      env, keys, paths
    requirements.txt
    .env.example
  frontend/          React + Vite (upload, progress, live preview, download)
  data/jobs/<id>/    uploads, workspace, artifacts, status.json   (gitignored)
```

## The 1024×768 decision (important)

`mkart.py` hardcodes `viewBox="0 0 1024 768"` for the emitted art. So the studio
**normalizes every upload to 1024×768** (aspect-fit onto a background-matched
canvas). This keeps the tracer valid and means the model's boxes come back in
stage coordinates with no rescaling — and those boxes are what the tracer's
exclusion rects are built from. The *page* is no longer a 1024×768 stage: it is a
normal responsive document, and 1024×768 is only the artwork's coordinate space.

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
   blocks `{text, role, section, part, bbox:[x0,y0,x1,y1]}`. The image carries an
   overlaid, labelled 64 px **coordinate grid** so the grouping is stable between
   identical calls. It is sent as WebP — a full-size PNG of the grid is ~1 MB and
   the local proxy silently drops images that large (the retry escalates the
   encoding: WebP → JPEG → PNG).
2. **Normalize roles by size.** The model is not stable about which line is the
   headline (it labels the largest title `headline` on one call and `brand` on
   the next); a `brand` block that is one of the largest lines is promoted.
3. **Refine locally** from the PNG (all deterministic):
   - snap each box onto the ink actually present — not to place glyphs, but so
     the tracer's exclusion rect covers the type exactly;
   - sample the ink **colours** (per run, so a two-tone wordmark keeps both) and
     a CTA's fill/label — the page is authored in the reference's palette;
   - measure a button's real rectangle — flood-fill for a solid fill, otherwise
     treat it as an outline button (border ring, transparent interior). A flood
     region *shorter* than its label is the surrounding artwork, not a button.
4. **Group into sections.** Prefer the model's `section`; attach unspecified
   blocks to the nearest declared section above them; group every block that
   shares a name into one section, ordered by position on the page (the model
   declares a section per block, so without the grouping a 75-block page would
   ship 75 `<section>`s — and merging only *adjacent* runs fragments a section
   whenever the reading order interleaves two names at the same `y`); when the
   model declares nothing, cluster by vertical gap and by **eyebrow labels**
   ("OUR SERVICES") and name groups by position. Card grids are rebuilt by
   grouping blocks that share an x-range (`_columns`).
5. Generate:
   - `content-<id>.json` — the page: `title`, `description`, `cta_href`,
     `sections`, and `markup` — a header (brand + nav), a hero, one `<section>`
     per group, and a footer, with exactly one `<h1>` and real anchors.
   - `<id>.page.css` — the site's stylesheet: role-based type scale, `clamp()`-ed
     display sizes, an auto-fit card grid, breakpoints. No absolute positioning,
     no fixed stage.
   - `designs/<id>.json` — `layout: "page"`, `box` = full frame, `text` = the
     page blocks' rects grown by a safety margin.

The LLM's boxes double as the `text`-exclusion rects `mkart.py` needs, so the
traced art never bakes in a rasterised copy of the page's own copy.

### Not baking a ghost of the copy

`mkart.py` **inpaints the glyph ink out of the reference** inside those rects
before tracing (gated on `text_bg_lum`, i.e. only for a light background, so the
shipped dark designs are byte-identical).  The background is measured locally
(a median filter wider than the glyphs), because a real page has type on a dark
footer panel and over a photo, not just on the page ground.  This is strictly
better than the earlier band-dropping rule: Montiva **8.78** vs **12.32** on the
old whole-page metric.

## Verification

Two checks, deliberately not blended:

- **Art fidelity**: the traced SVG is rendered at 1024×768 (headless Chrome →
  Lanczos downsample, reusing `qa/downsample.py`) and compared to the reference
  over the **art region** (the page-copy exclusion rects masked out). Rendering
  the SVG alone — rather than screenshotting the reflowing page — is what makes
  this a measure of the *tracer*; the page-wide diff is still reported for
  reference. Existing posters (`layout: "poster"`, a fixed stage) keep scoring
  the page screenshot, because there the page *is* the artwork's frame.
- **Structure**: `app/structure.py` reads the built DOM and reports landmarks,
  sections, heading counts, link resolution and whether the content is in flow,
  plus any problems. Reported in the UI and as job warnings.

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
- `polarity` — synthetic light/dark checks for the ink and extraction scope, plus
  the generator's structure logic: section grouping, header/hero/footer naming,
  a clean generated page, and the palette following the ground (no model).
- `fixtures` — replays the saved extractions (light, montiva, antho) through the
  whole local pipeline and asserts each page's **structure** and art fidelity.
  This is the end-to-end regression suite for the studio page builder.
- `light` — the light fixture alone (kept as a stable entry point).
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
2. Extraction + generation.
3. Packaging + quality self-check.
4. React UI.
5. Smoke-test the whole flow; confirm `pipeline/` untouched and
   `qa/verify.sh` still 2.71/2.76/2.99.

### Done: the website pivot

6. Extraction asks for **structure** (sections + roles + copy), not just boxes.
7. Generation emits a **semantic, responsive page** in normal flow with a
   role-based type scale; the text-metrics layer is retired.
8. `gen-page.mjs` gains a `"page"` layout (art as the hero backdrop) alongside
   the `"poster"` layout A/B/C keep for the tracer's regression.
9. Verification splits into **art-region fidelity** + a **structure report**.
10. `doctor polarity` / `fixtures` re-targeted at structure; A/B/C still PASS.
11. Every block sharing a section name becomes one section, ordered by position,
    however the reading order interleaves (a 75-block page shipped 75
    `<section>`s before this, and adjacent-run merging fragmented interleaved
    sections); a section may hold several bands, each rendered as its own title
    row + cards. A `"page"` layout scores the **traced SVG** rather than the
    reflowing page.
12. `palette()` enforces contrast against the ground and prefers the CTA's fill
    as the accent; `build_page_css` emits a designed stylesheet (sticky header,
    hero scrim, section title rows, card grids, columns, alternating surfaces)
    rather than a reset.

## Risks

- **Structure inference is a heuristic.** A vision model plus clustering can miss
  or misorder a section. Mitigation: deterministic gap/eyebrow clustering as a
  backstop, and a structure self-check that *reports* problems (missing `h1`,
  dead links, no sections) instead of shipping silently.
- **No font is recovered.** The page is authored in Inter; the reference's
  typeface is not imitated. This is by design, not a gap. (Earlier drafts tried to
  *measure* type from the pixels — `measure_lines`, `measure_weight`,
  `sample_line_colors` — to place DOM glyphs on the reference's. That layer is
  **retired**: its residual was font substitution, which no tuning removes. Do not
  resurrect it; the page is authored at a role-based scale instead.)
- **The artwork is one backdrop.** Per-section art would be more faithful and
  much more fragile.
- **`node_modules` symlink under Astro** — verified in milestone 1; fallback is a
  per-job `npm install`.
- **Long builds** — serialized worker, timeouts, live progress.
- **Python 3.14** venv — FastAPI wheels are thin; `studio/.venv` is separate and
  a `python@3.12` fallback is available.
