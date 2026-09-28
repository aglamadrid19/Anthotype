// Copy the built self-contained page into the design's Astro project.
// Usage: node to-astro.mjs <design>
//
// The site directory is resolved by lib/designs.mjs (explicit `site` in the
// design config, else the variant-<name> / sites/variant-<name> convention),
// so this works for any design, in either supported layout.
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { designNames, siteDir } from './lib/designs.mjs';

const PIPE = dirname(fileURLToPath(import.meta.url));
const v = process.argv[2] || designNames()[0];
if (!v) throw new Error('no designs configured: add pipeline/designs/<name>.json');

const site = siteDir(v);
const out = join(site, 'src', 'pages', 'index.astro');
mkdirSync(join(site, 'src', 'pages'), { recursive: true });
writeFileSync(out, readFileSync(join(PIPE, `${v}-full.html`), 'utf8'));
console.log(`wrote ${out}`);
