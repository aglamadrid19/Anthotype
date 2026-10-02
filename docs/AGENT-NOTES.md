# Agent notes

Append-only scratchpad for things future agents discover: gotchas, ruled-out
approaches, non-obvious fixes, and corrections to older docs. Keep it short and
concrete. `AGENTS.md` points here.

**How to add a note.** Newest at the top. Use this shape:

```
## YYYY-MM-DD — <short title>
- **What:** <the fact, in one or two sentences>
- **Why / evidence:** <how you know — a command, a measurement, a file>
- **Action:** <what to do, or what NOT to do, next time>
```

Rules of thumb:

- One note per discovery; no essay.
- If it contradicts a doc, say which doc and why (and prefer the code / a fresh
  `qa/verify.sh` run over a historical figure).
- If it's big enough to change the current state, also update
  `docs/CHECKPOINT.md` and `docs/STATE.json` — this file is for the smaller,
  hard-won details that don't warrant a state change.

---

## Template (copy this)

```
## YYYY-MM-DD — <short title>
- **What:**
- **Why / evidence:**
- **Action:**
```

---

## Notes

## 2026-10-01 — Structure defects are already detected and shown; fix the CAUSE
- **What:** `structure_issues` (from `generate.structure_issues` and `app.structure.inspect`) is not an invisible warning: the fixture gate already **fails** on it (`_run_fixture`: `failed = _fixture_ok(...) + issues`), and the studio UI shows it (the result card switches to "Your site is built — review the notes", lists the issues, and the Headings stat reads `h1×2`). So do not "add" detection — the real work is fixing the *causes* for designs the fixtures do not cover, and adding a cheap `doctor polarity` guard so a cause cannot come back.
- **Why / evidence:** the AntHosting upload reported `2 <h1> elements (should be one)` and still showed it in the UI — the defect was visible, it just was not *fixed*. The cause was a two-line hero lockup arriving as two `headline` blocks (see the note above); the guard is "two headline blocks -> one h1".
- **Action:** when a novel upload trips a structure issue, reproduce it as a `doctor polarity` case (synthetic blocks, no model) and fix the generator. The fixtures only cover three designs; the polarity suite is where a new shape gets pinned.

## 2026-10-01 — A hero lockup is two `headline` blocks; that shipped two `h1`s
- **What:** a real upload ("AntHosting" / "Coming soon" drawn as a two-line lockup) came back from the model as **two `headline` blocks**, and `_hero_html` emitted an `<h1>` for each — a page with **two `h1`s**, which is exactly what the north star's "one `h1`" forbids. `structure_issues` / `app.structure` both caught it, but only as a job *warning*: the pipeline reported the defect and shipped it anyway. The fix emits the first headline as the `h1` and any further headline block as the secondary accent line (`.subhead.accent`, the accent colour the mockup uses).
- **Why / evidence:** `structure_issues: ['2 <h1> elements (should be one)']` on job `c77d28058a31`; the built `index.html` had `grep -o '<h1' | wc -l` = 2. A `doctor polarity` guard now drives `_hero_html` with two headline blocks and asserts one `h1` plus the accent subhead.
- **Gotcha (review noise, again):** the same defect showed up in the vision review as the *aesthetic* note "'Coming soon' renders white instead of the mockup's green" — the review saw the symptom, not the structure defect. Read the job's `structure_issues`, not just the review.
- **Gotcha (scrim shape):** the hero scrim was a full-height `linear-gradient(96deg, …)`, so it dimmed the artwork *directly above and below the copy column* too — a hero whose art surrounds the text lost its top-left and bottom-left nodes (a stable `critique --votes` finding on the AntHosting upload, 3/3 runs). A copy-local **radial** gradient fixes that, but the ellipse must be **tight and offset down** (`ellipse 48% 74% at 0% 52%`): the art's own mid-left node sits level with the copy, and a wider `66% 80% at 0% 50%` left it a ghost — measured node green **138** in the mockup, **24** through the first scrim, **69** with the tight one (copy column still dark: first stop 97% ground).

## 2026-10-01 — The review is noisy; `critique --votes` / `--baseline` make it a signal
- **What:** a single `doctor critique` verdict is unstable — the same hero art was "washed out" in one run and "too faint, and the copy unreadable" in the next. `--votes N` runs the review N times and keeps only complaints that recur in at least half of them. `--baseline report.json` tags each defect NEW or (carried), lists what got fixed, and `--fail-on-new` exits non-zero on a *new* high-severity defect.
- **Why / evidence:** the flip-flop cost a round. Matching on prose alone failed — the model called the same defect "barely visible ghosts" and "render faintly", which share almost no words — so the review now asks the model for a stable `key` slug per defect (`hero-art-nodes-faint`) and matches on that, with a stemmed-token fallback for older reports. A pure-helper test proves the merge keeps a 3/3 keyed defect, drops 1/3 noise, does not merge distinct complaints, and diffs a baseline across total rewording.
- **Gotcha (contention):** running `doctor gate` while the studio dev server is also tracing made a fixture job report `failed at tracing` mid-run. The next gate run passed **4/4** with no change — it is contention, not a real failure. Do not run the gate and a build at the same time, and re-run before believing a lone `failed tracing`.
- **Action:** for a hero/contrast claim, use `--votes 3` before acting; keep an `--out` report per build and pass it as `--baseline` next time.

## 2026-10-01 — The composition fixes a vision review drove (and what the gate cannot see)
- **What:** acted on the defects `doctor critique` found on the montiva fixture. (1) Hero scrim retuned twice — the original held ~86% page-ground out to two-thirds of the width, washing the traced art to mean **200** (reference **143**); a first fix softened it so far that a re-review called the lede unreadable. The final gradient holds the ground across the copy then releases the art by ~88%, and the hero copy is capped at 520px with a smaller `h1` (36–60px) — art mean **194**, std 54 → 61, copy legible, art visible on the right. (2) A phone line drawn *inside* a button plate folds into that button as `.cta-sub` (`generate._cta_sublabels`) instead of rendering as an orphan `<p class="lede">` under the row. (3) Badge row given more separation. (4) Card bands set `--cards` from `generate._balanced_cols`, so a 4-card band is 4 across, not 3+1. (5) Contact panel: `_value_label_pairs` pairs a phone/email/button with the caption under it, so captions stop merging into the wrong column and the panel is a titled card of value/label items. (6) Footer: `_footer_nav_links` finds the packed run of `other`-role links the model does not tag `cta`, the brand tagline stays with the brand, and the layout is brand+nav on top with the meta line full width below.
- **Why / evidence:** the saved critique reports + before/after art-region measures. The contact and footer defects dropped from high/medium to **low** in the re-review. Crucially the studio fixture gate does **not** see any of it: for `layout: page` the fixture score is the *traced SVG rendered alone* (`verify._render_art`), so page CSS cannot move it — montiva stayed **4.19**.
- **Gotcha:** `decorate` grows a CTA box to its full button plate (`refine_button_bbox` / `measure_button_bbox`), so a two-line button **contains** its second line — the phone's top (251) is *above* the CTA's bottom (270), and a caption on the plate's second line starts *inside* the value's box. A "directly below" test (gap 0..18px, or `_has_below`'s old `-2`) silently misses it. `snap_to_ink` does the same for short boxes (a brand and its tagline merge). Also: `.hero-copy > *` caps width but `.hero .lede`'s own `max-width: 60ch` overrides it.
- **Gotcha (review noise):** the critic flags things that are deliberate: "missing icons/avatars/star ratings" (the output carries **no raster assets** — the art is traced SVG, the page is DOM type). The critique prompt now excludes raster assets explicitly, and the first fix stopped the flood of those complaints. The hero-art-strength verdict is still unstable run to run (one review called the art washed out; the next called the *same* art too faint *and* the copy unreadable) — treat a single review as a hint, not a verdict, and re-run before acting on a hero/contrast claim.
- **Gotcha (capture):** `critique` screenshotted the page at a fixed 2400px window, which cut a real landing page's contact and footer sections — the first review never saw them, and they were only found after re-running at 3400px. It now opens the window tall, **trims the uniform background below the content**, and captures the whole page.
- **Action:** four `doctor polarity` guards cover the logic: "card bands fill their last row", "phone folds into its button", "contact panel pairs value + label", and "footer nav links detected".

## 2026-10-01 — `doctor critique`: the review loop is a tool now
- **What:** `doctor critique <job-id | design.png>` screenshots the built page, sends it + the mockup to the vision model, and prints a ranked list of composition/readability defects. `--page <built.html>` reviews an existing page; `--out report.json` saves the raw report; a PNG with no `--page` builds it first (deterministic under `STUDIO_FAKE_BLOCKS`).
- **Why / evidence:** every studio composition fix so far (ghosting, hero crop, ghost CTA plate, header layout, card density) came from an ad-hoc vision review. First run on the montiva fixture flagged a pale hero backdrop, an orphaned phone line, weak badge-row separation and a 3+1 card wrap — plausible, actionable defects.
- **Action:** it is a *review* tool, not a gate stage — it needs a live model and is subjective, so it stays out of `doctor gate`. Prompt explicitly excludes typeface differences (the page is authored in its own type). Use it after a composition change and diff two reports.

## 2026-10-01 — STATE.json drifts; `doctor regress` now checks it
- **What:** `docs/STATE.json` is hand-maintained and had drifted: `self_hosted_fonts.result` still quoted `2.77 / 2.90 / 3.11` as the current offline scores, and `next_priorities` still listed the long-resolved `_fmt` relative-coordinate lead.
- **Why / evidence:** the shipped scores are `2.71 / 2.76 / 2.99` (a fresh `qa/verify.sh`); `_fmt` is marked resolved in the same file's `resolved_leads`.
- **Action:** `doctor regress` now parses the `qa/verify.sh` means and fails if `STATE.json`'s `scores`/`targets` disagree with `designs/*.json` or the run (negative-tested both ways). When you change a target, update `STATE.json` in the same commit. The load-bearing state is small; keep it in sync rather than re-litigating prose.

## 2026-10-01 — A non-interactive shell has no node/Homebrew on PATH
- **What:** `doctor gate`'s `regress` stage failed with
  `./qa/verify.sh:16: command not found: node`, so the whole gate reported FAIL
  with no scores. `verify.sh` called bare `node` (nvm keeps node off a
  non-interactive PATH — an agent/launchd/CI shell), while `build.sh` and
  `bootstrap.sh` resolve node and prepend it. The same class of bug bites
  potrace: it lives at `/opt/homebrew/bin/potrace` with Homebrew off the base
  PATH, so bare `potrace` fails.
- **Why / evidence:** `cd pipeline && ./qa/verify.sh` → `command not found: node`
  (rc 127) even though `doctor env` found node via `_env.NODE`. Fixed: `verify.sh`
  now resolves `_env.NODE_DIR` and prepends it (like `build.sh`); `doctor env`'s
  potrace check and the studio's `node_env()` now share `procs.find_potrace()`.
  After the fix, `verify.sh` scores **2.71 / 2.76 / 2.99 PASS**.
- **Action:** resolve binaries through `_env` / `app.procs` — never trust the
  caller's PATH. `qa/verify.sh` now resolves node **and** Chrome/sips/sRGB via
  `_env` (so a Chromium install or non-standard profile works without editing
  it). `pipeline/qa/mkart.py` and `pipeline/qa/potrace_util.py` called bare
  `potrace`; both now use `_env.potrace_bin()` and regenerate a/b/c
  byte-identically.

## 2026-10-01 — The safety net is one command now (`doctor gate`), and CI runs it
- **What:** `studio/backend/doctor.py gate` runs the whole net in order —
  `env → polarity → fixtures → regress` — and exits non-zero if any stage fails.
  `--quick` runs `polarity` alone (no potrace, node, Chrome or model). `regress`
  *is* `qa/verify.sh`, so A/B/C PASS is covered. `.github/workflows/gate.yml`
  runs `gate --quick` on every push/PR and the full `gate` on `main` + nightly.
- **Why / evidence:** the gate was spread across `qa/verify.sh` + three `doctor`
  subcommands and nothing ran them automatically (`doctor.py`'s docstring already
  claimed "CI-able", but there was no `.github/`). `gate --quick` here passes in
  seconds; `gate` correctly reports `env FAIL` on this machine because `potrace`
  is not on PATH (the committed `{a,b,c}.svg` mean `build.sh` does not need it).
- **Action:** run `doctor gate` before committing; if a stage is irrelevant to a
  change, say which and why rather than skipping it silently. Python deps are now
  **pinned** (`pipeline/requirements.txt`, `studio/backend/requirements.txt`) —
  the scores are a numeric gate, so bump deliberately and re-record the numbers.

## 2026-10-01 — Inpainting must detect ink by COLOUR, not mean-luminance
- **What:** `mkart.build`'s light-design inpaint marked ink with
  `|lum - bg_local| > 15`, where `lum` is the **mean of RGB**. A saturated colour
  whose mean luminance sits near the ground is therefore invisible to it: the green
  `type` of a green-on-white wordmark has mean lum ~119 against a ~220 ground, so
  no ink was marked and the word was traced into the artwork while its DOM copy sat
  on top of it (the anthotype upload's `anthotype` + lede ghosts).
- **Why / evidence:** per-channel the green stroke differs from its local
  background by 60-220 (max channel), but only ~73 in mean luminance, and its glow
  is the same green so the stroke *core* reads as background. Replacing the test
  with a **max-channel RGB distance** (`|sub - bg_local_rgb|.max(axis=2) > 10`,
  `bg_local` a per-channel median) and dilating 3*up instead of 2*up took the
  anthotype wordmark region to **0 green ghost pixels**, whole-page mean 24.13 ->
  19.16 with the hero copy no longer double-exposed.
- **Action:** the inpaint path is gated on `text_bg_lum`, which only the studio's
  light designs and the fixtures set -- A/B/C never enter it, so they stay
  byte-identical. Do NOT "simplify" the ink test back to a luminance mean.

## 2026-10-01 — A hero illustration's own labels must not become DOM copy
- **What:** On the anthotype upload the vision model tagged *every* block
  `part: page`, including the diagram's own captions ("Generate", "Time", "Refine
  and grow meaning", a logo on the device screen, "1/2/3 Image/Sunlight/Plant
  Pigment"). They were emitted as DOM paragraphs and landed in the hero copy column
  as stray single words between the headline and the lede.
- **Why / evidence:** the hero copy reads as one column (headline, subhead, lede),
  so any *short* `other`/`brand` line that either (a) overlaps the headline/subhead
  band or (b) sits clear of the lede's right edge is a caption drawn on the
  illustration, not copy. `_drop_artwork_labels` in `studio/backend/app/generate.py`
  implements that; on the anthotype upload it drops 12 hero labels and keeps the
  brand/tagline/headline/subhead/lede/CTA, while on the Montiva upload it drops
  **0** (its trust badges sit beside the CTA row, inside the copy column).
- **Action:** `is_page_text` trusts the model's `part`; that is not enough when the
  model returns `page` for everything. The geometry filter is the backstop. The
  exclusion rects still use ALL blocks, so the dropped labels are still blanked out
  of the traced art -- DOM drops them, the tracer still removes them.

## 2026-10-01 — Studio jobs on disk predate the current generator
- **What:** Every job under `studio/data/jobs/*` was built **Sep 29**; the
  composition fixes (hero band, blank CTA rects, sections, single `<h1>`) landed
  **Sep 30** (`f9b70ab`). Their `index.html` has no `preserveAspectRatio`, a
  full-frame `viewBox`, 16 `<h1>` elements and zero `sec-*` sections.
- **Why / evidence:** `stat` the job dirs vs `studio/backend/app/generate.py`;
  `grep -c preserveAspectRatio <job>/index.html` → 0. Re-running the **current**
  pipeline on the same cached blocks improves art mean 11.46 → 4.24 and emits
  `features/testimonials/contact` + one `h1`.
- **Action:** Do not judge the studio by the on-disk jobs. Replay the current
  code over the cached blocks instead: `STUDIO_FAKE_BLOCKS=<job>/raw-blocks.json
  python doctor.py run <job>/ref.png` (no vision call, ~30 s).

## 2026-10-01 — `bands` is the lever, NOT the trace box (CORRECTED)
- **What:** Raising `bands` 48 → 96 on a real photographic upload improves the
  masked art mean **4.244 → 4.144**; beyond 96 it degrades (192/384 worse). The
  trace **box** must stay the FULL frame: cropping it to the hero band measures
  **worse** (5.37 vs 4.14 at 96 bands), because the tracer's luminance band edges
  are percentiles of the *box's own* histogram (`mkart.build`: `lo,hi =
  percentile(lum)` over the box) — a hero-only box re-bins the image against the
  hero's tonal range and loses fidelity everywhere.
- **Why / evidence:** same upload, same mask, `mkart.build(box=..., bands=...)`:
  full@48 4.244, full@96 **4.144**, hero@48 5.562, hero@96 5.374.
- **Correction:** an earlier version of this note claimed the hero-band box won
  (4.152) — that was a **measurement artifact**: the reference was cropped to the
  band while the mask was built in full-stage coordinates, so the two sides of the
  comparison disagreed. Always build ref, render and mask in the SAME coordinate
  space.
- **Action:** Pin `bands=96` in the studio's design config; keep `box` full frame.
  Verify by scoring the *whole box* with a mask built in stage coordinates.

## 2026-10-01 — Studio default was `bands=48`; A/B/C use 96
- **What:** `newdesign.py` scaffolds `bands=48` (`--bands` default), and the
  studio inherited it, so every studio upload was traced at half the resolution of
  the tuned A/B/C designs (`PARAMS` = 96). `generate.write_all` now pins
  `bands=96, up=2` in the per-job config (studio-only; A/B/C untouched).
- **Why / evidence:** `studio/data/jobs/*/workspace/pipeline/designs/*.json` all
  show `"bands": 48`. After the change, u1/u2/u4/u5 improved to 0.89/1.20/2.33/4.14.
- **Action:** Do not "max out" bands — 96 is the knee. Re-measure per upload if a
  new reference is very different.

## 2026-10-01 — The vision model tags every nav link `cta`
- **What:** A header/footer link row ("Home", "Services", "About") comes back with
  `role="cta"`, indistinguishable from a real button ("Book Service"), so every
  nav row rendered as a stack of boxed buttons. Fixed by classifying a short CTA
  in a row of >=3 short CTAs as a nav link — unless it has a **solid fill** (the
  real button keeps its fill; nav links on a busy row come back `outline`).
- **Why / evidence:** decorated Montiva blocks: nav links all `outline=True` with
  contaminated fills; `Book Service` `outline=None`, fill `(0,94,236)`. The
  discriminator lives in `generate._nav_cta_ids` / `_NAV_LINKS`; `_cta_html` emits
  `class="navlink"` for them.
- **Action:** Nav-vs-button is a *row-level* decision needing BOTH shape and fill.
  Shape alone misclassifies a short standalone button in a link row.

## 2026-10-01 — Ghosting on DARK designs: FIXED by inpainting, not band-dropping
- **What:** On a dark upload with glowing *colored* type (AntHosting green on
  near-black), the mockup's own headline was traced into the backdrop as a ghost
  behind the DOM copy. The metric could not see it: the rects are masked, and the
  ghost is the glyph *fringe* just outside them. The page shows it because the
  hero scales the art up (`preserveAspectRatio="slice"`).
- **Root cause:** the dark-path rule drops a band only when the band's median
  colour inside the rect is `> text_lum_max` (200) — it assumes near-white type.
  On colored type the median inside the rect sat at ~105 (the anti-aliased
  fringe), so no band cleared 200 and the fringe was traced.
- **Why the obvious fixes fail (all measured, do not retry):**
  - *Bigger exclusion rects* (pad 6→60): ghost 1398→1137 px, whole-page score
    gets WORSE. The ghost is not glow spilling outside; it is the glyph itself.
  - *A per-rect local-background band-drop rule* (`edge > rect_bg + margin`):
    re-bins the region and makes the text BRIGHTER (drops the ground, keeps the
    fringe) — the classic hole/plate inversion.
  - *Widening the inpaint median window*: the 21px window is narrower than a 50px
    headline, so `bg_local` reads the glyph as "background" and the glyph is not
    marked as ink.
- **The fix (works):** reuse the LIGHT path's inpainting for dark designs too —
  put the text rects through `blank_rects` AND set `text_bg_lum` to the design's
  ground luminance, so mkart finds ink by *local contrast* (polarity-agnostic) and
  fills it from the surroundings. Wired in `generate.write_all`: `bg_lum < 128`
  now appends `text_r` to `cfg["blank"]` and sets `text_bg_lum`. The traced ghost
  disappears completely; u1 art 0.89→0.88, u2 1.20→1.19. A/B/C are untouched (they
  do not set `text_bg_lum`, so mkart's legacy path is byte-identical).
- **Action:** dark text exclusion is inpainting, same as light. The absolute
  `text_lum_max` rule is only correct for near-white type — never rely on it for
  colored/dim glyphs.



## 2026-10-01 — `art_score` is not comparable across layouts
- **What:** The studio scores a `page` by rendering the traced SVG alone at
  1024×768 and masking the text rects (`verify.assess`, `art_source="svg"`). The
  headline "art mean" therefore depends on how much of the page is in the box and
  which rects are masked — a smaller box can *raise* the masked mean while looking
  better. Compare like-for-like, and always look at the render.
- **Why / evidence:** hero-band box scores 130.5 if scored over the full frame
  (the empty area below the band is a huge diff) but 4.15 when scored over the
  band it actually covers.
- **Action:** Any box/param change must be scored over the region the box covers,
  and eyeballed. Never compare a studio `art_score` to an A/B/C poster score.


## 2026-10-02 — The banding is chroma-blind; that IS the posterisation
- **What:** `mkart` cuts bands on **luminance only** and paints each with ONE
  median RGB. A band spanning blue sky, green foliage and brown wood therefore
  gets their average. That single decision is the lost colour *and* the
  posterisation a design review reported on real uploads.
- **Evidence:** isolated the cost of the banding model alone (no potrace, no
  blanking, no SVG). Per-band split along the two opponent chroma axes
  (CIELAB a*/b*-like) recovers **48%** on a photographic upload, 8% on flat art.
  Real end-to-end (traced + rendered + scored), turdsize 12, chroma_cells 2,
  gate 16, smooth 4: montiva 4.18 -> **3.47** mean, 17.67 -> **12.67** p95;
  anthotype 2.45 -> **2.04**, 13.00 -> **8.67**. The **p95** is the number that
  matters -- that is the blotchiness the eye reads as posterisation.
- **Gotcha that cost the most time:** a *pixel-error proxy* that only paints bands
  onto a canvas promises ~48% and 3x regions; the real trace gives **17-23%** and
  **4.5x payload**, because intersecting a cumulative luminance mask with a chroma
  cell shatters it and potrace spends thousands of points on the ragged boundary.
  Always bench with a real trace + render + score (`qa/` has the harness).
- **The fix that made it affordable:** `chroma_smooth` -- blur the chroma field
  BEFORE thresholding it, so each cell boundary is a smooth curve. That alone took
  montiva from 16.9 MB to 5.5 MB for most of the quality.
- **Action:** keep `chroma_cells=2, chroma_gate=16, chroma_smooth=4,
  turdsize=12` in `generate.write_all`. The gate keeps flat art on one colour per
  band, so A/B/C are byte-identical (verified). Do NOT raise `turdsize` to 30 to
  save payload: it eats fine line art (a glow-line design goes 1.72 -> 1.91).

## 2026-10-02 — `turdsize` 2 -> 12 is free payload
- **What:** the studio shipped `turdsize=2` (tuned for the flat A/B/C posters,
  which want every speck). On real photographic uploads that is pure waste:
  **-28% to -42% SVG size at an unchanged art mean** (montiva 3.80 -> 2.73 MB,
  4.19 -> 4.18; anthotype 6.24 -> 3.65 MB; anthosting 6.01 -> 3.91 MB).
- **Action:** the studio pins `turdsize=12`. Do not "restore" 2 -- it is A/B/C's
  value, not the studio's, and the two media want different answers.

## 2026-10-02 — harmonic inpainting the text rects is a REGRESSION (measured)
- **What:** replacing the nearest-non-ink fill with a diffusion fill (solve
  Laplace in the hole, so a gradient continues through it) is intuitively right --
  the blanked rects really are 4x-35x flatter than the artwork around them. It
  is measurably worse: montiva art mean **4.19 -> 4.54**, SVG **3.8 -> 9.3 MB**.
- **Why:** the tracer has to *band* whatever the fill produces. A smooth gradient
  across a big rect means every band edge crosses the hole, so the rect shatters
  into dozens of slivers. A flat plate is dull but traces cleanly and cheaply.
- **Action:** `inpaint=` defaults to `nearest`; `_hole_fill` is kept but unused,
  with the measurement recorded, because it is right for a *small* hole on a
  strong gradient. Do not "fix" this without re-measuring payload.

## 2026-10-02 — a filled button rect is NOT a visible artefact
- **What:** reviewing the **standalone traced SVG** makes every blanked button
  rect look like a pasted-on white plate, and a design review reading that image
  reports "worm-like smudge trails". On the **built page** the DOM button covers
  the rect exactly and there is nothing to see.
- **Evidence:** montiva's biggest diff blobs are 97% / 86% / 72% inside the
  removed-rect mask -- i.e. exactly where the page draws live DOM over the top.
  Screenshotting the real `index.html` shows a clean hero.
- **Action:** **always review the built page, never the bare SVG**, when judging
  whether blanking hurt. The SVG is a *decoration layer*; it is supposed to have
  holes where the chrome goes. This cost a wrong diagnosis and a rejected fix.

## 2026-10-02 — `whole_score` >> `art_score` is expected, not a blind metric
- **What:** `whole` is ~14x `art` on a real upload (60.94 vs 4.21). That is NOT
  evidence the art score is broken: the text rects are ~28% of the stage and the
  reference has crisp type there while the trace has none, so the unmasked mean is
  dominated by copy the page deliberately replaces.
- **Correction:** an earlier note in this session claimed the metric was
  "structurally blind" to the damage. It is not. Outside the rects it does score
  tracer defects -- the biggest montiva blob (1416 px) lies 0% inside the mask.
- **Action:** the gap is not a bug to fix. What genuinely needed covering was the
  fill *quality* at the rect edges, which is now `verify.blank_seams` (an absolute
  0-255 step, reported as `blank_seam`). It reads 3.5 on montiva vs 1.0/0.0 on the
  two clean designs, and is negative-tested in `doctor polarity`.

## 2026-10-02 — the hero was MAGNIFYING the art 2.5x; that was the "not sharp"
- **What:** the user reported the imagery was "not sharp enough" on the
  photographic uploads. It was not the tracer. `hero_band` cut the backdrop's
  viewBox to exactly the hero's own slice, and the hero box is far taller than
  that slice, so `preserveAspectRatio=slice` scaled the art to COVER it:
  **a 311 px band in a 785 px hero = 2.52x**, showing only **406 px of the 1024 px
  traced width (40%)**. On a 2x display, 5x. Every traced band was a huge blob.
- **Evidence:** rendered the same built page at band 311 / 550 / 768. At 550
  (1.45x) the laptop, tower, desk and real mountain ridgelines all appear; at 311
  they are unrecognisable blobs. `HERO_BAND_OVERSHOW=0.6` takes the band to 498
  (1.58x) and a bottom fade on `.hero-art::after` dissolves the overshoot, so the
  next section's cards do not read as clutter.
- **Action:** the crop existed to stop lower sections bleeding in -- keep that
  intent, but **overshoot and fade rather than cut exactly at the boundary**. A
  hard cut at the boundary maximises magnification. Guarded in `doctor polarity`
  ("hero backdrop band avoids magnifying the art", expects 380 < y1 < 768).

## 2026-10-02 — the tracer is SATURATED; stop tuning it for photographs
- **What:** measured every remaining knob on the worst photographic upload. None of
  them move it: bands 96 -> 192 gives 3.50 -> 3.43; chroma_gate 16 -> 0 gives
  3.50 -> 3.45; `up` 2 -> 4 gives 3.50 -> **3.43 while taking 888 s instead of 84 s**.
  p95 sits at 12.67 across nearly every configuration.
- **Why:** the residual is concentrated in the hero photograph (mean 10.62, p95
  27.07) while the rest of the page is 0.2-3.1. A photograph has effectively
  continuous tone; ~200 flat-filled vector regions cannot represent it, and no
  amount of banding resolution changes that. It is a limit of the representation,
  not of the parameters.
- **Action:** do NOT spend more effort tuning bands/up/turd/chroma against a
  photograph -- the returns are flat and the cost is large. The remaining levers
  are representational (SVG gradient fills instead of flat ones) or accepting the
  limit. Sharpness complaints are usually the *magnification* bug above, not this.

## 2026-10-02 — SVG `linearGradient` fills do NOT work for this tracer (measured)
- **What:** the last untried lever for photographic colour was replacing flat
  per-band fills with SVG `<linearGradient>`s. Built and measured it. **It is worse
  than flat**, decisively: montiva art mean **2.20 -> 4.45** in a paint
  simulation that replicates mkart's real cumulative paint order.
- **Also measured, same harness:** per-component flat colour (one median per
  CONNECTED COMPONENT of the cumulative mask, instead of per band cell) is
  **neutral** — 2.20 -> 2.21. Not worth the extra regions.
- **Why gradients fail:** a band is a thin luminance *ring* that wraps around
  objects, so the colour inside it is not a function of position along any single
  axis. Ceiling measurement: a per-channel least-squares linear model in (y, x) —
  strictly MORE expressive than one SVG gradient axis — explains only **24.5%** of
  montiva's within-band residual energy (46.5% on anthotype). A gradient
  interpolates between stops, so on a region where the fit is poor it overshoots at
  the extremes, which is where most of the area is: worse than a median.
- **Action:** do NOT implement gradient fills. This is the measured dead end the
  session note ("the only untried lever") pointed at, and it is now closed. The
  representation really is at its ceiling for photographs. Remaining options, all
  measured: more chroma cells (2 -> 3 buys p95 12.67 -> 10.67 for 5.6 -> 8.4 MB;
  4 cells costs 21.5 MB), more bands (96 -> 192 buys 3.50 -> 3.43 and leaves p95
  unchanged), or accepting the limit. Sharpness complaints are the hero-magnitude
  bug, not this — see the magnification note.
