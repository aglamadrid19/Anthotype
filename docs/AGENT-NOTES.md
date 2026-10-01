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

