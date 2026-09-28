#!/usr/bin/env python3
"""Serve every built design (and a gallery) from one process.

The design list is read from pipeline/designs/*.json, so a new design shows up
here with no edit to this file.

Routes:
  /                  gallery (an iframe per design, plus its live score)
  /<name>/           that design's built dist/index.html and its assets
  /ref/<name>.png    the reference PNG
  /diff/<name>.png   the amplified difference image (if one was generated)
"""
import http.server, json, os, socketserver, sys, urllib.parse

ROOT = os.environ.get('ANTHOSTING_ROOT') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = f'{ROOT}/pipeline'
DESIGNS_DIR = f'{PIPE}/designs'


def load_designs():
    """[{name, site_dist, ref, target}] for every configured design."""
    out = []
    if not os.path.isdir(DESIGNS_DIR):
        return out
    for fn in sorted(os.listdir(DESIGNS_DIR)):
        if not fn.endswith('.json'):
            continue
        name = fn[:-5]
        try:
            cfg = json.load(open(os.path.join(DESIGNS_DIR, fn)))
        except Exception:
            cfg = {}
        dist = None
        for cand in (cfg.get('site'), f'variant-{name}', f'sites/variant-{name}',
                     f'site-{name}', f'sites/site-{name}'):
            if not cand:
                continue
            for sub in (f'{ROOT}/{cand}/dist', f'{ROOT}/{cand}/dist/'):
                if os.path.isdir(sub.rstrip('/')):
                    dist = sub.rstrip('/')
                    break
            if dist:
                break
        ref = cfg.get('ref')
        out.append({'name': name, 'dist': dist, 'target': cfg.get('target'),
                    'ref': f'{PIPE}/{ref}' if ref and not os.path.isabs(ref) else ref})
    return out


DESIGNS = load_designs()
SITES = {d['name']: d['dist'] for d in DESIGNS if d['dist']}


def _first_dir(*cands):
    for c in cands:
        if os.path.isdir(c):
            return c
    return cands[0]


OUT = _first_dir(f'{ROOT}/preview/diff', f'{ROOT}/outputs', f'{ROOT}/../outputs')
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4173


def gallery():
    cards = []
    for d in DESIGNS:
        name, dist, target = d['name'], d['dist'], d['target']
        tgt = f' &middot; target &lt;{target:g}' if isinstance(target, (int, float)) else ''
        if dist:
            frame = (f'<iframe src="/{name}/" title="{name}" loading="lazy"></iframe>')
            link = f'<a href="/{name}/">open /{name}/ &rarr;</a>'
        else:
            frame = ('<div style="aspect-ratio:4/3;display:flex;align-items:center;'
                     'justify-content:center;color:#6b7d76;font-size:12.5px;'
                     'border:1px dashed #1d2a26;border-radius:8px">no build yet</div>')
            link = '<span style="color:#6b7d76">run ./build.sh</span>'
        cards.append(f'''<section class="card">
  <h2>{name}</h2>
  {frame}
  <p>{link}<br><span class="muted">ref <a href="/ref/{name}.png">/{name}.png</a>{tgt}</span></p>
</section>''')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Anthotype &mdash; live builds</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ background:#07090a; color:#dff5ec; padding:28px 24px 60px;
    font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif; }}
  h1 {{ font-size:22px; font-weight:600; letter-spacing:-.01em; margin-bottom:4px; }}
  h1 em {{ color:#3ee39f; font-style:normal; }}
  .sub {{ color:#7e9189; margin-bottom:22px; font-size:13px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(380px,1fr)); gap:22px; }}
  .card {{ background:#0d1211; border:1px solid #1d2a26; border-radius:12px; padding:14px; }}
  h2 {{ font-size:14px; font-weight:600; margin-bottom:10px; color:#eafff6; }}
  iframe {{ display:block; width:100%; aspect-ratio:4/3; border:0; border-radius:8px; background:#000; }}
  p {{ margin-top:9px; font-size:12.5px; }}
  a {{ color:#3ee39f; text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  .muted {{ color:#7e9189; }}
  .note {{ margin-top:26px; color:#7e9189; font-size:12.5px; border-top:1px solid #1d2a26; padding-top:14px; }}
</style></head><body>
<h1>Anthotype &mdash; <em>{len(SITES)}</em> live build(s)</h1>
<div class="sub">Served from each design&rsquo;s built <code>dist/</code> &mdash; the exact artifact
<code>qa/verify.sh</code> scores. Real DOM text + CSS + traced SVG art, no raster images.</div>
<div class="grid">
{''.join(cards)}
</div>
<div class="note">Generated from <code>pipeline/designs/*.json</code>.
The numbers come from <code>qa/verify.sh</code>; targets live in each design&rsquo;s config.</div>
</body></html>'''


class H(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *a):
        pass

    def _send(self, body, ctype, code=200):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        try:
            self.wfile.write(body)
        except BrokenPipeError:
            pass

    def _file(self, path, ctype=None):
        if not os.path.isfile(path):
            return self._send('not found', 'text/plain', 404)
        if ctype is None:
            low = path.lower()
            if low.endswith(('.html', '.htm')):
                ctype = 'text/html; charset=utf-8'
            elif low.endswith('.png'):
                ctype = 'image/png'
            elif low.endswith(('.jpg', '.jpeg')):
                ctype = 'image/jpeg'
            elif low.endswith('.svg'):
                ctype = 'image/svg+xml'
            elif low.endswith('.css'):
                ctype = 'text/css'
            elif low.endswith('.js'):
                ctype = 'text/javascript'
            else:
                ctype = 'application/octet-stream'
        with open(path, 'rb') as fh:
            self._send(fh.read(), ctype)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path).path
        if u in ('/', '/index.html'):
            return self._send(gallery(), 'text/html; charset=utf-8')
        # /<name>/...  -> that design's built dist
        for name, d in SITES.items():
            if u in (f'/{name}', f'/{name}/', f'/{name}/index.html'):
                return self._file(f'{d}/index.html')
            if u.startswith(f'/{name}/'):
                rel = u[len(name) + 2:]
                if '..' not in rel:
                    return self._file(os.path.join(d, rel))
        # /ref/<name>.png  /diff/<name>.png
        for pre, d in (('ref', f'{PIPE}/qa'), ('diff', OUT)):
            if u.startswith(f'/{pre}/'):
                v = u[len(pre) + 2:].split('.')[0].strip('/')
                return self._file(f'{d}/{pre}-{v}.png', 'image/png')
        rel = u.lstrip('/')
        if rel and '..' not in rel:
            return self._file(os.path.join(f'{ROOT}/preview', rel))
        return self._send('not found', 'text/plain', 404)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    with Server(('127.0.0.1', PORT), H) as httpd:
        print(f'serving {len(SITES)} build(s) on http://127.0.0.1:{PORT}/', flush=True)
        httpd.serve_forever()
