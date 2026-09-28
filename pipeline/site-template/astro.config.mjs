import { defineConfig } from 'astro/config';

export default defineConfig({
  server: { host: '0.0.0.0', allowedHosts: ['terminal.local'] },
  // Keep the whole page in one file: the inline SVG art + self-hosted fonts
  // push the stylesheet past Astro's default 4 kB auto-inline threshold, and
  // an external /_astro/*.css cannot resolve over file:// (which is exactly how
  // qa.sh and qa/verify.sh screenshot the build).
  build: { inlineStylesheets: 'always' },
});
