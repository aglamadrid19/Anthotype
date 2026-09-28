#!/usr/bin/env python3
"""Downsample a 2x screenshot to the reference resolution for scoring.

Why this exists as its own step: the pages are rendered at device-scale-factor 2
and compared against a 1024x768 reference, so a reconstruction filter is
unavoidable.  The filter is not a free choice -- it changes the measured score.

Measured on the shipped builds (same captures, only the filter varied):

    filter    A       B       C
    sips -z   2.7718  2.8970  3.1083
    box       2.7736  2.8312  3.0886
    hamming   2.7685  2.8721  3.0977
    bicubic   2.7616  2.8615  3.0910
    lanczos   2.7587  2.8205  3.0803

`sips -z` (the original toolchain) is the *worst* of these on B by 0.077 -- i.e.
about 2.7% of B's headline number was the scaler, not the page.  PIL's Lanczos is
the standard choice for downsampling and is also portable (no macOS dependency),
so it is now canonical.  The historical sips numbers are recorded above so older
notes stay readable.

usage: downsample.py <in.png> <out.png> [W] [H]
"""
import sys
from PIL import Image

def main():
    src, dst = sys.argv[1], sys.argv[2]
    w = int(sys.argv[3]) if len(sys.argv) > 3 else 1024
    h = int(sys.argv[4]) if len(sys.argv) > 4 else 768
    im = Image.open(src).convert('RGB')
    im.resize((w, h), Image.LANCZOS).save(dst)

if __name__ == '__main__':
    main()
