#!/bin/zsh
# Start the studio: FastAPI backend + Vite dev server.
#
#   ./studio/run.sh            # backend :8787, frontend :5173
#   ./studio/run.sh --backend  # backend only
#
# Ctrl-C stops both.
set -e
cd "$(dirname "$0")"
ROOT=$PWD

PY="$ROOT/.venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "no studio venv at $PY"
  echo "create it:  python3 -m venv studio/.venv && studio/.venv/bin/pip install -r studio/backend/requirements.txt"
  exit 1
fi

NODE="$(command -v node || true)"
[[ -n "$NODE" ]] || NODE="$(ls -d ~/.nvm/versions/node/*/bin/node 2>/dev/null | sort -V | tail -1)"
[[ -n "$NODE" ]] || { echo "no node found" >&2; exit 1 }
export PATH="${NODE:h}:$PATH"

mkdir -p data/jobs

echo "backend  -> http://127.0.0.1:8787"
"$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --app-dir backend &
BACKEND=$!
trap 'kill $BACKEND 2>/dev/null || true' EXIT INT TERM

if [[ "$1" != "--backend" ]]; then
  if [[ ! -d frontend/node_modules ]]; then
    echo "installing frontend deps ..."
    (cd frontend && npm install --no-audit --no-fund)
  fi
  echo "frontend -> http://127.0.0.1:5173"
  (cd frontend && npm run dev)
else
  wait $BACKEND
fi
