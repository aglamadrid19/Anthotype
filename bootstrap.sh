#!/bin/zsh
# One-time setup for this bundle.  Safe to re-run.
#
# Installs the two things the pipeline needs that are NOT vendored here (they are
# 150-200 MB each, so shipping them would dwarf the bundle):
#    * a Python venv with numpy / pillow / scipy / scikit-image
#    * each variant's node_modules (astro)
# Plus potrace, if it is missing.
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

echo "== node_modules =="
for v in a b c; do
  d="$ROOT/sites/variant-$v"
  if [[ -d "$d/node_modules/astro" ]]; then
    echo "  variant-$v: present"
  else
    echo "  variant-$v: installing..."
    (cd "$d" && npm install --silent)
  fi
done

echo
echo "done.  Next:"
echo "  cd pipeline && ./qa/verify.sh            # score all three (expect 2.71 / 2.76 / 2.99)"
echo "  $ROOT/preview/start-persistent.sh 4173  # then open http://127.0.0.1:4173/"
