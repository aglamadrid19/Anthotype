// Enumerate the configured designs.
//
// Single source of truth: `pipeline/designs/<name>.json`.  Every orchestration
// script (gen-page, to-astro, build.sh, verify.sh, bootstrap.sh, preview/serve)
// asks this module which designs exist instead of hardcoding a list, so adding
// a design is "drop in a JSON file" and nothing else has to change.
//
//   node lib/designs.mjs list          -> one design name per line
//   node lib/designs.mjs site <name>   -> absolute path to that design's site
//   node lib/designs.mjs show <name>   -> the parsed config as JSON
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

export const PIPE = dirname(dirname(fileURLToPath(import.meta.url))); // .../pipeline
export const ROOT = dirname(PIPE);                                    // repo root

// The convention used by the three shipped examples; a design may override it
// with an explicit `site` key when its project lives somewhere else.
export const SITE_CANDIDATES = (name) => [
  `variant-${name}`, `sites/variant-${name}`,
  `site-${name}`, `sites/site-${name}`,
];

export function designNames() {
  const dir = join(PIPE, 'designs');
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((f) => f.endsWith('.json'))
    .map((f) => f.slice(0, -'.json'.length))
    .sort();
}

export function loadDesign(name) {
  const p = join(PIPE, 'designs', `${name}.json`);
  if (!existsSync(p)) {
    throw new Error(`no design config at ${p} (have: ${designNames().join(', ') || 'none'})`);
  }
  return JSON.parse(readFileSync(p, 'utf8'));
}

// Where a design's Astro project lives.  Prefers an explicit `site` in the
// config, then the documented convention in either supported layout.
export function siteDir(name) {
  const explicit = loadDesign(name).site;
  for (const c of [explicit, ...SITE_CANDIDATES(name)].filter(Boolean)) {
    const abs = join(ROOT, c);
    if (existsSync(abs)) return abs;
  }
  return join(ROOT, `sites/variant-${name}`); // default location for a new design
}

const argv = process.argv.slice(2);
if (argv[0] === 'list') {
  process.stdout.write(designNames().join('\n') + (designNames().length ? '\n' : ''));
} else if (argv[0] === 'site') {
  process.stdout.write(siteDir(argv[1]) + '\n');
} else if (argv[0] === 'show') {
  process.stdout.write(JSON.stringify(loadDesign(argv[1]), null, 2) + '\n');
}
