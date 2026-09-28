# Anthotype

> *an anthotype is a photographic image made from a natural process — plant
> pigments, sunlight, and time, instead of film and chemistry.*

This is a software anthotype: a picture goes in, a real website comes out, and
the picture is not part of the result. The reference image is **input** to
recover geometry, never an embedded asset — by the time the page ships, the
image itself has been entirely consumed.

Turn a flat design PNG into a **real, code-native website** — DOM text, CSS and
SVG geometry, with no raster images in the output.

The output is not a screenshot. Every glyph is selectable text, every shape is a
vector path, and the page scales, re-colours and animates like any other site.

This repo contains the pipeline plus three fully-worked examples (A/B/C) that
demonstrate it end to end and act as the regression suite.

## What it does

The reference is exposed, banded, and traced; the pigment is CSS; the fixer is
Astro. Nothing of the original plate survives into the print.

```
design.png
   │
   ├─ qa/mkart.py        band the artwork by luminance, trace each band to SVG
   │                     paths with potrace, paint darkest-first         -> art.svg
   │
   ├─ content.json       the text layer: headline, tagline, CTA (real DOM)
   │  <v>.page.css       type metrics and layout, tuned against the reference
   │
   ├─ gen-page.mjs       compose  art + content + css  into one self-contained
   │                     page (fonts inlined, no network requests)       -> page.html
   │
   ├─ to-astro.mjs       hand that page to the Astro project
   │
   └─ astro build        -> dist/index.html          ← the shipped artifact
```

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

## Results on the three examples

Mean absolute pixel difference against the reference (1024×768, lower is better):

| | naive hand-authored art | **this pipeline** | payload |
|---|---|---|---|
| A | 12.17 | **2.71** | 6.4 MB / 870 KB gz |
| B | 16.92 | **2.76** | 3.4 MB / 523 KB gz |
| C | 15.09 | **2.99** | 7.7 MB / 1051 KB gz |

`pct>30` (share of pixels off by more than 30/255) is 1.13% / 1.59% / 1.57%.
Scores are stable to ±0.01 across repeated runs; `qa/verify.sh` enforces them.

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
deps are installed by `bootstrap.sh`.

## Adding a new design

**One command scaffolds everything.** The design name is the only thing you
supply — nothing in the pipeline hardcodes a design list.

```sh
cd pipeline
python qa/newdesign.py mydesign path/to/design.png      # config + ref + content + site
```

That writes `designs/mydesign.json` (the only per-design config), copies the
reference to `qa/ref-mydesign.png`, creates `content-mydesign.json` and
`mydesign.page.css` for your copy and layout, and scaffolds a ready-to-build
Astro project at `sites/variant-mydesign/`. Then:

```sh
python qa/mkart.py mydesign --out mydesign.svg          # trace the artwork
node gen-page.mjs mydesign && node to-astro.mjs mydesign
(cd ../sites/variant-mydesign && npm install && npm run build)
./qa/verify.sh mydesign
```

Only two things in `designs/mydesign.json` are genuinely per-design and worth
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
  designs/<n>.json     per-design config: ref, site, content, target, trace box,
                       text rects, tracing params, optional regions
  qa/INDEX.md          what every tool does, and which ones matter
  qa/mkart.py          the art tracer (the heart of this repo)
  qa/newdesign.py      scaffold a whole new design (config + content + site)
  qa/_bootstrap.py     re-exec a QA tool under the venv python if numpy is absent
  qa/verify.sh         score each built dist/ against its reference; PASS/FAIL
  qa/netcheck.py       assert the page fetches nothing over the network
  site-template/       what newdesign.py stamps out for a new design
  fonts/               vendored Inter (inlined at build time)
  {a,b,c}.svg          the traced artwork (committed — regenerating needs potrace)
  gen-page.mjs         compose the self-contained page
  to-astro.mjs         copy that page into the design's Astro project
  build.sh             build every configured design end to end
content.json           the shared text layer for the three shipped examples
content-<n>.json       a new design's own text layer (isolated from the above)
sites/variant-{a,b,c}/ the three worked examples
preview/               one static server for all builds + a generated gallery
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
  assets, so it renders identically from a URL or straight off disk.
- **The artwork is decorative** (`aria-hidden`), because the headline, tagline
  and CTA are real text and carry all the meaning.

## Known gaps

- **The CTA has no destination.** `href="#waitlist"` and no such element exists,
  so the button does nothing. The design specifies only its appearance; set the
  real URL in `content.json`.
- **Band quantisation is the accuracy floor.** The residual is dominated by the
  reference's own colour banding; the tracer's measured overhead above an
  oracle reconstruction is +0.24 / +0.10 / +0.16 mean. Payload and parity trade
  off along one dial (`bands`), roughly 1 KB of gzip per 0.001 mean.

`docs/HOME.md` — where this repo lives: the canonical mirror and the two
working checkouts, and how to publish to GitHub.
`docs/CHECKPOINT.md` — current state and what a future session must not break.
`docs/HANDOFF.md` — the full route, including the measured list of things already
ruled out. Read both before re-litigating font metrics or band edges.
