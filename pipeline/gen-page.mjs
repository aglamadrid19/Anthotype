// Build <variant>-full.html (self-contained page) from the variant's art modules.
// Usage: node gen-page.mjs <variant>
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { designNames, loadDesign } from './lib/designs.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
// The design name comes from the caller.  When it is omitted we fall back to
// the first configured design, so the script never hardcodes `a`.
const v = process.argv[2] || designNames()[0];
if (!v) throw new Error('no designs configured: add pipeline/designs/<name>.json');
const read = (f) => readFileSync(join(HERE, f), 'utf8');
// The art CSS is optional: a design may carry all its styling in <name>.page.css.
const readOpt = (f) => (existsSync(join(HERE, f)) ? readFileSync(join(HERE, f), 'utf8') : '');

// Self-hosted Inter: the reference designs use Inter, and relying on the
// Google Fonts CDN made the build's typography (and therefore its fidelity)
// depend on the network.  Vendored woff2 -> inlined @font-face, no requests.
const INTER_WEIGHTS = [400, 500, 600];
const interFaces = INTER_WEIGHTS.map((w) => {
  const b64 = readFileSync(join(HERE, 'fonts', `inter-latin-${w}-normal.woff2`)).toString('base64');
  return `@font-face{font-family:'Inter';font-style:normal;font-weight:${w};font-display:block;`
    + `src:url(data:font/woff2;base64,${b64}) format('woff2');}`;
}).join('\n');

const artSvg = read(`${v}.svg`);
const artCss = readOpt(`${v}.css`);
// The text layer for this design.  `content` in the design config is either a
// key in the shared content.json (the three shipped examples) or a path to a
// standalone JSON file (a new design gets its own, so it stays isolated).
const contentRef = loadDesign(v).content || v;
const content = contentRef.endsWith('.json')
  ? JSON.parse(read(contentRef))
  : JSON.parse(read('content.json'))[contentRef];
if (!content) throw new Error(`no content for design '${v}' (looked up '${contentRef}')`);
const { title, eyebrow, tagline, cta } = content;

const html = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${title}</title>
  <meta name="description" content="${content.description}" />
  <style is:global>${interFaces}</style>
</head>
<body>
  <main class="stage" id="stage">
    <section class="content">
      ${content.markup}
    </section>
    <section class="art">
      ${artSvg}
    </section>
  </main>
  <style is:global>
${readOpt(`${v}.page.css`)}
${artCss}
  </style>
  <script is:inline>
    const stage = document.getElementById('stage');
    const fit = () => {
      const s = Math.min(window.innerWidth / ${content.stage[0]}, window.innerHeight / ${content.stage[1]});
      stage.style.transform = 'translate(-50%, -50%) scale(' + s + ')';
    };
    addEventListener('resize', fit, { passive: true });
    fit();
  </script>
</body>
</html>`;

writeFileSync(join(HERE, `${v}-full.html`), html);
// static copy: identical but with animations frozen, for deterministic screenshots
// `CSS_OVERRIDE` is a test hook used by qa/tune.py to try candidate CSS through
// the real pipeline.  It is injected as its OWN <style> element, and omitted
// entirely when empty, so the file stays clean and grep-able: a leftover
// override in this file is a real hazard because qa.sh screenshots it.
const override = (process.env.CSS_OVERRIDE || '').trim();
const freeze = '<style>*{animation:none !important;transition:none !important}</style>';
const staticHtml = html.replace('</body>', (override ? `<style>${override}</style>` : '') + freeze + '</body>');
writeFileSync(join(HERE, `${v}-static.html`), staticHtml);
console.log(`wrote ${v}-full.html`);
