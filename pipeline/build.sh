#!/bin/zsh
# Rebuild every configured design end to end.
#
#   qa/mkart.py   ref PNG -> <name>.svg      (only if you changed the art params)
#   gen-page.mjs  art + content -> <name>-full.html / <name>-static.html
#   to-astro.mjs  page -> <site>/src/pages/index.astro
#   npm run build -> <site>/dist/index.html  (the scored artifact)
#
# Designs are discovered from pipeline/designs/*.json -- there is no hardcoded
# list here, so adding a design needs no edit to this script.
#
# NOTE: gen-a.mjs / gen-b.mjs / gen-astro.mjs are LEGACY hand-art generators and
# are deliberately not invoked -- they predate the mkart pipeline and would
# overwrite the traced art.  Use `qa/mkart.py <name>` to regenerate art.
set -e
cd "$(dirname "$0")"

# Resolve node without hardcoding an nvm path.
if [[ -z "$NODE" ]]; then
  NODE="$(command -v node || true)"
  [[ -n "$NODE" ]] || NODE="$(ls -d ~/.nvm/versions/node/*/bin/node 2>/dev/null | sort -V | tail -1)"
fi
[[ -n "$NODE" ]] || { echo "no node found" >&2; exit 1 }
export PATH="${NODE:h}:$PATH"

# Build the pages, then build each design's Astro site.  `--no-site` stops after
# page generation (useful when iterating on the CSS layer without an npm run).
BUILD_SITE=1
[[ "$1" == "--no-site" ]] && BUILD_SITE=0

DESIGNS=(${(f)"$(node lib/designs.mjs list)"})
[[ ${#DESIGNS[@]} -gt 0 ]] || { echo "no designs configured in pipeline/designs/" >&2; exit 1 }

for V in $DESIGNS; do
  node gen-page.mjs "$V"
  node to-astro.mjs "$V"
done

if (( BUILD_SITE )); then
  for V in $DESIGNS; do
    SITE="$(node lib/designs.mjs site "$V")"
    echo "building site for $V:  $SITE"
    (cd "$SITE" && npm run build)
  done
fi
echo "done: ${#DESIGNS[@]} design(s): $DESIGNS"
