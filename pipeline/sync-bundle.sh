#!/bin/zsh
# Sync the LIVE working tree into the portable deliverable bundle.
#
#   live:   /Volumes/CrucialX10/anthosting/{pipeline,variant-{a,b,c},preview}
#   bundle: /Volumes/CrucialX10/codex/2026-09-27/i-n/outputs/anthosting-coming-soon/
#
# The bundle is the hand-off artifact: it must contain everything needed to
# rebuild and re-score the three pages from a neutral path, with no absolute
# paths pointing back into this machine's layout.
#
# usage: ./sync-bundle.sh
set -e
LIVE=/Volumes/CrucialX10/anthosting
BUNDLE=/Volumes/CrucialX10/codex/2026-09-27/i-n/outputs/anthosting-coming-soon
DOCS=/Volumes/CrucialX10/codex/2026-09-27/i-n/outputs

[[ -d "$BUNDLE" ]] || { echo "no bundle at $BUNDLE" >&2; exit 1 }

# Mirror, don't accumulate.  A copy-only sync leaves files behind when a source
# path is renamed or dropped (a stale sites/*/public/design-reference.png once
# survived several syncs this way, and the bundle is meant to be exactly
# reproducible from the live tree).  Clear everything except the git repo and the
# hand-authored bundle README, then recreate the directory skeleton below.
python3 - "$BUNDLE" <<'PRUNE'
import os, shutil, sys
bundle = sys.argv[1]
keep = {'.git', 'README.md'}
for name in os.listdir(bundle):
    if name in keep:
        continue
    p = os.path.join(bundle, name)
    if os.path.isdir(p):
        shutil.rmtree(p)
    else:
        os.remove(p)
PRUNE

mkdir -p "$BUNDLE/pipeline/qa" "$BUNDLE/pipeline/fonts" \
         "$BUNDLE/preview/diff" "$BUNDLE/docs" \
         "$BUNDLE/sites/variant-a/src/pages" "$BUNDLE/sites/variant-b/src/pages" \
         "$BUNDLE/sites/variant-c/src/pages"

# --- pipeline: generators, art, vendored fonts, QA tools, refs -------------
for f in gen-page.mjs to-astro.mjs build.sh qa.sh content.json; do
  cp "$LIVE/pipeline/$f" "$BUNDLE/pipeline/$f"
done
# Note the two naming schemes: art is dotted (`a.svg`, `a.page.css`) while the
# generated pages are hyphenated (`a-full.html`, `a-static.html`).  Both must be
# listed explicitly -- building `$v.$ext` for the pages silently matches nothing.
for v in a b c; do
  for f in "$v.svg" "$v.css" "$v.page.css" "$v-full.html" "$v-static.html"; do
    [[ -f "$LIVE/pipeline/$f" ]] && cp "$LIVE/pipeline/$f" "$BUNDLE/pipeline/$f"
  done
done
mkdir -p "$BUNDLE/pipeline/fonts"
cp "$LIVE"/pipeline/fonts/*.woff2 "$BUNDLE/pipeline/fonts/"

# Per-design config (reference path, trace box, text rects, tracing params).
mkdir -p "$BUNDLE/pipeline/designs"
cp "$LIVE"/pipeline/designs/*.json "$BUNDLE/pipeline/designs/" 2>/dev/null || true

# Repo hygiene file lives in the live tree so both stay identical.
cp "$LIVE/pipeline/../.gitignore" "$BUNDLE/.gitignore" 2>/dev/null || true

# QA tooling (mkart + scorers + refs).  Keep the dirs clean of transient output.
mkdir -p "$BUNDLE/pipeline/qa"
find "$LIVE/pipeline/qa" -maxdepth 1 -type f \( -name '*.py' -o -name '*.sh' -o -name 'ref-*.png' \) \
  -exec cp {} "$BUNDLE/pipeline/qa/" \;
find "$LIVE/pipeline/qa" -maxdepth 1 -type f -name '*.mjs' -exec cp {} "$BUNDLE/pipeline/qa/" \;
cp "$LIVE/pipeline/qa/INDEX.md" "$BUNDLE/pipeline/qa/INDEX.md" 2>/dev/null || true

# --- preview server ---------------------------------------------------------
mkdir -p "$BUNDLE/preview/diff"
cp "$LIVE/preview/serve.py" "$LIVE/preview/index.html" "$BUNDLE/preview/"
cp "$LIVE/preview/start-persistent.sh" "$LIVE/preview/daemonize.py" "$BUNDLE/preview/"
cp "$LIVE"/preview/diff/*.png "$BUNDLE/preview/diff/" 2>/dev/null || true

# --- sites: sources + astro config + built dist -----------------------------
for v in a b c; do
  d="$BUNDLE/sites/variant-$v"
  mkdir -p "$d/src/pages"
  cp "$LIVE/variant-$v/package.json" "$LIVE/variant-$v/astro.config.mjs" "$d/"
  cp "$LIVE/variant-$v/src/pages/index.astro" "$d/src/pages/"
  # NB: no per-site design-reference.png -- it was an unreferenced duplicate of
  # pipeline/qa/ref-<v>.png (4.8 MB across the three sites).
  rm -rf "$d/dist"
  cp -R "$LIVE/variant-$v/dist" "$d/dist"
done

# --- bundle-level scripts ---------------------------------------------------
cp "$LIVE/pipeline/bootstrap.sh" "$BUNDLE/bootstrap.sh"
cp "$LIVE/pipeline/sync-bundle.sh" "$BUNDLE/pipeline/sync-bundle.sh"
chmod +x "$BUNDLE/bootstrap.sh" "$BUNDLE/pipeline/sync-bundle.sh"

# --- docs -------------------------------------------------------------------
mkdir -p "$BUNDLE/docs"
cp "$DOCS/HANDOFF.md" "$BUNDLE/docs/"
cp "$DOCS/STATE.json" "$BUNDLE/docs/"
cp "$DOCS/README.md" "$BUNDLE/docs/README-outputs.md"

echo "synced -> $BUNDLE"
du -sh "$BUNDLE"
