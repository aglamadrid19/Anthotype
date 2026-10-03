# Anthotype

> *an anthotype is a photographic image made from a natural process — plant
> pigments, sunlight, and time, instead of film and chemistry.*

This is a software anthotype: a picture goes in, a real website comes out. The
reference image is **input** to recover geometry and colour, never a copy of the
page.

Turn a flat design PNG into a **real, code-native website** — a responsive,
semantic page with DOM text and CSS, whose artwork is traced SVG geometry where
the artwork is flat and a fixed-resolution image export where it is photographic.

## The north star: a website, not a poster

The output is **not a pixel copy of the mockup**, and it is not a screenshot.
It is a website:

- **The artwork** is traced into real vector geometry (the landing page's
  decorative backdrop) — or, when the backdrop is *photographic*, exported at a
  fixed resolution to WebP. Flat vector regions cannot represent photographic
  tone at a web payload; see "Two representations for the hero" below.
- **The page** is semantic and responsive — `header`, `nav`, a hero, one
  `section` per page region, a `footer` — in normal document flow, with a
  role-based type scale and real links.
- **The copy** is authored DOM text in the site's own type, read from the
  reference by a vision model. The reference's own typeface is *not*
  reproduced; imitating it glyph-for-glyph is not the art of the landing page.

The reference PNG is consumed as **input** and never embedded as a copy of the
page. Text is never traced: every text block is excluded (or inpainted) before
the tracer runs, so the SVG art master contains artwork only — no glyphs, no
fonts.

### Two representations for the hero

| hero content | what the page ships | why |
|---|---|---|
| flat / vector art | **traced SVG** | exact, tiny, code-native, re-colourable |
| photographic | **WebP, at the upload's own resolution** | the tracer plateaus around 3.5 mean on a photograph while every knob is flat; the image is a fraction of the size and looks like the original |

The choice is made by measurement, not by guessing: `app/heroart.py` samples how
much colour survives area-averaging the hero band to a fixed grid — flat art
scores 29–91, photographs 245–358 — and is deliberately biased toward
rasterising, because a misclassified flat design merely costs bytes while a
misclassified photograph produces the smeared, posterised backdrop this exists
to fix.

Two things the raster gets right, and both are easy to get wrong:

- it is cropped from the **original upload**, not the normalised 1024×768 working
  reference, which discards real resolution (a real upload went 1672×941 →
  1024×576, 61% of its linear detail); and
- it is taken from the tracer's **text-removed** image, not a raw crop — the
  mockup is a picture *of a page*, so a raw crop bakes its nav bar, headline and
  buttons into the backdrop, where they ghost behind the real DOM copy.

The **SVG art master is always produced** and always shipped in the project zip.
For a photographic design the page does not use it, so it is a secondary
artifact and is not tuned.

## What it does

The reference is exposed, banded, and traced; the palette is sampled; the page
is assembled as semantic HTML. Where the artwork is photographic, the hero
backdrop is instead exported at a fixed resolution from the **original upload**
(never the normalised reference, which would bake in the ingest downscale) and
from the tracer's **text-removed** image (never the raw reference, which would
ghost the mockup's own type behind the copy).

```
design.png
   │
   ├─ app/heroart.py     is the hero flat art or a photograph?  (measured)
   │                     photographic -> the tracer prepares a native-resolution
   │                                    reference and inpaints the text out of it;
   │                                    that image is cropped to the hero band,
   │                                    encoded to WebP and inlined as a data URI
   │
   ├─ qa/mkart.py        band the artwork by luminance, trace each band to SVG
   │                     paths with potrace, paint darkest-first         -> art.svg
   │                     (the SVG art master: always produced, always shipped)
   │
   ├─ vision model       recover the page's sections, roles and copy
   │  content-<n>.json   the page markup (semantic sections, real DOM)
   │  <n>.page.css       the stylesheet (flow layout, role-based type scale)
   │
   ├─ gen-page.mjs       compose  art + page  into one self-contained file
   │                     (fonts inlined, no network requests)            -> page.html
   │
   ├─ to-astro.mjs       hand that page to the Astro project
   │
   └─ astro build        -> dist/index.html          ← the shipped artifact
```

## Three measures, not one

There used to be a single number — whole-page mean-abs-pixel-difference against
the reference — and the text layer was tuned against it. That target is
unwinnable by construction: the last measurable error was *font substitution*
(the reference's typeface is not the vendored one), which no amount of sizing,
weight or colour tuning removes. So the metric is split:

| layer | how it is judged |
|---|---|
| **the artwork** | pixel fidelity over the **art region** (the page-copy rects masked out). This is the moat — the tracer's job. |
| **the shipped hero** | for a photographic backdrop, mean-abs-diff of the **exported raster** against the reference band (`hero_fidelity`). The art score above measures the SVG master, which such a page no longer shows. |
| **the website** | structure: landmarks, sections, one `h1`, resolving links, flow layout, and reflow at phone/tablet/desktop widths. |

`studio/backend/app/structure.py` reads the built page and reports the last;
`verify.py` reports the first two. None is collapsed into another.

For a `"page"` layout the art score is taken by **rendering the traced SVG by
itself** at 1024×768 against the reference, not by screenshotting the reflowing
page: a responsive document's first viewport is a layout choice, not a tracing
result, so scoring it would measure the layout instead of the artwork. The
page-wide number is still reported alongside it (`whole_score`) for reference.
The A/B/C posters — fixed stages — keep scoring the page screenshot, which *is*
their artwork's frame.

## The tracer's regression suite (A/B/C)

The three AntHosting designs are the tracer's **regression suite**, not a
website: they are the fixed 1024×768 posters the tracer has always been scored
against. `gen-page.mjs` keeps them on the original fixed `stage` (a design with
no `<!--ART-->` placeholder, or `"layout": "poster"`, builds as a poster).

Mean absolute pixel difference against the reference (1024×768, lower is better):

| | naive hand-authored art | **this pipeline** | payload |
|---|---|---|---|
| A | 12.17 | **2.71** | 6.4 MB / 870 KB gz |
| B | 16.92 | **2.76** | 3.4 MB / 523 KB gz |
| C | 15.09 | **2.99** | 7.7 MB / 1051 KB gz |

Scores are stable to ±0.01 across repeated runs; `qa/verify.sh` enforces them.

## The one fact that matters most (the polarity rule)

**potrace fills the BLACK (bit-0) region of a bitmap.** PIL's `L -> '1'`
conversion also writes the mask as bit 0, so feeding a mask straight in traces
its *complement*: every band becomes an opaque plate, the artwork looks like a
solid slab, and the page still superficially "looks fine". Pass `(~mask) * 255`.
See `pipeline/qa/mkart.py::_potrace`.

The second most important: trace the **cumulative** mask `{lum >= e_i}` rather
than the disjoint band `{e_i <= lum < e_{i+1}}`. Painted darkest-first the two
are mathematically identical, but each cumulative mask is one solid nested region
instead of a scatter of 1px slivers — potrace reproduces it far better, with no
seams, at roughly half the file size.

## Quick start

```sh
./bootstrap.sh                  # potrace check + python venv + npm install
cd pipeline
./build.sh                      # build every configured design end to end
./qa/verify.sh                  # score each build against its reference
                                #   a 2.71 PASS   b 2.76 PASS   c 2.99 PASS
../preview/start-persistent.sh  # gallery at http://127.0.0.1:4173/
```

Requires `brew install potrace` — the only external binary. Node and Python
deps are installed by `bootstrap.sh` (the Python deps are pinned in
`pipeline/requirements.txt`).

Before committing anything, run the gate — one command that covers both measures:

```sh
studio/.venv/bin/python studio/backend/doctor.py gate      # env -> polarity -> fixtures -> regress
studio/.venv/bin/python studio/backend/doctor.py gate --quick   # polarity alone: no pipeline, no model
```

CI (`.github/workflows/gate.yml`) runs `gate --quick` on every push and PR, and
the full `gate` on `main` and nightly.

## Studio (upload → site)

There is a local web app on top of the pipeline that turns this into a product:

```sh
python3 -m venv studio/.venv
studio/.venv/bin/pip install -r studio/backend/requirements.txt
cp studio/backend/.env.example studio/backend/.env   # set your vision-model key
./studio/run.sh                                      # http://127.0.0.1:5173
```

Upload a design PNG, watch the pipeline run stage by stage, then download the
code-native site (a single self-contained `index.html` plus the full Astro
project). A vision model recovers the page's **structure and copy** — its
sections, reading order and text — which is emitted as a responsive, semantic
page; each job runs in its own isolated copy of the pipeline, so the A/B/C
regression suite is never touched. See `studio/README.md`.

## Adding a new design

**One command scaffolds everything.** The design name is the only thing you
supply — nothing in the pipeline hardcodes a design list.

```sh
cd pipeline
python qa/newdesign.py mydesign path/to/design.png      # config + ref + content + site
```

That writes `designs/mydesign.json` (the only per-design config), copies the
reference to `qa/ref-mydesign.png`, creates `content-mydesign.json` and
`mydesign.page.css` for your page, and scaffolds a ready-to-build Astro project
at `sites/variant-mydesign/`. Then:

```sh
python qa/mkart.py mydesign --out mydesign.svg          # trace the artwork
node gen-page.mjs mydesign && node to-astro.mjs mydesign
(cd ../sites/variant-mydesign && npm install && npm run build)
./qa/verify.sh mydesign
```

A design's `layout` chooses the page shape: **`"page"`** (the default for
scaffolded designs) emits a responsive website with the traced art as the hero
backdrop; **`"poster"`** keeps the historical fixed 1024×768 stage — which is
what A/B/C use, because they are the tracer's regression suite rather than a
website.

Two things in `designs/mydesign.json` are genuinely per-design and worth
checking by hand:

- **`box`** — the artwork region. Everything inside it is repainted by traced
  bands, so it must cover the art and *not* the DOM text.
- **`text`** — rectangles the artwork must not bake in. Leaving these empty
  bakes a rasterised copy of your headline into the art, which then ghosts any
  later copy edit. `qa/textrects.py` derives them automatically from a DOM-only
  render once your page CSS exists.

`qa/tune.py` runs coordinate descent over any CSS property through the real
pipeline; `designs/<n>.json` also accepts `regions` (per-region diagnostics for
`qa/compare.py`) and `target` (the pass threshold `qa/verify.sh` enforces).

Because every tool enumerates `designs/*.json`, a new design also appears
automatically in `build.sh`, `bootstrap.sh`, the preview gallery at
`http://127.0.0.1:4173/`, and `verify.sh` — with no edits to any of them.

## Layout

```
pipeline/
  lib/designs.mjs      THE design registry: enumerates designs/*.json for every
                       other tool (list / site / show). Single source of truth.
  designs/<n>.json     per-design config: ref, site, content, layout, target,
                       trace box, text rects, tracing params, optional regions
  qa/INDEX.md          what every tool does, and which ones matter
  qa/mkart.py          the art tracer (the heart of this repo); `--prepared-out`
                       also dumps its text-removed image for a photographic hero
  qa/newdesign.py      scaffold a whole new design (config + content + site)
  qa/_bootstrap.py     re-exec a QA tool under the venv python if numpy is absent
  qa/verify.sh         score each built dist/ against its reference; PASS/FAIL
  qa/netcheck.py       assert the page fetches nothing over the network
  site-template/       what newdesign.py stamps out for a new design
  fonts/               vendored Inter (inlined at build time)
  requirements.txt     pinned Python deps for the venv bootstrap.sh creates
  {a,b,c}.svg          the traced artwork (committed — regenerating needs potrace)
  gen-page.mjs         compose the self-contained page (page or poster layout)
  to-astro.mjs         copy that page into the design's Astro project
  build.sh             build every configured design end to end
.github/workflows/     gate.yml: the safety net as CI (polarity per PR, full gate on main)
content.json           the shared text layer for the three shipped examples
content-<n>.json       a new design's own page definition (isolated from the above)
sites/variant-{a,b,c}/ the three worked examples (the tracer's regression suite)
preview/               one static server for all builds + a generated gallery
studio/                the upload -> site web app (FastAPI + React)
  backend/app/         extract (structure), generate (semantic page), runner,
                       heroart (flat-vs-photograph + the raster hero export),
                       verify (art fidelity) + structure (page structure)
docs/HANDOFF.md        full engineering history: what was tried, what worked,
                       what is exhausted, and the landmines
```

## Things this repo deliberately enforces

- **Zero network requests.** Inter is inlined as `@font-face`; `qa/netcheck.py`
  proves it by rendering through Chrome's net log, and `qa/verify.sh` fails the
  build if a page-originated request appears. (It once silently depended on the
  Google Fonts CDN — offline, scores went 2.71 → 4.22.)
- **`build.inlineStylesheets: 'always'`** in every `astro.config.mjs`. The inlined
  font CSS is large enough that Astro's default 4 kB threshold externalises the
  stylesheet, and an external `/_astro/*.css` cannot load over `file://` — the
  protocol the QA scripts screenshot with.
- **A single-file deliverable.** Each page is one `index.html` with no external
  assets — a photographic hero is inlined as a data URI, so it renders
  identically from a URL or straight off disk. (That image is also shipped as a
  standalone file in the zip, for reuse elsewhere.)
- **The artwork is decorative** (`aria-hidden`), because the copy and the CTA are
  real text and carry all the meaning.
- **Only the vendored font weights are asked for.** The generated stylesheet uses
  400/500/600 because those are the weights in `pipeline/fonts/`; a page that
  requested 700 would silently get a synthetic bold.
- **One gate, and CI runs it.** `doctor gate` runs `env → polarity → fixtures →
  regress` and fails if any stage does, so both measures are guarded by one
  command; `.github/workflows/gate.yml` runs it. The Python deps are pinned
  (`pipeline/requirements.txt`, `studio/backend/requirements.txt`) because the
  scores are a numeric gate — an unpinned `pip install` could move them.

## Known gaps

- **The CTA links in-page.** The reference specifies only the button's
  appearance, so no real destination is recoverable from it. The studio points it
  at the most relevant section that exists on the page (never `#`); the A/B/C
  posters still carry `href="#waitlist"`. Set the real URL in the generated
  `content-*.json` (or `content.json`) once it is known.
- **The artwork is one backdrop, not per-section art.** The traced SVG is the
  hero's full-bleed decorative layer; lower sections sit on solid background
  tones derived from the reference. Cropping the trace per section would be more
  faithful to the mockup and considerably more fragile.
- **Structure inference is a heuristic.** The vision model returns sections and
  reading order, and the generator falls back to clustering the blocks by
  vertical gap and eyebrow labels when the model is vague. A page it gets wrong
  is reported (`structure_issues`, `doctor fixtures`) rather than shipped
  silently — but it is not a guarantee.
- **Band quantisation is the tracer's accuracy floor.** The residual is dominated
  by the reference's own colour banding; the tracer's measured overhead above an
  oracle reconstruction is +0.24 / +0.10 / +0.16 mean. Payload and parity trade
  off along one dial (`bands`), roughly 1 KB of gzip per 0.001 mean.

`docs/HOME.md` — where this repo lives: the canonical mirror and the two
working checkouts, and how to publish to GitHub.
`docs/CHECKPOINT.md` — current state and what a future session must not break.
`docs/HANDOFF.md` — the full route, including the measured list of things already
ruled out. Read both before re-litigating font metrics or band edges.
