#!/bin/zsh
# Verify the shipped state: score each built Astro dist/ against its reference.
# Prints one line per design plus PASS/FAIL, and exits non-zero on any failure.
#
# usage: qa/verify.sh [design...]        (default: every configured design)
#
# Designs come from pipeline/designs/*.json; the pass target comes from each
# design's own config (`target`), so this file never hardcodes a list or a score.
set -e
cd "$(dirname "$0")/.."
PY="${PY:-$(python3 -c "import sys;sys.path.insert(0,\"$PWD/qa\");import _env;print(_env.PY)")}"
# Resolve node the same way `_env.py` resolves python.  nvm keeps node off a
# non-interactive PATH (launchd, an agent shell, CI), where a bare `node` fails
# with `command not found` before any design is ever scored.
NODE_DIR="$("$PY" -c "import sys;sys.path.insert(0,\"$PWD/qa\");import _env;print(_env.NODE_DIR or '')")"
[[ -n "$NODE_DIR" ]] && export PATH="$NODE_DIR:$PATH"
# Chrome / sips / the sRGB profile are resolved by `_env.py` too, so a Chromium
# install or a non-standard profile works without editing this script.  Keep the
# macOS defaults as a last resort.
CHROME="${CHROME:-$("$PY" -c "import sys;sys.path.insert(0,\"$PWD/qa\");import _env;print(_env.CHROME or '')")}"
[[ -n "$CHROME" ]] || CHROME='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
SIPS="${SIPS:-$("$PY" -c "import sys;sys.path.insert(0,\"$PWD/qa\");import _env;print(_env.SIPS or 'sips')")}"
SRGB="${SRGB:-$("$PY" -c "import sys;sys.path.insert(0,\"$PWD/qa\");import _env;print(_env.SRGB or '')")}"
[[ -n "$SRGB" ]] || SRGB='/System/Library/ColorSync/Profiles/sRGB Profile.icc'

V=("$@")
[[ ${#V[@]} -eq 0 ]] && V=(${(f)"$(node lib/designs.mjs list)"})
[[ ${#V[@]} -gt 0 ]] || { echo "no designs configured" >&2; exit 1 }

FAILED=0
for v in $V; do
  # The site directory is resolved by lib/designs.mjs, so both the live layout
  # (<root>/variant-<v>) and the bundle layout (<root>/sites/variant-<v>) work.
  site="$(node lib/designs.mjs site "$v")"
  page="$site/dist/index.html"
  if [[ ! -f "$page" ]]; then
    echo "$v FAIL: no build at $page -- run 'npm run build' there (or ./build.sh)"
    FAILED=1
    continue
  fi

  # Network gate (behavioural, not a grep): render with Chrome's net log and
  # assert the page itself fetches nothing.  This is what catches a font/CSS
  # dependency that a string search could miss (e.g. a hashed CDN path).
  # qa/netcheck.py --selftest proves the detector can see a real CDN fetch.
  if ! "$PY" qa/netcheck.py "$page" >/dev/null 2>&1; then
    echo "$v FAIL: page made network requests -- run qa/netcheck.py $page to see them"
    FAILED=1
    continue
  fi

  # Self-containment gate: the build must not reach the network for anything
  # that affects rendering (fonts, CSS).  A remote stylesheet/font would make
  # both the fidelity and the page itself depend on the visitor's connection.
  if grep -qE 'fonts\.(googleapis|gstatic)\.com|https?://[^"]*\.(css|woff2?|ttf)' "$page"; then
    echo "$v FAIL: build references remote assets -- must be self-contained"
    grep -oE 'https?://[^"]*\.(css|woff2?|ttf)' "$page" | sort -u | head -5
    FAILED=1
    continue
  fi
  if grep -qE 'href="/_astro/[^"]*\.css"' "$page"; then
    echo "$v FAIL: external stylesheet (build.inlineStylesheets must be 'always')"
    FAILED=1
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
      --screenshot="$raw" "file://$page?cb=$RANDOM$RANDOM" >/dev/null 2>&1
    [[ -s $raw ]] && break
    sleep 1
  done
  "$SIPS" --matchTo "$SRGB" "$raw" --out "$raw.s.png" >/dev/null 2>&1
  # PIL Lanczos, not `sips -z` -- the scaler is ~0.077 of B's old headline
  # number.  See qa/downsample.py for the measured comparison.
  "$PY" qa/downsample.py "$raw.s.png" "/tmp/verify-$v.png" 1024 768

  # Target + reference path come from the design config (one node call).
  INFO="$(node -e "import('./lib/designs.mjs').then(m=>{const d=m.loadDesign('$v');process.stdout.write(d.ref+'\t'+String(d.target??''))})")"
  REF="$PWD/${INFO%%$'\t'*}"
  TARGET="${INFO#*$'\t'}"
  "$PY" - "$v" "$REF" "$TARGET" <<'PY' || FAILED=1
import sys, numpy as np
from PIL import Image
v, ref_path, target = sys.argv[1], sys.argv[2], sys.argv[3]
ref = np.asarray(Image.open(ref_path).convert('RGB')).astype(np.float32)
d   = np.asarray(Image.open(f'/tmp/verify-{v}.png').convert('RGB')).astype(np.float32)
mean = float(np.abs(ref-d).mean()); pct = 100*float((np.abs(ref-d).mean(axis=2)>30).mean())
if target == '':
    print(f'{v}  mean {mean:5.2f}  pct>30 {pct:4.2f}%  (no target set)')
    sys.exit(0)
t = float(target)
ok = mean < t
print(f'{v}  mean {mean:5.2f}  pct>30 {pct:4.2f}%  {"PASS" if ok else "FAIL"} (target <{t:g})')
sys.exit(0 if ok else 1)
PY
done
exit $FAILED
