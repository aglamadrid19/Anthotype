#!/usr/bin/env python3
"""Score-vs-size sweep for the traced art: (up, bands, turdsize) -> page mean + bytes.

Drives the real pipeline (gen-page.mjs + qa.sh) so the numbers are the shipped ones.

usage: sweep_up.py <variant> [--ups 4,6,8] [--bands 16,24,32] [--turd 1,2] [--csv F]
"""
import gzip, os, subprocess, sys, json, itertools

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)
from _env import PY, NODE
sys.path.insert(0, HERE)
import mkart


def arg(name, default):
    return sys.argv[sys.argv.index(name)+1] if name in sys.argv else default


def main():
    v = sys.argv[1]
    ups = [int(x) for x in arg('--ups', '4,6,8').split(',')]
    bds = [int(x) for x in arg('--bands', '16,24,32,40').split(',')]
    turds = [int(x) for x in arg('--turd', '1,2').split(',')]
    env = node_env()
    keep = open(f'{PIPE}/{v}.svg').read()
    rows = []
    try:
        for up, bands, turd in itertools.product(ups, bds, turds):
            p = dict(mkart.PARAMS[v])
            p.update(up=up, bands=bands, turdsize=turd, out=f'{PIPE}/{v}.svg')
            mkart.build(v, **p)
            raw = os.path.getsize(f'{PIPE}/{v}.svg')
            gz = len(gzip.compress(open(f'{PIPE}/{v}.svg','rb').read(), 6))
            subprocess.run([NODE, 'gen-page.mjs', v], cwd=PIPE, check=True, capture_output=True, env=env)
            r = subprocess.run(['./qa.sh', v], cwd=PIPE, capture_output=True, text=True)
            mean = next((float(l.split()[2]) for l in r.stdout.splitlines()
                         if l.startswith('OVERALL')), float('nan'))
            rows.append((mean, raw, gz, up, bands, turd))
            print(f'  up={up:2d} bands={bands:3d} turd={turd}  mean {mean:6.3f}  '
                  f'raw {raw/1e6:5.2f} MB  gz {gz/1024:5.0f} KB', flush=True)
            if '--csv' in sys.argv:
                json.dump(rows, open(arg('--csv', '/tmp/sweep.json'), 'w'))
    finally:
        open(f'{PIPE}/{v}.svg', 'w').write(keep)
        subprocess.run([NODE, 'gen-page.mjs', v], cwd=PIPE, capture_output=True, env=env)
    rows.sort()
    print(f'--- {v} Pareto (score, MB, up, bands, turd)')
    best = 9e9
    for mean, raw, gz, up, bands, turd in rows:
        if raw/1e6 > 10: continue
        print(f'   {mean:6.3f}  {raw/1e6:5.2f} MB  gz {gz/1024:5.0f} KB  up={up} bands={bands} turd={turd}')


if __name__ == '__main__':
    main()
