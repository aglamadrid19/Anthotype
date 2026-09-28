#!/usr/bin/env python3
"""Serve all three variant builds (and a gallery) from one process.

Routes:
  /            gallery (iframes all three)
  /a/ /b/ /c/  each variant's built dist/index.html
  /ref/<v>.png reference PNG, /diff/<v>.png amplified difference
"""
import http.server, os, socketserver, sys, urllib.parse

ROOT = os.environ.get('ANTHOSTING_ROOT') or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PIPE = f'{ROOT}/pipeline'
SITES = {}
for _v in 'abc':
    for _c in (f'{ROOT}/variant-{_v}/dist', f'{ROOT}/sites/variant-{_v}/dist'):
        if os.path.isdir(_c):
            SITES[_v] = _c
            break
def _first_dir(*cands):
    for c in cands:
        if os.path.isdir(c):
            return c
    return cands[0]


OUT = _first_dir(f'{ROOT}/preview/diff',
                 f'{ROOT}/outputs',
                 f'{ROOT}/../outputs',
                 f'{ROOT}/../outputs/anthosting-coming-soon/docs')
EXTRA = {'ref': f'{PIPE}/qa', 'diff': OUT}
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 4173


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
            return self._file(f'{ROOT}/preview/index.html')
        base = f'{ROOT}/preview'
        for key, d in SITES.items():
            if u in (f'/{key}', f'/{key}/', f'/{key}/index.html'):
                return self._file(f'{d}/index.html')
            if u.startswith(f'/{key}/'):
                rel = u[len(f'/{key}/'):]
                if '..' not in rel:
                    return self._file(os.path.join(d, rel))
        for pre, d in EXTRA.items():
            if u.startswith(f'/{pre}/'):
                rel = u[len(f'/{pre}/'):]
                if '..' not in rel:
                    # /ref/a or /ref/a.png -> ref-a.png
                    v = rel.split('.')[0].strip('/')
                    return self._file(f'{d}/{pre}-{v}.png', 'image/png')
        rel = u.lstrip('/')
        if rel and '..' not in rel:
            return self._file(os.path.join(base, rel))
        return self._send('not found', 'text/plain', 404)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


if __name__ == '__main__':
    with Server(('127.0.0.1', PORT), H) as httpd:
        print(f'serving on http://127.0.0.1:{PORT}/', flush=True)
        httpd.serve_forever()
