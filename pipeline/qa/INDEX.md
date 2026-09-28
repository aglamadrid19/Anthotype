# QA tools

Every script here is a real tool used to get the pages to their current
accuracy. They are kept because they encode *measured* conclusions — most
exist to answer one question that was expensive to answer.

## The ones that matter

- `_env.py` — Resolves python/node/chrome without hardcoded paths, and locates a design's site via `designs/<name>.json`. Imported by the other tools.
- `_bootstrap.py` — Re-execs a tool under the venv python when numpy is missing, so `python qa/<tool>.py` works with the system python3.
- `artfloor.py` — Art-only floor: band-paint oracle vs the real render. Is the tracer the bottleneck?
- `compare.py` — Reference-vs-render metrics, per-region breakdown, side-by-side and amplified diff images.
- `downsample.py` — 2x screenshot -> 1024x768 with PIL Lanczos. The scaler choice changes the score.
- `glyph.py` — Trace a small glyph/brand-mark region into a standalone inline SVG.
- `mkart.py` — THE ART TRACER — bands the artwork by luminance and traces each band to SVG paths via potrace.
- `netcheck.py` — Assert the built page makes no network requests. Has --selftest so a zero is trustworthy.
- `newdesign.py` — Scaffold a COMPLETE new design (config + reference + content + page CSS + Astro site) from a reference PNG. Start here for a new design.
- `potrace_util.py` — Shared potrace wrapper. Note the polarity rule in its docstring.
- `svg2png.py` — Render a standalone SVG to PNG. Used by the art-only scorers.
- `sweep_up.py` — Score-vs-size sweep for the traced art: (up, bands, turdsize) -> mean + bytes.
- `textrects.py` — Auto-derive the text-exclusion rectangles from a DOM-only render.
- `tune.py` — Coordinate descent over any CSS property, through the real pipeline (gen-page + qa.sh).

## Everything else

Investigation tools. Run any with `python qa/<tool>.py --help`.

- `align2.py` — Search (scale, dx, dy) mapping src image region onto dst region to minimise diff.
- `artgap.py` — Where does the traced render lose to the band-paint oracle? Classifies each art-window pixel by its reference luminance and shows the render error and the oracle error per luminance bucket, so the loss can be attributed to bright specks vs flat fields.
- `artprobe.py` — Structural probe of dark-teal art: bright ink masks, tile detection, silhouette rows.
- `artrecon.py` — How close can the *banded trace* itself get? Paint the band masks at native resolution (what potrace reconstructs, minus its curve fitting) and score that against the reference.
- `artscore.py` — Fast art-only score: generate a variant's SVG with given params, render it standalone, and compare the art window against the reference.
- `artsweep.py` — Sweep vectorization parameters and score each against the reference.
- `batch.py` — Fast multi-candidate renderer for QA/tuning.
- `bgfit.py` — Fit the page background field: solve additive radial gradients from residual.
- `bgfit2.py` — Fit a small set of radial gradients to the page background, then *emit CSS and verify it empirically* -- the trick bgfit.py missed, which is that stacked CSS radial-gradients composite (src-over) rather than add, so a least-squares field fit does not survive the round-trip to CSS.
- `bgprof.py` — Background gradient profile: compare ref vs render luminance on a coarse grid.
- `boxopt.py` — Sweep the art trace box (and re-trace) for a variant, scoring in-page.
- `boxsweep.py` — Sweep art trace boxes (x0,y0,x1,y1) per variant, scoring in-page.
- `boxsweep2.py` — Sweep full-frame art trace boxes with live text excluded.
- `brandfit.py` — Measure the brand row's ink bboxes in ref and render and report offsets.
- `brandglyph.py` — Trace a variant's brand mark (icon/hex) from the reference and splice the resulting inline <svg> into content.json's markup for that variant.
- `dots.py` — Detect bright vertex dots (blobs) inside a region of the reference render.
- `edges.py` — Edge-structure map: Sobel magnitude + ridge points of the art region.
- `elemcmp.py` — Tight stacked (REF / RENDER / DIFF) zooms for each page element.
- `elements.py` — Per-element geometry comparison (text blocks + CTA), using windows that avoid the artwork so measurements are not contaminated by pod/route glow.
- `fit.py` — Coordinate search for an overlay image's (scale, dx, dy) minimising diff to the reference inside an artwork window.
- `fitmap.py` — Find the scale/offset that best maps a large-canvas render onto a reference.
- `fonttest.py` — Compare candidate font stacks for the left column against the reference.
- `ftune.py` — Coarse-to-fine coordinate-descent CSS tuner (full-frame objective).
- `ftune_win.py` — (no docstring)
- `geom.py` — Render <variant>-full.html with a CSS override and report left-column ink bands + per-window element geometry.
- `glyphbox.py` — Per-glyph column segmentation of a text band: fit font-size / letter-spacing.
- `glyphfit.py` — Grid-search glyph tracer parameters against the reference crop.
- `glyphopt.py` — End-to-end optimizer for a traced brand glyph.
- `greedy.py` — Greedy element-wise acceptance on the full-frame objective.
- `grid.py` — Overlay a labelled coordinate grid on a crop of ref/render, for reading geometry.
- `gridimg.py` — Overlay a labelled coordinate grid on an image crop for manual reading.
- `gridtune.py` — Fast grid tuner using batch rendering (one Chrome pass per 8 candidates).
- `heat.py` — Coarse-grained (cell) diff heatmap with the worst cells ranked.
- `heatblocks.py` — Block-wise diff heatmap (text) between ref and render.
- `hexfit.py` — Fit the B hexagon's exact geometry against the reference.
- `measure.py` — Measure ink bounding boxes in given windows for ref/render of a variant.
- `met.py` — Measurement-based type fitter.
- `mkbrand.py` — Build a variant's brand mark as real inline SVG and splice it into content.json.
- `opt.py` — Coordinate-descent optimizer over CSS declarations, scored on a region.
- `oracle.py` — Fast (no-render) oracle: band-quantisation floor for a given (up, bands, minpx).
- `overlay.py` — Channel overlay: reference ink -> magenta, render ink -> green.
- `polish.py` — Full-frame polish pass: tune colour / weight / spacing / shadow of one element.
- `scan.py` — Row-by-row numeric scan of a region: silhouette extents (green ink) and bright strokes (lum), so geometry can be read instead of eyeballed.
- `shape.py` — Row-wise ink extent + luminance profile of an art region.
- `shoot.py` — Robust headless-Chrome screenshot -> sRGB 1024x768 PNG.
- `solve.py` — Measure-and-solve type fitter.
- `sweep_parts.py` — Sweep body-part mesh/rotation/scale parameters and score tight part regions.
- `sweep_scale.py` — Sweep the ant part scales/positions plus mesh, scoring tight part regions.
- `tiles.py` — Detect bright rounded-square provider tiles in an art region.
- `tiles2.py` — Tile detector v2: tiles have a bright outline ring; use luminance peaks.
- `tracefid.py` — Potrace fidelity: rasterise the emitted band paths and compare directly to the band-paint oracle (both on the same flat background, same resolution).
- `traceicon.py` — Trace a small glyph region of a reference into a compact inline SVG snippet.
- `tune2.py` — Coordinate-descent tuner (variant-generic) using geom.render.
- `typeref.py` — Measure left-column type bands in a reference/render PNG.
- `typetune.py` — Coordinate-descent tuner over *type* CSS vars for one element window.
- `vectorize.py` — Vectorize a reference-art region into layered SVG paths (genuine code output).
- `winref.py` — Print reference window geometry for a variant (same windows as geom.py).

## Typical loop

```sh
python qa/mkart.py a      # trace the art
node gen-page.mjs a       # compose the page
./qa.sh a                 # render + score the working page
./build.sh                # build every design's Astro site
./qa/verify.sh            # score each built dist/ against its target
```

The design list comes from `../designs/*.json` (via `../lib/designs.mjs`), so
these commands take a design name and cover every configured design by default.

