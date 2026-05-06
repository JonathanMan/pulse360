#!/usr/bin/env python3
"""
save_macro_signals.py
---------------------
Reads macro signal JSON from stdin and upserts it to the Supabase
macro_signals table (single row, id=1).

Usage:
    echo '<json>' | python scripts/save_macro_signals.py

Called by the macro-pulse-signal-refresh scheduled task after it has
web-searched and assembled the latest forecaster signals.
"""
import sys
import json
from pathlib import Path

# ── Load secrets ──────────────────────────────────────────────────────────────
secrets_path = Path(__file__).parent.parent / ".streamlit" / "secrets.toml"
if not secrets_path.exists():
    print(f"ERROR: secrets.toml not found at {secrets_path}", file=sys.stderr)
    sys.exit(2)

try:
    import tomllib  # Python 3.11+ stdlib
except ImportError:
    try:
        import tomli as tomllib  # fallback for older Python
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "tomli", "-q"])
        import tomli as tomllib  # type: ignore

with open(secrets_path, "rb") as f:
    secrets = tomllib.load(f)

# ── Supabase client ───────────────────────────────────────────────────────────
try:
    from supabase import create_client
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "supabase", "-q"])
    from supabase import create_client  # type: ignore

sb = create_client(secrets["SUPABASE_URL"], secrets["SUPABASE_KEY"])

# ── Read JSON from stdin ──────────────────────────────────────────────────────
raw = sys.stdin.read().strip()
if not raw:
    print("ERROR: no JSON received on stdin", file=sys.stderr)
    sys.exit(2)

try:
    signals_json = json.loads(raw)
except json.JSONDecodeError as e:
    print(f"ERROR: invalid JSON — {e}", file=sys.stderr)
    sys.exit(2)

# ── Validate structure ────────────────────────────────────────────────────────
if "forecasters" not in signals_json or not signals_json["forecasters"]:
    print("ERROR: signals JSON missing 'forecasters' list", file=sys.stderr)
    sys.exit(2)

# ── Upsert to Supabase ────────────────────────────────────────────────────────
result = sb.table("macro_signals").upsert({
    "id": 1,
    "signals_json": signals_json,
}).execute()

n = len(signals_json["forecasters"])
last_updated = signals_json.get("last_updated", "unknown")
print(f"✓ Signals saved to Supabase ({n} forecasters, last_updated: {last_updated})")
