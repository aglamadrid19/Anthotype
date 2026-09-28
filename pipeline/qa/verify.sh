#!/bin/zsh
# Verify the shipped state: score the ASTRO dist output (the real artifact)
# against each reference.  Prints one line per variant plus a PASS/FAIL.
#
# usage: qa/verify.sh [variant...]      (default: a b c)
set -e
cd "$(dirname "$0")/.."
PY="${PY:-$(python3 -c "import sys;sys.path.insert(0,\"$PWD/qa\");import _env;print(_env.PY)")}"
CHROME="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
SRGB='/System/Library/ColorSync/Profiles/sRGB Profile.icc'
V=("$@"); [[ ${#V[@]} -eq 0 ]] && V=(a b c)
# Targets are set ~0.06 above the shipped, run-to-run stable values
# (2.71 / 2.76 / 2.99, stable to +/-0.01 over 3 runs) so they catch a real
# regression without failing on capture noise.  They were 2.90/3.00/3.25 under
# the old `sips -z` scaler; see qa/downsample.py.
TARGET_A=2.77; TARGET_B=2.82; TARGET_C=3.05
for v in $V; do
  # live layout: <root>/variant-a/ ; bundle layout: <root>/sites/variant-a/
  if [[ -f ../variant-$v/dist/index.html ]]; then
    site=../variant-$v
  elif [[ -f ../sites/variant-$v/dist/index.html ]]; then
    site=../sites/variant-$v
  else
    echo "$v FAIL: no build at variant-$v/dist or sites/variant-$v/dist -- run npm-run-build there"
    continue
  fi
  page="$site/dist/index.html"

  # Network gate (behavioural, not a grep): render with Chrome's net log and
  # assert the page itself fetches nothing.  This is what catches a font/CSS
  # dependency that a string search could miss (e.g. a hashed CDN path).
  # qa/netcheck.py --selftest proves the detector can see a real CDN fetch.
  if ! "$PY" qa/netcheck.py "$v" >/dev/null 2>&1; then
    echo "$v FAIL: page made network requests -- run qa/netcheck.py $v to see them"
    continue
  fi

  # Self-containment gate: the build must not reach the network for anything
  # that affects rendering (fonts, CSS).  A remote stylesheet/font would make
  # both the fidelity and the page itself depend on the visitor's connection.
  if grep -qE 'fonts\.(googleapis|gstatic)\.com|https?://[^"]*\.(css|woff2?|ttf)' "$page"; then
    echo "$v FAIL: build references remote assets -- must be self-contained"
    grep -oE 'https?://[^"]*\.(css|woff2?|ttf)' "$page" | sort -u | head -5
    continue
  fi
  if grep -qE 'href="/_astro/[^"]*\.css"' "$page"; then
    echo "$v FAIL: external stylesheet (build.inlineStylesheets must be 'always')"
    continue
  fi

  raw=/tmp/verify-$v.png
  for try in 1 2 3 4; do
    # DNS-blackhole the font CDNs so an accidental remote dependency shows up
    # as a score regression instead of silently passing on a warm cache.
    "$CHROME" --headless=new --disable-gpu --hide-scrollbars \
      --force-device-scale-factor=2 --force-color-profile=srgb --no-first-run \
      --no-default-browser-check --disable-http-cache --incognito \
      --host-resolver-rules="MAP fonts.googleapis.com 127.0.0.1:1,MAP fonts.gstatic.com 127.0.0.1:1" \
      --window-size=1024,768 --virtual-time-budget=8000 \
      --screenshot="$raw" "file://$PWD/$page?cb=$RANDOM$RANDOM" >/dev/null 2>&1
    [[ -s $raw ]] && break
    sleep 1
  done
  sips --matchTo "$SRGB" "$raw" --out "$raw.s.png" >/dev/null 2>&1
  # PIL Lanczos, not `sips -z` -- the scaler is ~0.077 of B's old headline
  # number.  See qa/downsample.py for the measured comparison.
  "$PY" qa/downsample.py "$raw.s.png" "/tmp/verify-$v.png" 1024 768
  "$PY" - "$v" <<'PY'
import sys, numpy as np
from PIL import Image
v = sys.argv[1]
T = {'a':2.77,'b':2.82,'c':3.05}[v]
ref = np.asarray(Image.open(f'qa/ref-{v}.png').convert('RGB')).astype(np.float32)
d   = np.asarray(Image.open(f'/tmp/verify-{v}.png').convert('RGB')).astype(np.float32)
mean = float(np.abs(ref-d).mean()); pct = 100*float((np.abs(ref-d).mean(axis=2)>30).mean())
print(f'{v}  mean {mean:5.2f}  pct>30 {pct:4.2f}%  {"PASS" if mean < T else "FAIL"} (target <{T})')
PY
done
