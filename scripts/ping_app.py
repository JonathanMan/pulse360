#!/usr/bin/env python3
"""
scripts/ping_app.py
====================
Lightweight HTTP ping for the Pie360 Streamlit app.
Used by .github/workflows/warmup.yml and runnable locally.

Usage:
    python scripts/ping_app.py [URL]
    python scripts/ping_app.py  # uses APP_URL env var or hardcoded default
"""

import os, sys, time, urllib.request, urllib.error

APP_URL = (
    sys.argv[1]
    if len(sys.argv) > 1
    else os.environ.get(
        "APP_URL",
        "https://pulse360-4qnaz6vcs7txp6prpkksg3.streamlit.app",
    )
)

print(f"Pinging {APP_URL} …", flush=True)
t0 = time.time()

try:
    req = urllib.request.Request(
        APP_URL,
        headers={"User-Agent": "Pie360-Warmup/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        elapsed = time.time() - t0
        print(f"✅  HTTP {resp.status}  ({elapsed:.1f}s)", flush=True)
        sys.exit(0)
except urllib.error.HTTPError as exc:
    elapsed = time.time() - t0
    print(f"⚠️  HTTP {exc.code}  ({elapsed:.1f}s) — app may be waking", flush=True)
    sys.exit(0)   # non-fatal — 5xx during wake is expected
except Exception as exc:
    elapsed = time.time() - t0
    print(f"❌  {exc}  ({elapsed:.1f}s)", flush=True)
    sys.exit(1)
"""
"""
