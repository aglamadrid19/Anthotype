#!/usr/bin/env python3
"""End-to-end smoke test of the studio API against a running backend.

    python studio/backend/smoke.py [png] [--base http://127.0.0.1:8787]

Uploads a PNG, polls the job, prints each stage as it happens, and reports the
final score + artifact paths.  Exits non-zero on failure.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("png", nargs="?", default="/tmp/studio-test-a.png")
    ap.add_argument("--base", default="http://127.0.0.1:8787")
    ap.add_argument("--timeout", type=int, default=1800)
    a = ap.parse_args()

    png = Path(a.png)
    if not png.is_file():
        print(f"no such file: {png}", file=sys.stderr)
        return 2

    base = a.base.rstrip("/")
    with httpx.Client(base_url=base, timeout=60) as c:
        health = c.get("/api/health").json()
        print(f"backend ok; vision={health['vision']}")
        with png.open("rb") as fh:
            r = c.post("/api/jobs", files={"file": (png.name, fh, "image/png")})
        if r.status_code >= 400:
            print(f"upload failed {r.status_code}: {r.text}", file=sys.stderr)
            return 1
        jid = r.json()["id"]
        print(f"job {jid} created")

        seen = None
        deadline = time.time() + a.timeout
        while time.time() < deadline:
            job = c.get(f"/api/jobs/{jid}").json()
            if job["stage"] != seen:
                seen = job["stage"]
                print(f"  [{job['progress']*100:5.1f}%] {job['stage']:11s} {job['message']}")
            if job["status"] in ("done", "failed"):
                break
            time.sleep(1.5)

        job = c.get(f"/api/jobs/{jid}").json()
        print("\n--- final ---")
        print(json.dumps({k: job[k] for k in
                          ("status", "stage", "score", "pct_over_30",
                           "artifacts", "warnings", "error")}, indent=2))
        if job["status"] != "done":
            print("\n--- log tail ---")
            print("\n".join(job["logs"][-40:]))
            return 1

        for name in ("preview", "download"):
            r = c.get(f"/api/jobs/{jid}/{name}")
            print(f"{name:9s} -> {r.status_code} {r.headers.get('content-type')} "
                  f"{len(r.content)} bytes")
        print(f"\nOK  job {jid}")
        return 0


if __name__ == "__main__":
    sys.exit(main())
