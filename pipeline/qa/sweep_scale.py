#!/usr/bin/env python3
"""Sweep the ant part scales/positions plus mesh, scoring tight part regions."""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sweep_parts import GEN, build_and_shot, score

def patch(parts, mesh):
    s = open(GEN).read()
    s = re.sub(r"const mesh1 = [^;]+;", f"const mesh1 = {mesh};", s)
    for name, (cx, cy, sx, sy) in parts.items():
        s = re.sub(rf"\$\{{use\('ant-{name}', [^)]*\)\}}",
                   f"${{use('ant-{name}', {cx}, {cy}, {sx}, {sy})}}", s)
    s = re.sub(r"const headGlyph = sphereGlyph\(([\d.]+)", f"const headGlyph = sphereGlyph(0.040", s)
    open(GEN, 'w').write(s)

if __name__ == '__main__':
    orig = open(GEN).read()
    base = {
        'head':   (670, 261, 42, 41),
        'thorax': (671, 358, 46, 50),
        'belly':  (671, 480, 84, 80),
    }
    trials = []
    meshes = ["uvSphere(7, 3)", "uvSphere(6, 3)", "uvSphere(8, 4)", "kisSphere()"]
    scales = {
        'head':   [(42, 41), (44, 43), (40, 39), (46, 45)],
        'thorax': [(46, 50), (48, 52), (44, 48), (50, 54)],
        'belly':  [(84, 80), (88, 84), (80, 76), (92, 88)],
    }
    try:
        for m in meshes:
            for hs in scales['head']:
                for ts in scales['thorax'][:2]:
                    for bs in scales['belly'][:2]:
                        p = dict(base)
                        p['head'] = (base['head'][0], base['head'][1], hs[0], hs[1])
                        p['thorax'] = (base['thorax'][0], base['thorax'][1], ts[0], ts[1])
                        p['belly'] = (base['belly'][0], base['belly'][1], bs[0], bs[1])
                        patch(p, m)
                        build_and_shot()
                        s = score(None)
                        trials.append((s['ant'], m, hs, ts, bs, s))
                        print(f"{s['ant']:7.3f} {m:<15} h{hs} t{ts} b{bs}  head {s['head']:6.2f} thx {s['thorax']:6.2f} bel {s['belly']:6.2f}")
    finally:
        open(GEN, 'w').write(orig)
        build_and_shot()
    trials.sort()
    print("\nBEST:")
    for t in trials[:6]:
        print(f"  {t[0]:7.3f}  {t[1]}  head{t[2]} thorax{t[3]} belly{t[4]}")
