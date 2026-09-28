# START HERE

**AntHosting coming-soon pages.** Three pages that are *code* (Astro + DOM text +
CSS + SVG geometry, no raster images) matching three reference design PNGs.

**Status: complete and verified.** Worst score 3.11 mean, from 12.17-16.92 at the
conversation's start.

## Read this first

1. **`HANDOFF.md`** — the full route: what was tried, what worked, why, the
   landmines, and where the remaining error lives. Everything you need.
2. **`STATE.json`** — machine-readable current state (scores, params, sizes).

## In one minute

- Pipeline: `/Volumes/CrucialX10/anthosting/pipeline`
- Sites: `/Volumes/CrucialX10/anthosting/variant-{a,b,c}`
- The art is **traced from the reference** (`pipeline/qa/mkart.py`), not drawn.
- **The #1 fact: potrace fills the BLACK / bit-0 region.** Feed it `(~mask)*255`,
  never the mask. Get this wrong and the art layer silently becomes an opaque
  plate while the page still *looks* fine.
- Current scores: **A 2.77 · B 2.90 · C 3.11** (mean abs pixel diff vs
  reference, lower is better).

## Verify it in two commands

```sh
export PATH="/Users/alamadrid/.nvm/versions/node/v22.23.2/bin:$PATH"
cd /Volumes/CrucialX10/anthosting/pipeline
./qa/verify.sh        # scores each variant's built dist/index.html; PASS/FAIL
```

## Look at it

```sh
/Volumes/CrucialX10/codex/2026-09-27/i-n/work/.venv/bin/python \
  /Volumes/CrucialX10/anthosting/preview/serve.py 4173
#   http://127.0.0.1:4173/       gallery
#   http://127.0.0.1:4173/a/     variant A   (b/, c/ likewise)
```
Or open `variant-{a,b,c}/dist/index.html` directly — no server needed.
(Default browser is Safari, not Chrome.)

## Regenerate the artwork

```sh
PY=/Volumes/CrucialX10/codex/2026-09-27/i-n/work/.venv/bin/python
for v in a b c; do
  $PY qa/mkart.py $v && node gen-page.mjs $v && ./qa.sh $v
  node to-astro.mjs $v && (cd ../variant-$v && npm run build)
done
```
Verified deterministic: this reproduces the shipped SVGs byte-for-byte.
Current params live in `PARAMS` at the top of `qa/mkart.py`.

## Do NOT

- Re-run `gen-a.mjs` / `gen-b.mjs` — legacy hand-art generators that overwrite the
  good `{v}.svg`.
- Rewrite potrace's path coordinates — compose with nested `<g>`.
- Assume `astro dev` works — it hangs on this art size. Serve `dist/` statically.
- Re-test the exhausted list in `HANDOFF.md` §4 (fonts, blur, band edges, type
  metrics). It is a long list and it is all measured.
