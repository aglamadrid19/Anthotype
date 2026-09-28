# Anthotype — engineering handoff

**The project.** A pipeline that turns a flat design PNG into a *code-native*
website — Astro + DOM text + CSS + traced SVG geometry, no raster images in the
output. The reference PNG is pipeline *input*; it is never embedded.

**This repo is design-agnostic.** `pipeline/lib/designs.mjs` enumerates
`pipeline/designs/*.json`, and every orchestrator uses it, so adding a design is
`python qa/newdesign.py <name> <ref.png>` plus a trace/build — no edits to the
pipeline. The three AntHosting designs (A/B/C) are the worked examples and the
regression suite, not the scope. See `README.md` for the one-command flow and
`docs/CHECKPOINT.md` for current state.

**Status: done and verified.** Every design builds clean, and
`pipeline/qa/verify.sh` scores each real built `dist/index.html` against its
reference. Nothing is in flight.

| Variant | at conversation start | **shipped now** | payload | page |
|---|---|---|---|---|
| A | 12.17 | **2.71** | 6.4 MB raw / 870 KB gz | `sites/variant-a/dist/index.html` |
| B | 16.92 | **2.76** | 3.4 MB raw / 523 KB gz | `sites/variant-b/dist/index.html` |
| C | 15.09 | **2.99** | 7.7 MB raw / 1051 KB gz | `sites/variant-c/dist/index.html` |

Metric = mean absolute per-pixel RGB difference vs the reference PNG at
1024x768, 0-255 units. Lower is closer; 0 would be a perfect match.
`pct>30` = share of pixels off by more than 30, currently 1.13% / 1.59% / 1.57%.
The scores above predate this session's glow re-sweep and self-hosted fonts;
the intermediate table in section 3 is the older operating point.

---

## 1. Where everything lives

This document was written inside the development tree; **in this repo the same
things live in one place**, so paths below have been mapped accordingly.

| What | In this repo |
|---|---|
| Art generation + all QA tooling | `pipeline/` |
| The three Astro sites | `sites/variant-{a,b,c}/` |
| Reference PNGs | `pipeline/qa/ref-{a,b,c}.png` |
| Per-design config (box, text rects, params) | `pipeline/designs/{a,b,c}.json` |
| Vendored Inter | `pipeline/fonts/*.woff2` |
| This handoff + machine-readable state | `docs/HANDOFF.md`, `docs/STATE.json` |
| Preview server + gallery | `preview/` |

### Environment preamble

Nothing needs exporting. `bootstrap.sh` creates the venv, and `qa/_env.py`
resolves python/node/chrome by probing for a working interpreter rather than
trusting a hardcoded path:

```sh
./bootstrap.sh                  # potrace check + python venv + npm install
cd pipeline && ./qa/verify.sh   # score the three builds
```

External dependencies: **potrace** (`brew install potrace` — the only required
one), plus Google Chrome and `sips` for screenshots.

---

### Adding a design

```sh
cd pipeline
python qa/newdesign.py <name> path/to/design.png   # config + ref + content + site
python qa/mkart.py <name> --out <name>.svg         # trace the art
node gen-page.mjs <name> && node to-astro.mjs <name>
(cd ../sites/variant-<name> && npm install && npm run build)
./qa/verify.sh <name>
```

The only per-design inputs that matter are `box` (the artwork region) and `text`
(rectangles of DOM type the art must not bake in), both in
`designs/<name>.json`. `designs/<name>.json` also carries `site`, `content` and
`target`, so nothing else needs editing: `build.sh`, `bootstrap.sh`,
`verify.sh` and the preview gallery all discover designs from that directory.

---

## 2. The route we took (chronological, with the reasoning)

### Stage 0 — hand-authored art fails (12.17 / 16.92 / 15.09)
The first attempts drew the artwork as hand-written SVG shapes (icospheres,
hexagons, tiles). That plateaus around 12-17 mean: hand-guessing hundreds of
glow shapes by eye cannot land on the reference.

### Stage 1 — recover the art *from* the reference (the pivot)
Instead of drawing it, **trace** it: split the art region into luminance bands,
run potrace on each band's mask, emit the result as ordinary SVG path data.
This is still real vector code — scalable, re-colourable, animatable, no
embedded bitmap — and it is what got the score under 6.

### Stage 2 — THE POLARITY BUG (the single most important fact here)
potrace fills the **black / bit-0** region of a bitmap: it treats *unset* bits as
ink. PIL's `L -> '1'` conversion *also* writes the pixel value as bit 0. So
feeding a mask straight in makes potrace trace its **complement** — an opaque
near-black plate spanning the whole frame, painted over the art layer.

Symptom: the page *looked* plausible because the art was contributing almost
nothing; hiding `.art` entirely changed the score by **<0.01**.

Fix (`pipeline/qa/mkart.py::_potrace`): pass `(~mask) * 255` to potrace. With the
polarity right, potrace's outline *is* the mask (holes included, via winding), so
the old coordinate-rewriting helper `_fmt()` and the frame-plate stripper both
disappeared — potrace's own `translate(0,H) scale(1,-1)` is now emitted verbatim
and composed with nested `<g>` elements.

**Never rewrite potrace's path coordinates.** Compose transforms with `<g>`.

### Stage 3 — text exclusion, and the `up` dial
- `exclude_text=True` with **`text_lum_max=200`**: inside the live-text
  rectangles, drop only the near-white bands (the rasterised glyph cores) while
  keeping the dim glow the type sits on. Baking the glyphs in scored ~0.3 better
  but would leave a ghost of the old headline behind any later copy edit.
- `TEXT` rectangles are **auto-derived**, not hand-guessed: `qa/textrects.py`
  renders the page DOM-only and measures where the words actually are.
- `up` (supersampling before tracing) recovers fine detail at linear file cost.

### Stage 4 — the cumulative-mask fix (this session's big win)
**This is the highest-value change after polarity.**

The original band decomposition used *disjoint* bands:
`{e_i <= lum < e_{i+1}}`. Each of those is a scatter of 1-5px slivers with
hairline gaps between neighbours — exactly what potrace reconstructs worst and
most verbosely.

We now trace the **cumulative** mask `{lum >= e_i}` instead. Painted
darkest-first the two are **mathematically identical**: region `[e_i, e_{i+1})`
still ends up band *i*'s colour, because bands `i+1...` do not cover it. The
difference is that potrace now receives one solid nested region per band.

| | before | after |
|---|---|---|
| A | 3.76 | **2.99** |
| B | 3.36 | **3.23** |
| C | 3.78 | **3.32** |
| `a.svg` | 9.0 MB | **4.1 MB** |

Better score *and* half the bytes. Painting order is load-bearing here: bands
must go **darkest (lowest `e_i`) first**, or the largest dark region covers the
bright detail and the art renders ~4x too dark.

This retired two of the previous session's open leads: the `_fmt()`
relative-coordinate theory is moot (no coordinate rewriting happens at all), and
the "A/C bright-band speck" diagnosis was a *symptom* of disjoint bands, not the
cause.

### Stage 5 — flat polygons, and the size/parity knee
- **`alphamax=0, opttol=0`**. With solid masks the polygons are already
  sub-pixel smooth at `up>=2`; curve fitting only adds bytes. Worth ~0.1 on A and
  C and makes files *smaller*. `opttol` is inert in this range; `alphamax=1.0`
  makes files bigger.
- **`-webkit-font-smoothing: antialiased`** on all three (~0.04-0.08 each).
- Operating point chosen at the **knee** of the measured score-vs-size curve, so
  the shipped payload is no larger than the old build while scoring ~1 mean
  better.

---

## 3. How to reproduce, verify, and change the art

### Rebuild everything from the committed sources
```sh
$PY qa/mkart.py a && node gen-page.mjs a && ./qa.sh a     # per variant, a/b/c
node to-astro.mjs a                                       # copy page into the site
(cd ../variant-a && npm run build)                        # Astro build
./qa/verify.sh                                            # PASS/FAIL vs dist output
```
**Verified this session: re-running `qa/mkart.py` from the committed `PARAMS`
reproduces the shipped `{a,b,c}.svg` byte-for-byte.** The whole pipeline is
deterministic.

### Current parameters (`qa/mkart.py`, `PARAMS`)
| v | box | bands | up | turdsize | alphamax | opttol | exclude_text |
|---|---|---|---|---|---|---|---|
| a | 418,0,1024,742 | 96 | 2 | 2 | 0.0 | 0.0 | True |
| b | 0,46,1024,726 | 24 | 4 | 2 | 0.0 | 0.0 | True |
| c | 0,78,1024,742 | 96 | 2 | 2 | 0.0 | 0.0 | True |

All three: `text_lum_max=200.0`, `cumulative=True`, art blur **0 px**, and
`{a,b,c}.css` intentionally empty (art colour lives in the SVG band fills).

### Verify targets are enforced
`qa/verify.sh` fails if a variant regresses past: **A 2.90, B 3.00, C 3.25**.

### Useful QA tools
```sh
$PY qa/artfloor.py c        # art-only floor: oracle vs render, live text excluded
$PY qa/artgap.py a          # render error per reference-luminance bucket
$PY qa/tracefid.py a        # splits loss into "tracer" vs "browser"
$PY qa/sweep_up.py a --ups 2,3 --bands 64,96,128 --turd 2   # score-vs-size sweep
$PY qa/oracle.py a --ups 1 --bands 64,128,256               # no-render floor
$PY qa/compare.py a --regions     # per-region metrics + side-a.png / diff
$PY qa/heatblocks.py a 32         # block diff heatmap
$PY qa/textrects.py b --grow 4    # re-derive text rects (after a copy/layout edit)
$PY qa/tune.py b /tmp/spec.json --rounds 2   # real-pipeline CSS optimiser
```

---

## 4. Where the remaining error is (so nobody re-litigates it)

Contribution to the overall mean, split by area:

| | text (DOM) | art | rest |
|---|---|---|---|
| A | 9.3% px, **1.47** | 56.8% px, 1.06 | 33.9% px, 0.46 |
| B | 11.4% px, **1.75** | 77.2% px, 1.42 | 11.5% px, 0.07 |
| C | 10.4% px, **1.77** | 76.1% px, 1.37 | 13.5% px, 0.18 |

### Per-region means (shipped state, from `qa/compare.py <v> --regions`)

| region | A | B | C |
|---|---|---|---|
| brand | — | 5.87 | 7.68 |
| title | 14.35 | 14.02 | 14.62 |
| coming | 10.59 | 10.59 | 12.22 |
| divider | — | — | 4.55 |
| tagline | 17.41 | 9.25 | 11.28 |
| cta | 5.78 | 9.91 | 9.95 |
| ant | 2.17 | 2.87 | 3.60 |
| pods | 1.88 | 1.96 | 2.16 |
| bgTL | 0.78 | 2.52 | 2.04 |
| bgR | 1.06 | 1.14 | 1.67 |
| bgB | 0.80 | 0.66 | 1.17 |

`title`/`coming`/`tagline` are the DOM text regions and are the worst means —
this is the residual that is at a local optimum for the Inter stack (§4).
`brand` is the small logo mark; `pods`/`ant`/`bg*` are art or background and
are all low. The art window as a whole is at its floor.

### The art is at its floor
`qa/artfloor.py` (oracle = band-paint reconstruction; both masked to the art
window with live-text rects excluded):

| | oracle floor | actual render | **trace overhead** |
|---|---|---|---|
| A | 1.21 | 1.45 | +0.24 |
| B | 1.17 | 1.27 | +0.10 |
| C | 1.33 | 1.49 | +0.16 |

(Re-measured with the corrected Lanczos scorer; the previous table read
1.48 / 1.38 / 1.53 for the render column under `sips -z`.)

A's overhead was **+1.56** before the cumulative-mask fix (measured at the
then-current 40-band parameter set; the floors above are the shipped 96-band set). The tracer is no
longer the bottleneck; what is left is the reference's own band quantisation.

### Everything below was measured and is EXHAUSTED — do not re-test
- **Font family**: Inter beats Inter Tight, Inter Display, SF Pro Display,
  Helvetica Neue, Archivo and Public Sans by ~1.3 mean on A and ~0.9 on C.
  (These tests are valid: they ran with the Google Fonts CDN reachable, so real
  Inter was loaded.  Note that Inter is **not installed on this machine** — a
  bare `font-family: Inter` with no `@font-face` and no CDN falls back to
  Helvetica, which is why `/tmp`-style probes that omit the font CSS appear to
  show "no difference between families".  Check `pipeline/fonts/` is in play.)
- **Font smoothing**: `antialiased` > `auto` > `subpixel-antialiased`, confirmed
  both with and without `text-shadow`.  (Re-checked under the corrected scorer
  -- still holds.  Glow radius/alpha did *not* hold; see the glow section.)
- **Type metrics**: `h1` font-size sits at a sharp optimum on all three (A 80,
  B 84, C 82 px — +/-2px costs 0.3-0.9). Letter-spacing, font-weight, transform,
  `--ink` colour and element opacity all fail to improve it. The reference glyph
  cores sample ~0.84-0.9x our ink, but dimming trades mean for `pct>30` (real
  contrast loss), so it is not a win.
- **Art blur**: 0 px optimal (0.5 px costs 0.04-0.27). The old `1.8px` only ever
  compensated for the missing art.
- **Band edges**: uniform binning beats quantile binning and 1-D k-medians;
  k-medians over-weights the huge dark region (A paint error 1.74 vs 1.77 vs 3.45).
- **`opttol`** is inert; **`alphamax=1.0`** makes files bigger.

### Font loading is now self-hosted (fixed this session)
The reference designs use **Inter**, and until now the page pulled it from the
Google Fonts CDN via `<link href="https://fonts.googleapis.com/css2?family=Inter...">`.
That made the build's typography — and therefore its measured fidelity — depend
on the network.  Proof: with the two font CDNs DNS-blackholed, variant A scored
**4.22** instead of **2.77** (the page silently fell back to Helvetica).

Fix: Inter's latin woff2 files are vendored at `pipeline/fonts/` (6 weights,
144 KB total) and inlined as `@font-face` rules by `gen-page.mjs`.  The Google
Fonts `<link>`s are gone.  Measured result with the CDNs blackholed:
**2.77 / 2.90 / 3.11 — pixel-identical to the online render** (delta < 0.0001
mean, max channel difference under 0.01), so this costs nothing and removes the
dependency.

Two consequences that will bite if you undo them:
1. **`build.inlineStylesheets: 'always'`** is now set in every
   `astro.config.mjs`.  The inlined font CSS pushes the stylesheet past Astro's
   default 4 kB auto-inline threshold; without this Astro externalises it to
   `/_astro/index.*.css`, which **cannot load over `file://`** — the exact
   protocol `qa.sh` and `qa/verify.sh` screenshot with.  Symptom if it regresses:
   scores jump to 158/170/227 and everything renders unstyled.
2. **`qa/verify.sh` now fails hard on remote assets** and on any external
   `/_astro/*.css` href, and it DNS-blackholes the font CDNs during the
   screenshot.  A reintroduced CDN dependency therefore shows up as a FAIL
   rather than passing on a warm cache.  Negative-tested: re-adding the
   `<link>` produces `a FAIL: build references remote assets`.

To refresh the vendored fonts:
`npm pack @fontsource/inter` then copy `package/files/inter-latin-{300..800}-normal.woff2`
into `pipeline/fonts/`.

### Text glow was NOT at its optimum (fixed this session)
The previous session swept `text-shadow` and concluded the shipped values were
optimal (2.770 either way). That result was **an artifact of the `sips -z`
scaler**: once the scorer was corrected (see above), a glow sweep through
`qa/tune.py` -- which drives the real pipeline, `gen-page.mjs` + `qa.sh` -- finds
a consistent, reproducible improvement on all three.

The pattern is the same everywhere: **tighter radius, lower alpha** on the green
word. The old values bloomed the colour too widely, which the blur-happy `sips`
downsample then hid.

| | old | new | gain |
|---|---|---|---|
| A | 2.76 | **2.71** | -0.05 |
| B | 2.82 | **2.76** | -0.06 |
| C | 3.08 | **2.99** | -0.09 |

Specifics (all three variants):
- `h1` white glow radius **14-18px -> 8-10px**.
- `h1 .green` radius **18-20px -> 6-10px**, alpha **.30-.32 -> .20-.22**.
- `h2` radius **12px -> 6px**.

Verified stable to +/-0.01 over three consecutive runs, and `pct>30` is
unchanged (1.13 / 1.59 / 1.57) -- i.e. this is not a contrast trade, which is
exactly why the older "dimming trades mean for pct>30" objection does not apply.

Lesson worth keeping: **the old sweep was run through the old scorer.** Any
"exhausted, do not re-test" entry below that was measured only in aggregate
(mean) is worth one re-check now that the measurement is honest. Font metrics
were re-checked and are still at their optimum; glow was not.

### The one remaining dial: payload vs parity
Bands are the lever; `up` barely matters now. Measured with `qa/sweep_up.py`:

| variant | cheaper points | shipped |
|---|---|---|
| A | 2.86 @ 4.3 MB (u2/b64), 2.85 @ 5.7 MB (u3/b64) | **2.77 @ 6.7 MB (u2/b96)** |
| B | 3.09 @ 1.9 MB (u4/b16), 3.23 @ 1.2 MB (u4/b12) | **2.90 @ 3.5 MB (u4/b24)** |
| C | 3.24 @ 4.8 MB (u2/b64) | **3.11 @ 8.0 MB (u2/b96)** |

A at 128 bands reaches 2.75 for 8.8 MB (~1 KB gzip per 0.001 mean). Choosing a
different point is a one-parameter change: edit `PARAMS`, then re-run
`qa/mkart.py` + `gen-page.mjs` + `qa.sh` (or just `qa/sweep_up.py`).

### Local optimum note
The text residual is not fixable by tuning the current font stack. Moving it
would need a genuinely different font, or a higher-resolution reference.

---

## 5. Landmines (each of these cost real time once)

1. **potrace polarity.** Pass `(~mask)*255`. Get this wrong and every band
   becomes an opaque plate — and the page still *looks* fine.
2. **Keep potrace's `translate(0,H) scale(1,-1)`**; compose with nested `<g>`,
   never rewrite coordinates.
3. **Paint bands darkest-first.** Sorting by pixel count instead puts the huge
   dark band on top and erases the bright detail.
4. **`qa.sh` screenshots over `file://`** — no server, no cache. A stray
   `http.server` once served stale art for an entire round.
5. **`gen-{a,b}.mjs` are legacy hand-art generators — do NOT re-run them.** They
   overwrite the good `{v}.svg`.
6. `qa/batch.py` renders from a cached style block and **can disagree with
   `qa.sh`**. For load-bearing decisions use `qa/tune.py` (real pipeline) or the
   `qa.sh` loop directly.
7. Headless Chrome is flaky; retry loops exist in `qa.sh`, `qa/batch.py`,
   `qa/svg2png.py`, `qa/geom.py`. `pkill -f "Google Chrome"` before big batches.
8. This shell rejects `rm -f` in some contexts — use
   `python3 -c "import os;os.remove(...)"`.
9. `sips`/Chrome cannot be assumed to agree on colour space; everything is
   colour-managed to sRGB before scoring.
10. **`astro dev` is impractical for this project.** This Astro build runs a
    *managed* dev server that ignores `--port`, and even attached directly it
    hangs per request because dev mode re-transforms ~7 MB of inline SVG on every
    hit. Serve the built `dist/` with a static server instead (see §6).
11. **Never let Astro externalise the stylesheet.** `build.inlineStylesheets`
    must stay `'always'` in every `astro.config.mjs`. The inlined font CSS is
    large enough that Astro's default 4 kB auto-inline threshold kicks in, and an
    external `/_astro/*.css` cannot load over `file://` -- the protocol
    `qa.sh` / `qa/verify.sh` screenshot with and the simplest way to open the
    page. Symptom: scores jump to ~158/170/227 and the page renders unstyled.
    `qa/verify.sh` now fails hard on this -- both with a string check *and* with
  `qa/netcheck.py`, which renders the page through Chrome's net log and asserts
  zero page-originated requests.  Run `qa/netcheck.py --selftest` first: it
  renders a page that deliberately links the Google Fonts CDN and confirms the
  detector sees it (3 requests), so a zero elsewhere is a real zero and not a
  broken measurement.  Negative-tested both ways.
12. **`Inter` is not installed on this machine as a system font.** A
    `font-family: Inter` with no `@font-face` and no CDN silently falls back to
    Helvetica. Font-family A/B tests are only meaningful with
    `pipeline/fonts/` in play; a bare `/tmp` probe will wrongly report "every
    family measures the same".
13. **Art names are dotted, page names are hyphenated** (`a.svg`, `a.page.css`
    vs `a-full.html`, `a-static.html`). Any code that constructs `$v.$ext` for
    the *pages* silently matches nothing and ships stale pages — which happened
    once (in the now-removed `sync-bundle.sh`) and only surfaced via `cmp`.
    `pipeline/*-full.html` and `pipeline/*-static.html` are the real patterns.

---

### The scorer was slightly pessimistic (fixed this session)
The pages render at device-scale-factor 2 and are compared against a 1024x768
reference, so a downsampling filter is unavoidable -- and **the filter changes
the measured score**. Measured on identical captures, varying only the filter:

| filter | A | B | C |
|---|---|---|---|
| `sips -z` (what the toolchain used) | 2.7718 | 2.8970 | 3.1083 |
| PIL box | 2.7736 | 2.8312 | 3.0886 |
| PIL hamming | 2.7685 | 2.8721 | 3.0977 |
| PIL bicubic | 2.7616 | 2.8615 | 3.0910 |
| **PIL lanczos (now canonical)** | **2.7587** | **2.8205** | **3.0803** |

`sips -z` was the *worst* of the five on B by 0.077 -- about 2.7% of B's headline
number was the scaler, not the page. It was never a rendering problem; it was a
measurement artifact, which is why **the page was not changed to get this**.
Lanczos is the standard downsampling filter and is also portable (no macOS
dependency), so `qa/downsample.py` now does the resize and both `qa.sh` and
`qa/verify.sh` call it.

Consequences:
- **Shipped scores are now 2.76 / 2.82 / 3.08** (were 2.77 / 2.90 / 3.11).
  Stable to +/-0.01 over three consecutive runs.
- **Verify targets tightened to 2.82 / 2.88 / 3.15** (~0.06 headroom above the
  stable value, so capture noise cannot fail the build but a real regression
  will).
- The old numbers in this document and in `STATE.json` were produced with
  `sips -z`. The table above lets you translate between the two.

### Clean-room verification (re-run this after any change)
This repo is verified reproducible from a neutral path with no reference back to
this machine's layout (see `docs/HOME.md` for where the checkouts live):

```sh
git clone <repo> /tmp/cr && cd /tmp/cr
./bootstrap.sh                 # venv (numpy/pillow/scipy/skimage) + node_modules
cd pipeline
./build.sh                     # every design: page -> astro -> dist
./qa/verify.sh                 # -> PASS 2.71 / 2.76 / 2.99
python qa/mkart.py a           # art regenerates BYTE-IDENTICAL from its own refs
./qa/verify.sh                 # still PASS after a full from-source rebuild
```

Last run confirmed all of the above, plus that no absolute path to the
development tree or the author's home directory remains anywhere in the repo.
`qa/_env.py` resolves the interpreter by *probing* candidates for numpy rather
than trusting a hardcoded path, and `qa/verify.sh` needs no environment variables
at all.  A fresh `git clone` was then bootstrapped, rebuilt and re-scored from
scratch to confirm the committed files are sufficient.

---

## 6. Viewing the builds

`preview/serve.py` serves all three built `dist/` directories plus a gallery
from one process:

```sh
cd preview && ./start-persistent.sh 4173
#   http://127.0.0.1:4173/      gallery (iframes all three + scores)
#   http://127.0.0.1:4173/a/    variant A   (b/, c/ likewise)
#   http://127.0.0.1:4173/ref/a   reference PNG
#   http://127.0.0.1:4173/diff/a  difference amplified x4
```

**Use `start-persistent.sh`, not a background `&`.** A plain
`python serve.py &` is a child of the shell that launched it, so it dies the
moment that shell (or an agent session) exits -- which is exactly why the URLs
previously stopped resolving in the browser.  `start-persistent.sh` uses
`daemonize.py` (double-fork + `setsid`) so the server is re-parented to launchd
(`PPID 1`) and keeps serving across sessions.  It also frees the port first,
records the pid in `/tmp/anthosting-preview-<port>.pid`, and logs to
`/tmp/anthosting-preview-<port>.log`.

`launchctl submit` is *not* a workaround here: launchd cannot read this external
volume (`Operation not permitted`), so the submitted job dies at interpreter
startup.

If no server is convenient, the pages are self-contained — open
`variant-{a,b,c}/dist/index.html` directly with no server at all.

**Note:** the user's default browser is **Safari**, so a bare `open <url>` goes
to Safari, not Chrome. Verify with
`osascript -e 'tell application "Safari" to get URL of every tab of every window'`.

---

## 7. Correctness issues found and fixed (non-pixel)

The pixel metric cannot see any of these; they were found by inspecting the built
DOM.  Worth repeating after any change to the content layer.

**Fixed this session**
- **The artwork SVG was announced to screen readers as
  `aria-label="AntHosting {v} artwork"`** — an internal variant letter leaking
  into user-facing copy.  The artwork is decorative (the headline, tagline and
  CTA carry the meaning), so `mkart.py` now emits `aria-hidden="true"
  focusable="false"`.  Regenerating only changes the `<svg ...>` header; the
  traced path geometry is byte-identical, and scores are unchanged.

**Open -- needs a product decision, not a code fix**
- **The CTA is a dead link in all three variants.** `href="#waitlist"`, and no
  element with `id="waitlist"` (or any target) exists on any page, so clicking
  "Join the waitlist" does nothing.  The design PNGs only specify the button's
  appearance, so no real destination is recoverable from them.  Set the real
  waitlist URL in `pipeline/content.json` (the `href` lives inside each
  variant's `markup` string) once it is known.
- **`<main>` has no heading landmark pairing beyond `h1`/`h2`** -- acceptable
  here, flagged only because the page is otherwise semantically clean.

---

## 8. What is committed, and what is generated

The dividing line is *"can it be regenerated from the committed files, and is it
expensive?"*

**Committed** (inputs, logic, and the expensive artifact):
- `pipeline/{a,b,c}.svg` — the traced artwork. This is the one output worth
  committing: regenerating it needs potrace and a few minutes per variant.
- `pipeline/designs/{a,b,c}.json` — per-design trace box, text rects, params.
- `pipeline/qa/ref-{a,b,c}.png` — the design references.
- `pipeline/fonts/*.woff2` — vendored Inter.
- `pipeline/{a,b,c}.page.css`, `pipeline/content.json` — the DOM/CSS layer.
- all QA tooling, the sites' `package.json` / `astro.config.mjs`, `preview/`.

**Generated** (gitignored; see `.gitignore`):
- `pipeline/{v}-full.html`, `{v}-static.html` — from `gen-page.mjs`.
- `sites/*/src/pages/index.astro` — from `to-astro.mjs`.
- `sites/*/dist/` — from `astro build`.
- `qa/render-*.png` and friends — scratch output from the scorer.

So a fresh clone is three commands from a passing build:

```sh
./bootstrap.sh
cd pipeline && ./build.sh && ./qa/verify.sh
```

`build.sh` discovers designs from `designs/*.json` and builds each one's Astro
site, so there is no per-design loop to keep in sync.
- `mkart-backup.py` — the pre-polarity-fix `mkart.py`, kept as a reference for
  how the masks used to be (wrongly) built.
- **this repo is the deliverable.** The old dev-tree mirror (`sync-bundle.sh`)
  was removed; edit a checkout directly (see `docs/HOME.md`).
