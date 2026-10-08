# CHECKPOINT

> **New agent? Read `AGENTS.md` first** — it is the entry point (setup, hard
> rules, landmines, and what not to re-litigate). This file is the current-state
> record; come here for depth, not orientation.

State at the end of the session that packaged this repo. Read this first, then
`README.md` for how the pipeline works and `docs/HANDOFF.md` for how it got here.

## What this is

Turn a flat design PNG into a **real, code-native website** — a responsive,
semantic page with DOM text and CSS, whose decorative hero backdrop is either
traced SVG artwork (flat designs with no more resolution than the working stage)
or a fixed-resolution image export (a photo hero, or an upload carrying more
detail than the stage). The reference PNG is input to the pipeline, not a copy of
the page.

**The north star changed.** This used to be a pixel-parity project: whole-page
mean-abs-pixel-difference against the reference, with a large text-measurement
layer tuned to make DOM glyphs land on the reference's pixels. That target is
unwinnable — its largest residual was **font substitution** (the reference's
typeface is not the vendored Inter), which no sizing or tuning removes. The
metric is now split:

- **the artwork** is scored on pixels, over the **art region** only (the page-copy
  rects masked out) — the tracer's job — and its tail is reported as `art_p95`,
  over the pixels the eye reads as artwork, because the mean is dominated by
  whatever is flat and large;
- **the shipped hero** is scored separately when the page ships a raster rather
  than the traced SVG: its own mean against the region the page actually shows
  (the hero band, or a split illustration's own figure) covers what a visitor
  sees;
- **the website** is scored on **structure** — landmarks, sections, one `h1`,
  resolving links, flow layout, reflow — which is what makes it a website.

**The no-raster rule was relaxed, deliberately.** A photograph cannot be
represented as flat vector regions at a sane payload: the tracer plateaus around
3.5 mean on a photo hero while every knob is flat, and coherent segmentation
reaches 0.89 only at ~214k regions / ~60 MB of SVG. A second, independent reason
to ship the raster: the traced SVG is bounded by the 1024 px stage and the hero is
full-bleed, so on any desktop wider than 1024 it is magnified (1.37× at 1400 px,
1.88× at 1920 px) while the upload may carry much more detail. So the page ships a
WebP when **either** the artwork is continuous-tone **or** the upload carries
≥1.2× the stage's linear resolution. It is built from the original upload (not the
1024×768 working reference) and from the tracer's **prepared** image — the mockup
copy the page replaces is inpainted out of it (otherwise the reference's nav bar
and headline ghost behind the DOM copy), while an illustration's own labels are
kept. The SVG art master is produced for every design regardless.

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
- `doctor polarity` → all checks pass (ink/box/two-tone/scope, the structure
  checks, the hero-representation guards, the two hero-band guards, and the
  "loose header box cannot crop the hero art" guard).
- `doctor fixtures` → **light / montiva / antho / dashboard all PASS**.  The
  first three pin `hero_kind=photographic`, a shipped-hero-art bound (means
  1.57 / 1.89 / 1.57) and an `art_p95_max` bound (22.67 / 35.67 / 22.67
  measured); the dashboard fixture pins the integrated scene prototype (layout,
  3840 px budget, all 33 labels in the shipped scene, worst label 15.0/43.9
  mean/p95, shipped hero 0.82).
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
  the artwork as the hero backdrop (`<!--ART-->` placeholder). The backdrop is
  the traced SVG for flat art uploaded at the stage's own width, or an inlined
  fixed-resolution WebP otherwise — a photo hero, or a wider-than-stage upload
  (chosen by `studio/backend/app/heroart.py`).
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

## The four things future work must not break

1. **potrace fills the BLACK (bit-0) region.** Pass `(~mask)*255`. Get it wrong
   and every band becomes an opaque plate while the page still *looks* fine.
   `pipeline/qa/mkart.py::_potrace`.
2. **Trace the CUMULATIVE mask `{lum >= e_i}`, painted darkest-first** — not
   disjoint bands. Mathematically identical, but potrace gets one solid nested
   region per band instead of 1px slivers: ~0.8 better mean, ~half the file size.
3. **A raster hero comes from the tracer's prepared image, at the upload's own
   resolution.** Cropping the raw reference ghosts the mockup's own text behind
   the DOM copy; cropping the normalised 1024×768 reference inherits the ingest
   downscale. `app/heroart.py::native_reference` + `mkart --prepared-out`, guarded
   by `doctor polarity` and each fixture's `hero_kind` / `hero_max`.
4. **The hero band describes the hero, not the frame.** It starts below the
   mockup's own header and is trimmed to the hero box's aspect (`1.75`), so
   `cover` does not magnify it — a hero-only page otherwise ran the band to the
   bottom of the stage (letterbox + nav bar + empty strip) at aspect 1.33, which
   `cover` magnified 1.37×/1.88× and cropped a quarter away.
   `generate.hero_band`, guarded by two `doctor polarity` checks.

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

That fix gave `text_rects` **every** text block.  It stopped the ghosting, but it
also blanked the illustration's own labels (resolved in the latest session: the
exclusion is now scoped to the copy the page actually replaces).  The ghosting
rule still holds for replaced copy: a text block that becomes DOM must be
blanked, and the tracer repaints it from the surrounding pixels, so there is no
hard hole.

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
- **Artwork-internal labels are blanked — RESOLVED (see the illustration-labels
  section below).** Blanking every text block removed the illustration's own
  captions (the anthotype step labels).  Labels are now preserved in the artwork,
  and a flat hero whose illustration has its own labels gets its own region
  beside the copy, so a preserved label cannot sit behind DOM text.
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
  the whole built page (captured tall, trimmed to the content, so lower sections
  are reviewed too), sends it and the mockup to the vision model, and prints a
  ranked list of composition/readability defects (typeface differences and
  missing raster assets are explicitly out of scope). `--page` reviews an
  existing page, `--out` saves the raw report. A single verdict is noisy, so
  `--votes N` keeps only the complaints that recur across runs and `--baseline`
  tags each defect NEW/carried (with `--fail-on-new` to fail on a new
  high-severity one); defects carry a model-assigned stable `key` so they match
  across runs and builds. It is a *review* tool, not a gate stage: it needs a
  live model and is subjective. On the montiva fixture it flagged a pale hero
  backdrop, an orphaned phone line, weak badge-row separation and a 3+1 card
  wrap — all since fixed.
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

## This session's changes (the tracer's chroma blindness)

Driven by the user's report that the **website** was good but **the imagery was not**
on some uploads. Reviewed three real outputs side-by-side with the vision model
(mockup vs traced SVG): the line-art design read "largely faithful… usable", while
the two photographic ones read "**unusable** as a hero backdrop" and "**badly
degraded**… not usable without a full retrace" — posterisation, lost colour, lost
detail. The metric had said 1.43 / 2.39 / 4.21 for those.

**Root cause: the banding is chroma-blind.** `mkart` cuts bands on luminance only and
paints each with one median RGB, so a band spanning blue sky, green foliage and
brown wood gets their average. That single decision is the lost colour *and* the
posterisation. Isolating the banding model from everything else (no potrace, no
blanking, no SVG) put its cost at 3.3 mean / 16.3 p95 on a photographic upload, of
which a chroma split recovers ~48%.

- **`chroma_cells` / `chroma_gate`** — a band whose chroma spread exceeds the gate is
  split along the two opponent chroma axes. Splitting *per band* (not one global
  partition) keeps every emitted mask a solid nested region, so the cumulative-mask
  trick and potrace's despeckling both survive. The gate keeps flat art on one colour
  per band.
- **`chroma_smooth`** — blur the chroma field before thresholding it. The cell
  boundaries become the traced contours, so raw per-pixel thresholding gives a ragged
  edge: unsmoothed the split took montiva from 3.8 MB to **16.9 MB**. Smoothing is
  what makes it affordable (**5.5 MB**).
- **`turdsize` 2 → 12** for the studio. 2 is A/B/C's value, tuned for flat art that
  wants every speck; on photographs it is pure waste (−28% to −42% payload, unchanged
  score). 30 is too far — it eats fine line art (1.72 → 1.91).

Measured end to end, traced + rendered + scored, against what the studio shipped:

| design | art mean | p95 | SVG |
|---|---|---|---|
| montiva | 4.21 → **3.44** | 17.7 → **12.7** | 3.8 → 5.5 MB |
| anthotype | 2.40 → **2.04** | 12.7 → **8.7** | 6.2 → 6.0 MB |
| anthosting | 1.72 → **1.65** | 5.0 → **4.7** | 6.0 → 4.5 MB |

Two of the three are *smaller and better* than what shipped. The **p95** is the
number that matters — that is the blotchiness the eye reads as posterisation, and the
mean alone hides it. A visual A/B on the rebuilt page confirms it: the hero plant is
green again instead of grey-blue and the mountains hold their blue.

**`blank_seam`** — `art_score` masks the text rects out, so it cannot see a fill that
went wrong. `verify.blank_seams` measures the absolute tonal step (0–255) the trace
leaves at the edge of every rect it had to fill, reported per job, warned above 12,
and pinned per fixture with `seam_max` (negative-tested). Numpy-only, because the
studio venv runs the scorer and pins no scipy.

**Two corrections to beliefs formed earlier in this session**, both now in
`docs/AGENT-NOTES.md` so they are not re-adopted:

- A blanked button rect is **not** a visible artefact. The standalone SVG shows a
  white plate where each CTA was; the built page draws the button over it. Judging
  blanking on the bare SVG produces a false defect — this caused a rejected fix.
- `whole_score` ≈ 14× `art_score` is **expected**, not a blind metric: the text rects
  are ~28% of the stage and hold crisp type in the reference and nothing in the trace.

**Also measured and rejected:** harmonic (diffusion) inpainting of the text rects.
Intuitively right — the blanked rects are 4×–35× flatter than the art around them —
and measurably worse (montiva 4.19 → 4.54, 3.8 → 9.3 MB), because the tracer has to
band whatever the fill produces and a gradient across a big rect means every band
edge crosses it. `_hole_fill` is kept but **not** the default, with the measurement
recorded.

`doctor gate` → **PASS 4/4**; `qa/verify.sh` → 2.71 / 2.76 / 2.99 PASS; all three
posters regenerate **byte-identically** (chroma is studio-only and off by default).

## This session's changes (hero framing + using the upload's resolution)

Driven by the user's report that a real upload's backdrop "needs work to match
the original image" and "the quality needs to improve". The dark dashboard
upload (`57e872a21037`, 1586×992) had shipped as a **traced SVG** (colour score
113, just under the 150 cut) inside a band that magnified it.

- **The hero band was the whole frame.** `hero_band` returns the slice from just
  below the mockup's header to where the next section starts. A hero-only page
  has no section below it, so the second half of that never fired and the band
  ran to the bottom of the stage — 128 px of ingest letterbox, the mockup's own
  nav bar, and an empty strip — at aspect **1.33** when the hero box's aspect is
  **1.75**. `cover` then magnified the art **1.37× at 1400 px and 1.88× at
  1920 px** and cropped a quarter of it away; the built page showed the artwork
  oversized, re-centred, with a **second nav bar** ghosted inside the hero. Now
  the band starts below the mockup's header and is trimmed to
  `HERO_BAND_ASPECT` (1.75), symmetrically about the hero copy — only *shrinking*,
  because reaching the target from below would pull in the next section.
  Yours: `[0, 768]` → `[112, 697]`. (A loose header box is capped at 12 px so it
  cannot crop hero art.)
- **The upload's resolution was thrown away.** The traced SVG is bounded by the
  1024 px stage, so a full-bleed hero on a 1400 px desktop is magnified 1.37× and
  on 1920 px 1.88× — structurally soft. The upload carried 1.55× more linear
  detail than the tracer used. `heroart.wants_raster` now has a **second,
  independent reason** to ship the raster: `native_factor` (== 1/stage_scale) ≥
  `MIN_NATIVE_GAIN` (1.2). Flat art uploaded at the stage's own width keeps the
  traced SVG; a wider flat upload ships the raster too.
- **What was NOT the problem, and the measurement that says so.** The traced
  SVG's artwork-region p95 for this design was **17.3** — inside the range of the
  flat posters considered fine (15.3–26.0). So the tracer's banding was not the
  bottleneck; resolution and framing were. This is why no tracer knob was
  retuned.
- **The metric that would have caught it.** `art_score` read **1.37** because the
  mean is dominated by the flat near-black ground, while the artwork the eye
  reads (7% of the region) was **6.84** mean / **23.3** p95 — against 4.7 p95 for
  a raster of the same hero. `verify.assess` now reports `art_p95` alongside the
  mean and each fixture pins `art_p95_max`. `hero_fidelity` likewise gained a
  p95.
- **A dead artifact path.** `artifacts["svg"]` pointed at `<jid>/<jid>.svg`,
  which the tracer never wrote to the job dir (it lives in `workspace/pipeline/`
  and inside the zip), so any route serving it 404'd. `_package` now copies it
  beside the page.

Guarded by `doctor polarity` (band aspect, header floor, the resolution arm, the
loose-header cap) and the fixture bounds; both negative-tested. `doctor gate` →
**PASS 4/4**; `qa/verify.sh` → 2.71 / 2.76 / 2.99 PASS.

## This session's changes (the review loop, and its first fixes)

The studio's design review — which had found every composition defect by hand —
is now a repeatable tool, and its first run found four defects on the montiva
fixture. All four are fixed.

- **`doctor critique <job-id | design.png>`** screenshots the whole built page,
  sends it and the mockup to the vision model, and prints a ranked list of
  composition/readability defects (typeface differences and missing raster
  assets explicitly excluded). `--page` reviews an existing page; `--out` saves
  the raw report; a PNG with no `--page` builds it first. A single verdict is
  noisy, so `--votes N` keeps only the complaints that recur across runs and
  `--baseline` tags each defect NEW/carried (`--fail-on-new` fails on a new
  high-severity one); defects carry a model-assigned stable `key` so they match
  across runs and builds. A *review* tool, not a gate stage (live model,
  subjective).
- **Hero scrim retuned.** The old gradient held ~86% of the page ground out to
  two-thirds of the width, washing the traced art to mean **200** where the
  reference is **143**. A first fix over-corrected (a re-review called the lede
  unreadable); the final gradient holds the ground across the copy and releases
  the art by ~88%, with the hero copy capped at 520px and a smaller `h1`
  (36–60px). Art mean **194**, std 54 → 61: copy legible, art visible on the
  right. **Later made radial** (`ellipse 66% 80% at 0% 50%`): the full-height
  linear band also dimmed the artwork *above and below* the copy, so a hero whose
  art surrounds the text (a real upload, "AntHosting") lost its top-left and
  bottom-left nodes — a stable `critique --votes` finding, 3/3 runs.
- **A two-line hero lockup is one `h1`, not two.** A design drawn as
  "AntHosting" / "Coming soon" came back from the model as **two `headline`
  blocks** and shipped **two `h1`s** — the exact thing the north star's "one
  `h1`" forbids. `structure_issues` caught it, but only as a warning, so the page
  shipped anyway. The first headline is now the `h1`; a further headline block
  becomes the secondary accent line (`.subhead.accent`), which is also the
  colour the mockup uses. This is why the pipeline *reports* a structure defect:
  act on the report.
- **A phone line folds into its button.** The model returns a two-line button's
  second line ("Call Now" / "(801) 810-4242") as its own block; it rendered as an
  orphan paragraph under the button row. `generate._cta_sublabels` folds it in as
  `.cta-sub`. (Gotcha: `decorate` grows the CTA to its plate, so the line is
  *inside* the button, not below it — a "directly below" test misses it.)
- **Card bands fill their last row.** `--cards` is set from `_balanced_cols`, so
  a four-card band is four across, not a stranded 3+1.
- **Contact panel.** The model returns a value's caption ("Call or Text",
  "Email Us") as its own block, so grouping by x-overlap merged captions into
  the wrong column and could promote the email address to a heading.
  `_value_label_pairs` pairs a value (phone / email / button) with the caption
  under it, and the panel is a titled card of value/label items.
- **Footer.** The repeated nav links are role `other` (the model tags header
  links `cta`), so they fell into the meta row and the footer read as one
  jumbled wrap. `_footer_nav_links` finds the packed run of short links; the
  brand's tagline stays with the brand; the footer is brand+nav on top with the
  legal/meta line full width below.
- **Five new `doctor polarity` guards** total cover the logic: "card bands fill
  their last row", "phone folds into its button", "contact panel pairs value +
  label", "footer nav links detected", and "two headline blocks -> one h1".

The fixture score is the **traced SVG rendered alone** for a `page` layout
(`verify._render_art`), so none of this moved it — montiva stayed **4.19**. Page
CSS and the tracer are scored separately, by design. `doctor gate` → **PASS 4/4**.

## This session's changes (illustration labels, the figure region, resolution honesty)

Driven by a review of the saved dashboard job (`d9d0855d6cf5`): Studio produced a
good page but had **deliberately erased the illustration's own labels** (33
`part: artwork` blocks), then **cropped and dimmed** what survived with
`object-fit: cover` + the copy scrim, and its checks could not see any of it —
`hero_fidelity` resized the asset to the reference band (ignoring the crop and
the overlays) and `assess` overwrote the seam advisory with the structure issues.

- **Only the copy the page replaces is excluded.** `generate.write_all` builds
  `text`/`blank` from `page_blocks` minus the hero labels `_drop_artwork_labels`
  keeps out of the DOM.  An illustration's labels stay in the traced master and
  in the tracer's prepared image.  Guarded by the rewritten `doctor polarity`
  check.
- **A flat illustration gets its own region** (first milestone; the scene
  prototype below supersedes it as the automatic composition -- `split` remains
  an available mode).  `generate.hero_figure` detects a
  hero whose artwork labels form a column clear of the copy; `build_content`
  records `hero_layout` / `hero_figure`; `gen-page.mjs` adds `.hero-split` and
  narrows the SVG viewBox to the figure; the CSS shows it whole (no `cover`, no
  scrim), stacking below 880 px.  `runner._hero_art` declines the split for
  continuous-tone artwork (a photograph stays full-bleed) and crops the raster
  export to the figure (`heroart.export_from_prepared(figure=…)`).
- **Resolution is sized and reported honestly.** Export target 2048 → 2880 → 3840
  (`EXPORT_TARGET_WIDTH`, 2× a 1920 px desktop after the artwork-quality
  experiment; never upscaled past the source).
  `heroart.resolution_gap` records `hero_needed` / `hero_scale` per job and warns
  when the upload is short.  The split figure is **capped at 560 CSS px** by the
  page CSS (`HERO_FIGURE_MAX_CSS`), because without the cap the stacked layout
  let it grow to 816 px at an 880 px viewport while the warning still assumed
  560 — a reviewer caught the understated 1.43×.  `doctor polarity` now fails if
  the emitted CSS and `heroart.HERO_CSS_SPLIT` drift, so the budget is the true
  worst case.
- **The checks now see it.** `verify.hero_fidelity` scores the raster against the
  region the page actually shows (figure or band); `verify.label_fidelity`
  reports the worst artwork label as **mean and p95** (`hero_label_max` /
  `hero_label_p95`, warned above 28/255 and 64/255) — the p95 is what catches a
  sparse caption whose erased strokes leave the rectangle mean low (a synthetic
  thin-stroke label reads 20/255 mean but 200/255 p95); the seam advisory
  survives the structure merge; the job carries an `assets` inventory that is
  honest about what ships (under a split hero, artwork outside the figure is
  `artwork-master`, not `hero-artwork`); the critique prompt treats a
  missing/smeared illustration label as a defect instead of exempting "missing
  fine detail".
- **Fixtures:** **4/4 PASS**, now including a permanent `dashboard` fixture
  (`studio/fixtures/dashboard-ref.png` = the original 1586×992 upload, plus a
  cached extraction re-merged with its section assignments, which the raw job
  cache omitted).  It pins `hero_layout='split'`, the 1120 px budget, all 33
  labels in the shipped figure, and the worst label mean/p95 (17.3 / 49.1
  measured).  The full-bleed three: art means 2.12 / 3.58 / 2.12
  (light/montiva/antho) — 0.09–0.14 above the previous run, because the label
  pixels are no longer masked out of the score.  Bounds unchanged (3.0/4.0;
  seams 0/3/0).
- **A/B/C regress:** untouched — the tracer and poster shell were not changed.

Validation beyond the cached replay: a **fresh live upload** through the studio
path (real vision call, no cache) finished `split` with a 782×906 WebP, all 33
artwork blocks `hero-illustration`, worst label 8.0 mean / 23.4 p95, no
structure issues.  A viewport matrix on the built page — 390, 834, 880, 881,
1440, 1920 px — shows `scrollWidth == innerWidth` at every width, the figure
whole (no `cover`/letterboxing) and never wider than the 560 px cap (350 / 560 /
560 / 381 / 498 / 498 px in that order).

**Known limit (unchanged by this work):** the figure's bounds come from the
model's labels, so a drawing element that extends past its own labels — the
dashboard's leftmost rack — is still clipped by ~50 stage px at the panel edge
(visibly checked against the reference).  Recovering that needs pixel
segmentation; the plan keeps it for the models benchmark, and every labelled
element is preserved.

## This session's changes (the reference-led scene prototype)

The next milestone was a *convincing reconstruction* of the dashboard hero — not
more fixes to the split template: the complete native-resolution copy-removed
scene (racks, floor, lighting, the UI illustration) integrated across the hero,
with the reference's hierarchy rebuilt as real HTML.

- **A new `scene` composition** (`generate.build_page_css`, `gen-page.mjs`): the
  whole copy-removed band IS the hero — an in-flow image at its own aspect, a
  grid sibling of the copy in the same cell (`display: grid`, both children in
  `1 / 1`), so nothing is cropped, there is no `cover`, no boxed column and no
  scrim.  A flat illustration hero is composed this way automatically; the
  previous `split` mode remains available, and a continuous-tone hero (a
  photograph) stays `full`.
- **The reference's own interface elements are gone from the artwork.**  The
  page's eyebrow/headline/paragraph/buttons were already in the blank/inpaint
  rects; a new benefit-row blank removes the reference's benefit icons wholesale
  (they would duplicate the live row).  Illustration labels are retained.
- **The benefit row moved inside the hero.**  The model tags it `features`; in
  scene mode `_benefit_candidates` lifts the short value/sub-label lines that sit
  under the copy and inside the band into the hero (at least two sharing a row),
  dropping the section if it empties.  It renders as `.hero-benefits` (dot, bold
  value, muted sub-label) — one line at desktop, wrapping on phones.
- **Only "AntSeed" is accented.**  The two-tone headline's run *text* boundary is
  unreliable on a wrapped block (`sample_runs` splits inside "hosting"), so the
  accent is recovered from its share of the ink (`_tone_fraction`, classified by
  chroma) and turned back into trailing words with the real Inter advances
  (`_accent_html`).  `doctor polarity` guards the wrapped case.
- **The prototype ships lossless.**  `heroart.export_from_prepared(lossless=True)`
  writes a lossless WebP for the scene, so the composition is judged without
  added compression: 1586×907, 782 KB, shipped scene mean **0.82** against the
  reference band (worst label 15.0 mean / 43.9 p95).  The source-resolution
  caveat stays explicit: 1586 px against the 3840 px a 1920 CSS @2x hero wants
  (`hero_scale` 1.82), reported per job.
- **The flat/photo verdict precedes the transformation.**  `runner.__call__`
  measures `is_photographic` from the normalised upload *before* `write_all` and
  passes `scene_ok`; the scene's content edits (benefit lift + blank) only run
  for flat artwork.  The first cut ran them unconditionally, and the gate caught
  it: photographic montiva's benefit row was lifted and blanked out of its
  traced master (art mean 3.58 → 4.27, over its bound).  With `scene_ok=False`
  montiva is back to 3.58.
- **A live extraction is the acceptance test, not only the fixture.**  The fresh
  live run returned all six benefit lines as `other` (the fixture had values
  `other` + sub-labels `tagline`); that broke the pairing and let
  `_drop_artwork_labels` swallow the row's right-hand items.  The pairer is now
  role-agnostic and runs before the label filter, protecting its pairs; the live
  job's own cache replay (`e47860139c4d`) renders all three benefits.
- **Acceptance:** the side-by-side at 1024×768 (the reference's own aspect) at
  `compare-1024.png` matches the hierarchy — wider headline with only "AntSeed"
  accented, lighter supporting copy, buttons, and the benefit row inside the
  hero — over the complete scene; 834/880 stack the scene above the copy (the
  copy is nearly as tall as the scene below 900 px); 390 has no horizontal
  overflow; 1440 keeps the copy on the scene's dark side at the reference's own
  left proportion.  The fixed prototype built from the live extraction's own
  cache is job `e47860139c4d` (`studio/data/jobs/e47860139c4d/index.html`);
  opened in Safari for the human visual check.
- **Known limits:** inpaint quality (a faint smudge can remain where the
  reference's own copy/buttons were; the live copy covers most) and the 1586 px
  source — a larger artwork upload is still needed for native Retina sharpness.
  The scene shows the whole band, so the unlabelled left rack is no longer
  clipped.

`doctor gate --no-env` with the final tree: polarity all pass, fixtures **4/4**
(light 2.12 / montiva 3.58 / antho 2.12 / dashboard scene 0.82), regress
**2.71 / 2.76 / 2.99**, and the STATE.json consistency check passes.  A fresh
live upload through the studio path (real vision call) finished `scene` too.

## This session's changes (artwork-quality experiment — the better hero)

The planning agent judged the integrated scene composition right but the
backdrop damaged (pill/dot remnants, button ghosts, fill streaks) and short of
Retina.  One controlled experiment against the original upload answered it; the
cleanup was deliberately held out of Studio until the comparison succeeded; on
that verdict it is now integrated (below).

- **Component masks.** The old masks were glyph-tight; the pill (dot included),
  both button plates and the benefit row (icons included) are now measured from
  the source pixels and masked whole.  That alone removes the remnants; the copy
  blocks are masked as full boxes so no glyph ghosts remain.
- **LaMa masked inpainting wins the fill.** Nearest/Telea/diffusion smear or
  replicate the element borders; LaMa continues the floor striping and glow
  through the repaired boxes.  Outside the masks every candidate is
  byte-identical to the source (max diff 0.0).
- **Retina:** ×2 Lanczos and ×2 Real-ESRGAN (x2plus) both look dramatically
  crisper than the 1586 native asset at 2×; Real-ESRGAN is slightly crunchier
  and not clearly better — and neither is genuine detail.  A larger original
  artwork remains the real fix.
- **Artifacts:** `studio/data/experiments/artwork-quality/` — `before-after.png`
  (the visible damage vs the winner), `masks.png`, `hero-lama.html`,
  `hero-lama-x2-lanczos.html`, `hero-lama-x2-resr.html`, candidate WebPs and
  `experiment.py` (masks → fills → LaMa → upscale → pages).
- **Integrated (approved trial):** the winning cleanup is wired into the scene
  path — optional external LaMa over upload-driven complete-element masks
  (`app/cleanup.py`, `studio/setup-cleanup.sh`; via `STUDIO_CLEANUP_PYTHON` or
  `studio/.cleanup-venv`), original pixels kept outside the masks, and an
  explicit `hero_cleanup="fallback"` + warning when the cleaner is absent.  The
  scene rendition is Lanczos ×2 (display sharpness only) and lossy
  `SCENE_QUALITY=90`; the resolution warning uses `source_w` (the upload's own
  width), so the 2.42× shortfall is still reported honestly.  Export target
  2880 → **3840** and `MAX_NATIVE_SCALE` 3 → **4** for 1920 CSS @2× support.
  Real-ESRGAN deferred: its comparison had a channel-order bug (basicsr takes
  and returns BGR) — corrected, it is comparable to Lanczos q90 and no better.
  Dashboard fixture through both paths: LaMa hero **1.39**, fallback **1.27**,
  labels 15.4/42.4, both PASS.
- **Review fixes (2026-10-04):** the first integrated run still ghosted the
  eyebrow/buttons because component routing used "blank minus text" (on a dark
  design `blank` contains every text rect, so only the benefit row was routed);
  components are now named (CTA plates, the eyebrow's grown rect, the benefit
  row pad-only) and header/nav rects are dropped.  Growth is **seed-connected**
  (a rack edge inside the search window is no longer swallowed; the guard tests
  a decoy inside the window).  `setup-cleanup.sh` fetches the model to
  `torch.hub.get_dir()`, which is `~/.cache/torch` on macOS -- not the
  `~/Library/Caches/torch` it previously assumed.  Fresh verification: the
  rebuilt fixture ships hero **1.30**; a fresh live upload
  (`f177dea4e2d8`, 12 masks after the header-band filter) ships 3172×1814 q90
  at 206 KB, fidelity **1.30**, all 33 labels `hero-scene`; the whole-hero and
  left-zone before/after/target comparisons live in the experiment dir and match
  the approved prototype.

## This session's changes (the Google enhancement: opt-in, audited, preview-before-accepting)

The artwork-quality experiment's follow-up: a generative high-resolution
rendition is available as an **opt-in, preview-before-accepting** step, never an
automatic one.

- **Label audit.** Every one of the 33 artwork labels was re-checked against the
  cleaned source (local macOS Vision OCR + 2× visual sheets,
  `studio/data/experiments/artwork-quality/google-probe/`).
  `gemini-3-pro-image` 4K changed content — `28ms→26ms`, `36ms→26ms`,
  `Staging→Slaping`, `End-to-end encrypted→Eod-to-end-encrypted` — while
  `gemini-3.1-flash-image` 4K preserved all four in that run.  The earlier
  "labels survive" claim was wrong for Pro and is corrected in the probe README.
- **The metric caveat.** The enhanced band is aligned (best diff at 0–1 px
  shift), but its `hero_fidelity` reads **4.8** against the base's **1.30**
  because the metric measures **pixel drift** from the reference, not sharpness:
  a resample of the source drifts least; a generative re-render drifts more
  while being sharper.  The 4.8 is a real measurement of increased drift, not an
  incomparable number; acceptance logs that note and the per-label audit is the
  verdict on labels.
- **Integration.** `app/enhance.py` (Google client + cache), runner
  `_enhance_scene` / `accept_enhance`, `GET /api/jobs/<id>/enhance`,
  `POST /api/jobs/<id>/enhance/accept` and the result-view card with *Accept
  enhanced artwork*.  `STUDIO_ART_ENHANCE` selects `google-flash` (default
  mode), `google-pro` or `auto`; `GEMINI_API_KEY` comes from the environment or
  `studio/backend/.env`.  Results are cached by
  `sha256(cleaned PNG)[:24] + model + size` under `studio/data/enhance-cache/`,
  so retries and acceptance never pay twice.  `_verify` now scores the file the
  content actually names (`_hero_image_path`), and `_package` ships the shipped
  asset plus the pending candidate as provenance.
- **Provenance.** The accepted asset keeps `hero_image.source_w` = the
  **upload's** width (the resolution warning is unchanged) and adds
  `hero_image.enhance` {provider, mode, model, size, generated, input_sha256,
  image_tokens} with `rendition="enhance"`.  LaMa/Lanczos stays the fallback;
  the runtime page is unchanged (asset inlined, zero network requests).
- **Hardening (review follow-up).** `doctor gate` / `fixtures` force
  `STUDIO_ART_ENHANCE_NETWORK=forbidden`, honored by `enhance.available()` and
  `candidate()`, so a configured environment cannot make the gate call the
  provider.  The whole candidate step (request, band crop, WebP encode, disk)
  is inside the optional handler — any failure keeps LaMa/Lanczos.  Acceptance
  is serialized (a runner lock) and failure-safe: the content, the job-dir
  files, the generated **workspace pages** (`<id>-full.html`, the Astro
  `index.astro`, the whole `dist/` tree) and every field the rebuild touches
  are snapshotted and rolled back on any failure, and
  `hero_enhance="accepted"` is set only after packaging succeeds.  It accepts
  only a **finished** job (`status == "done"`; a running/queued/failed job gets
  409).  Acceptance requires `reviewed=True` (the UI's checkbox gates the
  button; the API body carries it) and records
  `hero_enhance_audit={reviewed, method, at, candidate_sha256}` — the record
  cannot claim an audit that did not happen.
- **Verification.** `doctor polarity` gained "enhancement is opt-in, keyed,
  cached and killable" and "enhancement acceptance is failure-safe and
  serialized" (mocked: review gate, packaging-failure rollback, two concurrent
  acceptances → exactly one wins).  Headless end-to-end
  (`test_enhance_flow.py`, cache-seeded so no API call): candidate 3840×2193 /
  269 KB from a 5220×3264 Flash output; acceptance rebuilt the page (477 KB)
  shipping `<id>-hero-enhanced.webp` with the review audit recorded; the routes
  answered 200 / 409 / 404 as expected.  The gate was rerun with
  `STUDIO_ART_ENHANCE=google-flash` **configured**: the dashboard fixture
  recorded `hero_enhance="skipped"` / "network forbidden -- skipped" and
  shipped the LaMa hero 1.30, and the run passed **4/4** (fixtures 4/4, regress
  2.71 / 2.76 / 2.99).  It was rerun once more after the round-two acceptance
  fixes (finished-job gate, workspace-page rollback) with the same result and
  the extended self-test green: `unfinished rejected=True`,
  `rollback(incl. workspace pages)=True`, `accepted+audit=True`,
  `serialized=True`.

## This session's changes (full-layout raster heroes: cleanup + enhancement)

The opt-in enhancement covered only `scene` jobs, so a photographic (or
wider-than-stage) upload — `hero_layout="full"` — silently bypassed it even
with `STUDIO_ART_ENHANCE` set.  A real upload (`ddbc2872f5dd`, 1672×941,
colour score 214) exposed two gaps in sequence.

- **The tracer's prepared fill is not a clean enhancement input.**  It is
  text-removed but leaves rectangular patches, a residual CTA plate and the
  feature icons/smears.  `_clean_scene` became **`_clean_artwork`**, run for
  both `scene` and `full` raster layouts, with masks detected from the page's
  own structure: CTA plates (`button_rects`), the hero eyebrow, the config's
  copy rects, and the row drawn inside the band whose copy a later DOM section
  replaces (`_benefit_blank_rects(..., any_layout=True)` — short lines sharing
  a row, never a hard-coded cutoff).  The full-layout export now comes from the
  cleaned upload, so the shipped backdrop is clean even without enhancement;
  `hero_cleanup` is `lama`/`fallback` for both layouts.
- **The enhancement input is the cleaned upload** for both layouts
  (`_enhance_artwork`, band mapped through the ingest fit).  A missing cleaner
  **skips** the enhancement — the prepared fill is never sent to the model.
  The threshold and the layout decision were not touched (the upload is
  genuinely continuous-tone, 214 ≥ 150).
- **Framing + label guards (review follow-up).**  The enhancement input must
  cover the band's full extent: `enhance.cover_band` extends it with the
  design's background when the band runs past the upload (candidate 3840×2194,
  fallback 3840×2193 — previously clamped to 3840×1929); no padding leaves the
  scene input unchanged, so its cache keys stay valid.  Cleanup masks can never
  remove an artwork label: `cleanup.subtract_rects` subtracts every label rect
  from the masks (logged when it fires), `label_fidelity` scores a fully masked
  label instead of skipping it (a synthetic erased label still reads 190/190),
  and the combined exclusions are cleared of label rects (`verify._clear_rects`)
  so a *partially* masked label still shows its damage (synthetic erased glyph
  run: hidden 0/0 vs cleared 28.5/190).
- **Tests:** `doctor polarity` gained "enhancement maps the cleaned upload and
  stays optional" (incl. the padded-band framing), "the full-layout row blank
  is detected from its blocks" (rendering stays scene-only) and "cleanup masks
  never erase an artwork label from the check".  Fixture **`hosting`**
  (`studio/fixtures/hosting-ref.png` + `hosting-blocks.json`) pins the
  full-layout path: structure header/nav/hero/features, art 2.41 / p95 33.67,
  hero 3.26, layout `full`, 26 artwork blocks → `hero-artwork`; `STATE.json`
  records its bounds.
- **Verification:** the hosting fixture with the integrated cleanup ships
  `hero_cleanup=lama` (12 masks); the three feature-icon zones go 381/361/415
  green pixels → **0/0/0** with the floor/rack glow preserved, labels unchanged
  (18.0/67.7).  The cleanup's masks are recorded as `cleanup_removed` and
  excluded from the raster score (montiva 2.52 → **2.02**, bound 2.5), never
  from the seam check.  A build with enhancement configured and
  `STUDIO_ART_ENHANCE_NETWORK=forbidden` records `hero_enhance="skipped"` /
  "network forbidden -- skipped" (no spend).  `doctor gate` (5 fixtures)
  passes.

## This session's changes (the repair becomes a general stage)

The visually approved v2 repair of the hosting candidate is now a Studio stage,
not seven hard-coded patches.

- **`app/repair.py`** — design-agnostic, runs with every opted-in enhancement
  (scene + full): content detection from the **native pixels** (contrast against
  a local background; a component is kept only when the border around its bbox
  is flat — a UI panel, not artwork texture; shape-filtered so round blobs are
  dots, not content; merged) plus every extraction artwork box; restoration
  with the validated rules (exact source→output mapping, context-ring alignment
  with a verified-flat fallback, opaque cores + adaptive feathering, zero
  change outside, complete coverage); provenance (hashes, scale, regions,
  transforms, residuals) and a separate repair cache (`repair-v1.png/json`
  beside `output.png`).
- **Fail-safe** — the repair always runs when enabled (even with **empty
  extraction boxes**: the pixel detector is independent; real cached data is
  complete either way — 50/50 with the job's boxes, 40/40 with none).  x clamps
  by width and y by height (a portrait image no longer loses lower content).
  Component bboxes are taken at **full resolution** (`_exact_bbox`), so a
  one-pixel shift cannot move a stroke's edge into the flatness border and
  zero the detector (regression: 2 detected / 2 repaired at both shifts, with
  actual restored pixels asserted at 3×).  **Zero detections is uncertain, not
  verified absence** (no-op repair removed).  `detected = repaired + skipped`
  is enforced, and only a **complete** repair (`detected > 0`, nothing skipped)
  is a normally acceptable `pending` candidate; partial/failed/off candidates
  are **`diagnostic`** — the cleaned-native fallback ships, the preview is
  shown for inspection, and `accept_enhance` refuses them.
  `STUDIO_ART_REPAIR=off` disables the stage (diagnostic-only candidates).
- **The approved hosting v2** was attached as a new candidate with the user's
  approval bound to its SHA-256 (`hero_enhance_audit.candidate_sha256`),
  accepted through the normal safeguards; the original Flash band is preserved
  (`-hero-enhance-flash.webp`) and `ddbc2872f5dd` is untouched.
- **Tests** — `doctor polarity` gained "source-preserving repair restores
  content and never guesses" (synthetic panel: text+icon detected, textured half
  excluded, core diff 7.2, outside 0, feather 3220 px, noise refused) and "the
  enhancement repairs before deriving the band" (runner integration with a
  mocked model output).  The configured gate runs spend-free.

## Environment

`brew install potrace` — the only required external binary. `bootstrap.sh` then
creates the Python venv (numpy/pillow/scipy/scikit-image) and installs each
site's `node_modules`. `qa/_env.py` finds python/node/Chrome by probing, with no
hardcoded paths anywhere in the repo.
