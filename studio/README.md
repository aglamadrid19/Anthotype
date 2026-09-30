# Anthotype Studio

A local web app on top of the pipeline: **upload a design PNG → the backend runs
the pipeline → download a code-native website** (a single self-contained
`index.html` plus the full Astro project).

The output has no raster images: the artwork is traced SVG geometry, the text is
real DOM, and the page is one file with zero network requests.

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
upload ─▶ normalize to 1024×768 ─▶ vision LLM extracts text + boxes
       ─▶ refine locally (snap to ink, colour runs, button measure)
       ─▶ generate content-<id>.json, <id>.page.css, designs/<id>.json
       ─▶ qa/mkart.py  (trace the artwork with potrace)
       ─▶ gen-page.mjs (compose the self-contained page)
       ─▶ to-astro.mjs + astro build
       ─▶ verify (screenshot → Lanczos downsample → mean abs diff vs reference)
       ─▶ package the zip
```

Every upload is normalized to the pipeline's fixed **1024×768** stage, so the
existing toolchain (which hardwires that stage) is used unmodified and the
vision model's boxes are already in stage coordinates.

Each job runs in its **own isolated copy** of the pipeline skeleton, so builds
never collide and the shipped A/B/C regression suite is never touched.

The vision model's text boxes double as the `text`-exclusion rectangles the
tracer needs, so the artwork never bakes in a rasterised copy of the words.

### Boxes are the hard part

The model's boxes are what everything else is built from, and they are only
approximate. Two things make them usable:

- the image sent to the model has a **labelled 64 px coordinate grid** overlaid
  (a plain mockup gives boxes biased by tens of pixels that move between
  identical calls);
- each box is then **snapped onto the ink actually in the reference**, and its
  colours sampled from that ink — including splitting a two-tone run such as a
  white "Ant" plus green "Hosting".

Measured against the shipped references the studio scores **a 2.72 / b 3.16 /
c 3.34** (hand-tuned A/B/C are 2.71 / 2.76 / 2.99). A matches; B and C are a
real, editable starting point rather than the hand-authored fidelity. Those
numbers move by a few tenths between runs — the vision model's boxes shift
slightly on identical calls — so treat them as a band, not a constant.

The two uploads that came back worst (a multi-section landing page at **12.04**
and a photorealistic hero at **6.39**) are now committed fixtures and replay
through the whole pipeline without a model: **montiva 8.78**, **antho 6.41**,
**light 6.42** (`doctor fixtures`). What closed that gap was measuring the line
count, weight and per-line colour from the reference instead of inferring them
from a box, and inpainting the glyph ink out of the artwork so the DOM type is
not sitting on a ghost of itself. The remaining residue on all three is the
reference's own typeface, which is not Inter.

### Light designs

A/B/C are all light-type-on-dark, and the first uploads that were not exposed how
much of the layer had quietly assumed that:

- ink is sampled and boxes snapped by **distance from the background**, and the
  sign of the ink (darker or lighter than the background) is measured per block
  rather than assumed. `snap_to_ink`'s old `mean > bg + 40` is unsatisfiable on a
  near-white page, so it was a no-op on every light design.
- a wrapped block is sized from its **box height and line count** (the model
  reports a wrapped block as one box), not from the one-line width of the whole
  string — the latter collapsed eight blocks on the light upload to the 8 px
  floor.
- the tracer is told where the page background sits (`text_bg_lum` in the design
  config) so it drops the *ink* bands inside a text rect. The default
  `text_lum_max` rule is one-sided and, on a light design, removes the whole
  rect — a hard hole. The new param is only set for a light background; a dark
  design keeps the rule it was scored with.
- `color-scheme` follows the background polarity.

`text_bg_lum` is additive: `mkart.py` behaves exactly as before when it is
absent. `qa/mkart.py a` re-traces to a byte-identical `pipeline/a.svg`.

### Why the type lands where it does (and three things measured, not guessed)

A vision model returns a box, not a font.  Three properties the box cannot tell
you are recovered from the reference pixels instead:

- **Line count.** The model reports a wrapped block as ONE box, and neither the
  box's width nor its height says how many lines it holds — the Montiva hero box
  is 273×43, whose text fits on one 14 px line, yet the reference sets it on two
  ~25 px lines.  `generate.measure_lines` projects the ink rows inside the
  snapped box and counts the bands, which also gives the reference's own leading
  (`pitch`) to within a pixel.  This was the single largest layout bug: the DOM
  headline rendered at one-third its true size.
- **Weight.** `sample_runs` gives colour, but a bold display headline set at 400
  is a large error and no sizing fixes it.  `measure_weight` compares the ink
  *coverage* (share of the ink box that is ink) of the reference against the same
  string rasterised in each vendored Inter weight, and picks the closest.  On the
  Montiva hero: reference 0.44, Inter 400 0.21, 600 0.28 → 600.
- **Per-line colour.** A wrapped display line is often painted per line — the
  Montiva hero is navy on line 1, blue on line 2.  Sampling the whole block
  collapses that to one colour, so each measured line gets its own hard-stop
  gradient (background-clip: text), applied only to large type where the
  per-line medians differ by more than anti-aliasing.

### The artwork must not contain a ghost of the words

On a light design the tracer's legacy text-exclusion rule is backwards.  It keeps
the bands *near* the page background so the type's glow survives — but on a light
page the glyph ink and its anti-aliased halo sit just *below* the background, so
they are kept and the tracer bakes a full pale ghost of every word into the SVG,
underneath the DOM text that is supposed to replace it.

`mkart.py` now **inpaints the glyph ink out of the reference** before tracing
(gated on `text_bg_lum`, so the three shipped dark designs keep the legacy path
byte-for-byte).  Two details matter:

- the background is measured **locally** (a median filter wider than the glyphs),
  not from the page border — a real landing page has type on a dark footer panel
  and over a photograph as well as on the page ground, and one global value
  punches the footer's own plate out and leaves a bright smear;
- the ink mask is **dilated**, because the anti-aliased fringe is the *outline*
  of every glyph and leaving it draws a pale ghost even when the cores are gone.

Measured on the Montiva fixture, same layout: inpaint **8.78** vs the old
keep-the-bands rule **12.32**.

### The honest limit: font substitution

The shipped Inter is the only face available, and a real mockup often is not set
in Inter.  The `antho` fixture's "antseed" logo and the Montiva wordmarks are
other typefaces, and the residue on those glyphs is font substitution, not
layout — no amount of sizing, colour or wrapping tuning removes it.  That is
what sets the fixture targets (light 6.6, montiva 9.2, antho 7.0) rather than
the hand-tuned A/B/C band.

### What is page copy, and what is artwork

Text inside the illustration (step callouts, a device mockup's own wordmark) must
not become DOM: the box is unreliable and the exclusion rect punches a hole in
the busiest art. The extractor tags each block `part: page | artwork`, and
`generate.page_blocks` drops `artwork` blocks plus any `other` block too small to
be page copy. The invariant holds either way: **the exclusion rects are exactly
the blocks that are emitted as DOM.**

The trade-off is fidelity for very small page text: the shipped Inter is the only
face available, so a design whose typeface is not Inter (the first light upload's
display face) leaves a per-pixel residue on its text that no amount of sizing or
weight tuning removes. Expect that — it is a font-substitution problem, not a
layout one.

## API

| method | path | purpose |
|---|---|---|
| `GET` | `/api/health` | status + vision config |
| `POST` | `/api/jobs` | multipart upload → `{id}` |
| `GET` | `/api/jobs/{id}` | status, stage, progress, score, blocks, logs |
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
studio/.venv/bin/python studio/backend/doctor.py env        # every dependency + the vision endpoint
studio/.venv/bin/python studio/backend/doctor.py polarity   # light/dark ink, wrapping, scope, weight (no model)
studio/.venv/bin/python studio/backend/doctor.py fixtures   # the light + montiva + antho fixtures, end to end (no model)
studio/.venv/bin/python studio/backend/doctor.py light      # the light fixture alone
studio/.venv/bin/python studio/backend/doctor.py regress    # run the repo's qa/verify.sh (A/B/C PASS)
studio/.venv/bin/python studio/backend/doctor.py run x.png  # one design end to end, per-stage timings
studio/.venv/bin/python studio/backend/doctor.py jobs       # list recent jobs
studio/.venv/bin/python studio/backend/doctor.py job <id>   # full status + logs for one job
```

- **`env`** proves the whole toolchain is present: the repo venv, node/npm,
  potrace, Chrome, the vendored fonts, the pipeline files, and that the vision
  endpoint answers. Exit code is non-zero on failure.
- **`polarity`** is the cheap guard for the light/dark assumptions: it draws a
  synthetic stage with light type on a dark ground *and* dark type on a light
  one, then checks that the ink is sampled and the box snapped on both, that a
  two-tone wordmark still splits into its two runs, that a wrapped block is sized
  from its height, that the reference-driven **line count**, **per-line colour**
  and **weight** measurements agree with what was drawn, that the page-copy
  filter keeps a wide footer and a small wordmark while dropping a narrow caption
  and an `artwork` block, and that the vision retry escalates its image encoding.
  No vision model, no pipeline, a second or so — run it after touching any of the
  sampling, wrapping, weight or scope heuristics.
- **`fixtures`** is the end-to-end guard that `polarity` cannot be.  Each
  fixture is a *saved extraction* replayed against its reference through the
  whole local pipeline (layout, `mkart` tracing, Astro build, scoring), so it is
  deterministic, free, and needs no vision model:
  - `light` — the synthetic light design (`fixtures/light-ref.png`): asserts the
    score stays ≤ 6.6 and that all 8 page blocks are emitted as DOM while every
    `artwork` block is left to the tracer.
  - `montiva` — a real multi-section landing page that scored **12.04** before
    the reference-driven line measurement and the ink inpainting landed (its
    model box was 273×43 and the layout used to guess one 14 px line where the
    reference sets two ~25 px ones).
  - `antho` — a real photorealistic hero that scored **6.39**.

  `--keep` leaves a job directory behind for `doctor job <id>`.  The fixtures are
  the regression suite for the whole studio text layer — extend them when a new
  failure class appears.
- **`regress`** is the safety net for the *pipeline itself*: it runs the repo's
  own `qa/verify.sh`, which scores each built A/B/C site against its reference
  and asserts the network/stylesheet gates. If a studio change ever disturbed
  the shipped pipeline, this catches it. Expect `2.71 / 2.76 / 2.99 PASS`.
- **`run`** does a full job in-process (no HTTP, no queue) and prints each stage
  with timings — the fastest way to see where a build is spending time or
  failing.
- **`job`/`jobs`** read the on-disk job store, so a failed job's full log is
  available after the fact.

Every job also keeps its whole working tree at `studio/data/jobs/<id>/workspace/`
(the isolated pipeline copy, the traced SVG, the generated page) and its logs in
`studio/data/jobs/<id>/status.json`, so a failure can be reproduced by hand.

## Notes and limits

- **The target is a real, editable page, not a pixel match.** The studio's job is
  to rebuild a *photograph of a design* as code — traced art plus live DOM — and
  the tracer has a band-paint floor of its own. On the shipped A/B/C designs that
  floor is 2.16 / 2.16 / 2.12 and the hand-tuned sites land at 2.71 / 2.76 /
  2.99. A first upload whose reference is a photorealistic render (soft shadows,
  gradients, a non-Inter display face) will sit higher; the light fixture scores
  ~6.4 and that is the font substitution, not the layout. Judge a build by the
  rendered page, and treat the number as a band.
- **First-pass typography is approximate.** The model gives boxes, not font
  metrics, so the generated CSS positions and sizes each block from its box.
  Line count, weight and per-line colour *are* measured from the reference (see
  above), so the boxes are no longer the only signal — but the reference's
  typeface usually is not Inter, and the residual on those glyphs is
  substitution, not layout. Runs are also not bit-identical: the model's boxes
  move a little between calls, so the score varies by roughly ±0.1.
- **A CTA icon is not reproduced.** The button becomes a DOM element sized to the
  reference's plate, and its interior is excluded from the trace, so a decorative
  arrow inside the button is dropped. The label and the plate colour survive.
- **One build at a time.** Builds are serialized (potrace + Astro are heavy);
  extra uploads queue.
- Local tool: no auth, and uploads are trusted. The image type is validated and
  the dimensions are capped regardless.
- The CTA is generated with `href="#"`; set the real destination in the returned
  `content-<id>.json`.
