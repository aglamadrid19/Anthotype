// Build <design>-full.html from the design's art + content + stylesheet.
//
// Two page shapes, chosen by the design's `layout`:
//
//   "page"  (default for generated designs) -- a REAL WEBSITE: semantic sections
//           in normal document flow, a role-based type scale, responsive down to
//           mobile.  The traced artwork is the hero backdrop.  The generated
//           markup carries a `<!--ART-->` placeholder where the art is spliced in.
//
//   "poster" (the hand-authored A/B/C examples) -- the original fixed 1024x768
//           stage, scaled to the viewport.  Kept so `qa/verify.sh` still scores
//           the traced art against its reference exactly as it always did: A/B/C
//           are the tracer's regression suite, not a website.
//
// Usage: node gen-page.mjs <design>
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

const design = loadDesign(v);
// Only the weights actually vendored in pipeline/fonts/ are inlined.  A page
// that asks for a weight that is absent would silently fall back to the
// browser's synthetic bold, so the generated CSS uses 400/500/600 only.
const INTER_WEIGHTS = [300, 400, 500, 600, 700, 800, 900].filter((w) =>
  existsSync(join(HERE, 'fonts', `inter-latin-${w}-normal.woff2`)));
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
const contentRef = design.content || v;
const content = contentRef.endsWith('.json')
  ? JSON.parse(read(contentRef))
  : JSON.parse(read('content.json'))[contentRef];
if (!content) throw new Error(`no content for design '${v}' (looked up '${contentRef}')`);
const { title } = content;

// An explicit layout wins; otherwise a design whose markup carries the art
// placeholder is a generated page, and the historical examples are posters.
const layout = design.layout || (content.markup.includes('<!--ART-->') ? 'page' : 'poster');
const head = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${title}</title>
  <meta name="description" content="${content.description}" />
  <style is:global>${interFaces}</style>
</head>
<body>`;

let html;
if (layout === 'poster') {
  // The original self-contained page: a fixed stage scaled to the viewport.
  const [sw, sh] = content.stage || [1024, 768];
  html = `${head}
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
      const s = Math.min(window.innerWidth / ${sw}, window.innerHeight / ${sh});
      stage.style.transform = 'translate(-50%, -50%) scale(' + s + ')';
    };
    addEventListener('resize', fit, { passive: true });
    fit();
  </script>
</body>
</html>`;
} else {
  // A real website: the traced art is the hero backdrop, content flows.
  // `slice` makes the art cover the hero box instead of letterboxing inside it;
  // the scrim in the page CSS keeps the copy legible over it.
  const heroArt = artSvg.replace('<svg ', '<svg preserveAspectRatio="xMidYMin slice" ');
  const markup = content.markup.replace('<!--ART-->', heroArt);
  html = `${head}
  ${markup}
  <style is:global>
${readOpt(`${v}.page.css`)}
${artCss}
  </style>
</body>
</html>`;
}

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
console.log(`wrote ${v}-full.html (${layout})`);
