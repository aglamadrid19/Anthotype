#!/usr/bin/env python3
"""Compare candidate font stacks for the left column against the reference."""
import os, sys, numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch

FAMILIES = [
 'Inter',
 'Inter Tight',
 'Inter Display',
 'National 2',
 'Söhne',
 'SF Pro Text',
 '-apple-system',
 'Helvetica Neue',
 'Arial',
 'Roboto',
 'IBM Plex Sans',
 'Manrope',
 'DM Sans',
 'Plus Jakarta Sans',
 'Figtree',
 'Public Sans',
 'Work Sans',
 'Rubik',
 'Outfit',
 'Archivo',
]

GF = 'https://fonts.googleapis.com/css2?family={f}:wght@300;400;500;600;700&display=swap'

def inject(fam):
    if fam.startswith('-') or fam in ('SF Pro Text','Helvetica Neue','Arial','National 2','Söhne'):
        return f"body{{font-family:'{fam}',system-ui,sans-serif}}"
    return (f"@import url('{GF.format(f=fam.replace(' ','+'))}');\n"
            f"body{{font-family:'{fam}',system-ui,sans-serif}}")

def main():
    v = sys.argv[1]
    ovs = [inject(f) for f in FAMILIES]
    sc = batch.score(v, ovs, None, False, scale=1)
    order = np.argsort(sc)
    base = batch.score(v, [''], None, False, scale=1)[0]
    print(f"{v}: current-stack baseline {base:.3f}")
    for i in order:
        print(f"  {FAMILIES[i]:20} {sc[i]:7.3f}")

if __name__ == '__main__':
    main()
