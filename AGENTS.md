# AGENTS.md — start here

Agent entry point for **Anthotype**: a pipeline that turns a flat design PNG into
a **real, code-native website** — a responsive, semantic page in normal document
flow, with the artwork as a decorative backdrop (traced SVG geometry for flat
art, a fixed-resolution image export for a photograph) and the copy authored as
DOM text. The reference PNG is pipeline **input**, never a copy of the page.

This file is the map. It is deliberately concise and points at depth. Read it
first, then follow the pointers — do not try to hold `docs/HANDOFF.md` (762
lines) in your head.

> **New here?** Do the golden path below before touching anything. Then read the
> hard rules. Then skim "already ruled out" so you don't spend hours re-testing
> things that were measured and settled.

---

## The north star (read this before proposing changes)

The output is **a website, not a pixel copy of the mockup**. Three things follow:

- The **artwork** is judged on pixels — mean-abs-pixel-difference over the **art
  region** (page-copy rects masked out). This is the tracer's job and the moat.
- The **shipped hero** is judged separately when the backdrop is photographic:
  the page ships a fixed-resolution image, not the traced SVG, so its own mean
  against the reference band is what covers the thing a visitor actually sees.
- The **website** is judged on **structure** — landmarks, sections, one `h1`,
  resolving links, flow layout, reflow.

Pixel parity with the reference's **typeface** is deliberately **not** a target.
Its residual is font substitution, which no amount of sizing, weight or colour
tuning removes. The old text-metrics machinery is retired — do not resurrect it.
See `README.md` §"Three measures, not one".

---

## Golden path (setup → build → verify)

```sh
./bootstrap.sh                          # potrace check + python venv + npm install
cd pipeline
./build.sh                              # build every configured design end to end
./qa/verify.sh                          # score each build vs its reference
                                        #   expect:  a 2.71  b 2.76  c 2.99  (PASS)
../preview/start-persistent.sh 4173     # gallery at http://127.0.0.1:4173/
```

Only external binary: **potrace** (`brew install potrace`). Chrome + `sips` are
used for screenshots. `bootstrap.sh` installs the Python deps (pinned in
`pipeline/requirements.txt`) into `.venv` and each site's `node_modules`.

**After ANY change, run the gate:**
`studio/.venv/bin/python studio/backend/doctor.py gate` runs `env → polarity →
fixtures → regress` and fails if any stage does (`regress` *is* `./qa/verify.sh`,
so A/B/C PASS is covered). `--quick` runs `polarity` alone — no potrace, node,
Chrome or model. CI (`.github/workflows/gate.yml`) runs the same command, and
`bootstrap.sh` points git at `.githooks/`, whose pre-commit hook runs
`gate --quick`, so the cheap guard cannot be forgotten. If you touched the
tracing or a page shell, also confirm the traced SVGs regenerate
byte-identically (`python qa/mkart.py a` is deterministic).

---

## Hard rules — DO NOT BREAK

These five are load-bearing. Each cost real time to discover. Full list of
landmines in `docs/HANDOFF.md` §5 (15 of them).

1. **potrace polarity.** potrace fills the **BLACK (bit-0)** region of a bitmap,
   and PIL's `L -> '1'` conversion also writes the mask as bit 0 — so feeding a
   mask straight in traces its **complement**: every band becomes an opaque
   plate, the art looks like a solid slab, and the page still *superficially
   looks fine*. Pass `(~mask) * 255`. See `pipeline/qa/mkart.py::_potrace`.

2. **Cumulative masks, painted darkest-first.** Trace `{lum >= e_i}`, not the
   disjoint band `{e_i <= lum < e_{i+1}}`. Mathematically identical once painted,
   but potrace gets one solid nested region instead of 1px slivers: ~0.8 better
   mean and ~half the file size. Bands must go **darkest (lowest `e_i`) first**.

3. **`build.inlineStylesheets: 'always'`** in every `astro.config.mjs`. The
   inlined font CSS pushes the stylesheet past Astro's 4 kB auto-inline
   threshold; an external `/_astro/*.css` **cannot load over `file://`** — the
   protocol the QA scripts screenshot with. Symptom if it regresses: scores jump
   to ~158/170/227 and the page renders unstyled.

4. **Zero network requests.** Inter is vendored (`pipeline/fonts/`) and inlined;
   `qa/netcheck.py` proves it via Chrome's net log and `qa/verify.sh` fails on
   any page-originated request or remote asset. (It once silently depended on the
   Google Fonts CDN — offline, scores went 2.71 → 4.22.)

5. **A photographic hero's raster must come from the tracer's *prepared* image,
   at the upload's own resolution.** Two failure modes, both invisible to
   `art_score` (which masks text rects and measures the SVG):
   - **Cropping the raw reference** bakes the mockup's own nav bar, headline and
     buttons into the backdrop, where they sit behind the real DOM copy as
     ghosts of themselves. The glyphs are inpainted out by `mkart.py`, so the
     export is taken from its `--prepared-out` image.
   - **Cropping the normalised 1024×768 reference** inherits the ingest
     downscale (a real upload went 1672×941 → 1024×576, 61% of its linear
     detail). So `mkart` is fed a native-resolution reference built from the
     upload by `app/heroart.py::native_reference`, and the stage→native mapping
     is a single factor `m`.

   `doctor polarity` guards both, and each fixture pins `hero_kind`/`hero_max`.

Also: the artwork SVG is `aria-hidden` **decoration** (the copy carries the
meaning), and only the vendored font weights 400/500/600 are ever requested.

---

## High-cost landmines (beyond the four above)

- **`qa.sh` screenshots over `file://`** — no server, no cache. A stray
  `http.server` once served stale art for an entire round.
- **`astro dev` does not work here.** It runs a managed dev server that ignores
  `--port`, and re-transforms ~7 MB of inline SVG per request (hangs). Serve the
  built `dist/` with a static server instead.
- **`gen-{a,b}.mjs` are legacy hand-art generators — do NOT re-run them.** They
  overwrite the good `{v}.svg`.
- **Art names are dotted, page names hyphenated** (`a.svg`, `a.page.css` vs
  `a-full.html`, `a-static.html`). Constructing `$v.$ext` for a *page* silently
  matches nothing and ships stale pages — this shipped once and only surfaced via
  `cmp`.
- **`Inter` is not installed as a system font.** A bare `font-family: Inter` with
  no `@font-face` and no CDN silently falls back to Helvetica. Font A/B tests are
  only meaningful with `pipeline/fonts/` in play.
- **Page layout is chosen by `design.layout` or by the markup.** A design with
  `layout: "poster"` (A/B/C) builds the fixed 1024×768 stage and is scored on
  whole-stage pixels; `layout: "page"` — or any markup containing `<!--ART-->` —
  builds the responsive website and splices the art at that placeholder.
  **Removing the placeholder silently degrades a page build to a poster.**
- **`doctor fixtures` guards structure and a per-fixture art bound, not pixel
  parity.** Comparing studio fixture scores to A/B/C's is meaningless — a studio
  page reflows and is authored in its own type.
- **`mkart --prepared-out` is a separate mode: it saves the text-removed image
  and returns before tracing.** It reads whatever config it is given, so the
  studio points it at a generated `designs/<id>-hi.json` whose box and rects are
  the stage geometry scaled by the native factor `m`. It also needs `--up 1`
  (the native reference is already at full scale; the default `up=2` would
  upscale it for nothing).

Prefer dedicated tools over shell; this shell rejects `rm -f` in some contexts
(use `python3 -c "import os;os.remove(...)"`). See `docs/HANDOFF.md` §5 for the
remainder.

---

## Already ruled out — do not re-litigate

Measured and settled (full reasoning in `docs/HANDOFF.md` §4):

- **Font family** — Inter beats Inter Tight / Inter Display / SF Pro / Helvetica
  Neue / Archivo / Public Sans by ~1.3 mean on A.
- **Type metrics** — `h1` font-size is at a sharp optimum (A 80, B 84, C 82 px);
  letter-spacing, weight, transform, ink colour, opacity do not improve it.
- **Font smoothing** — `antialiased > auto > subpixel-antialiased`.
- **Art blur** — 0 px optimal (0.5 px costs 0.04-0.27).
- **Band edges** — uniform binning beats quantile binning and k-medians.
- **`opttol`** is inert; **`alphamax=1.0`** makes files bigger.
- **The text residual on A/B/C is a local optimum** for the Inter stack; only a
  different font or a higher-resolution reference could move it. This is exactly
  why the studio *authors* pages instead of imitating them.
- **The tracer cannot represent a photograph at a sane payload.** Every knob is
  flat (bands 96→192 = 3.50→3.43; chroma_gate 16→0 = 3.50→3.45) and `up` 2→4
  buys 0.07 for 10× the time, because the error lives in the hero photo (mean
  10.62) while the rest of the page is 0.2–3.1. Hence the raster export.
- **Coherent segmentation is a dead end.** k-means in Lab + connected components
  reaches mean 0.89 vs banding's 2.20 in a like-for-like paint sim — but it needs
  ~214k regions (~60 MB SVG). Grid quantise+merge = 8.69; transitive union-find
  merge collapses 214k → 18 regions (the cascade is inherent, not a bug).
- **SVG `linearGradient` fills and harmonic/diffusion inpainting are dead ends**
  for the same job (montiva 2.20 → 4.45 and 4.19 → 4.54 respectively).
- **Native-resolution SVG tracing is pointless** while the page ships a raster
  for photos; the SVG master stays at stage resolution.

> **The caveat worth remembering:** anything in that list judged only by the
> aggregate mean was measured through a scorer that was later found to be
> pessimistic (`sips -z` vs PIL Lanczos). Font metrics were re-checked and still
> hold; **text glow did not** — tightening it gained 0.05-0.09 on every variant.
> So a single re-check with the honest scorer (`qa/downsample.py`) is fair game.
> Record what you find in `docs/AGENT-NOTES.md`.

The one remaining dial for the SVG master is **payload vs parity**: `bands` is
the lever, ~1 KB gzip per 0.001 mean. Choosing a different operating point is a
one-parameter change — see `qa/sweep_up.py`.

---

## Where things live

```
pipeline/
  lib/designs.mjs      THE design registry — enumerates designs/*.json for every
                       other tool. Single source of truth; nothing hardcodes a
                       design list.
  designs/<n>.json     per-design config: ref, site, content, layout, target,
                       box, text rects, params, optional regions/blank
  qa/INDEX.md          what every QA tool does, and which ones matter
  qa/mkart.py          the art tracer (the heart of the repo); `--prepared-out`
                       also dumps its text-removed image for the raster hero
  qa/verify.sh         score each built dist/ vs its reference; PASS/FAIL
  qa/newdesign.py      scaffold a whole new design in one command
  qa/tune.py           coordinate descent over any CSS property, real pipeline
  gen-page.mjs         compose the self-contained page (page or poster layout)
  to-astro.mjs         copy that page into the design's Astro project
  build.sh             build every configured design end to end
  {a,b,c}.svg          the traced artwork — COMMITTED (regenerating needs potrace)
sites/variant-{a,b,c}/ the three worked examples (the tracer's regression suite)
preview/               one static server for all builds + a generated gallery
studio/                the upload -> site web app (FastAPI + React)
  backend/app/heroart.py   flat-vs-photograph decision + the raster hero export
  backend/app/runner.py    the orchestrator (stages, verify, package)
docs/                  HANDOFF.md, CHECKPOINT.md, STATE.json, HOME.md, ...
```

**Committed vs generated** (the line is *"can it be regenerated, and is it
expensive?"*): the traced `{a,b,c}.svg` and `designs/*.json` are committed;
`pipeline/{v}-full.html`, `sites/*/src/pages/index.astro` and `sites/*/dist/` are
gitignored pure products. Do not commit build output.

---

## Freedom to try new things

The repo is **design-agnostic** — a design name is the only input, and every
orchestrator discovers designs from `designs/*.json`. So there is nothing to edit
in the pipeline to add one:

```sh
cd pipeline
python qa/newdesign.py mydesign path/to/design.png   # config + ref + content + site
python qa/mkart.py mydesign --out mydesign.svg       # trace the art
node gen-page.mjs mydesign && node to-astro.mjs mydesign
(cd ../sites/variant-mydesign && npm install && npm run build)
./qa/verify.sh mydesign
```

New designs scaffold as `layout: "page"` (a responsive website). Two things in
`designs/mydesign.json` are genuinely per-design and worth checking by hand:
**`box`** (the art region — must cover the art and *not* the DOM text) and
**`text`** (rects the art must not bake in). `qa/textrects.py` derives `text`
automatically once the page CSS exists.

A design whose hero is a photograph needs no extra config: the studio measures
the hero band (`app/heroart.py`), and on a photographic result builds the raster
from a native-resolution reference and the tracer's own text-removed image. A
flat design is unaffected and keeps the traced SVG.

Useful entry points for investigation: `python qa/<tool>.py --help`, and the
"ones that matter" list in `pipeline/qa/INDEX.md`. `qa/artfloor.py` answers "is
the tracer still the bottleneck?"; `qa/tune.py` and `qa/sweep_up.py` are the real
optimisers; `qa/compare.py --regions` gives per-region diagnostics.

**Experiment freely — then prove you didn't break the moat.** The A/B/C posters
are the tracer's regression suite, not a website. `qa/verify.sh` (and
`studio/backend/doctor.py regress`, which runs it) is the gate. A change that
helps the studio but regresses A/B/C is not a win. The studio's own gate is
`doctor.py gate` (`env → polarity → fixtures → regress`), and the fixtures pin
both the traced-SVG master and the shipped raster hero.

---

## Docs map, and which one wins

Read in this order for depth:

| doc | what it is |
|---|---|
| `AGENTS.md` (this file) | entry point: rules, landmines, orientation |
| `README.md` | how the pipeline works; the product view |
| `docs/CHECKPOINT.md` | current state + "the two things future work must not break" |
| `docs/HANDOFF.md` | the full route: what was tried, what is exhausted, the 15 landmines |
| `docs/STATE.json` | machine-readable state (scores, params, targets, history) |
| `pipeline/qa/INDEX.md` | every QA tool and which matter |
| `studio/README.md` + `docs/STUDIO-PLAN.md` | the upload → site web app |
| `docs/HOME.md` | where the repo lives (machine-specific checkouts) |
| `docs/AGENT-NOTES.md` | append-only gotchas future agents discover |

**When docs disagree, trust these, in order:**

1. **The code and its configs** — `pipeline/designs/*.json` holds the enforced
   `target`; `qa/mkart.py` holds the tracer's truth.
2. **A fresh `./qa/verify.sh` run** — the scores it prints are the scores.
3. `AGENTS.md` / `CHECKPOINT.md` / `STATE.json` — kept current.
4. `HANDOFF.md` / `STUDIO-PLAN.md` — **historical record**. Valuable for
   reasoning and the exhausted list, but some figures predate later scoring
   changes; do not treat a number there as authoritative over (1) or (2).

`docs/HOME.md` contains machine-specific absolute paths (a second checkout, an
external volume). They are the author's layout, **not** a contract — do not treat
them as canonical or "fix" them.

---

## Recording what you learn

When you discover a gotcha, a ruled-out approach, or a non-obvious fix, append it
to **`docs/AGENT-NOTES.md`** (format described in that file). Keeping discoveries
in one agreed place is how this repo's knowledge stays trustworthy. If a finding
is big enough to change the current state, also update `docs/CHECKPOINT.md` and
`docs/STATE.json`.
