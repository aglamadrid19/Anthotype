#!/usr/bin/env python3
"""Re-exec the current script under the project's python if numpy is missing.

The QA tools need numpy / pillow / scipy / scikit-image, which live in a venv
that bootstrap.sh creates.  Without this, the documented commands
(`python qa/mkart.py <name>`) fail with ModuleNotFoundError when the ambient
`python3` is the system one.

Import this at the very top of an entry-point script:

    import _bootstrap  # noqa: F401  (re-execs into the venv python if needed)

`_env` is deliberately import-safe on a bare interpreter (it probes candidates
with subprocess rather than importing numpy), so this indirection is cheap.

The "am I already inside the venv?" test deliberately does NOT compare
interpreter paths: a venv's `bin/python` is usually a SYMLINK to the base
interpreter, so `os.path.realpath` resolves them to the same file and a naive
check never fires.  Instead we (a) compare `sys.prefix` against the venv root,
and (b) set a sentinel env var so a bad re-exec can never loop.
"""
import os
import sys

try:
    import numpy  # noqa: F401
    import PIL    # noqa: F401
except ImportError:
    if os.environ.get('_QA_BOOTSTRAPPED'):
        sys.stderr.write(
            'qa: still missing numpy/PIL after re-exec; run ./bootstrap.sh\n')
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        try:
            from _env import PY
        except Exception:
            PY = None
        venv_root = os.path.dirname(os.path.dirname(PY)) if PY else None
        if PY and os.path.isfile(PY) and sys.prefix != venv_root:
            sys.stderr.write(f'qa: re-exec under {PY}\n')
            env = dict(os.environ, _QA_BOOTSTRAPPED='1')
            os.execve(PY, [PY] + sys.argv, env)
        sys.stderr.write(
            'qa: numpy/PIL are missing and no usable venv was found.\n'
            '    Run ./bootstrap.sh once, or set PY=/path/to/python.\n')
