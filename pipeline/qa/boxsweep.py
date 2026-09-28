#!/usr/bin/env python3
"""Sweep art trace boxes (x0,y0,x1,y1) per variant, scoring in-page."""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import batch, mkart

def run(v, box, tag):
    svg = f'/tmp/boxsw-{v}.svg'
    mkart.build(v, out=svg, box=box, **mkart.PARAMS[v])
    open(f'{PIPE}/{v}.svg', 'w').write(open(svg).read())
    subprocess.run(['node', f'{PIPE}/gen-page.mjs', v], cwd=PIPE, check=True,
                   capture_output=True)
    batch._CACHE.pop(v, None)
    s = batch.score(v, [''], windows={'all': (0, 0, 1024, 768)})[0]
    return s['all'], os.path.getsize(svg), tag

if __name__ == '__main__':
    v = sys.argv[1]
    base = list(mkart.BOX[v])
    boxes = {
      'current': tuple(base),
      'full':    (0, 0, 1024, 768),
      'x0=0':    (0, base[1], base[2], base[3]),
      'y0=0':    (base[0], 0, base[2], base[3]),
      'y1=768':  (base[0], base[1], base[2], 768),
      'x0=0,y0=0': (0, 0, base[2], base[3]),
      'x0=0,y0=0,y1=768': (0, 0, base[2], 768),
    }
    for tag, box in boxes.items():
        res = run(v, box, tag)
        print(f'  {tag:20s} box {box}  all {res[0]:6.3f}  {res[1]/1024:7.0f} KB', flush=True)
