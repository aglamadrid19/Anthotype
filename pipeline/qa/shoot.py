#!/usr/bin/env python3
"""Robust headless-Chrome screenshot -> sRGB 1024x768 PNG.

usage: shoot.py <url> <out.png> [w] [h] [dpr]
"""
import os, shutil, subprocess, sys, time, uuid
from PIL import Image

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SRGB = "/System/Library/ColorSync/Profiles/sRGB Profile.icc"

def shoot(url, out, w=1024, h=768, dpr=2, tries=6):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    raw = f"/tmp/shoot-{uuid.uuid4().hex}.png"
    last = ""
    for i in range(tries):
        if os.path.exists(raw):
            os.remove(raw)
        try:
            p = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                            f"--force-device-scale-factor={dpr}", "--force-color-profile=srgb",
                            "--no-first-run", "--no-default-browser-check",
                            f"--window-size={w},{h}", "--virtual-time-budget=6000",
                            f"--screenshot={raw}", url],
                           capture_output=True, text=True, timeout=45)
        except subprocess.TimeoutExpired:
            last = "timeout"
            p = None
        if os.path.exists(raw) and os.path.getsize(raw) > 5000:
            s = f"{raw}.s.png"
            subprocess.run(["sips", "--matchTo", SRGB, raw, "--out", s], capture_output=True)
            r = f"{raw}.r.png"
            from PIL import Image as _I
            _I.open(s).convert("RGB").resize((w, h), _I.LANCZOS).save(r)
            if os.path.exists(r) and os.path.getsize(r) > 1000:
                shutil.move(r, out)
                for f in (raw, s, r):
                    if os.path.exists(f):
                        os.remove(f)
                return out
            last = "sips failed"
        else:
            last = "no screenshot"
        time.sleep(0.7)
    raise RuntimeError(f"screenshot failed after {tries} tries for {url}: {last}")

if __name__ == '__main__':
    print(shoot(sys.argv[1], sys.argv[2],
                int(sys.argv[3]) if len(sys.argv) > 3 else 1024,
                int(sys.argv[4]) if len(sys.argv) > 4 else 768,
                int(sys.argv[5]) if len(sys.argv) > 5 else 2))
