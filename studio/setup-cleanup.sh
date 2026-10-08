#!/bin/zsh
# Optional: create the external LaMa environment the scene cleanup uses.
#
#   ./studio/setup-cleanup.sh
#
# It is deliberately separate from the studio venv (torch is gigabytes), and it
# is optional: without it, scene jobs keep the tracer's nearest fill and say so.
# The runner looks for `STUDIO_CLEANUP_PYTHON`, then `studio/.cleanup-venv`.
set -e
cd "$(dirname "$0")"

PY="${PY:-}"
if [[ -z "$PY" ]]; then
  for c in python3.13 python3.12 python3.11; do
    if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
  done
  [[ -n "$PY" ]] || PY=python3
fi
"$PY" - <<'PY' || { echo "cleanup needs Python 3.9-3.13 (torch wheels); set PY=... and retry" >&2; exit 1; }
import sys
sys.exit(0 if (3, 9) <= sys.version_info[:2] <= (3, 13) else 1)
PY

if [[ ! -d .cleanup-venv ]]; then
  echo "creating studio/.cleanup-venv with $PY"
  "$PY" -m venv .cleanup-venv
fi
.cleanup-venv/bin/pip install --quiet --upgrade pip
.cleanup-venv/bin/pip install --quiet torch torchvision simple-lama-inpainting

# The model weights.  torch's urllib has no CA store on some Python builds, so
# curl (system trust store) fetches them -- into exactly the hub directory the
# worker's torch will look in.  Asking torch is the only reliable way: the
# default is ~/.cache/torch on macOS, not ~/Library/Caches/torch.
CACHE="$(.cleanup-venv/bin/python -c 'import torch; print(torch.hub.get_dir() + "/checkpoints")')"
URL="https://github.com/enesmsahin/simple-lama-inpainting/releases/download/v0.1.0/big-lama.pt"
mkdir -p "$CACHE"
if [[ ! -f "$CACHE/big-lama.pt" ]]; then
  echo "downloading big-lama.pt (~200 MB) -> $CACHE"
  curl -L --fail --progress-bar -o "$CACHE/big-lama.pt" "$URL"
fi

.cleanup-venv/bin/python -c "
from simple_lama_inpainting import SimpleLama
SimpleLama()
print('cleanup ready: studio/.cleanup-venv')
"
