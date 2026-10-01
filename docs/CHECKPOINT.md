# CHECKPOINT

State at the end of the session that packaged this repo. Read this first, then
`README.md` for how the pipeline works and `docs/HANDOFF.md` for how it got here.

## What this is

Turn a flat design PNG into a **real, code-native website** — a responsive,
semantic page with traced SVG artwork, DOM text and CSS, and no raster images in
the output. The reference PNG is input to the pipeline, not an embedded asset.

**The north star changed.** This used to be a pixel-parity project: whole-page
mean-abs-pixel-difference against the reference, with a large text-measurement
layer tuned to make DOM glyphs land on the reference's pixels. That target is
unwinnable — its largest residual was **font substitution** (the reference's
typeface is not the vendored Inter), which no sizing or tuning removes. The
metric is now split:

- **the artwork** is scored on pixels, over the **art region** only (the page-copy
  rects masked out) — the tracer's job;
- **the website** is scored on **structure** — landmarks, sections, one `h1`,
  resolving links, flow layout, reflow — which is what makes it a website.

The retired text-metrics machinery (`measure_lines`, `measure_weight`,
`sample_line_colors`, per-line gradients, glow, `cap_top_offset` placement,
width-solved font sizes) is gone.

Three worked examples (A/B/C) remain as the **tracer's** regression suite: they
are fixed 1024×768 posters (`"layout": "poster"`) scored exactly as before.

## Status: done and verified

| | score (mean abs pixel diff, lower better) | payload |
|---|---|---|
| A | **2.71** | 6.4 MB / 870 KB gz |
| B | **2.76** | 3.4 MB / 523 KB gz |
| C | **2.99** | 7.7 MB / 1051 KB gz |

`pct>30` = 1.13% / 1.59% / 1.57%. Stable to ±0.01 over repeated runs.

- `qa/verify.sh` → **2.71 / 2.76 / 2.99 PASS** (unchanged: the poster shell and
  the tracer are untouched).
- `doctor polarity` → all checks pass (ink/box/two-tone/scope + the new
  structure-inference checks).
- `doctor fixtures` → **light / montiva / antho all PASS** (structure, not pixel
  targets).
- `doctor regress` → **regression PASS**.
- The studio builds a real page end to end on the montiva fixture (a real vision
  call): header + nav, hero, **3 content sections** (features / testimonials /
  contact), footer; one `h1`; no dead links; flow layout; no structure issues.
- Art fidelity is now taken by rendering the **traced SVG** at the reference
  stage (the page reflows, so a page screenshot would measure layout, not
  tracing). On the montiva fixture that reads **4.56** for the tracing itself,
  where the page screenshot reads ~62 (its first viewport is one reflowed band).
- The generated page has a **real visual design layer**: a role-based type scale,
  a sticky header, a hero with the traced art under a directional scrim, section
  title rows with action links, card grids, column bands and alternating section
  surfaces. `palette()` samples the reference's colours but enforces contrast and
  prefers the CTA's fill as the accent. `doctor polarity` guards palette polarity,
  palette contrast on a dark ground, accent-follows-CTA, and that interleaved
  same-name blocks still merge into one section.
- Branch `main`; published to **https://github.com/aglamadrid19/Anthotype**
  (remote `origin` on the canonical mirror and both checkouts).

## The two page shapes

`gen-page.mjs` builds one of two pages, chosen by the design's `layout`:

- **`"page"`** (default for scaffolded designs, and what the studio emits) — a
  responsive website: semantic sections in normal flow, a role-based type scale,
  the traced art as the hero backdrop (`<!--ART-->` placeholder).
- **`"poster"`** (A/B/C) — the historical fixed 1024×768 stage scaled to the
  viewport, so `qa/verify.sh` keeps scoring the traced art as it always did.

## Design-agnostic: a design name is the only input

The pipeline knows nothing about A/B/C. `pipeline/lib/designs.mjs` enumerates
`pipeline/designs/*.json`, and `build.sh`, `bootstrap.sh`, `qa/verify.sh` and the
preview gallery all ask it — so adding a design needs no edits to any of them.

Adding a design is one command (it scaffolds a `"layout": "page"` website):

```sh
python qa/newdesign.py <name> path/to/design.png    # config + ref + content + site
python qa/mkart.py <name> --out <name>.svg          # trace the art
node gen-page.mjs <name> && node to-astro.mjs <name>
(cd ../sites/variant-<name> && npm install && npm run build)
./qa/verify.sh <name>
```

`designs/<n>.json` carries everything per-design: `ref`, `site`, `content`,
`layout`, `target` (the score `verify.sh` enforces), `box`, `text` rects, tracing
`params`, and optional `regions`.

## The two things future work must not break

1. **potrace fills the BLACK (bit-0) region.** Pass `(~mask)*255`. Get it wrong
   and every band becomes an opaque plate while the page still *looks* fine.
   `pipeline/qa/mkart.py::_potrace`.
2. **Trace the CUMULATIVE mask `{lum >= e_i}`, painted darkest-first** — not
   disjoint bands. Mathematically identical, but potrace gets one solid nested
   region per band instead of 1px slivers: ~0.8 better mean, ~half the file size.

`qa/verify.sh` guards the rest: it fails on a score regression, on remote
assets, on an external stylesheet, and on any page-originated network request
(`qa/netcheck.py`, which has `--selftest` so a zero can be trusted).

## Committed vs generated

Committed: the traced art (`pipeline/{a,b,c}.svg` — expensive, needs potrace),
per-design config (`pipeline/designs/*.json`), the design registry
(`pipeline/lib/designs.mjs`) and site template (`pipeline/site-template/`),
references (`pipeline/qa/ref-{a,b,c}.png`), vendored Inter, the CSS/content
layer, all QA tooling, site configs + `package-lock.json`, `preview/`.

Gitignored: `pipeline/{v}-full.html` / `-static.html`, `sites/*/src/pages/`,
`sites/*/dist/`, QA render scratch. All are pure products of the committed files.

## Known gap (needs a product decision, not code)

**The A/B/C posters' CTA has no destination.** `href="#waitlist"`, and no element
with that id exists in the poster variants, so the button does nothing. Those are
the tracer's regression suite (fixed posters), not a website. The **studio's**
generated pages no longer have this gap: their CTAs point at a real in-page
anchor on the generated page. Set a real URL in the returned `content-<id>.json`
when you have one.

## Earlier session's changes

- **Scorer corrected.** The 2×→reference resize used `sips -z`, the worst of the
  five filters measured; 0.077 of B's number was the scaler, not the page. Now
  PIL Lanczos (`qa/downsample.py`). *No page pixels changed for this.*
- **Text glow was not exhausted after all.** The previous session's glow sweep
  ran through that same blurry scaler. Re-swept with the corrected one, tighter
  radius / lower alpha wins on all three: A 2.76→2.71, B 2.82→2.76, C 3.08→2.99.
  `pct>30` unchanged, so it is not a contrast trade. `docs/HANDOFF.md` flags that
  any "exhausted" item judged only by aggregate mean is worth re-checking.
- **Fonts self-hosted.** The page was loading Inter from the Google Fonts CDN;
  with the CDNs blackholed, A scored **4.22** instead of 2.71 (silent fallback to
  Helvetica). Inter is now vendored and inlined — offline score is identical.
- **Network + stylesheet gates** added to `qa/verify.sh`, both negative-tested.
- **Per-design config externalised** to `pipeline/designs/*.json` +
  `qa/newdesign.py`, so a new reference needs no edits to the tracer.
- **Fixes to my own tooling:** the bundle was silently shipping stale pages (dot
  vs hyphen filename mismatch, caught by `cmp`); `qa/tune.py` was baking its last
  test candidate into the file `qa.sh` screenshots; and the `aria-label` on the
  artwork leaked the internal variant letter into user-facing text.

## This session's changes (design-agnostic packaging)

- **`pipeline/lib/designs.mjs`** — the design registry. One place that answers
  "which designs exist" and "where is this design's site", used by every
  orchestrator. Removed the hardcoded `a b c` loops from `build.sh`,
  `bootstrap.sh`, `qa/verify.sh`, `qa/netcheck.py`, `qa/_env.py`, `serve.py`.
- **`qa/newdesign.py` rewritten** to scaffold a complete design (config +
  reference + `content-<n>.json` + `<n>.page.css` + Astro site from
  `pipeline/site-template/`) in one command.
- **`designs/<n>.json` is now complete**: gained `site`, `content` and `target`;
  `qa/compare.py` and `qa/mkart.py` read their regions/box from it.
- **`qa/_bootstrap.py`** re-execs a QA tool under the venv python when numpy is
  missing, so `python qa/mkart.py <name>` works with the system `python3`. The
  guard compares `sys.prefix` (not `realpath` — a venv's `bin/python` is a
  symlink to the base interpreter).
- **`preview/serve.py`** generates the gallery from the design configs and shows
  each target; the static `preview/index.html` is gone.
- **Removed `pipeline/sync-bundle.sh`** (see the landmine note above).
- **`package-lock.json`** is now committed per site for reproducible installs.

Verified from a fresh `git clone`: `./bootstrap.sh` → `./build.sh` →
`./qa/verify.sh` scores 2.71 / 2.76 / 2.99, and `qa/mkart.py` reproduces all
three committed SVGs byte-identically. A scaffolded fourth design was traced,
built and scored end to end, then removed.

## This session's changes (making the generated page good)

Stage 6 made the output a *website*; the pages it produced were structurally
correct but read as extracted content stacked in a column. Two fixes, both in
`studio/backend/app/generate.py`:

- **A name is one section, however the reading order interleaves.**
  `group_sections` now groups *all* blocks of a name into one section, ordered by
  position. Merging only adjacent runs was not enough: at a given y two sections
  can interleave (a testimonial's author line beside the contact band), which
  fragmented one section into three on a real upload. A landing page with two
  feature bands keeps both inside one `features` section, and `_section_body`
  renders each band — eyebrow, title row with any action link, cards — on its
  own. `doctor polarity` gained a check that interleaves two names.
- **A real visual design layer.** `build_page_css` emits a role-based type scale,
  a sticky header, a hero with the traced art under a directional scrim, section
  title rows, card grids with hover, plain column bands (contact details) and
  alternating section surfaces. `palette()` samples the reference's colours but
  *enforces contrast* — a design's headline can be a dark navy because it sat over
  a light hero panel, and using it as body ink on a dark page made the whole page
  unreadable — and prefers the CTA's fill as the accent so buttons and highlights
  agree. Testimonials render as `blockquote` cards; `gen-page.mjs` splices the
  hero art with `preserveAspectRatio="xMidYMin slice"` so it covers the hero box
  instead of letterboxing inside it.

Verified by rebuilding a real upload through the full pipeline (a coherent light
page) and the montiva fixture (`doctor run`), plus `doctor polarity` (structure,
palette polarity, palette contrast on a dark ground, accent-follows-CTA),
`doctor fixtures` 3/3 PASS, `doctor regress` PASS, and a frontend build.

### Ghosted copy in the hero backdrop (fixed)

A design review with a strong vision model (`gemini-3.1-pro` on the AntSeed
proxy) reviewing two real uploads against their mockups found the same
top-ranked defect on both: **the mockup's own text was traced into the hero
backdrop**, so the real DOM copy sat on top of a ghost of itself.  It read as a
double exposure and made the headline unreadable.

The cause: the extraction correctly separates page copy from text *inside* the
artwork (`part: page | artwork`) and only page copy becomes DOM — but
`write_all` built the tracer's exclusion rects from the page blocks alone,
deliberately leaving artwork-internal text to the tracer.  The anthotype upload
had **12 artwork blocks** (the "1 Image / 2 Sunlight / … / 5 Generate" step
labels, plus the mockup's own wordmark and headline) all baked into the
backdrop.

Now `text_rects` is given **every** text block.  A text block is not art: it is
blanked either way, and the tracer repaints it from the surrounding pixels, so
there is no hard hole.  Guarded by a new `doctor polarity` check that the rects
cover artwork text as well as page copy.

Rebuilding both uploads end to end confirmed the ghosting is gone (the montiva
hero now shows the photographed office, not a faded copy of its own headline),
with `doctor polarity` / `fixtures` / `regress` all still passing.

**Still open** (noted, not fixed): the traced artwork includes the mockup's own
CTA *button*, so a pale button shape can sit under the real one; and a light
mockup's artwork gets no crop allowance for its bottom third.

## Landmine: the sync script (removed)

`pipeline/sync-bundle.sh` used to mirror a *development tree* into this repo. It
was **deleted** this session: it hardcoded A/B/C, it mirrored a dev tree that no
longer exists, and it once deleted its own source when both paths defaulted to
the same directory. **This repo is now the single working tree** — edit it
directly; there is no second tree to sync from.

The incident it caused is historical: the separate development directory
`/Volumes/CrucialX10/anthosting` was destroyed and held duplicate working copies
of the three sites plus four extra assets (`anthosting-teaser-v{1,2}.png`,
`anthosting-social-square-v{1,2}.png`). Those were unrecoverable but nothing in
the pipeline referenced them. **The repo was not affected** and re-verifies
byte-for-byte from a fresh clone.

## Environment

`brew install potrace` — the only required external binary. `bootstrap.sh` then
creates the Python venv (numpy/pillow/scipy/scikit-image) and installs each
site's `node_modules`. `qa/_env.py` finds python/node/Chrome by probing, with no
hardcoded paths anywhere in the repo.
