# Anthotype Studio

A local web app on top of the pipeline: **upload a design PNG → the backend runs
the pipeline → download a real website** (a single self-contained `index.html`
plus the full Astro project).

The output is a **responsive, semantic page**, not a pixel copy of the mockup:
the artwork is the hero backdrop, and the copy is real DOM text in the site's own
type scale. The page is one file with zero network requests.

The backdrop takes one of three shapes, chosen by measuring the hero and the text
the model recovered inside it:

| hero content | what the page ships | why |
|---|---|---|
| flat art, uploaded at the stage's own width, no illustration labels | **traced SVG**, full-bleed | exact, tiny, code-native, re-colourable |
| flat art **with its own labels** (a dashboard, a device, a diagram) | **the whole copy-removed scene**, shown at its own aspect with the copy over its dark side | the scene IS the hero: no `cover` crop, no boxed column, no scrim; the reference's own copy, buttons and benefit row are removed and rebuilt as HTML (LaMa-reconstructed when the optional cleanup environment exists), then Lanczos-upscaled for display with the source resolution still reported honestly |
| photographic | **WebP at the upload's own resolution**, full-bleed | the tracer plateaus around 3.5 mean on a photograph while every knob is flat; the image is a fraction of the size and looks like the original |
| flat art, but a *wider* upload | **WebP at the upload's own resolution** | the trace is bounded by the 1024 px stage and the hero is full-bleed, so on any wider screen the traced art is magnified (1.37× at 1400 px, 1.88× at 1920 px) and soft, while the raster is ~1:1 |

Either of two independent reasons is enough to ship a raster
(`app/heroart.py::wants_raster`): the artwork is continuous-tone, **or** the
upload carries ≥1.2× the stage's linear resolution.  The reason is reported per
job as `hero_reason`.  The illustration `scene` is taken only for **flat**
artwork: a photograph is backdrop texture and stays full-bleed even when the
model found labels in it.

The export is built from your **original upload** (not the 1024×768 working
reference, which throws away real resolution) and from the tracer's
**text-removed** image — but only the copy the page actually **replaces** is
inpainted out; an illustration's own labels are content and are kept.  The export
target is 2× a 1920 px desktop (3840 px, never upscaled past the source), and when
the upload cannot reach it the job records the shortfall (`hero_scale`) instead of
hiding it.  The image is inlined into the page as a data URI and also shipped as a
standalone file.  The traced SVG master is produced either way and always
included.

```
studio/
  backend/          FastAPI: upload, job queue, pipeline orchestration, packaging
  frontend/         React + Vite: upload, live progress, preview, download
  data/jobs/<id>/   uploads, per-job workspace, artifacts   (gitignored)
  run.sh            start backend + frontend
```

## Setup

One-time, from the repo root:

```sh
python3 -m venv studio/.venv
studio/.venv/bin/pip install -r studio/backend/requirements.txt
```

The backend shells out to the **repo's** Python venv (`.venv`, created by
`./bootstrap.sh`) for the tracer, and to `node` for the page build, so run
`./bootstrap.sh` first if you have not. `potrace` must be installed
(`brew install potrace`).

### Optional: the artwork cleanup environment (LaMa)

A raster hero's removed copy (the scene, or a full-bleed photographic hero) is
reconstructed by an **optional external** LaMa environment; without it the hero
keeps the tracer's nearest fill and the job says so. Torch is gigabytes, so it
never enters the studio venv:

```sh
./studio/setup-cleanup.sh          # creates studio/.cleanup-venv + big-lama.pt
# or point at another interpreter with torch + simple-lama-inpainting:
export STUDIO_CLEANUP_PYTHON=/path/to/python
```

The runner cleans the **original upload** with masks that cover the complete
interface elements — the copy rects, the CTA plates and eyebrow grown to the
element they belong to, and the row drawn inside the band whose copy a later
DOM section replaces (its icons included), hard-capped so artwork content is
never swallowed — and composites the result so every pixel outside the masks
is the original.  A scene rendition is then Lanczos-upscaled for display
sharpness and encoded at `SCENE_QUALITY` (90); a full-bleed hero ships the
cleaned upload at its native scale.  Either way the upscale is a *rendering*
enhancement, so the resolution warning keeps reporting the **source** width
(`hero_image.source_w`).

### Optional: the Google enhancement (opt-in, preview before accepting)

With `STUDIO_ART_ENHANCE` set (and `GEMINI_API_KEY` in `studio/backend/.env`),
a job that ships a raster hero additionally asks Google's image model for a
high-resolution rendition and offers it as a **candidate**.  The input is the
**LaMa-cleaned artwork** for both raster layouts (scene and full-bleed); a
missing cleaner **skips** the enhancement, because the tracer's prepared fill
is text-removed but not clean (rectangular patches and component remnants
would be re-rendered by the model).  The raw model output then goes through the
**source-preserving repair**: the artwork's protected content — labels, values
and icons, detected from the native pixels *including content the extraction
boxes missed* — is restored from the native artwork (exact mapping,
context-checked alignment, feathered edges), so a candidate cannot silently
carry a corrupted label.  Only a **complete** repair becomes a normally
acceptable candidate; if any region cannot be verified the candidate is
**diagnostic only** — it cannot be accepted, the cleaned-native artwork keeps
shipping, and the preview is shown for inspection.  The
shipped page keeps the LaMa/Lanczos asset until you press *Accept enhanced
artwork* in the result view (`POST /api/jobs/<id>/enhance/accept`), which swaps
the asset in and rebuilds the page. LaMa/Lanczos remains the fallback, and
results are cached by the cleaned image's hash + model + size, so retries and
acceptance never pay twice.

```sh
# in studio/backend/.env, or the environment:
STUDIO_ART_ENHANCE=google-flash   # gemini-3.1-flash-image at 4K (the default mode)
# STUDIO_ART_ENHANCE=google-pro   # gemini-3-pro-image at 4K
# STUDIO_ART_ENHANCE=auto         # -> google-flash
GEMINI_API_KEY=...
```

The candidate is a **generative re-render**: it is visibly sharper, but it can
alter small labels (a measured Pro run changed `28ms`→`26ms`, `36ms`→`26ms`,
`Staging`→`Slaping` and `End-to-end encrypted`→`Eod-to-end-encrypted`; Flash
preserved all four in that run). Acceptance therefore requires an **explicit
per-candidate review** — the result view's checkbox, or `reviewed: true` in the
API body — and records it against the candidate's own hash
(`hero_enhance_audit`), so a candidate is never shipped, and never *claimed* to
have been audited, without the review happening. Acceptance also requires the
original job to be **finished** (a running job gets 409), and is serialized and
failure-safe: it snapshots the content, the packaged files, the generated
workspace pages and its record, rolls everything back on any failure, and only
marks the job accepted after packaging succeeds. The accepted asset records both provenances
separately: `hero_image.source_w` stays the *upload's* width (the resolution
warning is unchanged) and `hero_image.enhance` records the model, size and
generated dimensions. The pixel metric is a measure of **pixel drift**, not
sharpness: a generative re-render is sharper but not pixel-identical, so its
`hero_fidelity` reads higher, and the acceptance logs that note. The runtime
page is unchanged — the asset is inlined and the page makes zero network
requests.

For tests, `STUDIO_ART_ENHANCE_NETWORK=forbidden` is a hard kill switch (no
provider call whatever else is set); `doctor gate` and `doctor fixtures` set it
for their run, so a configured environment can never make the gate spend money
or depend on the network.

## Configure the vision model

Text extraction uses a vision LLM. Copy the example env and fill it in:

```sh
cp studio/backend/.env.example studio/backend/.env
```

| variable | meaning |
|---|---|
| `VISION_PROVIDER` | `openai` (any OpenAI-compatible endpoint), `anthropic`, or `stub` |
| `VISION_MODEL` | the model id |
| `VISION_API_KEY` | your key |
| `VISION_BASE_URL` | API base, e.g. `https://api.openai.com/v1` |

### On this machine: the local AntSeed proxy

AntSeed VPR exposes an OpenAI-compatible marketplace on `127.0.0.1:8377`. Point
the studio at the vision model that transcribes the mockup best there:

```sh
VISION_PROVIDER=openai
VISION_MODEL=glm-5.3-flash
VISION_FALLBACK_MODELS=deepseek-v4-flash-vision-exp,kimi-k3-fast
VISION_API_KEY=antseed-local
VISION_BASE_URL=http://127.0.0.1:8377/v1
```

`glm-5.3-flash` is the recommended model on this marketplace: on the light
reference it extracts every page block and returns accurate boxes (8/8 blocks,
~0.99 mean box IoU). `VISION_FALLBACK_MODELS` is tried in order when the chosen
model or peer fails — P2P routing is not reliable, and one dead peer should not
fail a build. Prefer *different* models for the fallbacks: retrying the same one
usually lands on the same peer. Verify them with `doctor env`: a fallback that
does not answer is worse than none.

Verify it before running a job:

```sh
studio/.venv/bin/python studio/backend/doctor.py env     # checks the endpoint
curl -s http://127.0.0.1:8377/v1/models | head -c 200    # is the proxy up?
```

`VISION_PROVIDER=stub` needs no key: it produces an art-only page (no text
layer), which is handy for exercising the pipeline offline.

## Run

```sh
./studio/run.sh              # backend :8787 + frontend :5173
./studio/run.sh --backend    # backend only
```

Open **http://127.0.0.1:5173**, drop in a design PNG, and download the project.

## How a job runs

```
upload ─▶ normalize to 1024×768 ─▶ vision LLM recovers the page STRUCTURE
                                   (sections, roles, copy) + boxes
       ─▶ refine locally (snap boxes to the ink's exclusion rects, sample colours,
                          measure a button's real rectangle)
       ─▶ generate content-<id>.json (semantic sections), <id>.page.css (flow
          layout + role-based type scale), designs/<id>.json (trace + exclusions)
       ─▶ qa/mkart.py  (trace the artwork with potrace)
       ─▶ gen-page.mjs (compose the self-contained page; art is the hero backdrop)
       ─▶ to-astro.mjs + astro build
       ─▶ verify (art-region fidelity + a structural read of the built DOM)
       ─▶ package the zip
```

Every upload is normalized to the pipeline's fixed **1024×768** stage so the
tracer (which hardwires that stage) is used unmodified and the vision model's
boxes are already in stage coordinates.

Each job runs in its **own isolated copy** of the pipeline skeleton, so builds
never collide and the shipped A/B/C regression suite is never touched.

The vision model's text boxes double as the `text`-exclusion rectangles the
tracer needs, so the artwork never bakes in a rasterised copy of the page's copy.

### Structure is the hard part

The model returns the page's sections, roles and copy; those become real DOM.
What matters is *grouping and order*, not exact pixels, so two things make it
usable:

- the image sent to the model has a **labelled 64 px coordinate grid** overlaid,
  which keeps the grouping stable between identical calls;
- the returned boxes are then **snapped onto the ink actually in the reference**
  and used to build the tracer's exclusion rects — and their **colours are
  sampled** from that ink, so the page stays in the reference's palette.

When the model is vague about sections, the generator falls back to clustering
the blocks by vertical gap and by **eyebrow labels** ("OUR SERVICES", "WHAT OUR
CLIENTS SAY") — the all-caps kickers a landing page puts above each section — and
names groups by position. A card grid is reconstructed by grouping blocks that
share an x-range, so `title1 title2 …` followed by `body1 body2 …` comes back as
one card per column rather than a title/body soup.

Whatever the source, every block that shares a section name becomes **one**
section, ordered by where it sits on the page — the model tags each block
(`features` on the eyebrow, the heading and every card), and one `<section>` per
block is not a website. Merging only *adjacent* runs is not enough: at a given
`y` the reading order can interleave two names (a testimonial's author line sits
beside the contact band), which fragmented one section into three on a real
upload.

### What the page becomes

`generate.build_markup` emits a header (brand + nav), a hero, one `<section>` per
inferred region (features/testimonials/pricing/contact), and a footer — with
exactly one `<h1>` (in the hero), `<h3>` card titles, and every CTA pointing at a
real in-page anchor. A section can hold more than one *band* (a landing page with
an "OUR SERVICES" grid and a "WHY CHOOSE US" grid names both `features`), and
each band renders as its own eyebrow + title row + cards.

`build_page_css` emits a designed stylesheet, not a reset: a role-based type
scale, a sticky header (brand left, nav centred, phone + button right — three
grid groups, not one flex row), a hero with the artwork under a directional
scrim, a section title row with action links, auto-fit card grids with hover and
a soft shadow (`palette()` returns `card`/`tint`/`shadow` so a card is near-white
on a tinted band, not a grey panel on grey), plain column bands, and alternating
section surfaces. `palette()` samples the reference's colours but **enforces
contrast**, because a design's most prominent headline can be a dark navy that
only worked over a light hero panel — using it as body ink on a dark page makes
the whole page unreadable — and it prefers the CTA's fill as the accent so
buttons and highlights agree.

Rows are emitted where they actually sit: buttons are not appended after the
copy (a fine-print line drawn under them in the reference would become a caption
above them), and buttons sharing a row are ordered left-to-right rather than by
top edge, which swaps a pair drawn two pixels apart.

The traced artwork is the hero's decorative layer (`aria-hidden`). A hero
**without** a clear illustration column uses it as the full-bleed backdrop
(`preserveAspectRatio="xMidYMid slice"`), **cropped to the hero's own band**: the
traced SVG is the whole mockup, so splicing it whole put the next section's cards
and icons behind the hero copy, where they read as clutter.
`generate.hero_band()` computes the mockup's hero slice and `gen-page.mjs`
narrows the *spliced* SVG's `viewBox` to it — the SVG file itself is untouched,
so the art metric still renders the full artwork.  Content flows over it.

The band starts **below the mockup's own header** (the page renders its own
header, so the mockup's nav bar would otherwise show as a second nav inside the
hero) and is **trimmed to the hero box's aspect** (`HERO_BAND_ASPECT`, 1.75),
symmetrically about the hero copy.  Without that trim a hero-only page — which has
no section below it, so the boundary rule never fires — ran the band to the bottom
of the stage (letterbox padding, nav bar and an empty strip) at aspect 1.33, and
`cover` magnified the art 1.37× at 1400 px and 1.88× at 1920 px, cropping a quarter
of it away.

An illustration hero (below) instead gets its own region beside the copy and is
shown whole, so neither `cover` nor the scrim touches it.

### Only the copy the page replaces is removed from the artwork

The extraction distinguishes page copy from text *inside* the artwork (a
dashboard's region names, a device mockup's captions, a diagram's step labels).
Page copy becomes DOM; illustration text does not.  The tracer's exclusion rects
therefore cover **exactly the blocks the page renders as DOM**
(`generate.page_blocks`, minus the hero labels `_drop_artwork_labels` keeps out
of the copy column): those are what would double with a ghost of themselves.
Illustration labels are **not** blanked — they are content of the artwork, and
blanking them stripped a real dashboard of its 33 labels (region names, table
values, the "Secure private tunnel" caption) and left fill smears where they had
been.  `doctor polarity` guards the contract: replaced copy in the rects, artwork
text never.

A hero whose artwork is an illustration — enough labels, clear of the copy
column — is composed as an **integrated scene**: the whole copy-removed band is
the hero, an in-flow image at its own aspect, with the live copy over its dark
side (`generate.build_page_css`, `.hero.hero-scene`, `gen-page.mjs`).  There is
no `object-fit: cover` to crop the sides the labels sit on, no boxed image
column and no copy scrim; below 900 px the scene and the copy stack.  The
reference's own benefit row is lifted out of `features` into the hero (and its
icons blanked out of the artwork, so they cannot duplicate the live row), and a
two-tone headline's accent word is recovered from its share of the ink so only
"AntSeed" is coloured.  The earlier `split` mode (the illustration in its own
capped column) remains available; a photograph is backdrop texture and stays
full-bleed even when the model found labels in it.  `verify.label_fidelity`
reports the worst label's difference so a label the asset lost is visible in the
job record, not only in the pixels.
The scene's removed copy is reconstructed from the **original upload** by the
optional external LaMa cleanup (complete-element masks, original pixels kept
outside them) and falls back to the tracer's fill -- with a logged warning --
when `studio/.cleanup-venv` / `STUDIO_CLEANUP_PYTHON` is absent.  The rendition
is Lanczos-upscaled for display sharpness and encoded lossy at `SCENE_QUALITY`;
`hero_image.source_w` and the job's resolution warning keep reporting the
upload's own width, because an upscale creates no detail.  With the opt-in
Google enhancement enabled the scene asset is instead the **accepted
candidate** (see above); `hero_image.enhance` records the model, size and
generated dimensions, and the source-width provenance is unchanged.

On a light design the tracer's legacy text-exclusion rule is also backwards.  It
keeps the bands *near* the page background so the type's glow survives — but on a
light page the glyph ink and its anti-aliased halo sit just *below* the
background, so they are kept and the tracer bakes a full pale ghost of every word
into the SVG, underneath the DOM text that is supposed to replace it.

`mkart.py` **inpaints the replaced glyph ink out of the reference** before
tracing (gated on `text_bg_lum`, so the three shipped dark designs keep the
legacy path byte-for-byte).  Two details matter:

- the background is measured **locally** (a median filter wider than the glyphs),
  not from the page border — a real landing page has type on a dark footer panel
  and over a photograph as well as on the page ground, and one global value
  punches the footer's own plate out and leaves a bright smear;
- the ink mask is **dilated**, because the anti-aliased fringe is the *outline*
  of every glyph and leaving it draws a pale ghost even when the cores are gone.

A button is not a glyph, though: it is a solid **plate**.  Inpainting the label
leaves the plate, which then ghosts under the DOM button — the design review
called it "an empty ghost button".  The design config therefore carries a second
list, `blank`: rectangles removed *whole* (`generate.button_rects`).  A button is
chrome, never artwork.  This is exclusion policy, not tracing math, and
`doctor regress` confirms A/B/C are untouched.

### What is page copy, and what is artwork

Text inside the illustration (step callouts, a device mockup's own wordmark) must
not become DOM: its box is unreliable and the element lands in the wrong place.
The extractor tags each block `part: page | artwork`, and the generator drops
`artwork` blocks from the markup — while keeping them in the artwork asset, where
they belong.

For a *website* the size backstop is deliberately lax — dropping a real nav link
("Home", "Services") breaks the page, while emitting a stray caption is cosmetic.
Only a genuinely tiny `other` fragment is rejected.

### Why the artwork is posterised, and what fixes it

The tracer cuts bands on **luminance only** and paints each with **one median RGB**
— which is cheap, and exactly right for flat art like the A/B/C posters. On a
*photograph* it is the whole problem: a band spanning blue sky, green foliage and
brown wood gets their average, so colour desaturates and smooth gradients break into
flat blobs. A design review on real uploads called it "the hero photo has dissolved
into white blotches" and "mountains flattened into jagged stepped blobs".

Two settings fix most of it, both pinned in `generate.write_all` (studio-only; the
A/B/C posters are untouched and stay byte-identical):

- **`chroma_cells=2, chroma_gate=16`** — a band whose chroma spread exceeds the gate
  is split along the two opponent chroma axes before painting, so it carries two
  colours instead of their average. The gate keeps flat art on one colour per band.
- **`chroma_smooth=4`** — blur the chroma field *before* thresholding it. This is
  what makes the split affordable: the cell boundaries become the traced contours,
  so raw per-pixel thresholding gives a ragged edge and potrace spends thousands of
  points on it. Unsmoothed it took one upload from 3.8 MB to 16.9 MB; smoothed, 5.5 MB.
- **`turdsize=12`** — the studio shipped A/B/C's value of 2, tuned for flat art that
  wants every speck. On photographs that is pure waste: −28% to −42% payload at an
  unchanged score. Do not raise it to 30 to save more; that eats fine line art.

Measured end to end (traced, rendered, scored), against what the studio shipped:

| design | art mean | p95 | SVG |
|---|---|---|---|
| montiva | 4.21 → **3.44** | 17.7 → **12.7** | 3.8 → 5.5 MB |
| anthotype | 2.40 → **2.04** | 12.7 → **8.7** | 6.2 → 6.0 MB |
| anthosting | 1.72 → **1.65** | 5.0 → **4.7** | 6.0 → 4.5 MB |

The **p95** is the number that matters — that is the blotchiness the eye reads as
posterisation. The mean alone hides it.

Two things that look like bugs and are not:

- **A blanked button rect is a hole in the SVG on purpose.** Reviewing the
  *standalone* SVG shows a white plate where each CTA was; the built page draws the
  real button over it. Judge blanking on the built page, never on the bare SVG.
- **`whole_score` is ~14× `art_score`, and that is expected.** The text rects are
  ~28% of the stage and the reference has crisp type there while the trace has none.
  The unmasked mean is dominated by copy the page deliberately replaces.

### `blank_seam`: the number that covers the masked pixels

`art_score` is measured *outside* the text rects, so on its own it cannot see a fill
that went wrong. `verify.blank_seams` measures the tonal step the trace leaves at the
edge of every rect the tracer had to fill — an absolute 0–255 value, so it stays
meaningful on a nearly flat design. It is reported per job as `blank_seam`, warns
above 12, and each fixture pins it with `seam_max`.

### The honest limit: the type is not reproduced

The generated page is authored in the vendored Inter at a role-based scale; the
reference's own typeface is **not** imitated. This is deliberate — the last
measurable error in the old pixel-matched approach was font substitution, which
no amount of sizing, weight or colour tuning removes. The page is judged on its
structure and on the artwork's fidelity, not on how closely its glyphs match the
mockup's.

Because the page reflows, its art score is taken by rendering the traced SVG by
itself at the reference stage rather than by screenshotting the page — a
responsive document's first viewport is a layout choice, not a tracing result.

## API

| method | path | purpose |
|---|---|---|
| `GET` | `/api/health` | status + vision config |
| `POST` | `/api/jobs` | multipart upload → `{id}` |
| `GET` | `/api/jobs/{id}` | status, stage, progress, art fidelity, structure, blocks, logs |
| `GET` | `/api/jobs/{id}/preview` | the built self-contained page |
| `GET` | `/api/jobs/{id}/ref` | the normalized reference |
| `GET` | `/api/jobs/{id}/download` | the project zip |

## Test it end to end

With the backend running:

```sh
studio/.venv/bin/python studio/backend/smoke.py path/to/design.png
```

Uploads, polls every stage, and reports the final score and artifacts.

## Verify and debug

`doctor.py` is the entry point when something looks wrong. It re-execs itself
under the studio venv, so `python3` works too.

```sh
studio/.venv/bin/python studio/backend/doctor.py gate       # the whole safety net, in order
studio/.venv/bin/python studio/backend/doctor.py env        # every dependency + the vision endpoint
studio/.venv/bin/python studio/backend/doctor.py polarity   # light/dark + structure logic (no model)
studio/.venv/bin/python studio/backend/doctor.py fixtures   # the light/montiva/antho/dashboard fixtures, end to end (no model)
studio/.venv/bin/python studio/backend/doctor.py light      # the light fixture alone
studio/.venv/bin/python studio/backend/doctor.py regress    # run the repo's qa/verify.sh (A/B/C PASS)
studio/.venv/bin/python studio/backend/doctor.py run x.png  # one design end to end, per-stage timings
studio/.venv/bin/python studio/backend/doctor.py critique <job-id | x.png>  # vision review vs the mockup
studio/.venv/bin/python studio/backend/doctor.py jobs       # list recent jobs
studio/.venv/bin/python studio/backend/doctor.py job <id>   # full status + logs for one job
```

- **`gate`** is the one command to run before committing: it runs `env →
  polarity → fixtures → regress` and exits non-zero if any stage fails, so it
  guards both measures at once — the artwork's pixel fidelity (the A/B/C
  posters, via `regress`) and the website's structure (the fixtures). `--quick`
  runs `polarity` alone: no potrace, node, Chrome or model, so it is the cheap
  pre-commit / fast-CI guard. CI (`.github/workflows/gate.yml`) calls the same
  command.

- **`env`** proves the whole toolchain is present: the repo venv, node/npm,
  potrace, Chrome, the vendored fonts, the pipeline files, and that the vision
  endpoint answers. Exit code is non-zero on failure.
- **`polarity`** is the cheap guard for the light/dark assumptions and for the
  generator's structure logic: it draws a synthetic stage with light type on a
  dark ground *and* dark type on a light one, then checks that the ink is sampled
  and the box snapped on both, that a two-tone wordmark still splits into its two
  runs, that the page-copy filter keeps a nav link while dropping a tiny speck
  and an `artwork` block, that a synthetic page is grouped into header / hero /
  features / testimonials / footer, that every block sharing a section name
  merges into one `<section>` even when the reading order interleaves two names,
  that the generated markup is clean (one h1,
  no dead links, flow layout), that the palette follows the ground and stays
  legible on it and that the accent follows the CTA, and that the
  vision retry escalates its image encoding. No vision model, no pipeline.
- **`fixtures`** is the end-to-end guard: each fixture is a *saved extraction*
  replayed against its reference through the whole local pipeline (structure,
  `mkart` tracing, Astro build, art-fidelity scoring), so it is deterministic,
  free, and needs no vision model.  It guards **both measures**: the page's structure and the artwork's pixel
  fidelity — `score_max` bounds the art-region mean with a little headroom (a
  tracer regression such as half-resolution bands or baked-in text raises it), and
  `art_p95_max` bounds the *tail* of the same diff over the pixels the eye reads as
  artwork, because the mean is dominated by whatever is flat and large (a real dark
  design passed at 1.37 while its artwork p95 was 17.3 against 4.7 for a raster of
  the same hero).  Each also pins `hero_kind`, `hero_max` on the shipped raster,
  and `seam_max` on the blanked rects.  The scores are not comparable *between*
  fixtures; each pins its own.
  - `light` — the synthetic light design: a hero-only page; asserts the structure
    and that all 8 page blocks are emitted as DOM while every `artwork` block is
    left to the tracer.
  - `montiva` — a real multi-section landing page: asserts a header, nav, main,
    sections, testimonials, contact and a footer.
  - `antho` — a real photorealistic hero: a hero-only page.
  - `dashboard` — the flat dashboard illustration that drove the scene
    prototype: the integrated `scene` with all 33 of its own labels present in
    the shipped artwork (`hero_layout`, the 3840 px full-bleed budget,
    `min_assets`/`asset_dest`, and the worst-label mean/p95 are pinned).  The
    other three exercise the full-bleed path; this is the one that fails if the
    scene path regresses.

  `--keep` leaves a job directory behind for `doctor job <id>`.  The fixtures are
  the regression suite for the whole studio page builder — extend them when a new
  failure class appears.
- **`regress`** is the safety net for the *pipeline itself*: it runs the repo's
  own `qa/verify.sh`, which scores each built A/B/C poster against its reference
  and asserts the network/stylesheet gates. If a studio change ever disturbed the
  shipped pipeline, this catches it. Expect `2.71 / 2.76 / 2.99 PASS`. It then
  checks that `docs/STATE.json`'s `scores`/`targets` still match the designs and
  the run just measured, so the machine-readable state cannot silently drift.
- **`run`** does a full job in-process (no HTTP, no queue) and prints each stage
  with timings — the fastest way to see where a build is spending time or
  failing.
- **`critique`** is the design review, made repeatable. Give it a job id (review
  the existing build) or a design PNG (build it first), and it screenshots the
  **whole** built page (captured tall, trimmed to the content, so the lower
  sections are reviewed too), sends it and the mockup to the vision model, and
  prints a ranked list of composition/readability defects. Typeface differences
  are explicitly out of scope (the page is authored in its own type), but a
  ghosted hero backdrop is not, and neither is a damaged or missing illustration:
  the review prompt expects the mockup's own copy to be absent from the artwork
  and the illustration's own labels to be present. This is the loop that found the
  hero ghosting and the composition defects; `--out report.json` keeps the raw
  report so two builds can be compared. A single verdict is noisy, so
  `--votes N` reports only the complaints that recur across N runs (with a
  vote count), and `--baseline report.json` tags each defect NEW or carried,
  lists what got fixed, and — with `--fail-on-new` — exits non-zero on a new
  high-severity defect.
- **`job`/`jobs`** read the on-disk job store, so a failed job's full log is
  available after the fact.

Every job also keeps its whole working tree at `studio/data/jobs/<id>/workspace/`
(the isolated pipeline copy, the traced SVG, the generated page) and its logs in
`studio/data/jobs/<id>/status.json`, so a failure can be reproduced by hand.

## Notes and limits

- **The target is a real, editable page, not a pixel match.** The studio's job is
  to rebuild a *photograph of a design* as a website — traced art plus semantic
  DOM — and the pixel score now measures the **artwork region** only. The type is
  authored in the vendored Inter, so a reference set in another typeface is not
  imitated; judge a build by the rendered page, not by the number.
- **The page is a first pass.** Section grouping and copy come from a vision
  model plus deterministic clustering, so a section can be missed or misordered.
  The build *reports* structural problems (`structure_issues`, and the warnings
  in the UI) instead of hiding them behind a score — review them, then edit
  `content-<id>.json` / `<id>.page.css` in the download.
- **The artwork is the hero's.** It is a decorative layer — a full-bleed backdrop,
  or, when the hero carries an illustration with its own labels, that
  illustration shown whole in its own region beside the copy. Lower sections sit
  on solid tones derived from the reference palette. Per-section art crops and a
  general asset pipeline for lower-section logos and icons are future work; the
  job's `assets` record says where every recovered artwork label ended up.
- **Runs are not bit-identical.** The model's boxes move a little between calls,
  so the inferred grouping can vary slightly.
- **A CTA icon is not reproduced.** The button becomes a DOM element; its
  interior is excluded from the trace, so a decorative arrow inside it is
  dropped. The label and the plate colour survive.
- **The CTA links in-page.** No real destination is recoverable from a picture,
  so it points at the most relevant section that exists (never `#`). Set the real
  URL in the returned `content-<id>.json`.
- **One build at a time.** Builds are serialized (potrace + Astro are heavy);
  extra uploads queue.
- Local tool: no auth, and uploads are trusted. The image type is validated and
  the dimensions are capped regardless.
