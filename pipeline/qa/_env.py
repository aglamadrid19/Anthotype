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


def variant_dir(name, v):
    """Locate a variant's site directory in either supported layout.

    Live layout:  <root>/pipeline/  + <root>/variant-a/
    Bundle layout: <root>/pipeline/ + <root>/sites/variant-a/
    """
    for cand in (os.path.join(os.path.dirname(PIPE), name),
                 os.path.join(os.path.dirname(PIPE), 'sites', name)):
        if os.path.isdir(cand):
            return cand
    return os.path.join(os.path.dirname(PIPE), name)


if __name__ == '__main__':
    print(f'PIPE   {PIPE}')
    print(f'PY     {PY}')
    print(f'NODE   {NODE}')
    print(f'CHROME {CHROME}')
    print(f'SIPS   {SIPS}')
