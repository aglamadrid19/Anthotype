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

## 2026-10-08 — the one-pixel detection hole: exact bboxes, zero-detect uncertain, accounting
- **What:** A one-pixel shift of the same strokes zeroed the detector (2 detected
  at shift 0, 0 at shift 1).  Cause: the component bbox came from the
  **downsampled** mask (`[::2]`), and `*2` can be offset by one full-res row
  from the real stroke, so the stroke's own edge leaked into the flatness
  border (`border_std` 0.0 → 33.7) and the component was rejected.  The bbox is
  now the **exact full-res bbox** of the component's contrast pixels
  (`_exact_bbox`, one-cell margin), which fixes the shift without touching the
  flatness gate.  Two further fail-safe fixes: **zero detections is now
  uncertain** — the no-op "no content" path is gone, so a detector miss can
  never become a normally acceptable candidate; and `repair_candidate` enforces
  **`detected = repaired + skipped`** (any silent drop is an accounting
  mismatch → None → diagnostic).  The runner requires `detected > 0`,
  `repaired == detected` and `skipped == 0` for a complete candidate.
- **Why / evidence:** the regression builds the exact case (strokes at
  `[30,40,200,52]`/`[30,120,170,132]`, both shifts, empty boxes, **3× model
  output with both strokes erased**) and asserts the **restored pixels**:
  `shift 0: det=2 rep=2 pixels=True; shift 1: det=2 rep=2 pixels=True`.  Blank
  input → repair refuses (`zero-detect-uncertain=True`).
- **Documentation correction:** earlier notes said "45/45 with boxes and empty
  boxes".  With the fixed detector the real cached hosting data gives **50/50
  with the job's boxes**, 34/34 with the fixture blocks, and **40/40 with empty
  boxes** — all complete, 0 skipped, 0 outside.  The counts depend on the box
  set (boxes merge with detected regions); the invariant is completeness, not
  identical counts.
- **Action:** keep the exact-bbox step before the flatness test; never treat
  zero detections as verified absence; keep the accounting check.

## 2026-10-08 — repair gaps fixed: empty boxes, portrait clamping, diagnostic-only failures
- **What:** Three automation gaps from the review.  (1) The runner skipped the
  repair when the extraction had no artwork boxes — the pixel detector now
  always runs when enabled (real hosting data with EMPTY boxes: 45 detected /
  45 repaired / 0 skipped, same as with boxes).  (2) `repair_candidate` clamped
  *all four* patch coordinates by image **width**, so a portrait image silently
  lost lower content (120×300: 2 detected, 1 repaired); x now clamps by width
  and y by height.  (3) A partial/failed repair used to produce a normally
  acceptable pending candidate.  Now only a **complete** repair (0 skipped) is
  `hero_enhance="pending"`; partial/failed/off candidates are `"diagnostic"` —
  the cleaned-native fallback ships, the preview is shown for inspection, and
  `accept_enhance` refuses them with a clear message.  A no-content artwork (a
  pure photograph) is a *no-op repair*, not a failure, and stays normally
  reviewable.
- **Why / evidence:** polarity checks "repair handles empty boxes, portraits and
  invalid regions" (all true; an out-of-bounds box is skipped with a reason, not
  fatal) and "a partial repair is diagnostic and cannot be accepted"
  (state=diagnostic, skipped=1, accept refused).  Real cached data: with boxes
  45/45, EMPTY boxes 45/45, 0 outside, 19–25 s.
- **Action:** never gate the repair on extraction boxes; keep the width/height
  clamp split; any future "partial" outcome must stay diagnostic (the UI shows
  the preview without an Accept button).

## 2026-10-06 — the repair is a general Studio stage now (design-agnostic)
- **What:** `app/repair.py` turns the seven-patch experiment into a general
  stage that runs with every opted-in enhancement (scene and full layouts):
  native cleanup → Flash/cache → **source-preserving repair** → audit → pending
  preview → manual acceptance.  Content is detected from the **native pixels**,
  not the extraction boxes: contrast against a local background, components kept
  only when the **border around their bbox is flat** (a UI panel; artwork
  texture — globe dots, hardware, glow — is not), shape-filtered (round compact
  blobs = dots, not content), merged, plus every extraction artwork box.
  Restoration uses the validated rules: exact source→output mapping, context-ring
  alignment (structured pixels; a verified flat ring accepts the global
  mapping), opaque cores with adaptive feathering, zero change outside, complete
  coverage.  Uncertain alignment/coverage returns None: the raw candidate stays
  and the job warns.  Repaired variants cache separately (`repair-v1.png/json`
  beside `output.png`) with provenance (hashes, scale, regions, transforms,
  residuals).  `STUDIO_ART_REPAIR=off` disables it.
- **Why / evidence:** polarity checks "source-preserving repair restores content
  and never guesses" (synthetic panel: text+icon detected, textured half
  excluded, core diff 7.2, outside 0, feather px 3220, noise → refused) and "the
  enhancement repairs before deriving the band" (runner integration with a
  mocked model output).  On the real hosting data (cached raw output, no model
  calls): **45 regions detected (26 extraction boxes + 19 unboxed values/icons),
  45/45 repaired, 0 diff outside, max residual 39, 24.8 s**; the general-stage
  band reads like the accepted v2 at page scale
  (`hosting-general-repair/`, `page-hosting-general.html`,
  `hosting-general-compare.png`).  The accepted hosting asset (`d4ad5d4ac0aa`)
  is the manual v2, attached with the user's approval bound to its SHA-256
  (`hero_enhance_audit.candidate_sha256`).
- **Skip semantics:** a region whose context is untrustworthy (content drawn
  over re-rendered artwork, e.g. a chip on the globe) falls back to
  content-based alignment; if that also fails the region is **skipped with a
  warning** (the candidate keeps the model's version there, the audit lists
  it), and the repair only refuses outright when *no* region can be aligned.
  This is what makes the stage usable on real scenes instead of refusing on the
  first globe label.
- **Action:** the stage restores ALL detected content, so enhanced text/icons
  are native (softer) rather than the model's re-render — the deliberate trade
  for guaranteed fidelity; manual acceptance stays mandatory.  The detector is
  heuristic: keep its synthetic tests green and add fixtures when a new design
  shape appears.

## 2026-10-06 — repair v2: real feathering, exact mapping, measured icon coverage
- **What:** The first repair had three implementation bugs the review caught: the
  "feather" blurred a solid-white mask (no softening at all — opaque
  rectangles), the source crop gained a 4 px margin but was resized into the
  *unexpanded* destination (glyphs squeezed), and overlapping box-derived
  patches left stray fragments around Team and row-3.  v2: patch masks are a
  solid core inset by 8 raw px then blurred (opaque glyph cores, soft borders);
  the source crop's own integer bounds map through the model scale
  (Fx 3.0885 / Fy 3.088, no squeeze); icon patches are measured from the actual
  native pixels (brightness bbox in a tight window — green blades and the light
  Team outline alike), non-overlapping.
- **Why / evidence:** HF energy per icon area (candidate / repaired / source):
  team 1297.9/173.7/186.3, row1 622.3/105.5/101.9, row2 703.3/141.0/133.9,
  row3 777.0/129.1/122.2 — garbled marks gone.  Panel OCR: Deployments /
  Regions / 26ms all correct.  0 diff outside the patches before encoding
  (0.67% repaired).  `hosting-repair-closeups.png`,
  `hosting-repair-before-after.png`, `hosting-repair/repair-provenance.json`.
- **Action:** keep unaccepted; the Studio Accept button targets the unrepaired
  Flash candidate — a repaired asset must be attached as a new candidate with
  this provenance, not accepted through the existing one.

## 2026-10-06 — hosting audit corrected; offline repair preview (unaccepted)
- **What:** The boxed 26-label audit was incomplete: the extraction's table boxes
  sit ~27 stage px above the drawn rows and the bottom latency value was never
  boxed.  A panel-wide OCR diff plus icon sheets gave the complete damage list:
  **Deployments → garbled**, **Regions → Regices**, **26ms → 20ms**, the
  **Team** icon and the **three row icons** garbled (the other icons are
  re-rendered but clean; the chevron and labels are fine).  An offline repair
  restored those regions from the cleaned native source into the raw Flash
  output (per-patch local alignment, 7-px feather, 7 patches, **0 difference
  outside the patches before encoding**, 1.09% repaired), re-derived through the
  same band crop and encoded at q90: `hosting-repair/…-hero-repaired.webp`
  (3840×2194, 419 KB).  OCR confirms Deployments / Regions / 26ms; closeups
  confirm the icons and clean seams.
- **Why / evidence:** `hosting-audit-*` (sidebar/cards/table-full/icons),
  `hosting-repair-closeups.png`, `hosting-repair-before-after.png`,
  `page-hosting-repaired.html`, `repair_hosting_candidate.py`.  No model calls;
  the job's pending candidate and the shipped fallback are untouched.
- **Action:** audit visible content, not just extracted boxes — extraction boxes
  can be offset and can miss labels entirely.  The repaired patches are softer
  (source upscaled ×3.1) but read correctly at page size; acceptance remains the
  user's call, and the job still ships the cleaned native export.

## 2026-10-06 — the hosting Flash candidate fails the label audit (2/26 corrupted)
- **What:** The one approved Flash 4K call on the cleaned hosting input produced
  a pending candidate (job `d4ad5d4ac0aa`, band 3840×2194, 418 KB).  The 26-label
  audit against the exact model input (the padded cleaned canvas) found **two
  content corruptions**: sidebar "Deployments" → "DorioroUaros" and card
  "Regions" → "Regices".  Everything else is preserved: the table rows
  (us-west-1 / eu-central-1 Staging / ap-southeast-1, Production, Healthy,
  12ms/28ms), the region chips, "Anthosting", "All systems operational",
  "Infrastructure", "Monitoring", "Team", "Settings", "99.99% Uptime",
  "Secure private tunnel / End-to-end encrypted", "Your AntSeed deployment",
  "Private. Secure. Fully managed.".
- **Why / evidence:** `studio/data/experiments/artwork-quality/google-probe/`
  `hosting-audit-labels.png` (all 26), `hosting-audit-sidebar.png` (the
  corruption), `hosting-audit-cards.png` (the second), `hosting-audit-table.png`
  and `hosting-audit-rest.png` (clean).  The candidate is **pending** and was
  NOT accepted; the job still ships the cleaned native export (hero 3.19,
  labels 18.0/67.7), and `ddbc2872f5dd` is untouched.
- **Action:** do not accept this candidate; a re-run is a fresh spend decision.
  The audit-before-accept rule is what caught it — never accept on the pixel
  metric alone.

## 2026-10-06 — a partially masked label must still show its damage
- **What:** `label_fidelity` scored only the *unmasked* pixels of a label rect,
  so damage under a mask edge was invisible: an erased glyph run partially
  covered by the exclusion read **0/0** instead of 114/228.  The earlier fix
  only covered a *fully* masked label.  Artwork-label rects are now cleared from
  the combined exclusions (`verify._clear_rects` applied to `removed ∪
  cleanup_rects`) and scored in full — an exclusion can never cover a label,
  partially or wholly.
- **Why / evidence:** polarity "a partially masked artwork label still shows its
  damage": hidden (0.0, 0.0) vs cleared (28.5, 190.0) on a synthetic erased
  glyph run.  The fully masked case still passes ("masked label still scored
  190/190").
- **Action:** any exclusion that feeds the raster score must pass through
  `_clear_rects` with the artwork rects; never score a label on a masked
  subset.

## 2026-10-06 — enhancement framing: the input must cover the band; labels stay in the check
- **What:** Two review findings. (1) The enhancement input was the bare cleaned
  upload, but the band is trimmed to the hero box's aspect and can extend past
  the upload's own pixels (into the canvas letterbox) — the crop clamped and
  returned a candidate **shorter than the fallback's geometry** (measured
  3840×1929 vs 3840×2193 on the hosting upload).  `enhance.cover_band` extends
  the input with the design's own background so the band's rows are inside it
  (3840×2194 after rounding); no padding → the scene input is unchanged and its
  cache keys stay valid.  (2) `verify.label_fidelity` skipped a label whose rect
  was fully covered by a mask — with the cleanup masks merged into the
  exclusion, a damaged label could read as "no label" (a synthetic erased label
  went 114/228 → 0/0).  It now scores the full rectangle instead of skipping,
  and `_clean_artwork` subtracts every artwork-label rect from the cleanup masks
  (`cleanup.subtract_rects`, logged when it fires) — labels can never be removed
  and their scoring coverage never decreases.
- **Why / evidence:** polarity checks "padded-band framing=True" and "cleanup
  masks never erase an artwork label from the check" (subtract cut=1 → 4 rects;
  masked label still scored 190/190).  Real geometry: hosting upload rows
  101.2..1056.4 → padded input 1672×1057 → simulated 4K candidate band
  3840×2194 (fallback 3840×2193).
- **Action:** any input for the enhancement must cover the band's full extent;
  use `cover_band`, never the bare upload when the band can exceed it.  Never
  let an exclusion mask remove a label from scoring.

## 2026-10-06 — the cleanup's removal must be excluded from the raster score
- **What:** After the full-layout cleanup ran, montiva's shipped hero score rose
  1.89 -> 2.52 (over its 2.5 bound).  The cleanup changes only pixels inside its
  masks, but those masks are *bigger* than the tracer's `text`/`blank`: the
  grown CTA plates and the band row (icons) lie outside it, and the reference
  still shows them, so the deliberate removal read as a fidelity regression.
  `_clean_artwork` now records its masks in the design config as
  `cleanup_removed` (stage coords), and `verify.assess` merges them into the
  mask used by `hero_fidelity`/`label_fidelity` — never into `blank_seams`,
  because the tracer never filled those pixels.
- **Why / evidence:** montiva 2.52 -> **2.02** (bound 2.5; the pre-cleanup
  baseline was 1.89 and the residual is mask-edge/encode noise); labels
  4.5/13.7 unchanged.  `verify._merge_rects`.
- **Action:** any future step that deliberately removes pixels from the shipped
  hero (not just the tracer's own fill) must record its rects the same way, or
  the raster score will punish the removal.

## 2026-10-06 — the cleanup is integrated for full-layout raster heroes
- **What:** `_clean_scene` became `_clean_artwork`, run for both `scene` and
  `full` raster layouts.  Its masks are all detected from the page's own
  structure: CTA plates (`button_rects`), the hero eyebrow, the config's copy
  rects, and the row drawn inside the band whose copy a later DOM section
  replaces (`_benefit_blank_rects(..., any_layout=True)`, whose candidates are
  short lines sharing a row — no hard-coded cutoff).  The full-layout export
  now comes from the cleaned upload (`source_png = cleaned_src`), so the
  shipped backdrop is clean even without the enhancement; the enhancement's
  input is the same cleaned upload for both layouts, and a missing cleaner
  skips the enhancement instead of sending the artifact-laden prepared fill.
- **Why / evidence:** hosting fixture with the integrated path: `hero_cleanup
  lama`, 12 masks, shipped hero 3.26 (max 4); icon green pixels in the three
  feature zones 381/361/415 -> **0/0/0**, floor/rack glow preserved; labels
  unchanged (18.0/67.7).  Polarity checks: "enhancement maps the cleaned
  upload and stays optional" and "the full-layout row blank is detected from
  its blocks" (rendering stays scene-only).  Configured gate: 5/5 fixtures.
- **Action:** the prepared-canvas enhancement fallback was removed on purpose
  — it is text-removed but not clean, and the model would re-render its
  artifacts.  If the cleaner is absent, the enhancement is skipped.

## 2026-10-06 — full-layout cleanup preview: the prepared fill is NOT a clean input
- **What:** The tracer's prepared image for a full-layout job is *text-removed*,
  not *visually clean*: the nearest fill leaves large rectangular patches where
  the headline/subhead were, a residual dark CTA plate, and the feature-row
  icons plus green horizontal smears.  Feeding that to the enhancement model
  would ask it to re-render the artifacts.  The validated LaMa complete-element
  cleanup removes them: copy masks for the page text, grown component masks for
  the CTA plates + eyebrow pill, and a pad-only row mask for the feature icons.
- **Why / evidence:** `studio/data/experiments/artwork-quality/google-probe/`
  — `full_clean_preview.py` (offline, LaMa/MPS, 12 masks; 0 difference outside
  the masks), `full-clean/{jid}-cleaned-full.png` (native cleaned input),
  `-clean-canvas.png`, `-hero-clean.webp` (1672×955 band, 106 KB),
  `page-full-clean.html` (unchanged page, only the hero asset swapped),
  `full-clean-copy/buttons/features/band.png` before/after sheets.  The job and
  its shipped asset were not touched.
- **Action:** if approved, the integration is to run this cleanup for full-layout
  raster heroes before the export/enhancement (extend `_clean_scene` beyond
  `scene`), with `hero_cleanup="lama"` provenance.  No paid call until the
  cleaned input is approved.

## 2026-10-06 — the enhancement now reaches full-layout raster heroes
- **What:** The opt-in enhancement ran only for `scene` jobs, so a photographic
  (or wider-than-stage) upload — `hero_layout="full"` — silently bypassed it even
  with `STUDIO_ART_ENHANCE` set.  `runner._enhance_full` now produces the same
  pending candidate for a full-bleed raster hero.  Its input is the tracer's
  **prepared image** (native resolution, page copy already removed — the same
  image the shipped export is cropped from, hard rule 5), and the band is mapped
  through the canvas factor: crop rows = `band * m`, then the candidate's own
  scale.  Review/acceptance/caching safeguards are shared with the scene path.
  The photographic threshold and the layout decision were NOT touched.
- **Why / evidence:** job `ddbc2872f5dd` (1672×941 "Anthosting Private Hosting
  Dashboard") shipped `hero_kind=photographic`, `hero_layout=full`,
  `hero_enhance=None` despite the env var.  After the change, a real offline
  build of the same upload with enhancement configured but
  `STUDIO_ART_ENHANCE_NETWORK=forbidden` records `hero_enhance="skipped"` /
  "network forbidden -- skipped" (the branch is reached, no spend).  A mocked
  mapping test in `doctor polarity` ("full-layout enhancement maps the band and
  stays optional") checks band [10,40] × m=2 → candidate rows 40..160 and the
  failure → skipped path.  New fixture **`hosting`** (`studio/fixtures/
  hosting-ref.png` + `hosting-blocks.json`) pins the full-layout raster path:
  structure header/nav/hero/features, art 2.41/p95 33.67, hero 3.17, layout
  full, 26 artwork blocks → `hero-artwork`.
- **Action:** the first real candidate for this upload costs one Flash 4K call
  (~$0.15); re-running the upload with `STUDIO_ART_ENHANCE=google-flash` makes
  it.  Keep new full-layout coverage in the fixture; the gate stays spend-free.

## 2026-10-04 — the upper-globe softness is baked-in DoF; offline region sharpening helps
- **What:** The user noticed the globe's top is softer than the rest.  It is
  already soft in the cleaned source and survives the Flash enhancement — baked
  depth-of-field, not a rendering or integration problem.  An **offline,
  region-restricted** unsharp mask (r=3, 150%, threshold=4) inside a feathered
  upper-globe region — labels excluded, the threshold gate leaving the smooth
  atmospheric glow alone — visibly restores the dot/coastline crispness to
  match the sharp lower dot field.  It is a local correction of the accepted
  rendition, **not** new model output, and it cannot recover detail the source
  never had.
- **Mask-order gotcha (fixed):** the first candidate painted the label
  exclusions *before* feathering the region mask, so the 60 px blur leaked
  sharpening back into the labels (up to 85/255 pre-encoding).  Correct order:
  **feather the region first, then hard-zero the protection**.  Protection now
  covers the label rects *and* the bright connection-arc/node cores
  (max-channel > 120), so USM cannot touch them.
- **Why / evidence:** `studio/data/experiments/artwork-quality/google-probe/`
  — `globe_sharpen.py` (variants A–D at 1:1; A is the balanced pick, D reads
  over-etched), `globe_candidate.py` (candidate + preview page),
  `cand-globe-sharp.webp` (3840×2193, 290 KB, +21 KB), `page-globe-sharp.html`
  (the unchanged page with only the hero data URI swapped),
  `globe-protect-mask.png`, `globe-before-after.png`, `globe-fixed-1x.png`,
  `globe-fixed-2x.png`.  Pre-encoding differences: **0 outside the region, 0
  inside every label box, 0 on every protected bright pixel**; the edit touches
  2.1% of the band.
- **Action:** preview before replacing anything (the accepted asset and the job
  page are untouched).  If approved, swap the candidate into the job's accepted
  rendition; keep the edit region/label masks with the artifact so it can be
  regenerated.  A stronger result needs a targeted reference edit (reconstruction,
  i.e. generated detail) — a deliberate appearance change, not recovered original
  detail.

## 2026-10-04 — acceptance, round two: finished jobs only; workspace pages roll back
- **What:** Two more acceptance gaps. (1) Accepting now requires the original
  job to be finished (`status == "done"`); a queued/running/failed job gets a
  409 (`NothingToAccept`, "the job is not finished") instead of interleaving a
  rebuild with an in-flight build. (2) The rollback now also restores the
  generated **workspace** pages, not only the content and the packaged files:
  `<id>-full.html`, `sites/variant-<id>/src/pages/index.astro` and the whole
  `sites/variant-<id>/dist/` tree.  A failed acceptance leaves the workspace
  exactly as it was, so nothing downstream can read a half-rebuilt page that no
  longer matches the restored content.
- **Why / evidence:** `doctor polarity`'s mocked acceptance self-test now seeds
  base sentinels for all of those, stubs the compose/to-astro/build stages to
  overwrite them, fails *after* the packager wrote `index.html`/`dist.zip`, and
  asserts every one is restored; it also asserts a running job is rejected.
  Detail: "unfinished rejected=True, review gate=True, rollback(incl. workspace
  pages)=True, accepted+audit=True, serialized=True".  The real headless flow
  re-ran clean (cache candidate → reviewed accept → audit recorded), and the
  configured gate was rerun.
- **Action:** keep the finished-job check — an acceptance is a rebuild and must
  not race the original build.  Any new file a rebuild writes belongs in the
  snapshot list (job dir + workspace pages + dist tree).

## 2026-10-04 — enhancement hardening: spend-free gate, safe acceptance, recorded review
- **What:** Four gaps closed after a review. (1) `doctor gate` / `fixtures` force
  `STUDIO_ART_ENHANCE_NETWORK=forbidden` for their run, and `enhance.available()`
  (and `candidate()`) honor it, so a machine with the enhancement configured can
  never make the gate spend money. (2) The whole candidate step (request, band
  crop, WebP encode, disk) sits inside the optional-step handler — any failure
  keeps the LaMa/Lanczos asset instead of failing the build. (3) `accept_enhance`
  is serialized by a runner lock and failure-safe: it snapshots the content, the
  job-dir files and every field the rebuild touches, rolls all of them back on
  any failure, and marks `hero_enhance="accepted"` only after packaging
  succeeds — a failed acceptance leaves the base artwork shipping and is never
  left "accepted". (4) Acceptance now *requires* `reviewed=True` (the UI
  checkbox; the API body) and records
  `hero_enhance_audit={reviewed, method, at, candidate_sha256}` against the
  candidate's own hash, so the record cannot claim an audit that did not happen.
- **Why / evidence:** `doctor polarity` gained "enhancement acceptance is
  failure-safe and serialized" (mocked: review gate, packaging-failure rollback,
  two concurrent acceptances → exactly one wins) plus the kill-switch arm of the
  existing enhancement check. Headless end-to-end re-run: cache candidate →
  accept with review → audit recorded. The gate was rerun with
  `STUDIO_ART_ENHANCE=google-flash` configured; fixtures logged "network
  forbidden -- skipped" and stayed on LaMa/Lanczos.
- **Action:** keep paid calls out of tests via the kill switch; never bypass the
  review gate when accepting (the audit is what makes the acceptance note
  truthful). The score note now says the rise is **pixel drift**, not a quality
  loss — it is a real measurement of drift, not an "incomparable" number.

## 2026-10-04 — Google enhancement integrated: opt-in, preview-before-accepting
- **What:** The scene path can now produce a Google-enhanced candidate backdrop
  (`app/enhance.py`). It is **never shipped automatically**: the job records
  `hero_enhance="pending"`, the result view shows the candidate with an *Accept*
  button (`POST /api/jobs/<id>/enhance/accept`), and only acceptance swaps the
  asset into the page and rebuilds (`runner.accept_enhance`). LaMa/Lanczos stays
  the fallback; results are cached by `sha256(cleaned PNG)[:24] + model + 4k`
  under `studio/data/enhance-cache/`, so retries and acceptance never pay twice.
  Accepted provenance keeps `hero_image.source_w` = the *upload* width and adds
  `hero_image.enhance` {model, size, generated, input_sha256, image_tokens}.
- **Why / evidence:** headless end-to-end test
  (`google-probe/test_enhance_flow.py`, cache seeded from the probe so there is
  no network call): candidate 3840×2193 (269 KB) from a 5220×3264 Flash 4K
  output; acceptance rebuilt the page (477 KB) with `hero_enhance=accepted` and
  artifact `<id>-hero-enhanced.webp`. `doctor polarity` guards opt-in-off,
  key-required, cache-key stability and the band mapping. The runtime page is
  unchanged: the asset is inlined and makes zero network requests.
- **Action:** keep `STUDIO_ART_ENHANCE` unset in CI/fixtures (the gate must
  exercise the offline LaMa/Lanczos path). A candidate is a generative
  re-render — audit it before accepting; on rejection the base asset stays.

## 2026-10-04 — the Google label audit: Pro corrupts strings, Flash preserved them
- **What:** The earlier "labels survive" claim was wrong for Pro. Audited all 33
  `part: artwork` labels against the cleaned source with local macOS Vision OCR
  (`ocr.swift`) plus 2× visual sheets. `gemini-3-pro-image` 4K changed
  `28ms→26ms`, `36ms→26ms`, `Staging→Slaping` and
  `End-to-end encrypted→Eod-to-end-encrypted`; `gemini-3.1-flash-image` 4K
  preserved all four in this run (cards/regions/sidebar matched in both).
  Icon/glyph style still drifts slightly in both (re-render).
- **Why / evidence:** `google-probe/zoom-table.png`, `zoom-caption.png`,
  `audit_labels.py`; the audit is per-run, not a universal fidelity guarantee.
  Also: the enhanced band is aligned (best diff at dx 0–1, dy 0), and its
  `hero_fidelity` rises 1.30→4.8 **because the metric measures pixel identity,
  not sharpness** — a resample of the source wins it, a generative re-render
  cannot. `label_fidelity` (37/146) reflects re-rendered glyph edges, not wrong
  text.
- **Action:** default to Flash 4K for the opt-in enhancement; never compare
  `hero_fidelity` across renditions as if it were quality (the acceptance logs
  this). The per-label audit is the verdict on labels.

## 2026-10-04 — Antseed has no edit route; direct Google AI Studio does, and it wins
- **What:** the local Antseed catalog (41 image models, `/_antseed/peers`
  refreshed to 54 peers, Apex's 143 services) has **zero offers advertising
  image inputs**, which is the documented requirement for `/v1/images/edits`.
  The local buyer is not the blocker: a multipart request with an unknown model
  fails locally with `model_not_found`, and pinned to Apex the peer names that
  model — so multipart `model` is parsed and forwarded.  A valid multipart
  request (`nano-banana-pro`) then fails upstream with **“model is required”**
  while the JSON route works: the documented seller-side multipart fix
  (`provider-core ≥ 0.2.54`, `provider-openai ≥ 0.2.46`).  With the user's
  approval we switched the *experiment* to **Google AI Studio directly**
  (`GEMINI_API_KEY` in `studio/backend/.env`).
- **Why / evidence:** `gemini-3-pro-image` (Nano Banana Pro) and
  `gemini-3.1-flash-image` (Nano Banana 2) both accept the native cleaned
  artwork and return a reference-derived image: default 1305×816, 2K
  2610×1632, **4K 5220×3264**.  Labels at page 2× are identical (dashboard
  strings, values, sidebar), no page copy is restored, no controls invented;
  native 1:1 shows real glyph rendering, not upscaled blur.  Costs from the
  response tokens match Google's published per-image equivalents: Pro
  $0.134/1K–2K, $0.240/4K; Flash $0.067/1K, $0.151/4K; the five calls totalled
  **$0.726**.  Artifacts (sanitized requests, outputs, encoded pages,
  comparisons) in `studio/data/experiments/artwork-quality/google-probe/`.
- **Action:** the Google route is an **experiment**, not integrated.  The
  candidate is `gemini-3-pro-image` 4K → band → 3840 → q90 WebP (264 KB)
  against the same page; it is visibly better than the Lanczos rendition.
  Integration is a product decision (opt-in step, key handling, ~$0.13–0.24 per
  hero, network dependency) and should be asked before wiring.  Antseed remains
  viable only if a seller exposes an edit-capable service (+ the provider fix);
  nothing in the pipeline was changed for any of this.

## 2026-10-04 — Scene cleanup review fixes: named components, seed-connected growth
- **What:** a review of the integrated scene found interface ghosts caused by
  mask *routing*, not the model.  On a dark design `write_all` appends every
  text rect to `blank`, so "blank minus text" left only the benefit row: the
  CTA plates and the eyebrow kept a 3 px copy mask, and the eyebrow dot (source
  (83,235), outside every rect) was never masked at all.  `_clean_scene` now
  names component types explicitly -- CTA plates, the eyebrow (all-caps or a
  short line above the headline, using its `text_rects` *grown* rect so the
  pill outline intersects the seed), and the benefit row pad-only -- and drops
  rects above the scene band (the mockup header and its CTA).
- **Why / evidence:** `cleanup.component_masks` now grows only the pixels
  **connected** to the seed inside the capped window.  The polarity guard puts a
  decoy blob *inside* the window and shows it is not swallowed (the old guard
  placed it outside, which missed the failure the review reproduced).  A dry
  run on the dashboard blocks: eyebrow mask `[63,215,288,253]` covers the dot
  and both pill edges; no mask reaches above the band; the outline plate border
  (source x≈560-562) is inside its mask.  A 1:1 of the first fixed run then
  showed a faint pill-edge seam just outside the grown bbox, so the union is
  padded by 4 px (inside the hard cap), matching the approved prototype.
- **Action:** never route components by list subtraction -- name them.  Keep
  the benefit row pad-only: growing it lets the floor glow it sits on pull the
  mask to the window edge.  `studio/setup-cleanup.sh` now asks torch for
  `torch.hub.get_dir()` before downloading `big-lama.pt`; the old
  `~/Library/Caches/torch` default did not match torch's `~/.cache/torch`, so
  installer and worker disagreed about the cache.
- **Verified after the fix:** fixture hero 1.30; a fresh live upload
  (`f177dea4e2d8`, 12 masks after dropping the header band) fidelity 1.30, all
  33 labels `hero-scene`; `cleanup-zone-3way.png` and
  `whole-hero-shipped-vs-target.png` match the approved prototype with the
  pill/dot/ring/button ghosts gone.

## 2026-10-03 — Scene cleanup integrated (optional LaMa) + display upscale
- **What:** the approved experiment winner is integrated for scene heroes.
  `runner._clean_scene` runs the optional external LaMa cleaner over the
  **original upload** with upload-driven masks: the tracer's copy rects (light
  pad, `cleanup.copy_masks`) plus its component rects (`blank` minus `text`)
  grown to the complete element by `cleanup.component_masks`, hard-capped at 48
  source px so illustration content can never be swallowed.  The cleaned upload
  feeds the scene canvas; original pixels outside the masks are kept.  Without a
  cleaner (`STUDIO_CLEANUP_PYTHON` or `studio/.cleanup-venv`, created by the new
  `studio/setup-cleanup.sh`) the scene keeps the tracer's fill, records
  `hero_cleanup="fallback"` and warns.  The scene rendition is Lanczos ×2
  (capped at `EXPORT_TARGET_WIDTH`) and lossy `SCENE_QUALITY=90`; `source_w` in
  the export manifest and `resolution_gap(source_w, …)` keep the resolution
  warning about real source width — the upscale is display sharpness only.
- **Why / evidence:** the Real-ESRGAN comparison had a **channel-order bug**
  (basicsr `enhance` takes and returns BGR; the first run passed RGB through
  both ways).  Corrected, it is comparable to Lanczos q90, not better —
  deferred.  Lossy q82 visibly softens the dashboard lettering at 2×; q90 is
  close to lossless at 206 KB for 3172 px.  `doctor polarity` now guards the mask
  growth (covers the element, honours the cap, never reaches a decoy blob).
- **Action:** do NOT expand the copy rects with `component_masks` (the headline
  box's local contrast reaches the rack); the runner keeps `copy_masks` for
  those.  Real-ESRGAN stays out pending a real need.

## 2026-10-03 — Artwork-quality experiment: LaMa + component masks is the better hero
- **What / why:** a planning review found the scene backdrop visibly damaged
  (pill/dot remnants, button ghosts, fill streaks) and short of Retina.  A
  controlled experiment against the **original upload** (never the smeared
  backdrop) compared complete-interface-element masks + fills (nearest, OpenCV
  Telea, harmonic diffusion, **LaMa**) and ×2 resizes (Lanczos, Real-ESRGAN
  x2plus), all in the studio's band canvas and the same HTML/CSS.  Artifacts:
  `studio/data/experiments/artwork-quality/` (`before-after.png`, candidate
  pages, `experiment.py`).
- **Findings:** component masks alone kill the pill/dot remnants (the old masks
  were glyph-tight).  **LaMa keeps the floor striping and glow through the
  button/benefit boxes**, where every classical fill smears or replicates edges
  (nearest from a component's border reproduces the old ghost outline).
  Everything outside the masks is byte-identical to the source (max diff 0.0).
  At 2× the 1586 px asset is visibly soft; ×2 (either method) is dramatically
  crisper, but the information is still 1586 — a larger original is the real
  fix, and Real-ESRGAN is not clearly better than Lanczos here (slightly
  crunchier, no obvious invention).
- **Action:** the winning hero is the LaMa + component-mask backdrop
  (`hero-lama.html`; ×2 variants kept for comparison).  LaMa/Real-ESRGAN are
  **not** wired into Studio yet, per "prove one visibly better hero first".
  The caps the experiment required ARE integrated: `EXPORT_TARGET_WIDTH`
  2880 → 3840 (2× a 1920 CSS desktop) and `MAX_NATIVE_SCALE` 3 → 4, guarded by
  `doctor polarity` and the dashboard fixture (`hero_needed=3840`).
- **Gotcha:** the studio's prepared-image fill is nearest non-ink on
  glyph-tight rects; for large text that leaves ghost strokes, and for a
  component outline the border pixels just outside the rect become the fill
  source (the ghost button).  Mask the whole element and fill from outside it;
  a whole-box nearest fill then smears, which is why a learned fill is the one
  that reads clean.

## 2026-10-03 — The dashboard hero as an integrated scene (reference-led prototype)
- **What:** the next milestone replaced the split-image template's automatic use
  with a `scene` composition for flat illustration heroes: the whole
  copy-removed band is the hero as an in-flow image at its own aspect, a grid
  sibling of the copy in the same cell (no `cover`, no boxed column, no scrim).
  The reference's benefit row is lifted from `features` into the hero (and its
  original icons blanked out of the artwork), the paragraph is styled as
  lighter supporting copy, and only the sentence's "AntSeed" carries the accent.
  The prototype ships a **lossless** WebP (composition before compression).
- **Why / evidence:** the fixture replay (`dashboard`, kept job
  `e2cd897be125`) scores **0.82** shipped-scene mean / 15.0 worst-label mean /
  43.9 p95 with all 33 artwork blocks in the scene; side-by-side at 1024×768
  matches the reference hierarchy.  The accent trick: a wrapped two-tone block's
  run *text* boundary is wrong (`sample_runs` split "Managed private ho|sting
  for AntSeed."), so `_tone_fraction` classifies ink by chroma and `_accent_html`
  maps the share back onto trailing words with the real Inter advances --
  0.2324 measured vs "AntSeed."'s 0.240 width share.  Nearest-colour
  classification fails here (pale green is close to white): 0.43, not 0.24.
- **Action:** scene copy must span the hero (`width:100%; max-width:none`) or it
  inherits `.wrap`'s centered 1140px box and sits too far right at 1440 px; the
  scene stacks below **900px** (the copy is nearly as tall as the scene at
  narrower widths).  `ARTWORK` composition and format stay separate decisions:
  `hero_layout` picks the composition, `wants_raster` picks the format.
  Known limits: inpaint smudges where the reference's copy was, and the 1586px
  source (1.82× on Retina) -- benchmark better inpainting / ask for a larger
  artwork upload before generalizing.
- **Role instability, live:** the fresh live extraction returned all six benefit
  lines as `other` (the fixture had values `other` + sub-labels `tagline`),
  which broke two things the fixture hid: `_benefit_pairs` required a `tagline`
  sub, and `_drop_artwork_labels` then used the eyebrow as the only tagline
  anchor, collapsing the copy-column edge and swallowing the row's right-hand
  items.  Pairs are now role-agnostic (two short stacked lines in a column) and
  are identified **before** the label filter and protected from it; the polarity
  check renders the all-`other` shape through `_hero_html`.  Replaying the live
  job's own cache (`e47860139c4d`) renders all three benefit items.
- **Ordering gotcha:** the scene's content edits (lifting the benefit row and
  blanking its original out of the `designs/<id>.json` blank list) depend on the
  hero being flat, and the flat/photo verdict lives in the runner, not in
  `generate`.  `write_all` therefore takes `scene_ok`; measuring after writing
  made photographic montiva lift and blank its own features band (art master
  3.58 → 4.27, caught by the fixture bound).  Any future scene-only edit must go
  through the same gate, not into `build_content` unconditionally.

## 2026-10-03 — Validation gaps in the illustration work, fixed
- **What:** a review of the first milestone found four gaps, all closed:
  (1) the Retina budget assumed a 560 px figure while the stacked layout let it
  grow to 816 px at an 880 px viewport — the page CSS now caps the figure at
  `generate.HERO_FIGURE_MAX_CSS` and `doctor polarity` fails if the cap and
  `heroart.HERO_CSS_SPLIT` drift, so 1.43× is the true worst case;
  (2) a sparse erased label could score under the 28/255 mean warning
  (background dilutes the rectangle) — `label_fidelity` now returns
  `(mean, p95)`, and the polarity test proves a thin-stroke caption erased reads
  20 mean but 200 p95;
  (3) the asset inventory claimed `hero-artwork` for band content a split page
  no longer shows — outside the figure is now `artwork-master`, with a direct
  guard;
  (4) the split path had no end-to-end fixture — `dashboard` is now a permanent
  fixture (`studio/fixtures/dashboard-ref.png` + `dashboard-blocks.json`, whose
  sections were re-merged from the saved job because `raw-blocks.json` omits
  them) and pins layout, the 1120 px budget, all 33 labels and their worst
  mean/p95.
- **Why / evidence:** `gate --no-env` with the final tree → polarity all pass,
  fixtures **4/4**, regress 2.71/2.76/2.99, STATE consistency pass.  A fresh
  live upload (real vision call, no cache) also finished split with all 33
  labels (8.0 mean / 23.4 p95).  Viewport matrix 390/834/880/881/1440/1920 px:
  `scrollWidth == innerWidth` at every width, figure 350/560/560/381/498/498 px,
  never above the cap, aspect preserved.
- **Action:** the figure's label-derived bounds still clip a small unlabelled
  sliver (the dashboard's leftmost rack, ~50 stage px) — do not "fix" it by
  pulling the crop left of the copy floor; that would bake the reference's own
  copy into the panel.  Pixel segmentation is the sanctioned path.

## 2026-10-03 — An illustration's labels are artwork, not copy to blank
- **What:** the tracer's exclusion rects used to cover **every** text block, so
  an illustration's own labels were blanked out of both the traced SVG and the
  raster export.  Replaying the saved dashboard job `d9d0855d6cf5` (1586×992)
  showed the cost: all 33 `part: artwork` blocks (region names, table values,
  "Secure private tunnel") were inpainted away and the export carried fill
  smears in their place.  `write_all` now blanks only the blocks the page
  actually replaces with DOM (`page_blocks` minus the hero labels
  `_drop_artwork_labels` keeps out); a flat hero with enough artwork labels
  clear of the copy column gets its own figure region (`generate.hero_figure`),
  shown whole beside the copy (`gen-page.mjs` + `.hero.hero-split`) with the
  raster cropped to it (`heroart.export_from_prepared(figure=…)`) instead of
  `object-fit: cover` slicing the label sides off.  A continuous-tone hero is a
  photograph: `runner._hero_art` declines the split and it stays full-bleed.
- **Why / evidence:** the replay job `1fcec257a861` retained all 33 labels
  (`hero_label_max` 17.3/255) and exported the figure at 782×907 (the old job
  shipped a full-width 1586×907 band with the labels destroyed); the built page
  has `scrollWidth == innerWidth` at 500 and 1440 CSS px.  Fixtures pass with
  art means 2.12 / 3.58 / 2.12 — 0.09–0.14 above the previous run, because the
  label pixels are no longer **masked out of** the score; the old numbers were
  measured through a mask that hid the removed content.
- **Action:** do not put a `part: artwork` block into `text_rects`, and do not
  "restore" the old numbers by masking labels out of `hero_fidelity`.  The
  export target is now 2× a 1920 px desktop (`EXPORT_TARGET_WIDTH` 3840, was
  2048); `resolution_gap` warns per job when the source cannot reach it
  (`hero_scale`).

## 2026-10-03 — The hero band must describe the hero, not the frame
- **What:** a real dark-dashboard upload (1586×992, job `57e872a21037`) shipped a
  backdrop that "needs work to match the original image": the artwork was
  oversized, re-centred, and a **second nav bar** was ghosted inside the hero.
  `hero_band` returned `[0, 768]` — the whole stage, including 128 px of ingest
  letterbox and the mockup's own header. Its aspect was **1.33** while the hero
  box's is **1.75**, so `cover` magnified the art **1.37× at 1400 px and 1.88× at
  1920 px** and cropped a quarter of it away.
- **Why / evidence:** `hero_band` only stops at the next section when there *is*
  one below the hero; a hero-only page has none, so the band ran to the bottom.
  Measured the rendered box with `getBoundingClientRect` (1000×700 → 1.373) and
  derived 1400×800 → 1.75 from the CSS (`padding clamp(80,12vw,140)` +
  `min-height clamp(460,70vh,680)`, copy capped at 520 px so height stops growing
  with the viewport). New band `[112, 697]` = 585 px = 1024/1.75.
- **Action:** the band starts below the mockup's header (capped at +12 px so a
  loose model box cannot crop art) and is trimmed to `HERO_BAND_ASPECT` (1.75),
  symmetrically about the hero copy. **Only shrinking** — reaching the target from
  below would pull in the next section. Guarded by two `doctor polarity` checks
  and the "loose header box cannot crop the hero art" guard.

## 2026-10-03 — Rasterise when the upload carries more resolution than the stage
- **What:** the colour score (113) sat just under the 150 cut, so this design kept
  a traced SVG bounded by the 1024 px stage — while its upload had **1.55×** more
  linear detail. Full-bleed at 1400 px is therefore magnified 1.37× and at
  1920 px 1.88×; a raster built from the upload is ~1:1 at 1400 px and downscaled
  above that. `heroart.wants_raster` now has a **second, independent arm**:
  `native_factor` (== `1/stage_scale`, capped at 3) ≥ `MIN_NATIVE_GAIN` (1.2).
- **Why / evidence:** measured artwork-region p95 on the real traced SVG = **17.3**
  vs **4.7** for a raster of the same hero — but the p95 of the *flat posters we
  accept* is 15.3–26.0, so the colour score and the banding error were **not** the
  discriminator. Resolution was. This is why no tracer knob was retuned.
- **Action:** `hero_kind == "photographic"` no longer means "photographic" — read
  `hero_reason` (now recorded per job). Flat art uploaded at the stage's own width
  (m = 1.0) still keeps the traced SVG; a wider flat upload ships the raster too.
  That is the accepted trade of "use the upload's resolution when it exists".

## 2026-10-03 — The mean hides the artwork; report p95 over the pixels the eye reads
- **What:** `art_score` read **1.37** on that upload while the artwork the eye
  actually reads (7% of the art region, once the flat near-black ground is
  excluded) was **6.84** mean / **23.3** p95. The mean is dominated by whatever is
  flat and large, so it could not see the posterised glow the user complained
  about — and every metric in the gate was green.
- **Why / evidence:** `verify.artwork_mask` selects pixels that depart from the
  design's **median** luminance by > 14 (polarity-agnostic, so a light page selects
  its ink). `art_p95` is the 95th percentile of the per-pixel diff there; each
  fixture now pins `art_p95_max` (measured 21.0 / 39.0 / 21.0), and
  `hero_fidelity` returns a p95 too. This is the same lesson as the chroma note
  below ("p95 is the number that matters"), now enforced rather than noted.
- **Action:** when a score looks fine but the page does not, compute the p95 over
  the artwork before believing the mean. A new fixture bound needs its measured
  value recorded in `docs/STATE.json` `verification.fixture_bounds` in the same
  commit — `doctor regress` compares them.

## 2026-10-03 — `artifacts["svg"]` advertised a file that was never written
- **What:** `runner` set `artifacts["svg"] = "<jid>/<jid>.svg"`, but the tracer
  writes the SVG into `workspace/pipeline/` and `_package` only put it *inside the
  zip*. Nothing ever copied it into the job dir, so any route serving that path
  404'd (the artifact is exposed through the API's file route).
- **Why / evidence:** `os.path.exists(job/<jid>.svg)` → False while
  `workspace/pipeline/<jid>.svg` exists (3.5 MB on that job).
- **Action:** `_package` now copies the traced SVG beside the page, like the hero
  webp. When adding an `artifacts[...]` entry, make sure the file is actually
  placed in the job dir — the map is a promise the API serves.

## 2026-10-02 — A photographic hero ships a raster, and a RAW crop of it ghosts the mockup's own text
- **What:** the no-raster rule is relaxed for a photographic hero. The page now
  ships a fixed-resolution WebP (inlined as a data URI) instead of the traced
  SVG, chosen by measurement in `studio/backend/app/heroart.py`. The first
  implementation cropped the hero band straight out of the reference — and the
  rendered page showed the mockup's own **nav bar, headline, buttons and section
  headings ghosting behind the real DOM copy**, because the reference is a
  picture *of a page*.
- **Why / evidence:** looked at the built page (screenshot), not a score — every
  numeric metric was green. `art_score` could never see it: it masks the text
  rects and measures the SVG. The fix is to export from the tracer's
  **prepared** image (`mkart --prepared-out`), which is the same
  text-inpainted pixels the SVG master is built from.
- **Action:** never crop the raw reference for anything that lands on the page.
  Any future raster export must go through `mkart --prepared-out`. The review
  prompt (`doctor critique`) was updated to call a ghosted backdrop a defect, so
  the loop can catch a regression here.

## 2026-10-02 — Export the raster from the UPLOAD, not the normalised reference
- **What:** `normalize()` aspect-fits every upload onto the 1024×768 stage, and
  that is lossy: a real upload went **1672×941 → 1024×576** (61% of its linear
  detail) before it was ever traced. A raster exported from the normalised
  reference therefore bakes in the ingest downscale.
- **Why / evidence:** `heroart.native_reference` writes a stage-sized reference
  at the upload's own scale and returns a single factor `m`
  (`native = stage * m`), so the tracer's existing config carries over with the
  box and rects multiplied by `m`. Measured: montiva `m`=1.633 (1672×1254
  canvas), anthotype 1.732, a 1024×768 upload 1.0. The prepared image then has
  the upload's real pixels, not 1024 of them.
- **Action:** the generated `designs/<id>-hi.json` is the mechanism — point
  `mkart` at it with `--prepared-out` **and `--up 1`** (the reference is already
  at full scale; the default `up=2` would upscale it for nothing). Guarded by
  `doctor polarity` ("hero raster is built from the upload at its own
  resolution", 1600×800 source → 1600 px export, where a reference crop gives
  1024).

## 2026-10-02 — Photographic detection: a FIXED sample grid, not an aspect-derived one
- **What:** the signal is how many distinct 5-bit colours survive area-averaging
  the hero band. Deriving the sample width from the band's aspect made the score
  drift **60%** for the same artwork; a fixed `(64, 32)` grid is stable.
- **Why / evidence:** over every unique reference in the repo, flat art scores
  **29–91** and photographs **245–358** (2.7× gap). `PHOTO_DISTINCT = 150` sits
  between them with ~60% margin either way.
- **Action:** the cut is deliberately biased toward rasterising — a misclassified
  flat design becomes a WebP that looks identical (cheap), while a misclassified
  photograph goes back to the smeared backdrop this exists to fix (expensive).
  A synthetic test must use **low-frequency colour noise**, not a smooth
  gradient: a gradient averages down to a handful of colours and is not a
  photograph (`doctor polarity` guards this).

## 2026-10-02 — `hero_fidelity` must mask the removed rects, like `art_score` does
- **What:** the shipped raster is deliberately text-removed, so comparing it to
  the *raw* reference band penalises exactly the removal that makes it usable:
  montiva read **8.73** unmasked vs **1.60** over the artwork. `hero_fidelity`
  now takes the tracer's `_removed_mask`.
- **Why / evidence:** the same reasoning as `art_score` masking `text` — inside
  those rects the reference holds the mockup's type, which the page replaces
  with DOM.
- **Action:** each fixture pins `hero_kind` + `hero_max`, so a page that stopped
  rasterising, or whose export drifted, fails the gate instead of passing on
  `score_max` (which measures the SVG master such a page no longer shows).

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
