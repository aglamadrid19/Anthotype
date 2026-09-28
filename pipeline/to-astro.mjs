// Copy the built page into the variant's Astro page.
// Usage: node to-astro.mjs <variant>
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const v = process.argv[2] || 'a';
// live layout: <root>/variant-a/ ; bundle layout: <root>/sites/variant-a/
const root = join(HERE, '..');
const site = [join(root, `variant-${v}`), join(root, 'sites', `variant-${v}`)]
  .find((d) => existsSync(d));
if (!site) throw new Error(`no variant-${v} dir next to pipeline/ (or in sites/)`);
const out = join(site, 'src', 'pages', 'index.astro');
mkdirSync(join(site, 'src', 'pages'), { recursive: true });
writeFileSync(out, readFileSync(join(HERE, `${v}-full.html`), 'utf8'));
console.log(`wrote ${out}`);
