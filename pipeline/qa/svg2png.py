#!/usr/bin/env python3
"""Render a standalone SVG (1024x768) to a PNG on a flat background.

usage: svg2png.py <in.svg> <out.png> [w] [h] [bg]
"""
import os, subprocess, sys, uuid, shutil
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SRGB = "/System/Library/ColorSync/Profiles/sRGB Profile.icc"

def render(svg_path, out, w=1024, h=768, bg="#000a07", tries=4):
    svg = open(svg_path).read()
    html = f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0}}html,body{{width:{w}px;height:{h}px;overflow:hidden;background:{bg}}}
svg{{display:block;width:{w}px;height:{h}px;overflow:visible}}</style></head><body>{svg}</body></html>"""
    tmp = f"/tmp/svg2png-{uuid.uuid4().hex}.html"
    open(tmp, "w").write(html)
    raw = f"{tmp}.raw.png"
    for i in range(tries):
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=2", "--force-color-profile=srgb",
                        "--no-first-run", "--no-default-browser-check",
                        f"--window-size={w},{h}", "--virtual-time-budget=4000",
                        "--disable-http-cache", "--incognito",
                        f"--screenshot={raw}", f"file://{tmp}?cb={uuid.uuid4().hex}"],
                       capture_output=True, timeout=40)
        if os.path.exists(raw) and os.path.getsize(raw) > 2000:
            s = raw + ".s.png"
            subprocess.run(["sips", "--matchTo", SRGB, raw, "--out", s], capture_output=True)
            r = raw + ".r.png"
            # PIL Lanczos, matching the headline scorer (see qa/downsample.py).
            from PIL import Image as _I
            _I.open(s).convert("RGB").resize((w, h), _I.LANCZOS).save(r)
            if os.path.exists(r) and os.path.getsize(r) > 1000:
                shutil.move(r, out)
                for f in (tmp, raw, s, r):
                    if os.path.exists(f):
                        os.remove(f)
                return out
        print(f"  retry {i+1}", flush=True)
    raise RuntimeError("svg render failed")

if __name__ == "__main__":
    a = sys.argv
    print(render(a[1], a[2], int(a[3]) if len(a) > 3 else 1024,
                 int(a[4]) if len(a) > 4 else 768,
                 a[5] if len(a) > 5 else "#000a07"))
