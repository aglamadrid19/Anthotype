# CHECKPOINT

> **New agent? Read `AGENTS.md` first** — it is the entry point (setup, hard
> rules, landmines, and what not to re-litigate). This file is the current-state
> record; come here for depth, not orientation.

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

## This session's changes (the remaining fidelity defects)

The same vision critic was run again on the rebuilt uploads.  The ghost was
gone; what was left was a ranked list of composition defects, all now fixed and
guarded (full reasoning in `docs/HANDOFF.md`, Stage 9):

- **The hero backdrop showed the section below the hero** — the next section's
  cards and icons bled into the backdrop.  `generate.hero_band()` computes the
  mockup's actual hero slice and `gen-page.mjs` narrows the spliced SVG's
  `viewBox` to it.  The SVG file is untouched, so the art metric still renders
  the whole artwork.
- **The mockup's own CTA button was traced in** — a pale "ghost button" under
  the real one.  `mkart.build()` gained `blank_rects` (rectangles removed
  wholesale, from `generate.button_rects()`); on a light ground the exclusion
  *inpaints* glyph ink, which never touched a solid button plate.
- **Header layout** — one flex row of everything bunched the nav right.
  `_header_html` emits brand / nav / actions as three groups; the CSS is a
  3-column grid.  The phone is recognised by shape and gets a `tel:` link.
- **Cards were flat grey panels on grey** — `palette()` gained `card`, `tint`
  and `shadow`; cards are near-white with a soft shadow on a tinted band, and
  denser.
- **Hero order** — buttons were appended last, so a fine-print line drawn under
  them became a caption above them; and side-by-side buttons came out swapped.
  Rows are now emitted where they sit, buttons ordered left-to-right.
- **A hero's action/trust row became a stray section** — a headless group right
  after the hero is now the hero's own row, and back-to-back same-name groups
  merge.
- **Contact panels were crammed into the title row** — a short block with copy
  under it in its own column stays in that column.
- **Badges and two-line buttons were role-dependent** — badges are detected by
  shape; a button label with a trailing phone number renders as two lines.

**Still not fixable, and why** (so it is not re-litigated):

- **Icons.**  The mockup's card icons, star rows and map pin are artwork pixels,
  not DOM; a card's icon has no fixed position once the layout reflows.
  Recovering them as real assets is a separate feature.
- **Artwork-internal labels are blanked.**  Blanking every text block is right
  for the page's own copy but also removes the illustration's own captions (the
  anthotype step labels).  Keeping them re-introduces ghosting wherever a traced
  label lands behind DOM text, which is not known at trace time.
- **The traced art is flatter than the mockup** — it is posterised into 24-26
  luminance bands; that is the tracer's chosen payload/parity operating point.

## This session's changes (studio trace point + nav links)

Working from the real uploads, not just the fixtures. Two fixes, both guarded by
the full gate (`qa/verify.sh`, `doctor polarity/fixtures/regress` all pass):

- **The studio was tracing at half resolution.** `newdesign.py` scaffolds
  `bands=48` and the studio inherited it, while the tuned A/B/C designs use `96`.
  `generate.write_all` now pins **`bands=96, up=2`** in the per-job config. On the
  real uploads this improves the masked art mean (u5 4.244 → 4.144; u1/u2/u4 to
  0.89/1.20/2.33). It is a measured **knee** — 192/384 bands are *worse*, so the
  studio must not "max out" bands. Studio-only: A/B/C are untouched.
- **Nav links rendered as buttons.** The vision model tags every header/footer
  link `cta`, so a nav row ("Home", "Services", "About") came out as a stack of
  boxed buttons alongside the one real button. `generate._nav_cta_ids` classifies
  a short `cta` in a row of ≥3 short `cta`s as a nav link — unless it has a solid
  fill (the real button keeps its fill; links on a busy row come back `outline`).
  `_cta_html` emits `class="navlink"`; a run of them is wrapped in `.navlink-row`
  so it flows horizontally. Nav-vs-button needs **both** shape and fill — shape
  alone misclassifies a short button that sits inside a link row.

**Ruled out by measurement (do not retry):** cropping the trace **box** to the
hero band. It looks like an obvious win (only the hero is shown) but scores
worse — the tracer's band edges are percentiles of the *box's own* histogram, so
a hero-only box re-bins the image against the hero's tones and loses fidelity
(4.14 full box vs 5.37 hero box, same 96 bands). `hero_band` crops what is
*shown* (the viewBox), never what is traced. `docs/AGENT-NOTES.md` has the full
measurement, including a corrected earlier note that got this wrong.

## This session's changes (ghosting fixed for both polarities + hero composition)

The remaining visual defects from the user's report — low-quality extraction,
lost colour, and stray artwork text — are now fixed, and guarded by the full gate
(`qa/verify.sh` 2.71/2.76/2.99, `doctor polarity/fixtures/regress` all pass).

- **Dark-design ghosting (AntHosting green-on-black) — FIXED.** The dark-path
  exclusion drops a band only when its median colour inside the rect exceeds
  `text_lum_max` (200) — it assumes near-white type, so a colored/dim headline's
  anti-aliased fringe (lum ~105) survived and was traced as a ghost. The cure is
  to reuse the **light** path's inpainting: `generate.write_all` now sends the text
  rects through `blank_rects` and sets `text_bg_lum` for a **dark** background too,
  so `mkart` finds ink by local contrast and fills it from the surroundings. The
  traced ghost disappears (u1 art 0.89 → 0.88, page whole 9.19 → 9.05).
  *Ruled out by measurement:* bigger exclusion rects and a per-rect local-background
  band-drop both made it worse (the latter drops the ground and keeps the fringe —
  the classic hole/plate inversion). See `docs/AGENT-NOTES.md`.
- **Light-design ghosting from colour-blind inpainting — FIXED.** The inpaint
  marked ink with `|lum - bg_local| > 15`, where `lum` is the **mean of RGB**, so a
  saturated colour near the ground was invisible to it: the anthotype wordmark's
  green `type` (mean lum ~119 on a ~220 ground) was traced in full. The test is now
  a **max-channel RGB distance** against a per-channel local background. The
  anthotype wordmark region goes to **0 green ghost pixels**; the page whole mean
  drops 24.13 → 19.16. (A/B/C never enter the inpaint branch, so they are
  byte-identical.)
- **Hero illustration labels became DOM copy — FIXED.** On the anthotype upload the
  model tagged *every* block `part: page`, so the diagram's own captions
  ("Generate", "Time", "Refine and grow meaning", a device-screen logo, the
  "1/2/3 Image/Sunlight/Plant Pigment" legend) were emitted as DOM paragraphs in
  the hero copy column. `_drop_artwork_labels` drops a *short* `other`/`brand` line
  that overlaps the headline/subhead band or sits clear of the lede's right edge;
  the exclusion rects still use all blocks, so the labels are still blanked out of
  the art. Drops 12 labels on anthotype, **0** on Montiva.
- **Footer and nav composition — FIXED.** A run of nav links at the page bottom
  tagged `contact` by the model is lifted into the footer (`_lift_bottom_nav`), and
  the footer renders as a real bar — brand / nav row / meta — instead of a wall of
  equal-weight links (`_footer_html`).

**Also worth knowing:** every job under `studio/data/jobs/*` was built *before*
the Sep 30 composition fixes, so those on-disk pages are not what the current
code produces. Replay a job's cached extraction with
`STUDIO_FAKE_BLOCKS=<job>/raw-blocks.json python doctor.py run <job>/ref.png`
(no vision call) to see current output.

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

## This session's changes (the gate + CI)

The verification loop is now one command, and CI runs it.

- **`doctor gate`** — runs `env → polarity → fixtures → regress` in order and
  fails if any stage fails. `regress` is `qa/verify.sh`, so both measures are
  covered: the artwork's pixel fidelity (A/B/C) and the website's structure (the
  fixtures). `--quick` runs `polarity` alone — no potrace, node, Chrome or model.
- **`.github/workflows/gate.yml`** — `gate --quick` on every push and PR (fast,
  no pipeline); the full `gate` on `main` and nightly. `macos-latest` because
  `verify.sh` needs Chrome + `sips`.
- **A pre-commit hook** — `.githooks/pre-commit` runs `gate --quick` on every
  commit; `bootstrap.sh` activates it with `git config core.hooksPath .githooks`.
  The cheap guard can no longer be forgotten (skip with `--no-verify`).
- **`doctor critique <job-id | design.png>`** — the design review that found the
  ghosting and the composition defects is now a repeatable tool. It screenshots
  the built page, sends it and the mockup to the vision model, and prints a
  ranked list of composition/readability defects (typeface differences are
  explicitly out of scope). `--page` reviews an existing page, `--out` saves the
  raw report. It is a *review* tool, not a gate stage: it needs a live model and
  is subjective. First run (montiva fixture) flagged a pale hero backdrop, an
  orphaned phone line, weak badge-row separation and a 3+1 card wrap — real
  defects, not yet fixed.
- **Python deps pinned** — `pipeline/requirements.txt` (numpy/pillow/scipy/
  scikit-image) and `studio/backend/requirements.txt`. The A/B/C scores are a
  numeric gate computed through those libraries, so an unpinned `pip install`
  could move a score with no code change. `bootstrap.sh` installs from the pinned
  file.
- **`verify.sh` resolves node itself.** It called bare `node`, which a
  non-interactive shell (an agent, launchd, CI) does not have on PATH — nvm keeps
  it out — so `doctor gate`'s `regress` stage failed with zero scores. It now
  prepends `_env.NODE_DIR`, like `build.sh`. `doctor env`'s potrace check and the
  studio's `node_env()` also now share `procs.find_potrace()`, so Homebrew being
  off the base PATH no longer reports a false failure.
- **`verify.sh` resolves Chrome / sips / sRGB through `_env`** too, not just
  node, so a Chromium install or a non-standard colour profile needs no edit.
  Scores unchanged.
- **`doctor fixtures` now guards the artwork too.** It asserted structure only,
  so a tracer regression on a `page` build (half-resolution bands, baked-in
  text) would not fail it. Each fixture carries a `score_max` — the art-region
  mean with headroom (light/antho 3.0, montiva 5.0) — and the fixture fails when
  the traced render exceeds it. Negative-tested: forcing `light` to 0.1 yields
  `art region mean 2.39 >= max 0.1` and a non-zero exit.
- **`regress` checks the docs too.** After `qa/verify.sh` passes it parses the
  measured means and fails if `docs/STATE.json`'s `scores`/`targets` no longer
  match the designs and the run. STATE.json had drifted silently (a stale score
  string, resolved leads still listed as priorities); now the gate keeps it
  honest. Negative-tested both ways (score drift and target drift).

No pipeline, tracer or page code changed; the scores are unchanged
(`qa/verify.sh` → 2.71 / 2.76 / 2.99 PASS).

## This session's changes (the review loop, and its first fixes)

The studio's design review — which had found every composition defect by hand —
is now a repeatable tool, and its first run found four defects on the montiva
fixture. All four are fixed.

- **`doctor critique <job-id | design.png>`** screenshots the built page, sends
  it and the mockup to the vision model, and prints a ranked list of
  composition/readability defects (typeface differences explicitly excluded).
  `--page` reviews an existing page; `--out` saves the raw report; a PNG with no
  `--page` builds it first. A *review* tool, not a gate stage (live model,
  subjective).
- **Hero scrim retuned.** The old gradient held ~86% of the page ground out to
  two-thirds of the width, washing the traced art to mean **200** where the
  reference is **143**. A first fix over-corrected (a re-review called the lede
  unreadable); the final gradient holds the ground across the copy and releases
  the art by ~88%, with the hero copy capped at 520px and a smaller `h1`
  (36–60px). Art mean **194**, std 54 → 61: copy legible, art visible on the
  right.
- **A phone line folds into its button.** The model returns a two-line button's
  second line ("Call Now" / "(801) 810-4242") as its own block; it rendered as an
  orphan paragraph under the button row. `generate._cta_sublabels` folds it in as
  `.cta-sub`. (Gotcha: `decorate` grows the CTA to its plate, so the line is
  *inside* the button, not below it — a "directly below" test misses it.)
- **Card bands fill their last row.** `--cards` is set from `_balanced_cols`, so
  a four-card band is four across, not a stranded 3+1.
- **Two new `doctor polarity` guards** cover the logic: "card bands fill their
  last row" and "phone folds into its button".

The fixture score is the **traced SVG rendered alone** for a `page` layout
(`verify._render_art`), so none of this moved it — montiva stayed **4.19**. Page
CSS and the tracer are scored separately, by design. `doctor gate` → **PASS 4/4**.

## Environment

`brew install potrace` — the only required external binary. `bootstrap.sh` then
creates the Python venv (numpy/pillow/scipy/scikit-image) and installs each
site's `node_modules`. `qa/_env.py` finds python/node/Chrome by probing, with no
hardcoded paths anywhere in the repo.
