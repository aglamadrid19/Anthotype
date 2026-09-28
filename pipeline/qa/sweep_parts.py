#!/usr/bin/env python3
"""Sweep body-part mesh/rotation/scale parameters and score tight part regions.

usage: sweep_parts.py <variant> [--apply]
"""
import os, re, sys, subprocess, json
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
PIPE = os.path.dirname(HERE)
GEN = os.path.join(PIPE, 'gen-a.mjs')
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

PARTS = {
    'head':   (633, 224, 712, 302),
    'thorax': (642, 322, 702, 402),
    'belly':  (616, 424, 732, 558),
    'ant':    (505, 185, 830, 585),
}

def score(tag):
    ref = np.asarray(Image.open(f"{HERE}/ref-a.png").convert('RGB')).astype(np.float32)
    ren = np.asarray(Image.open(f"{HERE}/render-a.png").convert('RGB')).astype(np.float32)
    out = {}
    for n, (x0, y0, x1, y1) in PARTS.items():
        out[n] = float(np.abs(ref[y0:y1, x0:x1] - ren[y0:y1, x0:x1]).mean())
    return out

def build_and_shot():
    env = node_env()
    subprocess.run(["node", "gen-a.mjs"], cwd=PIPE, env=env, check=True, capture_output=True)
    subprocess.run(["node", "gen-page.mjs", "a"], cwd=PIPE, env=env, check=True, capture_output=True)
    raw = "/tmp/sweep-raw.png"
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--force-device-scale-factor=2", "--force-color-profile=srgb",
                    "--window-size=1024,768", "--virtual-time-budget=5000",
                    f"--screenshot={raw}", f"file://{PIPE}/a-static.html"], capture_output=True)
    subprocess.run(["sips", "--matchTo", "/System/Library/ColorSync/Profiles/sRGB Profile.icc",
                    raw, "--out", "/tmp/sweep-s.png"], capture_output=True)
    # PIL Lanczos, matching the headline scorer (see qa/downsample.py).
    from PIL import Image as _I
    _I.open("/tmp/sweep-s.png").convert("RGB").resize((1024, 768), _I.LANCZOS).save(f"{HERE}/render-a.png")

def patch(mesh, rot, belly_scale, egg):
    s = open(GEN).read()
    s = re.sub(r"const mesh1 = [^;]+;", f"const mesh1 = {mesh};", s)
    s = re.sub(r"const BODY_ROT = \{[^}]*\};", f"const BODY_ROT = {rot};", s)
    s = re.sub(r"\$\{use\('ant-belly', 671, 480, [^)]*\)\}", f"${{use('ant-belly', 671, 480, {belly_scale[0]}, {belly_scale[1]})}}", s)
    s = re.sub(r"const eggWarp = \(x, y\) => \{.*?\n\};", EGG_TEMPLATE.format(**egg), s, flags=re.S)
    open(GEN, 'w').write(s)

EGG_TEMPLATE = """const eggWarp = (x, y) => {{
  const s = y > 0 ? 1 - {lo} * y * y : 1 - {hi} * y * y;
  return [x * s, y];
}};"""

if __name__ == '__main__':
    orig = open(GEN).read()
    trials = []
    meshes = ["icosphere(1)", "icosphere(2)", "kisSphere()", "uvSphere(6, 3)", "uvSphere(8, 4)",
              "uvSphere(7, 3)", "uvSphere(9, 4)", "uvSphere(10, 4)"]
    rots = ["{ yaw: 0.0, pitch: 0.0, roll: 0.0 }",
            "{ yaw: 0.4, pitch: -0.25, roll: 0 }",
            "{ yaw: 0.9, pitch: -0.4, roll: 0 }"]
    try:
        for m in meshes:
            for r in rots:
                patch(m, r, (84, 80), dict(lo=0.42, hi=0.08))
                build_and_shot()
                s = score(None)
                trials.append((s['ant'], m, r, s))
                print(f"{s['ant']:7.3f}  {m:<16} {r:<34} head {s['head']:6.2f} thorax {s['thorax']:6.2f} belly {s['belly']:6.2f}")
    finally:
        open(GEN, 'w').write(orig)
        build_and_shot()
    trials.sort()
    print("\nBEST:")
    for t in trials[:5]:
        print(f"  {t[0]:7.3f}  {t[1]}  {t[2]}")
