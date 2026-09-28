#!/usr/bin/env python3
"""Sweep full-frame art trace boxes with live text excluded."""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import batch, mkart

def run(v, box, excl, tag):
    svg = f'/tmp/boxs2-{v}.svg'
    mkart.build(v, out=svg, box=box, exclude_text=excl, **mkart.PARAMS[v])
    open(f'{PIPE}/{v}.svg', 'w').write(open(svg).read())
    subprocess.run(['node', f'{PIPE}/gen-page.mjs', v], cwd=PIPE, check=True,
                   capture_output=True)
    batch._CACHE.pop(v, None)
    s = batch.score(v, [''], windows={'all': (0, 0, 1024, 768)})[0]
    return s['all'], os.path.getsize(svg), tag

if __name__ == '__main__':
    v = sys.argv[1]
    b = list(mkart.BOX[v])
    for tag, box, ex in [
        ('current',        tuple(b), False),
        ('current+excl',   tuple(b), True),
        ('full+excl',      (0, 0, 1024, 768), True),
        ('full',           (0, 0, 1024, 768), False),
        ('x0=0+excl',      (0, b[1], b[2], b[3]), True),
        ('y0=0+excl',      (b[0], 0, b[2], b[3]), True),
        ('y1=768+excl',    (b[0], b[1], b[2], 768), True),
    ]:
        r = run(v, box, ex, tag)
        print(f'  {tag:16s} all {r[0]:6.3f}  {r[1]/1024:7.0f} KB', flush=True)
