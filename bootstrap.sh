#!/bin/zsh
# One-time setup.  Safe to re-run.
#
# Installs the two things the pipeline needs that are NOT vendored here (they are
# 150-200 MB each, so shipping them would dwarf the repo):
#    * a Python venv with numpy / pillow / scipy / scikit-image
#    * each design's node_modules (astro)
# Plus potrace, if it is missing.
#
# The design list comes from pipeline/designs/*.json, so a new design is picked
# up automatically with no edit here.
set -e
cd "$(dirname "$0")"
ROOT=$PWD

echo "== potrace =="
if command -v potrace >/dev/null 2>&1; then
  echo "  present: $(potrace --version | head -1)"
else
  echo "  MISSING.  Install with:  brew install potrace"
  echo "  (it is the only external binary the art tracing needs)"
fi

echo "== python venv =="
if [[ -x "$ROOT/.venv/bin/python" ]] && "$ROOT/.venv/bin/python" -c 'import numpy, PIL, scipy, skimage' 2>/dev/null; then
  echo "  present: $ROOT/.venv"
else
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install --quiet --upgrade pip
  "$ROOT/.venv/bin/pip" install --quiet numpy pillow scipy scikit-image
  echo "  created: $ROOT/.venv"
fi
"$ROOT/.venv/bin/python" -c 'import numpy,PIL,scipy,skimage; print("  numpy",numpy.__version__,"pillow",PIL.__version__)'

NODE="$(command -v node || true)"
[[ -n "$NODE" ]] || NODE="$(ls -d ~/.nvm/versions/node/*/bin/node 2>/dev/null | sort -V | tail -1)"
[[ -n "$NODE" ]] || { echo "no node found" >&2; exit 1 }
export PATH="${NODE:h}:$PATH"

echo "== node_modules =="
DESIGNS=(${(f)"$(node pipeline/lib/designs.mjs list)"})
[[ ${#DESIGNS[@]} -gt 0 ]] || { echo "  no designs configured (pipeline/designs/*.json)" >&2; exit 1 }
for v in $DESIGNS; do
  d="$(node pipeline/lib/designs.mjs site "$v")"
  if [[ -d "$d/node_modules/astro" ]]; then
    echo "  $v: present"
  else
    echo "  $v: installing in $d ..."
    (cd "$d" && npm install --silent)
  fi
done

echo
echo "done.  Next:"
echo "  cd pipeline && ./build.sh && ./qa/verify.sh   # build + score every design"
echo "  $ROOT/preview/start-persistent.sh 4173        # then open http://127.0.0.1:4173/"
