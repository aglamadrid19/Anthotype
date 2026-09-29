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
VISION_FALLBACK_MODELS=deepseek-v4-1-flash,gpt-5.6-luna
VISION_API_KEY=antseed-local
VISION_BASE_URL=http://127.0.0.1:8377/v1
```

`glm-5.3-flash` is the recommended model on this marketplace: on the light
reference it extracts every page block and returns accurate boxes (8/8 blocks,
~0.72 mean box IoU). `VISION_FALLBACK_MODELS` is tried in order when the chosen
model or peer fails — P2P routing is not reliable, and one dead peer should not
fail a build. Prefer *different* models for the fallbacks: retrying the same one
usually lands on the same peer.

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
studio/.venv/bin/python studio/backend/doctor.py polarity   # light/dark ink, wrapping, scope (no model)
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
  from its height, and that the page-copy filter keeps the footer and drops a
  small mockup CTA. No vision model, no pipeline, a second or so — run it after
  touching any of the sampling, wrapping or scope heuristics.
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

- **First-pass typography is approximate.** The model gives boxes, not font
  metrics, so the generated CSS positions and sizes each block from its box.
  It is a real, editable starting point — not the hand-tuned fidelity of the
  repo's A/B/C examples. Runs are also not bit-identical: the model's boxes move
  a little between calls, so the score varies by roughly ±0.1.
- **One build at a time.** Builds are serialized (potrace + Astro are heavy);
  extra uploads queue.
- Local tool: no auth, and uploads are trusted. The image type is validated and
  the dimensions are capped regardless.
- The CTA is generated with `href="#"`; set the real destination in the returned
  `content-<id>.json`.
