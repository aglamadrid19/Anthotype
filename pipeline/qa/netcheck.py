#!/usr/bin/env python3
"""Prove a built page fetches nothing over the network for its rendering.

Motivation: the pages originally pulled Inter from the Google Fonts CDN, which
made typography -- and the scored fidelity -- depend on the visitor's network.
With the CDNs DNS-blackholed variant A scored 4.22 instead of 2.77, because the
page silently fell back to Helvetica.  Inter is now inlined; this tool keeps it
that way.

Method: render the page in headless Chrome with `--log-net-log` and read back
every URL_REQUEST/HTTP event.  Chrome's own telemetry (variations seed, update
checks, the new-tab page, component updater) is filtered out -- it is emitted by
the browser, not by the page, and appears identically for a blank document.

`--selftest` renders a one-line page that links the Google Fonts CSS and asserts
the tool *does* see the font request, so a zero result can never be a silently
broken measurement.

usage:
  netcheck.py <variant|path-to-html>...       # assert no font/CDN requests
  netcheck.py --selftest                      # verify the detector itself
"""
import glob
import json
import os
import subprocess
import sys
import tempfile
import time

CHROME = os.environ.get('CHROME',
                        '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')

# Requests the browser itself makes, independent of the page.  Verified by
# running the detector against a blank document.
BROWSER_NOISE = (
    'accounts.google.com', 'clients2.google.com', 'clients4.google.com',
    'clientservices.googleapis.com', 'update.googleapis.com',
    'clients2.googleusercontent.com', 'redirector.gvt1.com',
    'edgedl.me.gvt1.com', 'gvt1.com', 'gvt2.com', 'www.google.com',
    'googleusercontent.com', 'safebrowsing', 'optimizationguide',
    'content-autofill.googleapis.com', 'chromewebstore',
    'gstatic.com/ohttp_gateway', 'ohttp_gateway', 'pki.goog',
)

FONT_HOSTS = ('fonts.googleapis.com', 'fonts.gstatic.com')


def is_noise(url):
    return any(h in url for h in BROWSER_NOISE)


def is_font(url):
    return any(h in url for h in FONT_HOSTS) or url.endswith('.woff2') or url.endswith('.woff')


def capture(page_url, log_path):
    if os.path.exists(log_path):
        os.remove(log_path)
    subprocess.run([
        CHROME, '--headless=new', '--disable-gpu', '--hide-scrollbars',
        '--no-first-run', '--no-default-browser-check', '--disable-http-cache',
        '--incognito', '--force-device-scale-factor=2',
        '--window-size=1024,768', '--virtual-time-budget=8000',
        f'--log-net-log={log_path}', '--net-log-capture-mode=Everything',
        f'--screenshot={log_path}.png', page_url,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.3)
    with open(log_path, 'rb') as fh:
        data = json.load(fh)
    urls = set()
    for ev in data.get('events', []):
        url = str((ev.get('params') or {}).get('url', ''))
        if url.startswith(('http://', 'https://')):
            urls.add(url)
    return urls


def selftest():
    """The detector must SEE a known font request, else a 0 is meaningless."""
    d = tempfile.mkdtemp(prefix='netcheck')
    page = os.path.join(d, 'control.html')
    with open(page, 'w') as fh:
        fh.write('<!doctype html><meta charset=utf-8><body style="background:#000">'
                 '<link rel="stylesheet" '
                 'href="https://fonts.googleapis.com/css2?family=Inter:wght@400&display=swap">'
                 '<div style="font-family:Inter">control</div>')
    urls = capture('file://' + page, os.path.join(d, 'net.json'))
    hits = [u for u in urls if is_font(u)]
    if hits:
        print(f'selftest OK -- detector saw {len(hits)} font request(s) on a page that '
              f'deliberately uses the CDN')
        for h in hits:
            print('   ', h[:100])
        return 0
    print('selftest FAILED -- detector saw no font request even for a CDN page; '
          'a 0 result elsewhere cannot be trusted', file=sys.stderr)
    return 1


def main():
    args = sys.argv[1:]
    if not args or args[0] in ('--selftest', '-s'):
        return selftest()

    here = os.path.dirname(os.path.abspath(__file__))
    pipe = os.path.dirname(here)
    root = os.path.dirname(pipe)
    fail = 0
    for a in args:
        if os.path.isfile(a):
            page = os.path.abspath(a)
            tag = os.path.basename(a)
            url = 'file://' + page
        else:
            site = next((c for c in (f'{root}/variant-{a}/dist/index.html',
                                     f'{root}/sites/variant-{a}/dist/index.html')
                         if os.path.isfile(c)), None)
            if not site:
                print(f'{a}: no build found', file=sys.stderr)
                fail = 1
                continue
            tag = a
            url = 'file://' + site
        urls = capture(url + '?cb=1', f'/tmp/netcheck-{tag}.json')
        page_urls = sorted(u for u in urls if not is_noise(u))
        fonts = [u for u in page_urls if is_font(u)]
        status = 'PASS' if not fonts else 'FAIL'
        if fonts:
            fail = 1
        print(f'{tag:>12}  {status}  {len(fonts)} font/asset request(s), '
              f'{len(page_urls)} non-browser request(s) total')
        for u in fonts:
            print('       ', u[:110])
        for u in page_urls[:5]:
            if u not in fonts:
                print('        (remote)', u[:104])
    return fail


if __name__ == '__main__':
    sys.exit(main())
