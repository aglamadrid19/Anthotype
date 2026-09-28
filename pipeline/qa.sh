#!/bin/zsh
# Render a built variant headlessly (file:// — no server, no staleness) and
# score it against its reference PNG.
# usage: qa.sh <variant> [--crop x y w h zoom]
set -e
cd "$(dirname "$0")"
V="${1:-a}"; shift || true
PY="${PY:-$(python3 -c "import sys;sys.path.insert(0,\"$PWD/qa\");import _env;print(_env.PY)")}"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
SRGB='/System/Library/ColorSync/Profiles/sRGB Profile.icc'

TMP=/tmp/anthosting-qa-$V.png
rm -f "$TMP" "$TMP.srgb.png" 2>/dev/null || true
for try in 1 2 3 4; do
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars \
    --force-device-scale-factor=2 --force-color-profile=srgb \
    --no-first-run --no-default-browser-check --disable-http-cache --incognito \
    --window-size=1024,768 --virtual-time-budget=8000 \
    --screenshot="$TMP" "file://$PWD/$V-static.html?cb=$RANDOM$RANDOM" >/dev/null 2>&1
  [[ -s "$TMP" ]] && break
  sleep 1
done
sips --matchTo "$SRGB" "$TMP" --out "$TMP.srgb.png" >/dev/null 2>&1
# Downsample with PIL Lanczos, not `sips -z`: the reconstruction filter changes
# the score, and sips was the worst of the ones measured (see qa/downsample.py).
"${PY:-python3}" qa/downsample.py "$TMP.srgb.png" "qa/render-$V.png" 1024 768
rm -f "$TMP" "$TMP.srgb.png" 2>/dev/null || true
"$PY" qa/compare.py "$V" "$@"
