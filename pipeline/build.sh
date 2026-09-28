#!/bin/zsh
# Rebuild every variant end to end: art SVG -> self-contained page -> Astro.
#
#   qa/mkart.py   ref PNG -> <v>.svg      (only if you changed the art params)
#   gen-page.mjs  art + content -> <v>-full.html / <v>-static.html
#   to-astro.mjs  page -> sites/variant-<v>/src/pages/index.astro
#   npm run build -> sites/variant-<v>/dist/index.html   (the scored artifact)
#
# NOTE: gen-a.mjs / gen-b.mjs / gen-astro.mjs are LEGACY hand-art generators and
# are deliberately not invoked -- they predate the mkart pipeline and would
# overwrite the traced art.  Use `qa/mkart.py <v>` to regenerate art.
set -e
cd "$(dirname "$0")"

# Resolve node without hardcoding an nvm path.
if [[ -z "$NODE" ]]; then
  NODE="$(command -v node || true)"
  [[ -n "$NODE" ]] || NODE="$(ls -d ~/.nvm/versions/node/*/bin/node 2>/dev/null | sort -V | tail -1)"
fi
[[ -n "$NODE" ]] || { echo "no node found" >&2; exit 1 }
export PATH="${NODE:h}:$PATH"

for V in a b c; do
  node gen-page.mjs "$V"
  node to-astro.mjs "$V"
done
echo "pages generated; now build each site:  for v in a b c; do (cd ../variant-\$v && npm run build); done"
