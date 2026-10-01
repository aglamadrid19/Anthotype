#!/usr/bin/env python3
"""Resolve the interpreter and node binary without hardcoding absolute paths.

Resolution order, so this project can be copied anywhere (a handoff bundle, a
CI box, another checkout):

  python : $PY  ->  $REFMATCH_PY  ->  ../.venv/bin/python  ->  sys.executable
  node   : $NODE_BIN dir  ->  dirname(which node)  ->  the nvm default
  chrome : $CHROME  ->  the macOS app bundle  ->  chromium
  sips   : $SIPS  ->  /usr/bin/sips

Import as:  from _env import PY, NODE, NODE_DIR, CHROME, SIPS
(from a script inside qa/, add its own dir to sys.path first).
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)


def _first(*cands):
    for c in cands:
        if c and os.path.exists(c):
            return c
    return None


# ---- python ---------------------------------------------------------------
# The QA tools need numpy/pillow/scipy/skimage.  A bare `sys.executable` may be
# a system python without them, so candidates are *probed* rather than trusted:
# the first interpreter that can import numpy wins, and only if none can do we
# fall back to whatever is available (so the error surfaces at import time with
# a real traceback instead of silently using the wrong interpreter).
def _can_import_numpy(exe):
    import subprocess
    try:
        return subprocess.run([exe, '-c', 'import numpy'],
                              stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode == 0
    except OSError:
        return False


_CANDIDATES = [os.environ.get('PY'), os.environ.get('REFMATCH_PY'),
               os.path.join(PIPE, '.venv', 'bin', 'python'),                 # venv inside pipeline/
               os.path.join(os.path.dirname(PIPE), '.venv', 'bin', 'python'),  # bundle root (bootstrap.sh)
               os.path.join(os.path.dirname(PIPE), 'work', '.venv', 'bin', 'python'),
               sys.executable]

PY = next((c for c in _CANDIDATES if c and _can_import_numpy(c)), None) \
     or _first(*[c for c in _CANDIDATES if c]) \
     or sys.executable


# ---- node -----------------------------------------------------------------
NODE = os.environ.get('NODE') or shutil.which('node')
if not NODE:
    # nvm keeps node outside the default PATH; try any installed version.
    import glob
    NODE = _first(*sorted(glob.glob(os.path.expanduser('~/.nvm/versions/node/*/bin/node')),
                          reverse=True),
                  '/opt/homebrew/bin/node', '/usr/local/bin/node')
NODE_DIR = os.path.dirname(NODE) if NODE else ''


def node_env(extra=None):
    """os.environ with NODE_DIR prepended to PATH, plus any extra vars."""
    env = dict(os.environ)
    if NODE_DIR:
        env['PATH'] = NODE_DIR + os.pathsep + env.get('PATH', '')
    if extra:
        env.update(extra)
    return env


# ---- chrome / sips --------------------------------------------------------
CHROME = (os.environ.get('CHROME')
          or _first('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                    '/Applications/Chromium.app/Contents/MacOS/Chromium',
                    shutil.which('google-chrome') or '',
                    shutil.which('chromium') or '', ''))
SRGB = _first('/System/Library/ColorSync/Profiles/sRGB Profile.icc',
              '/usr/share/color/icc/sRGB.icc')
SIPS = os.environ.get('SIPS') or shutil.which('sips') or '/usr/bin/sips'
PYTHON = PY


# ---- potrace --------------------------------------------------------------
# Homebrew's bin is not on the PATH of a GUI-launched or minimal shell (an
# agent, launchd, CI), but `mkart.py` shells out to potrace -- so resolve it the
# way CHROME is resolved instead of trusting `shutil.which('potrace')`.
_EXTRA_BINS = ('/opt/homebrew/bin', '/usr/local/bin')


def potrace_bin():
    """argv[0] for potrace, or the bare name if nothing better is found.

    Never raises: a genuinely absent binary should fail at the subprocess call
    with potrace's own error, not here.
    """
    found = os.environ.get('POTRACE') or shutil.which('potrace')
    if found:
        return found
    for d in _EXTRA_BINS:
        cand = os.path.join(d, 'potrace')
        if os.path.isfile(cand):
            return cand
    return 'potrace'


def design_names():
    """Every configured design, from pipeline/designs/*.json (sorted)."""
    d = os.path.join(PIPE, 'designs')
    if not os.path.isdir(d):
        return []
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith('.json'))


def site_dir(name):
    """Locate a design's site directory.

    Resolution order: the `site` key in designs/<name>.json (relative to the
    repo root), then the documented convention in either supported layout
    (<root>/variant-<name> live, <root>/sites/variant-<name> bundle).
    """
    import json
    root = os.path.dirname(PIPE)
    cfg_path = os.path.join(PIPE, 'designs', f'{name}.json')
    explicit = None
    if os.path.isfile(cfg_path):
        try:
            explicit = json.load(open(cfg_path)).get('site')
        except Exception:
            explicit = None
    for cand in [explicit,
                 f'variant-{name}', f'sites/variant-{name}',
                 f'site-{name}', f'sites/site-{name}']:
        if not cand:
            continue
        abs_ = cand if os.path.isabs(cand) else os.path.join(root, cand)
        if os.path.isdir(abs_):
            return abs_
    return os.path.join(root, 'sites', f'variant-{name}')


# Backwards-compatible alias: older tools called variant_dir(<dirname>, <v>).
def variant_dir(_name, v):
    return site_dir(v)


if __name__ == '__main__':
    print(f'PIPE   {PIPE}')
    print(f'PY     {PY}')
    print(f'NODE   {NODE}')
    print(f'CHROME {CHROME}')
    print(f'SIPS   {SIPS}')
