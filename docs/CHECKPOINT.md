# CHECKPOINT

State at the end of the session that packaged this repo. Read this first, then
`README.md` for how the pipeline works and `docs/HANDOFF.md` for how it got here.

## What this is

Turn a flat design PNG into a **real, code-native website** — DOM text, CSS and
traced SVG geometry, no raster images in the output. The reference PNG is input
to the pipeline, not an embedded asset.

Three worked examples (A/B/C) demonstrate it end to end and serve as the
regression suite.

## Status: done and pushed-ready

| | score (mean abs pixel diff, lower better) | payload |
|---|---|---|
| A | **2.71** | 6.4 MB / 870 KB gz |
| B | **2.76** | 3.4 MB / 523 KB gz |
| C | **2.99** | 7.7 MB / 1051 KB gz |

`pct>30` = 1.13% / 1.59% / 1.57%. Stable to ±0.01 over repeated runs.

- Branch `main`, **4 commits**, working tree **clean**, 121 files.
- No git remote is configured. No `gh` CLI is installed — **push is the user's
  step** (`git remote add origin <url> && git push -u origin main`).
- Verified from a fresh `git clone`: `./bootstrap.sh`, regenerate pages, build
  all three Astro sites, `qa/verify.sh` → PASS. The tracer also reproduces the
  committed `{a,b,c}.svg` byte-identically from the committed references.

## Design-agnostic: a design name is the only input

The pipeline knows nothing about A/B/C. `pipeline/lib/designs.mjs` enumerates
`pipeline/designs/*.json`, and `build.sh`, `bootstrap.sh`, `qa/verify.sh` and the
preview gallery all ask it — so adding a design needs no edits to any of them.

Adding a design is one command:

```sh
python qa/newdesign.py <name> path/to/design.png    # config + ref + content + site
python qa/mkart.py <name> --out <name>.svg          # trace the art
node gen-page.mjs <name> && node to-astro.mjs <name>
(cd ../sites/variant-<name> && npm install && npm run build)
./qa/verify.sh <name>
```

`designs/<n>.json` carries everything per-design: `ref`, `site`, `content`
(a `content.json` key or a standalone file), `target` (the score `verify.sh`
enforces), `box`, `text` rects, tracing `params`, and optional `regions`.

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

**The CTA has no destination.** `href="#waitlist"`, and no element with that id
exists in any variant, so the button does nothing. The design PNGs specify only
its appearance. Set the real URL in `pipeline/content.json` (the `href` lives
inside each variant's `markup` string).

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
